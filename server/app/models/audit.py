"""审计服务本地台账模型

两张表（浙警智治零信任审计服务中心要求本地留存不少于两年）：
- `audit_logs`    待上报/已上报的应用日志与服务日志（16 字段规范在 services/audit.py 内组装）
- `audit_send`    上报批次记录（sendId、条数、结果、失败原因），用于排查与重推统计
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    num_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # 记录标识（规范 ≤32）
    log_type: Mapped[str] = mapped_column(String(1), default="1")             # 1=应用日志 2=服务日志
    sub_log_type: Mapped[str] = mapped_column(String(4), default="101")       # 101 / 201

    # ---- 规范 16 字段（应用日志与服务日志共用前 14 个语义，字段名按各自规范在导出时改名） ----
    user_id: Mapped[str] = mapped_column(String(40), default="")              # 身份证号或数字证书主体标识
    organization: Mapped[str] = mapped_column(String(100), default="")        # 单位名称
    organization_id: Mapped[str] = mapped_column(String(18), default="")      # 单位机构代码（12 位机构码）
    user_name: Mapped[str] = mapped_column(String(30), default="")
    operate_time: Mapped[str] = mapped_column(String(14), default="")         # YYYYMMDDhhmmss
    terminal_id: Mapped[str] = mapped_column(String(50), default="")          # 真实源 IP（X-Forwarded-For 首跳）
    operate_type: Mapped[int] = mapped_column(Integer, default=1)             # 0登录 1查询 2新增 3修改 4删除 5登出 6导出 7比对
    operate_result: Mapped[str] = mapped_column(String(1), default="1")       # 1成功 0失败
    error_code: Mapped[str] = mapped_column(String(4), default="")
    operate_name: Mapped[str] = mapped_column(String(30), default="")         # 功能模块名；登录时填实际登录方式（规范 ≤30）
    operate_condition: Mapped[str] = mapped_column(Text, default="")          # ≤5000
    display: Mapped[str] = mapped_column(Text, default="")                    # ≤5000
    data_level: Mapped[int] = mapped_column(Integer, default=1)               # 0公开 1一般 2公民个人信息 3隐私

    # ---- 服务日志专有 ----
    interface_name: Mapped[str] = mapped_column(String(50), default="")
    requester: Mapped[str] = mapped_column(String(50), default="")

    # ---- 上报状态 ----
    status: Mapped[str] = mapped_column(String(8), default="pending", index=True)  # pending/sent/dead
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditSend(Base):
    __tablename__ = "audit_send"

    id: Mapped[int] = mapped_column(primary_key=True)
    send_id: Mapped[str] = mapped_column(String(32), index=True)              # 批次号（规范 ≤32）
    log_type: Mapped[str] = mapped_column(String(1), default="1")
    count: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(String(8), default="")                # ok/fail
    status_code: Mapped[str] = mapped_column(String(8), default="")           # 审计服务返回 status_code
    message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
