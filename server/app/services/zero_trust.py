"""零信任 / 统一认证对接（用户域 + 省厅零信任）

登录路径（三种模式，由 ZHijing_MODE 切换）：
- `off`   纯本地账号密码（现状），零信任相关入口返回"未启用"
- `mock`  本地模拟身份，联调前就能把"免登录进首页 → 记录审计"整条链路跑通
- `live`  真机对接：先取令牌 Header `RZZX-USERTOKEN`/`RZZX-APPTOKEN`，
          取不到再回退请求参数；用户域应用用**动态秘钥**方式（认证回调携带人员信息）接入统一认证

认证方式二选一（ZHijing_LOGIN_SOURCE）：
- `rzzx`    令牌信息：令牌 → `getLoginUser` 复合接口校验并取人（数据域标准做法，用户域亦可支持）
- `dynamic` 动态秘钥：统一认证把人员信息直接回调给我们（用户域标准做法）
- `both`    先试令牌，失败再试动态秘钥参数（默认，联调最稳）

安全约束：无论走哪条路径，**都不信任前端自报身份**——只有平台回调/令牌校验成功才建会话；
动态秘钥模式下回调一次性票据（LoginTicket）即换即删，避免人员信息长时间停留在地址栏。
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.sm3 import sm3_hex
from ..models import LoginTicket, User
from . import audit
from .region_mapper import map_region_code

logger = logging.getLogger(__name__)

USER_TOKEN_HEADER = "RZZX-USERTOKEN"
APP_TOKEN_HEADER = "RZZX-APPTOKEN"

# 认证服务状态码（认证/权限/审计通用）
SC_OK = "0000"
SC_FAIL = "0001"
SC_TOKEN_EXPIRED = "0002"
SC_PERM_FROZEN = "0003"
SC_USER_TOKEN_DECRYPT_FAIL = "1000"
SC_USER_TOKEN_MISSING = "1001"
SC_APP_TOKEN_DECRYPT_FAIL = "1002"
SC_APP_TOKEN_MISSING = "1003"

# 服务日志里的接口中文名（规范：接口名称填被调用接口的具体中文名称）
API_NAME_GET_LOGIN_USER = "用户基本信息获取服务"
API_NAME_CREATE_APP_TOKEN = "应用令牌生成服务"
API_NAME_RENEW_OR_OFFLINE = "令牌续期注销服务"
API_NAME_APP_PERMISSION = "应用级鉴权服务"

TOKEN_BAD_CODES = {SC_TOKEN_EXPIRED, SC_USER_TOKEN_DECRYPT_FAIL, SC_USER_TOKEN_MISSING,
                   SC_APP_TOKEN_DECRYPT_FAIL, SC_APP_TOKEN_MISSING}


class ZeroTrustError(Exception):
    """对接异常：status_code / http_status / message 一起抛出，便于审计与前端提示"""

    def __init__(self, message: str, *, status_code: str = "", http_status: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.http_status = http_status


@dataclass
class PlatformIdentity:
    """平台下发的身份（来自令牌校验或统一认证回调参数）"""

    cert_id: str = ""            # 身份证号 / 数字证书主体标识 → 审计 userId
    real_name: str = ""
    police_no: str = ""
    org_code: str = ""           # 12 位机构代码 → 审计 organizationId
    dept_name: str = ""
    person_type: str = ""        # 人员类别 RYLB
    login_method: str = "数字证书"
    raw: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 令牌与参数提取（规范：Header 优先，取不到回退请求参数）
# --------------------------------------------------------------------------- #
def _first(headers: dict, params: dict, *names: str) -> str:
    for n in names:
        v = headers.get(n.lower()) or headers.get(n)
        if v:
            return str(v).strip()
    for n in names:
        v = params.get(n) or params.get(n.lower()) or params.get(n.upper())
        if v:
            return str(v).strip()
    return ""


def extract_tokens(headers: dict, params: dict) -> tuple[str, str]:
    """返回 (user_token, app_token)"""
    app_key = headers.get("rzzx-apptoken") or headers.get(APP_TOKEN_HEADER)
    if not app_key:
        app_key = params.get("RZZX-APPTOKEN") or params.get("rzzx-apptoken") or ""
    user_key = headers.get("rzzx-usertoken") or headers.get(USER_TOKEN_HEADER)
    if not user_key:
        user_key = params.get("RZZX-USERTOKEN") or params.get("rzzx-usertoken") or ""
    return str(user_key).strip(), str(app_key).strip()


def dynamic_identity(params: dict) -> PlatformIdentity | None:
    """从统一认证回调参数解析人员信息（字段名做多别名兼容，以实际组件调用文档为准）"""
    cert_id = _first({}, params, "sfzh", "SFZH", "idcard", "IDCARD", "zjh", "certId", "usernumber")
    name = _first({}, params, "xm", "XM", "username", "USERNAME", "jyName", "realName", "name")
    police_no = _first({}, params, "jh", "JH", "policenumber", "POLICENUMBER", "jycode", "JYCODE", "policeNo")
    org_code = _first({}, params, "jgdm", "JGDM", "dm", "DM", "orgCode", "bmcode", "BMCODE", "deptCode")
    dept_name = _first({}, params, "dwmc", "DWMC", "deptname", "DEPTNAME", "deptName", "bmmc", "BMMC")
    person_type = _first({}, params, "rylb", "RYLB", "personType")
    login_method = _first({}, params, "loginType", "login_type", "rzfs") or "数字证书"
    if not (cert_id or police_no or name):
        return None
    return PlatformIdentity(cert_id=cert_id, real_name=name, police_no=police_no, org_code=org_code,
                            dept_name=dept_name, person_type=person_type, login_method=login_method,
                            raw=dict(params))


# --------------------------------------------------------------------------- #
# 真机：认证服务调用
# --------------------------------------------------------------------------- #
def _rzzx_post(path: str, payload: dict, *, interface_name: str = "", user=None) -> dict:
    """调用认证服务并自动记服务日志（logType=2）；异常路径也要留痕，否则联调时无从排查"""
    url = f"{settings.zhijing_rz_url.rstrip('/')}{path}"
    name = interface_name or path
    try:
        with httpx.Client(timeout=settings.zhijing_timeout, verify=settings.zhijing_verify_ssl) as client:
            resp = client.post(url, json=payload)
    except Exception as exc:  # noqa: BLE001
        audit.service_log(interface_name=name, requester=settings.zhijing_sys_id or "方言语料采集平台",
                          user=user, interface_result="0", error_code="2000",
                          condition=f"POST {url}", display=f"认证服务不可达：{type(exc).__name__}",
                          data_level=1)
        raise ZeroTrustError(f"认证服务不可达：{type(exc).__name__}", http_status=502) from exc
    if resp.status_code != 200:
        audit.service_log(interface_name=name, requester=settings.zhijing_sys_id or "方言语料采集平台",
                          user=user, interface_result="0", error_code="2000",
                          condition=f"POST {url}", display=f"HTTP {resp.status_code}", data_level=1)
        raise ZeroTrustError(f"认证服务返回 HTTP {resp.status_code}", http_status=502)
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        audit.service_log(interface_name=name, requester=settings.zhijing_sys_id or "方言语料采集平台",
                          user=user, interface_result="0", error_code="1001",
                          condition=f"POST {url}", display="响应不是 JSON", data_level=1)
        raise ZeroTrustError("认证服务响应不是 JSON", http_status=502) from exc

    code = str(data.get("status_code", ""))
    audit.service_log(interface_name=name, requester=settings.zhijing_sys_id or "方言语料采集平台",
                      user=user, interface_result="1" if code == SC_OK else "0",
                      error_code="" if code == SC_OK else "1001",
                      condition=f"POST {path}",
                      display=f"status_code={code} message={str(data.get('message', ''))[:200]}",
                      data_level=1)
    return data


def get_login_user(user_token: str, app_token: str) -> PlatformIdentity:
    """用户基本信息获取服务（复合接口：含用户令牌校验 + 应用令牌校验 + 取人员信息）"""
    body = {
        "appTokenId": app_token,
        "userTokenId": user_token,
        "dqxtbs": settings.zhijing_dqxtbs or settings.zhijing_sys_id,
    }
    data = _rzzx_post(settings.zhijing_path_get_login_user, body,
                      interface_name=API_NAME_GET_LOGIN_USER)
    code = str(data.get("status_code", ""))
    message = str(data.get("message", ""))
    if code in TOKEN_BAD_CODES:
        raise ZeroTrustError(f"令牌无效或不存在的用户：{message}", status_code=code, http_status=401)
    if code == SC_PERM_FROZEN:
        raise ZeroTrustError(f"权限冻结：{message}", status_code=code, http_status=403)
    if code != SC_OK:
        raise ZeroTrustError(f"令牌校验失败（{code}）：{message}", status_code=code, http_status=401)

    result = data.get("result") or {}
    identity = PlatformIdentity(
        cert_id=str(result.get("SFZH", "") or ""),
        real_name=str(result.get("USERNAME", "") or ""),
        police_no=str(result.get("POLICENUMBER", "") or ""),
        org_code=str(result.get("DM", "") or ""),
        dept_name=str(result.get("DEPTNAME", "") or ""),
        person_type=str(result.get("RYLB", "") or ""),
        login_method="数字证书",
        raw=result,
    )
    # 复合接口已含应用级鉴权；仍需显式鉴权时调用 check_app_permission
    return identity


def create_app_token() -> str:
    """应用令牌生成服务（跨域调用/主动校验时需要；appKey + secureKey + 毫秒时间戳）"""
    if not settings.zhijing_app_key or not settings.zhijing_app_secret:
        audit.service_log(interface_name=API_NAME_CREATE_APP_TOKEN,
                          requester=settings.zhijing_sys_id or "方言语料采集平台",
                          interface_result="0", error_code="1001",
                          condition="未发起调用", display="缺少 appKey/secureKey 配置，无法生成应用令牌",
                          data_level=1)
        raise ZeroTrustError("缺少 appKey/secureKey，无法生成应用令牌", http_status=500)
    body = {
        "appKey": settings.zhijing_app_key,
        "secureKey": settings.zhijing_app_secret,
        "yhsj": int(datetime.now().timestamp() * 1000),
    }
    data = _rzzx_post(settings.zhijing_path_create_app_token, body,
                      interface_name=API_NAME_CREATE_APP_TOKEN)
    if str(data.get("status_code")) != SC_OK:
        raise ZeroTrustError(f"应用令牌生成失败：{data.get('message', '')}", http_status=502)
    return str((data.get("result") or {}).get("appToken", ""))


def build_renew_sign(params: dict) -> str:
    """令牌续期注销的 callerSign = SM3(key 升序拼接的 JSON 对象)

    规范：入参**去除 callerSign、dqxtbs 后按 key 递增排序**，对 JSON 对象做 SM3。
    """
    payload = {k: v for k, v in params.items() if k not in ("callerSign", "dqxtbs")}
    raw = json.dumps({k: payload[k] for k in sorted(payload)}, ensure_ascii=False, separators=(",", ":"))
    return sm3_hex(raw)


def renew_or_offline_token(token_id: str, *, token_type: str = "user", action: str = "renew",
                           caller_id: str = "") -> bool:
    """令牌续期 / 注销服务（含 SM3 签名）

    - `action=renew`   续期（用户令牌到期前调用）
    - `action=offline` 注销（用户登出/令牌失效时调用，避免平台侧残留有效令牌）
    返回 True 表示平台确认成功；失败抛 ZeroTrustError。
    """
    dqxtbs = settings.zhijing_dqxtbs or settings.zhijing_sys_id
    payload = {
        "tokenId": token_id,
        "type": token_type,
        "action": action,
        "callerId": caller_id or dqxtbs,
        "callerTimestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "callerNounce": secrets.token_hex(16),
    }
    payload["callerSign"] = build_renew_sign(payload)
    payload["dqxtbs"] = dqxtbs
    data = _rzzx_post(settings.zhijing_path_renew_token, payload,
                      interface_name=API_NAME_RENEW_OR_OFFLINE)
    code = str(data.get("status_code", ""))
    if code not in (SC_OK, "1004", "1005"):  # 1004/1005=不需要续期，视为成功
        raise ZeroTrustError(f"令牌{action}失败（{code}）：{data.get('message', '')}", http_status=502)
    return True


def check_app_permission(user_token: str, app_token: str = "") -> bool:
    """应用级鉴权服务（权限服务中心 SerQxIP）"""
    url = f"{settings.zhijing_qx_url.rstrip('/')}{settings.zhijing_path_app_permission}"
    payload = {"userTokenId": user_token, "appTokenId": app_token or None}
    if settings.zhijing_auth_button:
        payload["APPID"] = settings.zhijing_auth_button
    try:
        with httpx.Client(timeout=settings.zhijing_timeout, verify=settings.zhijing_verify_ssl) as client:
            resp = client.post(url, json=payload)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        audit.service_log(interface_name=API_NAME_APP_PERMISSION,
                          requester=settings.zhijing_sys_id or "方言语料采集平台",
                          interface_result="0", error_code="2000",
                          condition=f"POST {settings.zhijing_path_app_permission}",
                          display=f"权限服务不可达：{type(exc).__name__}", data_level=1)
        raise ZeroTrustError(f"权限服务不可达：{type(exc).__name__}", http_status=502) from exc

    code = str(data.get("status_code", ""))
    audit.service_log(interface_name=API_NAME_APP_PERMISSION,
                      requester=settings.zhijing_sys_id or "方言语料采集平台",
                      interface_result="1" if code == SC_OK else "0",
                      error_code="" if code == SC_OK else "3007",
                      condition=f"POST {settings.zhijing_path_app_permission}",
                      display=f"status_code={code} message={str(data.get('message', ''))[:200]}",
                      data_level=1)
    if code != SC_OK:
        raise ZeroTrustError(f"应用级鉴权失败：{data.get('message', '')}", http_status=403)
    body = data.get("data") or {}
    if "sfyqx" in body:
        return str(body.get("sfyqx")).lower() == "true"
    return True  # 返回应用标识列表形态：status_code=0000 即视为有权限


# --------------------------------------------------------------------------- #
# 身份 → 本地用户
# --------------------------------------------------------------------------- #
def _role_for(identity: PlatformIdentity) -> str:
    admins = {x.strip() for x in settings.zhijing_admin_police_numbers.split(",") if x.strip()}
    if identity.police_no and identity.police_no in admins:
        return "admin"
    return settings.zhijing_user_default_role or "user"


def upsert_user(db: Session, identity: PlatformIdentity) -> User:
    """按 身份证号 → 警号 → 手机号 顺序认人；命中就更新资料，未命中则建号

    必须把手机号也纳入认人顺序：`users.phone` 唯一，历史 seed/Excel 导入的账号
    其 `phone` 可能就是警号或身份证号，若不认出来会在插入时撞唯一约束。
    """
    user: User | None = None
    if identity.cert_id:
        user = db.scalar(select(User).where(User.cert_id == identity.cert_id))
    if user is None and identity.police_no:
        user = db.scalar(select(User).where(User.police_no == identity.police_no))
    if user is None:
        for key in (identity.police_no, identity.cert_id):
            if not key:
                continue
            user = db.scalar(select(User).where(User.phone == key))
            if user is not None:
                break

    mapping = map_region_code(db, identity.org_code)
    if user is None:
        user = User(
            phone=identity.police_no or identity.cert_id or None,
            password_hash="",
            real_name=identity.real_name or "未知名",
            region_code=mapping.region_code,
            role=_role_for(identity),
            source="zhijing",
        )
        db.add(user)

    if identity.real_name:
        user.real_name = identity.real_name
    if identity.cert_id:
        user.cert_id = identity.cert_id
    if identity.police_no:
        user.police_no = identity.police_no
        if not user.phone:
            user.phone = identity.police_no
    if identity.org_code:
        user.org_code = identity.org_code
    if identity.dept_name:
        user.dept_name = identity.dept_name
        user.police_station = identity.dept_name  # 现有统计按派出所/单位名称聚合
    if mapping.matched or not user.region_code:
        user.region_code = mapping.region_code
    user.source = "zhijing"  # 只要走过平台认证，来源即标记为平台（便于管理端区分本地导入账号）
    db.flush()
    return user


def create_ticket(db: Session, user: User, login_method: str) -> str:
    ticket = secrets.token_urlsafe(32)
    db.add(LoginTicket(ticket=ticket, user_id=user.id, login_method=login_method))
    db.flush()
    return ticket


def redeem_ticket(db: Session, ticket: str) -> tuple[User, str]:
    """一次性票据换会话；过期或已用视为无效"""
    row = db.get(LoginTicket, ticket)
    if row is None or row.used_at is not None:
        raise ZeroTrustError("登录票据无效或已使用，请重新从浙警智治进入", http_status=401)
    if row.created_at and datetime.now() - row.created_at > timedelta(minutes=settings.zhijing_pending_token_minutes):
        raise ZeroTrustError("登录票据已过期，请重新从浙警智治进入", http_status=401)
    row.used_at = datetime.now()
    user = db.get(User, row.user_id)
    if user is None:
        raise ZeroTrustError("票据对应的用户不存在", http_status=401)
    return user, row.login_method


# --------------------------------------------------------------------------- #
# mock：联调前的本地模拟
# --------------------------------------------------------------------------- #
_MOCK_REGIONS = ["331004", "331024", "330100", "330200", "331000"]


def mock_identity(params: dict) -> PlatformIdentity:
    """本地模拟平台身份：?police_no=33100400002&name=张三&org_code=331004410500&as_admin=1"""
    police_no = str(params.get("police_no") or params.get("jh") or "33100400002").strip()
    name = str(params.get("name") or params.get("xm") or "模拟民警").strip()
    region = str(params.get("region") or "").strip()
    if region not in _MOCK_REGIONS:
        region = _MOCK_REGIONS[abs(hash(police_no)) % len(_MOCK_REGIONS)]
    org_code = str(params.get("org_code") or f"{region}410500").strip()
    cert_id = str(params.get("cert_id") or params.get("sfzh") or f"3301{abs(hash(police_no)) % 100:02d}19900101{abs(hash(name)) % 10000:04d}").strip()
    identity = PlatformIdentity(
        cert_id=cert_id, real_name=name, police_no=police_no, org_code=org_code,
        dept_name=str(params.get("dept_name") or f"模拟单位（{region}）"),
        person_type="1", login_method="数字证书(mock)", raw=dict(params),
    )
    if str(params.get("as_admin") or "") in {"1", "true", "yes"}:
        settings.zhijing_admin_police_numbers = police_no
    return identity


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def resolve_identity(request: Request) -> PlatformIdentity:
    """按配置解析平台身份；失败抛 ZeroTrustError"""
    mode = settings.zhijing_mode
    params = dict(request.query_params)
    headers = {k.lower(): v for k, v in request.headers.items()}

    if mode == "off":
        raise ZeroTrustError("未启用浙警智治对接（ZHijing_MODE=off）", http_status=404)

    if mode == "mock":
        return mock_identity(params)

    user_token, app_token = extract_tokens(headers, params)
    source = settings.zhijing_login_source

    if source in ("rzzx", "both") and user_token:
        identity = get_login_user(user_token, app_token)
        if settings.zhijing_auth_button:
            # 规范：配了应用级鉴权就必须执行；返回"无权限"时**必须拒绝进入**，
            # 不能只看 status_code=0000（0000 只代表调用成功，不代表用户有这个应用的权限）
            if not check_app_permission(user_token, app_token):
                raise ZeroTrustError("当前用户没有本应用的访问权限", status_code=SC_PERM_FROZEN, http_status=403)
        return identity

    if source in ("dynamic", "both"):
        identity = dynamic_identity(params)
        if identity is not None:
            if not identity.cert_id and not identity.police_no:
                raise ZeroTrustError("统一认证回调缺少人员标识（身份证号/警号）", http_status=401)
            return identity

    raise ZeroTrustError("未收到平台令牌信息或统一认证参数", http_status=401)


def login_by_identity(db: Session, identity: PlatformIdentity, *, request: Request | None = None) -> User:
    """身份落库 + 记录登录审计（两条路径共用）"""
    user = upsert_user(db, identity)
    ip = audit.client_ip(request) if request is not None else ""
    user.last_login_at = datetime.now()
    user.last_login_ip = ip
    db.commit()
    db.refresh(user)
    audit.queue_audit(
        operate_type=audit.OP_LOGIN,
        operate_name=identity.login_method or "数字证书",
        user=user,
        request=request,
        operate_condition=f"通过[{identity.login_method or '数字证书'}]方式登录了系统。",
        display=f"用户[{user.real_name}]登录成功，来源={settings.zhijing_mode}",
        data_level=1,
    )
    return user


def self_check() -> dict:
    """联调自检：模式、配置完整性、地址可达性（不产生业务数据）"""
    info: dict = {
        "mode": settings.zhijing_mode,
        "login_source": settings.zhijing_login_source,
        "callback_path": settings.zhijing_callback_path,
        "legacy_login": settings.zhijing_legacy_login,
        "sys_id": bool(settings.zhijing_sys_id),
        "app_key": bool(settings.zhijing_app_key),
        "app_secret": bool(settings.zhijing_app_secret),
        "rz_url": settings.zhijing_rz_url,
        "qx_url": settings.zhijing_qx_url,
        "audit_url": settings.zhijing_audit_url,
    }
    if settings.zhijing_mode == "live":
        reachable = {}
        for name, base in (("rz", settings.zhijing_rz_url), ("qx", settings.zhijing_qx_url)):
            try:
                with httpx.Client(timeout=5, verify=settings.zhijing_verify_ssl) as client:
                    client.get(base)
                reachable[name] = "reachable"
            except Exception as exc:  # noqa: BLE001
                reachable[name] = f"{type(exc).__name__}"
        info["reachable"] = reachable
    return info
