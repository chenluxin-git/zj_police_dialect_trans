"""管理端请求 schema（T14 用户管理 / T15 批量导入共用；响应统一走 schemas.ok() 信封）"""
from typing import Optional

from pydantic import BaseModel


class UserCreateIn(BaseModel):
    phone: str
    real_name: str
    region_code: str
    police_station: str = ""
    role: str = "user"           # user/admin/super_admin；admin 不可创建 super_admin


class UserUpdateIn(BaseModel):
    real_name: Optional[str] = None
    region_code: Optional[str] = None
    police_station: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
