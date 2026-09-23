"""平台组织与同步游标模型（统一用户组件对接用）

- `org_units`：应用管理器同步下来的部门（12 位公安机关机构代码），并承载
  **机构代码 → 行政区划代码（region_code）** 的映射结果——本平台的三级数据权限
  完全依赖 `Region.code`（6 位区划码），而零信任/统一用户给的是 12 位机构代码，
  映射规则见 `services/org_sync.py::map_region_code`
- `org_sync_cursor`：增量游标（部门 BEGINID、警员 ZID）持久化位置，规范要求记录最后一条
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class OrgUnit(Base):
    __tablename__ = "org_units"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)   # 机构代码（12 位）
    name: Mapped[str] = mapped_column(String(200), default="")        # 机构名称全称
    parent_code: Mapped[str] = mapped_column(String(20), default="")
    platform_id: Mapped[str] = mapped_column(String(64), default="")  # 平台部门 ID（BMID）
    region_code: Mapped[str] = mapped_column(String(20), default="", index=True)  # 映射到的区划代码
    begin_id: Mapped[str] = mapped_column(String(32), default="")     # 平台增量游标 BEGINID
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class OrgSyncCursor(Base):
    __tablename__ = "org_sync_cursor"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)   # dept / user
    cursor: Mapped[str] = mapped_column(String(32), default="")       # BEGINID / ZID
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[str] = mapped_column(String(500), default="")
    total_synced: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class LoginTicket(Base):
    """动态秘钥模式下的一次性登录票据

    认证回调地址可能由平台以 GET 重定向打开（参数落在 URL/日志里），
    为避免把人员信息长期暴露在地址栏，回调只做交换：即换即删，前端拿 ticket 换本地会话。
    """
    __tablename__ = "login_tickets"

    ticket: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    login_method: Mapped[str] = mapped_column(String(32), default="数字证书")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
