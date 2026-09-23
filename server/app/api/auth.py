r"""认证：本地账号（过渡期）+ 浙警智治统一认证/零信任令牌登录

路由一览（均挂在 /api 前缀下）：
- POST /auth/register              本地注册（平台同步上线后可关闭）
- POST /auth/login                 手机号/警号 + 密码（过渡期，ZHijing_LEGACY_LOGIN 控制）
- GET  /auth/me                    当前用户
- POST /auth/logout                登出（记录审计 operateType=5）
- ANY  /auth/zhijing/callback      平台认证回调地址（上架时填报，接收 RZZX-* 令牌或统一认证参数）
- POST /auth/zhijing/exchange      前端用一次性票据换本地会话（避免人员信息停留在地址栏）
- GET  /auth/zhijing/self-check    联调自检（配置/地址可达性）

对接模式见 services/zero_trust.py（off / mock / live）
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..core.security import create_token, hash_password, verify_password
from ..models import Region, User
from ..schemas import ok
from ..schemas.auth import Token, UserInfo, UserCreate, UserLogin
from ..services import audit, zero_trust
from ..services.zero_trust import ZeroTrustError
from .deps import get_current_user, require_admin as get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])

PHONE_RE = re.compile(r"^\d{11}$")


def _token_payload(user: User) -> dict:
    return Token(token=create_token(str(user.id)), user=UserInfo.model_validate(user)).model_dump()


def _login_audit_failure(request: Request, phone: str, reason: str, error_code: str) -> None:
    audit.queue_audit(
        operate_type=audit.OP_LOGIN, operate_name="账号口令", request=request,
        user_id=phone, operate_result="0", error_code=error_code,
        operate_condition="通过[账号口令]方式登录了系统。",
        display=f"登录失败：{reason}", data_level=1,
    )


@router.post("/register")
def register(body: UserCreate, db: Session = Depends(get_db)):
    if not settings.zhijing_legacy_login:
        raise HTTPException(403, "本系统已切换为浙警智治统一认证登录，请从平台进入")
    if not PHONE_RE.fullmatch(body.phone):
        raise HTTPException(400, "手机号必须为11位数字")
    if db.scalar(select(User).where(User.phone == body.phone)) is not None:
        raise HTTPException(400, "手机号已注册")
    if db.get(Region, body.region_code) is None:
        raise HTTPException(400, "区域代码不存在")
    user = User(phone=body.phone, password_hash=hash_password(body.password),
                real_name=body.real_name, police_station=body.police_station,
                region_code=body.region_code, role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(_token_payload(user))


@router.post("/login")
def login(body: UserLogin, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.phone == body.phone))
    if not settings.zhijing_legacy_login:
        # 过渡期开关关闭后，仅超管应急账号可走本地口令
        if user is None or user.role != "super_admin":
            _login_audit_failure(request, body.phone, "登录方式已停用", audit.ERR_NO_PERMISSION)
            raise HTTPException(403, "本系统已切换为浙警智治统一认证登录，请从平台进入")
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        _login_audit_failure(request, body.phone, "手机号或密码错误", audit.ERR_BAD_CREDENTIAL)
        raise HTTPException(401, "手机号或密码错误")
    from datetime import datetime
    user.last_login_at = datetime.now()
    user.last_login_ip = audit.client_ip(request)
    db.commit()
    db.refresh(user)
    audit.queue_audit(operate_type=audit.OP_LOGIN, operate_name="账号口令", user=user, request=request,
                      operate_condition="通过[账号口令]方式登录了系统。", data_level=1)
    return ok(_token_payload(user))


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return ok(UserInfo.model_validate(current_user).model_dump())


@router.post("/logout")
def logout(request: Request, current_user: User = Depends(get_current_user)):
    audit.queue_audit(operate_type=audit.OP_LOGOUT, operate_name="退出登录", user=current_user,
                      request=request, operate_condition="退出系统。", data_level=1)
    # 令牌方式登录时同步注销平台侧用户令牌（规范：令牌续期注销服务，含 SM3 签名）
    user_token, _app_token = zero_trust.extract_tokens(
        {k.lower(): v for k, v in request.headers.items()}, dict(request.query_params))
    if user_token:
        try:
            zero_trust.renew_or_offline_token(user_token, token_type="user", action="offline")
        except ZeroTrustError as exc:
            logger.warning("平台令牌注销失败（不影响本地退出）：%s", exc.message)
    return ok(None, "已退出")


# --------------------------------------------------------------------------- #
# 浙警智治统一认证 / 零信任令牌登录
# --------------------------------------------------------------------------- #
def _frontend_base(request: Request) -> str:
    """前端基地址：优先 app.state（运行时注入），默认取配置 frontend_base"""
    base = getattr(request.app.state, "frontend_base", "") or settings.frontend_base or "/"
    return base.rstrip("/")


async def _callback_params(request: Request) -> dict:
    """回调参数合并：GET/POST 表单/JSON 三种形态都吃（平台默认 GET，支持 POST）"""
    params: dict = dict(request.query_params)
    if request.method == "POST":
        ctype = request.headers.get("content-type", "")
        try:
            if "application/json" in ctype:
                body = await request.json()
                if isinstance(body, dict):
                    params.update({k: v for k, v in body.items() if v is not None})
            else:
                form = await request.form()
                params.update({k: v for k, v in form.items() if isinstance(v, str)})
        except Exception:  # noqa: BLE001 —— 非表单体不影响 Header 令牌路径
            pass
    return params


@router.api_route("/zhijing/callback", methods=["GET", "POST"])
async def zhijing_callback(request: Request, db: Session = Depends(get_db)):
    """平台认证回调：校验令牌/统一认证参数 → 建/更新本地用户 → 下发会话

    GET  重定向到前端 `/#/auth?...`（令牌不落 URL 查询串，避免进 nginx 日志与 Referer）；
    POST 直接返回 JSON 信封，由前端完成跳转。
    """
    try:
        identity = zero_trust.resolve_identity(request)
    except ZeroTrustError as exc:
        audit.queue_audit(operate_type=audit.OP_LOGIN, operate_name="数字证书", request=request,
                          operate_result="0", error_code=audit.ERR_NO_PERMISSION,
                          operate_condition="通过[数字证书]方式登录了系统。",
                          display=f"认证失败：{exc.message}", data_level=1)
        if request.method == "GET":
            base = _frontend_base(request)
            return RedirectResponse(f"{base}/#/login?error=zhijing&msg={exc.message}", status_code=303)
        return JSONResponse(status_code=exc.http_status, content={"code": exc.http_status, "msg": exc.message, "data": None})

    user = zero_trust.login_by_identity(db, identity, request=request)
    token = create_token(str(user.id))
    payload = {"token": token, "user": UserInfo.model_validate(user).model_dump(),
               "login_method": identity.login_method}

    if request.method == "GET":
        base = _frontend_base(request)
        return RedirectResponse(f"{base}/#/auth?token={token}", status_code=303)
    return ok(payload)


@router.post("/zhijing/exchange")
def zhijing_exchange(body: dict, db: Session = Depends(get_db)):
    """一次性票据换会话（动态秘钥模式下前端不直接持有人员信息）"""
    ticket = str((body or {}).get("ticket", "")).strip()
    if not ticket:
        raise HTTPException(400, "缺少 ticket")
    try:
        user, _method = zero_trust.redeem_ticket(db, ticket)
    except ZeroTrustError as exc:
        raise HTTPException(exc.http_status, exc.message) from exc
    db.commit()
    return ok(_token_payload(user))


@router.get("/zhijing/mapping-health")
def zhijing_mapping_health(
    sample: str = "",
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """机构码→区划码映射体检（管理员）：上线前核对数据权限是否会被映射带偏

    `sample` 可传逗号分隔的机构代码样本，例如
    `/api/auth/zhijing/mapping-health?sample=330000410000,331000410000,331004410500`
    """
    from ..services.region_mapper import health_report

    codes = [c for c in (sample or "").split(",") if c.strip()]
    return ok(health_report(db, codes))


@router.get("/zhijing/self-check")
def zhijing_self_check():
    """联调自检：只读，不产生业务数据（阻塞时直接看这里哪一项没配好）"""
    from ..services import org_sync

    return ok({
        "zero_trust": zero_trust.self_check(),
        "audit": audit.audit_self_check(),
        "org_sync": org_sync.sync_status(),
    })
