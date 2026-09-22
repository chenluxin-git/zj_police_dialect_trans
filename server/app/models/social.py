"""用户与社交相关模型：users / tasks / messages / message_recipients / qc_logs"""
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, UniqueConstraint
from ..core.database import Base
from sqlalchemy.orm import Mapped, mapped_column

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(11), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    real_name: Mapped[str] = mapped_column(String(64))
    police_station: Mapped[str] = mapped_column(String(128), default="")
    region_code: Mapped[str] = mapped_column(String(6), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user/admin/super_admin
    import_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(16))                  # recording/annotation
    target_count: Mapped[int] = mapped_column(Integer)
    base_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/cancelled
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    sender_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None=系统自动
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class MessageRecipient(Base):
    __tablename__ = "message_recipients"
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 空=未读

class QCLog(Base):
    __tablename__ = "qc_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(Integer, index=True)  # 录音删除后仍保留，无外键
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    text_id: Mapped[int] = mapped_column(Integer)
    text_content: Mapped[str] = mapped_column(Text)
    asr_text: Mapped[str] = mapped_column(Text, default="")
    similarity: Mapped[float | None] = mapped_column(nullable=True)
    result: Mapped[str] = mapped_column(String(8))                  # passed/failed/error
    error_message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
