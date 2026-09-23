"""用户与社交相关模型：users / tasks / messages / message_recipients / qc_logs"""
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, DateTime, UniqueConstraint
from ..core.database import Base
from sqlalchemy.orm import Mapped, mapped_column

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)  # 手机号/警号
    password_hash: Mapped[str] = mapped_column(String(128), default="")  # 平台登录用户无本地口令
    real_name: Mapped[str] = mapped_column(String(64))
    police_station: Mapped[str] = mapped_column(String(128), default="")
    region_code: Mapped[str] = mapped_column(String(6), index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")  # user/admin/super_admin
    import_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # ---------- 浙警智治接入字段 ----------
    cert_id: Mapped[str] = mapped_column(String(40), default="", index=True)   # 身份证号/数字证书主体标识（审计 userId）
    police_no: Mapped[str] = mapped_column(String(32), default="", index=True)  # 警号 POLICENUMBER / JYCODE
    org_code: Mapped[str] = mapped_column(String(20), default="")               # 12 位公安机关机构代码（审计 organizationId）
    dept_name: Mapped[str] = mapped_column(String(200), default="")             # 所属部门名称
    source: Mapped[str] = mapped_column(String(16), default="local")            # local=本地注册/导入, zhijing=平台同步
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str] = mapped_column(String(50), default="")
    # 零信任联动 role-update：早于该时刻签发的本地会话令牌一律作废
    # 存**本地时间**（与本库其他 DateTime 列一致，如 created_at），比较时再换算成 UTC 秒级时间戳
    auth_invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
