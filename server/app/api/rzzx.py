"""零信任联动服务（由业务应用提供，零信任侧下发指令）

方向与认证/权限相反：**本系统是服务端**，接收零信任下发的 `role-update` / `token-offline` /
`token-online` / `token-renew` 指令，并按规范用 SM3 校验 `sign`。

签名算法（规范 §6.6）：
    sign = SM3("action=&msg=&userTokenId=&appTokenId=&pid=&appid=")

落地策略（与我们"平台令牌校验一次 + 本地会话"的机制匹配）：
- `role-update`    权限更新：登记指令；被点名用户（pid/令牌）下次进入强制重新鉴权
- `token-offline`  令牌下线：写入本地吊销表，则该令牌不能再换会话
- `token-online` / `token-renew`：登记令牌新鲜度，供排查

⚠️ 本服务地址由应用自定义，上架资料里要把它交给零信任侧（如 `https://<域名>/api/rzzx/linkage`），
并确保对方网络可达。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..core.sm3 import sm3_hex
from ..models import LinkageEvent, RevokedToken, User
from ..schemas import ok
from .deps import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rzzx", tags=["零信任联动"])

ACTIONS = {"role-update", "token-offline", "token-online", "token-renew"}


class LinkageTarget(BaseModel):
    userTokenId: str | None = None
    appTokenId: str | None = None
    pid: str | None = None
    appid: str | None = None


class LinkageBody(BaseModel):
    action: str
    msg: str = ""
    target: LinkageTarget | None = None
    sign: str = ""


def compute_sign(action: str, msg: str, user_token: str, app_token: str, pid: str, appid: str) -> str:
    raw = (f"action={action}&msg={msg}&userTokenId={user_token}"
           f"&appTokenId={app_token}&pid={pid}&appid={appid}")
    return sm3_hex(raw)


@router.post("/linkage")
def linkage(body: LinkageBody, db: Session = Depends(get_db)):
    """接收零信任指令；返回 {status_code, message}（规范要求的状态码约定）"""
    target = body.target or LinkageTarget()
    user_token = target.userTokenId or ""
    app_token = target.appTokenId or ""
    pid = target.pid or ""
    appid = target.appid or ""

    if body.action not in ACTIONS:
        return {"status_code": "0001", "message": f"未知指令：{body.action}"}

    # 签名校验：live 模式必须校验；mock/off 模式允许空签名（本地联调）
    sign_ok = "1"
    if settings.zhijing_mode == "live" or body.sign:
        expect = compute_sign(body.action, body.msg, user_token, app_token, pid, appid)
        if body.sign.lower() != expect.lower():
            sign_ok = "0"
            _record(db, body, user_token, app_token, pid, appid, sign_ok, "签名校验失败")
            logger.warning("联动服务签名校验失败：action=%s msg=%s", body.action, body.msg)
            return {"status_code": "0001", "message": "签名校验失败"}

    handled = ""
    if body.action == "token-offline":
        revoked = 0
        for token_id, token_type in ((user_token, "user"), (app_token, "app")):
            if token_id and db.get(RevokedToken, token_id) is None:
                db.add(RevokedToken(token_id=token_id, token_type=token_type, reason=body.msg or "零信任指令下线"))
                revoked += 1
        handled = f"已吊销 {revoked} 个令牌"
    elif body.action == "token-renew":
        # 令牌更新广播：本地不缓存令牌本身，仅登记（下次校验自然取到新令牌）
        handled = "已登记令牌更新"
    elif body.action == "token-online":
        # 令牌上线：解除历史吊销（同一令牌重新有效）
        for token_id in (user_token, app_token):
            row = db.get(RevokedToken, token_id) if token_id else None
            if row is not None:
                db.delete(row)
        handled = "已解除历史吊销"
    elif body.action == "role-update":
        # 清掉相关用户的本地会话标记：使其下次请求重新走平台鉴权
        count = _reset_user_sessions(db, pid=pid, appid=appid)
        handled = f"已标记 {count} 个用户需重新鉴权"

    _record(db, body, user_token, app_token, pid, appid, sign_ok, handled)
    logger.info("联动指令已处理：%s %s", body.action, handled)
    return {"status_code": "0000", "message": handled or "操作成功"}


def _reset_user_sessions(db: Session, *, pid: str, appid: str) -> int:
    """按 pid（身份证号/人员标识）作废本地会话

    本系统会话是无状态 JWT，无法服务端单点吊销；因此约定：
    `role-update` 落库时把该用户的 `auth_invalidated_at` 置为当前时间，
    `api/deps.py` 会丢弃签发时间早于该时刻的令牌（等效强制重新鉴权）。
    """
    from datetime import datetime, timedelta

    if not pid:
        return 0
    # 平台可能下发身份证号（人员标识）或警号；两种都认，避免"指令到了但没作用"
    user = db.scalar(select(User).where(User.cert_id == pid))
    if user is None:
        user = db.scalar(select(User).where(User.police_no == pid))
    if user is None:
        logger.warning("role-update 未匹配到本地用户：pid=%s", pid)
        return 0
    # 作废时刻取"当前秒的上界"（微秒清零后 +1s）：
    # JWT 的 iat 只有秒级精度，若直接用当前秒，同一秒内签发的旧令牌会与作废时刻相等而逃过校验。
    # 取上界可保证"指令之前签发的令牌（含同一秒）"一律失效；代价是权限变更后同一秒内
    # 重新登录会被要求再试一次（几秒后即恢复），安全侧优先。
    now = datetime.now()
    user.auth_invalidated_at = now.replace(microsecond=0) + timedelta(seconds=1)
    db.add(user)
    return 1


def _record(db: Session, body: LinkageBody, user_token: str, app_token: str, pid: str,
            appid: str, sign_ok: str, handled: str) -> None:
    db.add(LinkageEvent(action=body.action, message=body.msg[:500], user_token_id=user_token[:64],
                        app_token_id=app_token[:64], pid=pid[:64], appid=appid[:64],
                        sign_ok=sign_ok, handled=handled[:200]))
    db.commit()


@router.get("/revoked")
def revoked_list(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """管理端排查入口：当前被下线的令牌"""
    rows = db.scalars(select(RevokedToken).order_by(RevokedToken.revoked_at.desc()).limit(200)).all()
    return ok([{"token_id": r.token_id, "type": r.token_type, "reason": r.reason,
                "revoked_at": r.revoked_at.strftime("%Y-%m-%d %H:%M:%S") if r.revoked_at else ""} for r in rows])
