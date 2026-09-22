"""T7 文本分配 Pydantic 模型 + 统一响应信封
信封 ApiResponse/PageData 定义于此（P-media 独占文件），schemas/recording.py 复用；
统一口径 {code:0, msg:"", data:...}（Global Constraints）。
"""
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应信封：code=0 成功；业务性无货时 HTTP 404 + code=1"""
    code: int = 0
    msg: str = ""
    data: Optional[T] = None


class PageData(BaseModel, Generic[T]):
    """分页数据体"""
    total: int
    page: int
    page_size: int
    items: List[T]


class AssignTextData(BaseModel):
    """领取文本返回体（assign 与 custom 共用）"""
    text_id: int
    content: str
    category: str
    dialect: str
    region_code: str = ""
    dialect_code: str = ""
    remaining_seconds: int


class CustomTextIn(BaseModel):
    """自定义文本提交体"""
    content: str
