"""一次性数据搬迁：把 SQLite app.db 全部数据灌进 MySQL（实现方言无关，源/目标 URL 均可）。

用法（server 目录下）：
  python -m scripts.sqlite_to_mysql --sqlite ./data/app.db \
      --mysql "mysql+pymysql://zjpdt:密码@db:3306/zjpdt?charset=utf8mb4" [--force]

规则：
- 只搬"源库实际存在 且 在 Base 元数据中"的表，按元数据拓扑序逐表整搬；
- 目标缺失的表由脚本补建（fresh MySQL 库直接灌）；
- 显式带主键插入（保 id），整型自增主键搬完执行 ALTER TABLE ... AUTO_INCREMENT = max+1
  （sqlite 目标 rowid 自动跟随，跳过；字符串主键表无自增，跳过）；
- 目标任一表非空即中止（--force 先清空目标表再搬）。
"""
import argparse

from sqlalchemy import Integer, create_engine, func, inspect, select, text

from app import models  # noqa: F401  # 注册全部表元数据（Base.metadata）
from app.core.database import Base


def _table_pairs(src):
    """(表名, Table) 列表：仅取源库实际存在的表，按元数据拓扑序"""
    src_tables = set(inspect(src).get_table_names())
    return [(t.name, t) for t in Base.metadata.sorted_tables if t.name in src_tables]


def _chunks(src, table, batch_size):
    with src.connect() as c:
        result = c.execute(select(table))
        while True:
            rows = result.fetchmany(batch_size)
            if not rows:
                return
            yield [dict(r._mapping) for r in rows]


def _is_int_autoincrement(table) -> bool:
    """单列整型自增主键才需要顶 MySQL 计数器（Column.autoincrement 对字符串主键默认也是真值，
    必须叠加类型判断，否则会对 regions 这类字符串主键表生成非法 ALTER TABLE）"""
    pk = list(table.primary_key.columns)
    return len(pk) == 1 and pk[0].autoincrement and isinstance(pk[0].type, Integer)


def copy_database(src, dst, batch_size: int = 500, force: bool = False) -> dict[str, int]:
    """整库搬迁，返回 {表名: 行数}；目标任一表非空抛 RuntimeError（force=True 先清空）"""
    counts: dict[str, int] = {}
    pairs = _table_pairs(src)
    dst_tables = set(inspect(dst).get_table_names())

    with dst.connect() as conn:
        # 非空守卫
        for name, table in pairs:
            if name in dst_tables and conn.execute(select(table).limit(1)).first() is not None:
                if not force:
                    raise RuntimeError(f"目标表 {name} 非空，拒绝搬迁（确认后加 --force）")
        if force:
            for name, table in pairs:  # 无外键约束，清空顺序不敏感
                if name in dst_tables:
                    conn.execute(table.delete())
            conn.commit()
        # 目标补建缺失表
        missing = [t for name, t in pairs if name not in dst_tables]
        if missing:
            Base.metadata.create_all(bind=conn, tables=missing)
        # 逐表整搬（显式带主键，保 id）
        for name, table in pairs:
            n = 0
            for chunk in _chunks(src, table, batch_size):
                conn.execute(table.insert(), chunk)
                n += len(chunk)
            conn.commit()
            counts[name] = n
        # MySQL 整型自增主键：计数器顶到 max(id)+1，否则续插撞主键
        if dst.dialect.name == "mysql":
            for name, table in pairs:
                if _is_int_autoincrement(table):
                    max_id = conn.execute(select(func.max(table.primary_key.columns[0]))).scalar() or 0
                    conn.execute(text(f"ALTER TABLE {name} AUTO_INCREMENT = {int(max_id) + 1}"))
            conn.commit()
    return counts


def main():
    ap = argparse.ArgumentParser(description="SQLite → MySQL 一次性数据搬迁")
    ap.add_argument("--sqlite", default="./data/app.db", help="源 SQLite 文件路径")
    ap.add_argument("--mysql", required=True,
                    help="目标库 URL（mysql+pymysql://...?charset=utf8mb4）")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--force", action="store_true", help="目标非空时先清空目标表再搬")
    args = ap.parse_args()
    src = create_engine(f"sqlite:///{args.sqlite}")
    dst = create_engine(args.mysql, pool_pre_ping=True)
    counts = copy_database(src, dst, batch_size=args.batch_size, force=args.force)
    for name, n in sorted(counts.items()):
        print(f"{name}: {n}")
    print(f"完成，共 {sum(counts.values())} 行")


if __name__ == "__main__":
    main()
