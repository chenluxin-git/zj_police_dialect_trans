"""
安全模块
提供密码哈希验证、JWT令牌生成与解码功能
（移植自 audio-server-test/app/core/security.py：bcrypt 哈希 + python-jose JWT，
 函数名对齐新接口 hash_password/verify_password/create_token/decode_token）
"""
from datetime import datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from .config import settings

# 密码加密上下文，使用bcrypt算法
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """
    对密码进行哈希加密（处理bcrypt的72字节限制）

    Args:
        password: 明文密码

    Returns:
        哈希后的密码字符串
    """
    # bcrypt 只能处理前72字节，超出部分会被截断
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
        password = password_bytes.decode('utf-8', errors='ignore')
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码与哈希密码是否匹配

    Args:
        plain_password: 明文密码
        hashed_password: 哈希密码

    Returns:
        True 匹配，False 不匹配
    """
    return pwd_context.verify(plain_password, hashed_password)

def create_token(sub: str) -> str:
    """
    创建JWT访问令牌（有效期 settings.access_token_expire_hours 小时）

    Args:
        sub: 令牌主题，通常为用户ID字符串

    Returns:
        编码后的JWT字符串
    """
    expire = datetime.utcnow() + timedelta(hours=settings.access_token_expire_hours)
    to_encode = {"exp": expire, "sub": str(sub)}
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")

def decode_token(token: str) -> str | None:
    """
    解码JWT令牌

    Args:
        token: JWT字符串

    Returns:
        令牌的 sub（通常为用户ID字符串）；无效或过期返回 None
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.JWTError:
        return None
