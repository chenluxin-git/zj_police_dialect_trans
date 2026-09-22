r"""T5 认证：注册/登录/me（移植自 audio-server-test/app/api/auth.py，裁掉便捷版逻辑）
注册校验：phone ^\d{11}$、region_code 必须存在于 regions 表、role 固定 user；
响应统一 {code, msg, data}，登录 data={token, user:{id, real_name, role, region_code, ...}}
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import create_token, hash_password, verify_password
from ..models import Region, User
from ..schemas import ok
from ..schemas.auth import Token, UserInfo, UserCreate, UserLogin
from .deps import get_current_user

router = APIRouter(prefix="/auth", tags=["认证"])

PHONE_RE = re.compile(r"^\d{11}$")


def _token_payload(user: User) -> dict:
    return Token(token=create_token(str(user.id)), user=UserInfo.model_validate(user)).model_dump()


@router.post("/register")
def register(body: UserCreate, db: Session = Depends(get_db)):
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
def login(body: UserLogin, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.phone == body.phone))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "手机号或密码错误")
    return ok(_token_payload(user))


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return ok(UserInfo.model_validate(current_user).model_dump())
