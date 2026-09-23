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
    phone: str | None = None
    real_name: str
    police_station: str = ""
    region_code: str
    role: str
    # ---------- 浙警智治接入附加信息（前端顶栏可展示警号/部门） ----------
    cert_id: str = ""
    police_no: str = ""
    dept_name: str = ""
    org_code: str = ""
    source: str = "local"


class Token(BaseModel):
    token: str
    user: UserInfo
