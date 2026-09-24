"""语音转译模型：transcriptions 表（工作台上传音视频 → 后台泵串行识别 → 前端轮询）
无外键（同 recordings 口径，删除即删行）；region_code 为上传时用户区域快照（管理端 scope 过滤用）；
text_fixed 语义：""=未修正；修正后与 text_raw 相同表示已撤销（回 ""）
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text as TextType

from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class Transcription(Base):
    __tablename__ = "transcriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    region_code: Mapped[str] = mapped_column(String(20), index=True)  # 上传时区域快照
    file_name: Mapped[str] = mapped_column(String(255))               # 原始文件名
    file_ext: Mapped[str] = mapped_column(String(16))                 # wav/mp3/m4a/webm/mp4/mov
    file_path: Mapped[str] = mapped_column(String(255), default="")   # 转码后 wav 路径
    file_size: Mapped[int] = mapped_column(Integer, default=0)        # 原始文件字节数
    duration: Mapped[float] = mapped_column(Float, default=0.0)       # 秒
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # status: pending → processing → done / failed
    text_raw: Mapped[str] = mapped_column(TextType, default="")       # ASR 原始识别
    text_fixed: Mapped[str] = mapped_column(TextType, default="")     # 人工修正（""=未修正）
    error_message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
