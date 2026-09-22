"""管理端台账模型：import_tasks / export_tasks / user_import_batches
旧 ImportTask/ExportTask 的 filename/completed_at/params 等列本项目不再需要（YAGNI，按任务书字段表），
status 统一 String（旧 ImportTask 的 Enum 弃用）
"""
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime
from ..core.database import Base
from sqlalchemy.orm import Mapped, mapped_column

class ImportTask(Base):
    __tablename__ = "import_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending/processing/completed/failed
    error_message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class ExportTask(Base):
    __tablename__ = "export_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending/processing/completed/failed
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class UserImportBatch(Base):
    __tablename__ = "user_import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255))
    total: Mapped[int] = mapped_column(Integer)
    success: Mapped[int] = mapped_column(Integer)
    fail: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str] = mapped_column(Text, default="[]")              # 每行结果 JSON
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
