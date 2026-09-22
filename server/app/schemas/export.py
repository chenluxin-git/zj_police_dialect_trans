"""T23 数据集导出 Pydantic 模型 + 统一响应信封
信封自包含定义（code/msg/data 口径与 Global Constraints 一致；不依赖未合并进基线的其他包 schema 文件）。
"""
from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应信封 {code:0, msg:"", data:...}"""
    code: int = 0
    msg: str = ""
    data: Optional[T] = None


class PageData(BaseModel, Generic[T]):
    """分页数据体"""
    total: int
    page: int
    page_size: int
    items: List[T]


class TwoSourceItem(BaseModel):
    """两源合并清单行：recordings(仅 passed) + audio_files(已判方言)
    统一结构 {id, source, text_or_name, region_code, dialect_code, translation?}（计划 T23）"""
    id: int
    source: str                                  # "recording" | "audio_file"
    text_or_name: str                            # 录音=文本内容；音频库=文件名
    category: str = ""                           # 仅录音源有
    region_code: str = ""
    dialect_code: str = ""
    translation: Optional[str] = None            # 仅音频库源（已判方言译文）
    user_real_name: str = ""                     # 仅录音源
    duration: float = 0.0
    created_at: datetime


class ExportItemIn(BaseModel):
    """勾选导出项"""
    source: str                                  # "recording" | "audio_file"
    id: int


class ExportPostBody(BaseModel):
    """导出所选请求体"""
    items: List[ExportItemIn]


class ExportAllBody(BaseModel):
    """导出全部请求体（与 audio-list 同筛）"""
    region: Optional[str] = None
    category: Optional[str] = None
    dialect: Optional[str] = None
    annotated: Optional[bool] = None


class ExportCreatedData(BaseModel):
    task_id: int


class ExportTaskStatusData(BaseModel):
    """任务轮询体（进度 processed/total）"""
    status: str
    total_count: int
    processed_count: int
    file_url: Optional[str] = None
