"""T5 认证请求/响应模型"""
from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    phone: str
    password: str
    real_name: str
    police_station: str = ""
    region_code: str


class UserLogin(BaseModel):
    phone: str
    password: str


class UserInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    real_name: str
    police_station: str
    region_code: str
    role: str


class Token(BaseModel):
    token: str
    user: UserInfo
