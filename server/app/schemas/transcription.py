"""语音转译 Pydantic 模型（信封复用 schemas/text.py 的 ApiResponse/PageData——同为 P-media 独占文件）"""
from datetime import datetime

from pydantic import BaseModel

from .text import ApiResponse, PageData  # noqa: F401  ApiResponse/PageData 由此 re-export 供本模块与路由使用


class TranscriptionItem(BaseModel):
    """转译列表行 / 上传返回体（corrected 为派生字段：text_fixed != ""）"""
    id: int
    file_name: str
    file_ext: str
    file_size: int
    duration: float
    status: str  # pending/processing/done/failed
    text_raw: str = ""
    text_fixed: str = ""
    corrected: bool = False
    error_message: str = ""
    created_at: datetime
    file_url: str = ""


class TranscriptionFixIn(BaseModel):
    """修正提交体：text 与 text_raw 相同即撤销修正（回 ""）"""
    text: str
