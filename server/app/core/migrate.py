"""轻量加列迁移（SQLite / MySQL 通用）

背景：本项目用 `Base.metadata.create_all()` 建表，**不会为已存在的表补列**。
浙警智治接入给 `users` 增加了 cert_id / police_no / org_code / dept_name / source /
last_login_at / last_login_ip / auth_invalidated_at 等字段，若直接升级已有库（例如
本地 `server/data/app.db` 或内网已跑起来的库），新字段缺失会导致运行时 500。

做法：启动时按模型元数据比对实际表结构，**只做新增缺失列**（ADD COLUMN，带常量默认值）。
- 覆盖不到的场景：改列类型、改约束、加索引、重命名——这些必须人工写迁移脚本。
- 生产建议：正式库优先用 MySQL，并在上架前用本函数做一次校验（见 `/api/zhijing/info`）。

打印/日志中会列出本次实际执行的 DDL，便于运维留痕。
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from .database import Base, engine

logger = logging.getLogger(__name__)


def _column_ddl(column) -> str:
    """按模型列定义生成 ADD COLUMN 子句（只取类型与默认值，宁简勿错）"""
    col_type = column.type.compile(dialect=engine.dialect)
    ddl = f"{column.name} {col_type}"
    if not column.nullable:
        # 未给默认值的非空列：用类型安全的常量默认值兜底（SQLite/MySQL 都接受）
        default = column.default.arg if column.default is not None and not column.default.is_callable else None
        if isinstance(default, str):
            safe = default.replace("'", "''")
            ddl += f" DEFAULT '{safe}'"
        elif isinstance(default, bool):
            ddl += f" DEFAULT {1 if default else 0}"
        elif isinstance(default, (int, float)):
            ddl += f" DEFAULT {default}"
        elif col_type.upper().startswith(("VARCHAR", "CHAR", "TEXT", "STRING")):
            ddl += " DEFAULT ''"
        else:
            ddl += " DEFAULT 0"
    return ddl


def ensure_columns() -> list[str]:
    """为已存在的表补齐缺失列；返回本次执行的 DDL 列表"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    executed: list[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # 新建的表由 create_all 负责
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {_column_ddl(column)}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                executed.append(ddl)
            except Exception as exc:  # noqa: BLE001 —— 单列失败不阻断启动，但要留痕
                logger.error("加列失败（需人工处理）：%s —— %s", ddl, exc)

    if executed:
        logger.warning("已自动补齐 %d 个缺失列：%s", len(executed), "; ".join(executed))
    return executed
