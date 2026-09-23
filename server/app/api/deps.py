"""
认证与数据权限依赖（管理端统一入口）
get_current_user/require_admin：Bearer 认证 + 管理员门禁；
resolve_scope：按用户区域四级推导数据权限（None=不过滤）；
scope_filter：管理端所有列表查询统一套用的过滤条件工具

浙警智治接入：`get_current_user` 额外校验令牌是否被零信任联动 role-update 作废
（比对令牌 iat 与 user.auth_invalidated_at），被吊销的令牌立即 401 要求重新鉴权。
"""
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import decode_token_claims
from ..models import User, Region

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)

def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(401, "未登录")
    claims = decode_token_claims(cred.credentials)
    if claims is None:
        raise HTTPException(401, "登录已过期")
    sub = claims.get("sub")
    try:
        user = db.get(User, int(sub)) if sub is not None else None
    except (TypeError, ValueError):
        user = None
    if user is None:
        raise HTTPException(401, "用户不存在")
    if _token_superseded(claims, user):
        raise HTTPException(401, "权限已变更，请重新从浙警智治进入")
    return user


def _token_superseded(claims: dict, user: User) -> bool:
    """零信任联动 role-update 之后签发的令牌才有效

    基准统一为 **UTC 秒级时间戳**（JWT iat 即 UTC 秒）：
    - 库里的作废时刻是 naive 本地时间 → 先用 `astimezone()` 换算成真实 UTC 时刻；
    - 与 iat 按整秒比较，规避微秒/时区两类偏差。同一秒内重新登录签发的令牌视为有效
      （此时权限变更已生效，不存在越权窗口）。
    """
    invalidated = getattr(user, "auth_invalidated_at", None)
    if invalidated is None:
        return False
    if invalidated.tzinfo is None:
        invalidated = invalidated.astimezone()  # naive 视为本地时间 → 带本地时区
    invalid_ts = int(invalidated.timestamp())
    iat = claims.get("iat")
    if iat is None:
        return True  # 历史令牌无 iat：保守要求重新鉴权
    try:
        issued_ts = int(iat)
    except (TypeError, ValueError):
        return True
    return issued_ts < invalid_ts

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin", "super_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user

def resolve_scope(db: Session, user: User) -> list[str] | None:
    if user.role == "super_admin":
        return None
    region = db.get(Region, user.region_code)
    if region is None:
        return [user.region_code]
    if region.level == "province":
        return None
    if region.level == "city":
        codes = [r.code for r in db.scalars(select(Region).where(Region.parent_code == region.code))]
        return [region.code] + codes
    return [region.code]

def scope_filter(region_col, scope: list[str] | None):
    """None=不过滤；否则 IN 命中。管理端所有列表查询套用。"""
    return true() if scope is None else region_col.in_(scope)
