"""零信任联动服务落库模型

- `linkage_events`：零信任下发的指令流水（role-update / token-offline / token-online / token-renew），
  用于排查"为什么这个用户权限突然变了/被踢下线"
- `revoked_tokens`：被 `token-offline` 点名下线的令牌，本地会话校验时据此立即失效
"""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class LinkageEvent(Base):
    __tablename__ = "linkage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    user_token_id: Mapped[str] = mapped_column(String(64), default="")
    app_token_id: Mapped[str] = mapped_column(String(64), default="")
    pid: Mapped[str] = mapped_column(String(64), default="")
    appid: Mapped[str] = mapped_column(String(64), default="")
    sign_ok: Mapped[str] = mapped_column(String(1), default="")   # 1=校验通过 0=失败
    handled: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_type: Mapped[str] = mapped_column(String(8), default="user")   # user / app
    reason: Mapped[str] = mapped_column(Text, default="")
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
