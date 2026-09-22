"""
认证与数据权限依赖（管理端统一入口）
get_current_user/require_admin：Bearer 认证 + 管理员门禁；
resolve_scope：按用户区域四级推导数据权限（None=不过滤）；
scope_filter：管理端所有列表查询统一套用的过滤条件工具
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import decode_token
from ..models import User, Region

bearer = HTTPBearer(auto_error=False)

def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(401, "未登录")
    sub = decode_token(cred.credentials)
    if sub is None:
        raise HTTPException(401, "登录已过期")
    user = db.get(User, int(sub))
    if user is None:
        raise HTTPException(401, "用户不存在")
    return user

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
