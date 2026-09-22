"""T8 录音 Pydantic 模型（信封复用 schemas/text.py 的 ApiResponse/PageData——同为 P-media 独占文件）"""
from datetime import datetime

from pydantic import BaseModel

from .text import ApiResponse, PageData  # noqa: F401  ApiResponse/PageData 由此 re-export 供本模块与路由使用


class UploadResultData(BaseModel):
    """上传返回体：{id, duration, file_size, qc_status:"pending"}"""
    id: int
    duration: float
    file_size: int
    qc_status: str


class RecordingItem(BaseModel):
    """我的录音列表行"""
    id: int
    text_id: int
    text_content: str
    category: str = ""
    dialect: str = ""
    duration: float
    file_size: int
    qc_status: str
    created_at: datetime
    file_url: str
