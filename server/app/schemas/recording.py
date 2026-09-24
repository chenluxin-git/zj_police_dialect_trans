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


class QcLogItem(BaseModel):
    """质检流水行（原文/转译/相似度对比展示）"""
    id: int
    result: str  # passed/failed/error
    similarity: float | None
    asr_text: str
    text_content: str
    error_message: str
    created_at: datetime


class QcDetailData(BaseModel):
    """质检详情：按 (user_id, text_id) 聚合的全历史（含重录替换旧行前的流水）"""
    recording_id: int
    text_id: int
    text_content: str
    items: list[QcLogItem]
