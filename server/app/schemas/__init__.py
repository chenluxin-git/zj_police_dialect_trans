"""Pydantic schemas 包；统一响应信封 ResponseModel / ok 定义在此（各包共用，只导入不修改）"""
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ResponseModel(BaseModel, Generic[T]):
    """统一响应信封 {code:0, msg:"", data:...}；唯一例外 GET /api/health 返回裸 {"status":"ok"}"""
    code: int = 0
    msg: str = ""
    data: Optional[T] = None


def ok(data: Any = None, msg: str = "") -> dict:
    """端点直接 return ok(x) 即 {code:0, msg:"", data:x}"""
    return {"code": 0, "msg": msg, "data": data}
