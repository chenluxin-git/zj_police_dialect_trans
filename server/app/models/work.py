"""业务工作模型：texts / text_assignments / recordings / audio_files / file_assignments / annotations
列名与旧项目对应表保持一致；一律不建外键（录音/标注删除时流水保留，见 qc_logs 注释），
旧表 TIMESTAMP+server_default 改为 DateTime+default=datetime.now（与本项目 social.py 统一）
"""
from datetime import datetime
# 本模块定义同名模型类 Text（表 texts），SQLAlchemy 的 Text 大类型须别名引入以免被遮蔽
from sqlalchemy import String, Integer, Text as TextType, DateTime, Float, Boolean, UniqueConstraint
from ..core.database import Base
from sqlalchemy.orm import Mapped, mapped_column

class Text(Base):
    __tablename__ = "texts"
    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(TextType)
    dialect: Mapped[str] = mapped_column(String(50))
    category: Mapped[str] = mapped_column(String(20))
    region_code: Mapped[str] = mapped_column(String(20), index=True)
    dialect_code: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class TextAssignment(Base):
    __tablename__ = "text_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    text_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)  # 一条文本只分给一人
    user_id: Mapped[int] = mapped_column(Integer)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (UniqueConstraint("user_id", "text_id"),)  # 一人一条文本只录一次
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    text_id: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float)              # 秒，可为小数
    region_code: Mapped[str] = mapped_column(String(20), index=True)
    dialect_code: Mapped[str] = mapped_column(String(20))
    qc_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/passed/failed/error
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class AudioFile(Base):
    __tablename__ = "audio_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String(512), unique=True)
    file_name: Mapped[str] = mapped_column(String(255))
    duration: Mapped[float] = mapped_column(Float)              # 秒，可为小数
    region_code: Mapped[str] = mapped_column(String(20), index=True)
    dialect_code: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class FileAssignment(Base):
    __tablename__ = "file_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)  # 一个音频只分给一人
    user_id: Mapped[int] = mapped_column(Integer)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)  # 一个音频一条标注
    annotator_id: Mapped[int] = mapped_column(Integer, index=True)
    is_dialect: Mapped[bool] = mapped_column(Boolean, default=True)  # 已取消是否方言判定，恒 True（列保留兼容既有库）
    translation: Mapped[str] = mapped_column(TextType, default="")
    region_code: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
