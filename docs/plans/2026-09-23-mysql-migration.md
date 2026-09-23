# 数据库 MySQL 改造实施计划

> **执行状态（2026-09-23）**：Task 1–3 已完成并合入 main（`a696628` / `230db39` / `87203e9`，常规套件 156 passed + 4 skipped，4 个门控测试 SKIP 待真机）。Task 4 因本开发机无 docker，已细化移交 [2026-09-23-mysql-docker-rehearsal.md](2026-09-23-mysql-docker-rehearsal.md)，由 Linux + Docker 执行机完成真机演练与生产切换。下文任务勾选框不再单独维护，以本状态行为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生产部署从 SQLite 切换到 MySQL 8（utf8mb4），本机开发默认仍 SQLite；含 compose 编排、存量数据一次性搬迁脚本与 MySQL 集成测试。

**Architecture:** 利用现有单一 `DATABASE_URL` 间接层——config 默认值不动（开发 SQLite），MySQL 仅由部署环境变量注入。代码层只改 `database.py` 引擎构造（抽 `build_engine()` 加 MySQL 分支 `pool_recycle`）；模型/查询层零改动（已验证全部可移植）。新增方言无关的 `scripts/sqlite_to_mysql.py` 整库搬迁脚本 + `TEST_MYSQL_URL` 门控的集成测试。

**Tech Stack:** SQLAlchemy 2.0.23（锁定不动）· PyMySQL 1.1.0（已在 requirements.txt）· mysql:8.0（Docker Compose）· pytest（现有套件）

**Spec:** 本文件即规格（自包含；依据 2026-09-23 代码摸排结论）。

## 摸排结论（为什么这么改）

| 项 | 现状 | 结论 |
|---|---|---|
| 依赖 | requirements.txt 已有 `pymysql==1.1.0`；`cryptography`（MySQL 8 caching_sha2_password 需要）随 python-jose 引入 | 零新增依赖 |
| 引擎 | [database.py](../../server/app/core/database.py) 已分支 `check_same_thread`、已有 `pool_pre_ping` | 只差 `pool_recycle` |
| 模型 | 全部 `String(N)` 显式长度；`Text` 长文本；无外键、无 server_default、无 JSON 列；默认值全 Python 侧 | 模型零改动 |
| 查询 | 所有 `db.execute()` 均为 `select()`/`update()` 构造，无原生 SQL、无 `func.now()`/strftime | 查询零改动 |
| 种子 | `run_seed` 幂等（空表才灌/账号判重） | 启动即兼容 |
| 时间 | `DateTime` + Python 侧 `datetime.now`；MySQL DATETIME 秒级精度（fsp=0），分配锁 120/180s 窗口下亚秒截断无害 | 不动 |
| 缺口 | 无 `pool_recycle`、无 utf8mb4 约定、compose 无 MySQL、存量 `data/app.db` 搬迁、零 MySQL 实测 | 本计划补齐 |

## Global Constraints

- 依赖版本锁定不动：fastapi==0.104.1、sqlalchemy==2.0.23、pymysql==1.1.0（不新增任何依赖）。
- MySQL 版本下限 5.7（`String(512)` 唯一索引在 utf8mb4 下 2048 字节，需 InnoDB DYNAMIC 行格式；部署统一 `mysql:8.0`）。
- 连接串统一携带 `?charset=utf8mb4`；compose 内 MySQL 启动参数强制 `--character-set-server=utf8mb4`。
- ORM 层禁止 MySQL 专有语法（既有约定，database.py 头注释；唯一例外是搬迁脚本里的 `ALTER TABLE ... AUTO_INCREMENT`）。
- 本机开发默认 `database_url = "sqlite:///./data/app.db"` 不变（config.py 默认值不动），MySQL 仅由部署环境注入。
- 测试套件默认跑内存 SQLite（conftest.py 不动）；MySQL 集成测试由 `TEST_MYSQL_URL` 环境变量门控，未设置时 SKIP。
- 每个 commit 前在 server/ 下 `python -m pytest -q` 全绿：基线 151 → 计划完成后 **156 passed, 4 skipped**（设 `TEST_MYSQL_URL` 时 160 passed）。
- commit 信息中文，风格随仓库（一行式，写清为什么）。

## File Structure

```
server/
  app/core/database.py          # 改：抽 build_engine()，MySQL 分支加 pool_recycle=3600
  scripts/                      # 新建包
    __init__.py                 # 新建（空）
    sqlite_to_mysql.py          # 新建：方言无关整库搬迁（copy_database + CLI）
  tests/
    test_mysql_integration.py   # 新建：1 个常跑单测 + 4 个 TEST_MYSQL_URL 门控集成测试
    test_sqlite_to_mysql.py     # 新建：搬迁脚本 sqlite→sqlite 全覆盖（常跑）
docker-compose.yml              # 改：加 db 服务（mysql:8.0 + healthcheck + 卷）+ backend 依赖
server/.env.docker              # 改：DATABASE_URL 切 MySQL
deploy/README.md                # 改：搬迁步骤、备份卷清单、密钥同步说明
README.md                       # 改：技术栈行
```

---

### Task 1: `build_engine()` 方言分支（pool_recycle）+ MySQL 集成测试骨架

**Files:**
- Modify: `server/app/core/database.py`
- Create: `server/tests/test_mysql_integration.py`

**Interfaces:**
- Produces: `build_engine(url: str) -> Engine`（server/app/core/database.py；SQLite 分支带 `connect_args={"check_same_thread": False}`，MySQL/其他分支带 `pool_recycle=3600`，公共参数 `pool_pre_ping=True, echo=False`）。Task 2/4 与部署验证直接依赖此函数行为。

- [ ] **Step 1: 写失败的单测（常跑，无门控）**

新建 `server/tests/test_mysql_integration.py`：

```python
# tests/test_mysql_integration.py —— MySQL 改造：引擎分支单测（常跑）+ TEST_MYSQL_URL 门控集成测试
# 集成测试起库：docker run -d --name zjpdt-mysql-test -e MYSQL_ROOT_PASSWORD=root123 \
#   -e MYSQL_DATABASE=zjpdt_test -p 33061:3306 mysql:8.0
# export TEST_MYSQL_URL='mysql+pymysql://root:root123@127.0.0.1:33061/zjpdt_test?charset=utf8mb4'
import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

MYSQL_URL = os.environ.get("TEST_MYSQL_URL", "")
requires_mysql = pytest.mark.skipif(
    not MYSQL_URL, reason="TEST_MYSQL_URL 未设置，跳过 MySQL 集成测试")


def test_build_engine_branches():
    """SQLite 分支允许跨线程复用连接；MySQL 分支带 pool_recycle 防 wait_timeout 断连"""
    import threading
    from app.core.database import build_engine

    sq = build_engine("sqlite://")
    assert sq.dialect.name == "sqlite"
    conn = sq.connect()
    result = {}

    def use_in_thread():
        try:
            conn.exec_driver_sql("SELECT 1")
            result["ok"] = True
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=use_in_thread)
    t.start()
    t.join()
    conn.close()
    sq.dispose()
    assert result["ok"] is True  # check_same_thread=False 生效

    my = build_engine("mysql+pymysql://u:p@127.0.0.1:3306/x?charset=utf8mb4")
    assert my.dialect.name == "mysql"
    assert my.pool._recycle == 3600  # QueuePool 回收参数（防 MySQL server has gone away）
    my.dispose()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && python -m pytest tests/test_mysql_integration.py -v`
Expected: FAIL，`ImportError: cannot import name 'build_engine'`

- [ ] **Step 3: 最小实现——重构 database.py**

`server/app/core/database.py` 全量替换为：

```python
"""
数据库连接管理模块
创建SQLAlchemy引擎和会话工厂，提供获取数据库会话的依赖项与建表入口
（移植自 audio-server-test/app/core/database.py，保持同步 engine；默认 SQLite，
 去掉 MySQL 专有的 SET time_zone 连接事件——本项目 ORM 层不得使用 MySQL 专有语法）
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings


def build_engine(url: str):
    """按 URL 方言选连接参数：SQLite 允许跨线程复用连接（FastAPI 同步端点跑线程池）；
    MySQL 加 pool_recycle（wait_timeout 默认 8h，低流量时段空闲连接会被服务端掐断）"""
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_recycle"] = 3600
    return create_engine(url, pool_pre_ping=True, echo=False, **kwargs)


# 创建数据库引擎
engine = build_engine(settings.database_url)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 所有模型的基类
Base = declarative_base()

def get_db():
    """
    依赖项函数：获取数据库会话
    在请求处理中使用，请求结束后自动关闭会话
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    """按当前 Base 元数据建表（已存在的表跳过，供 startup 调用）"""
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && python -m pytest tests/test_mysql_integration.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 追加 4 个门控集成测试（本步骤只验证 SKIP 行为，真机跑在 Task 4）**

在 `tests/test_mysql_integration.py` 末尾追加：

```python
@requires_mysql
def test_mysql_create_all_and_chinese_roundtrip():
    """建表 + utf8mb4 中文往返（出现问号/乱码即 charset 配错）"""
    from app.core.database import Base
    from app.models import Text, User

    eng = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        s.add(User(phone="33100400002", password_hash="x", real_name="测试民警",
                   region_code="331004"))
        s.add(Text(content="下雨了，衣裳好收收了", dialect="台州话",
                   category="日常用语", region_code="331004"))
        s.commit()
        assert s.query(User).one().real_name == "测试民警"
        assert s.query(Text).one().content == "下雨了，衣裳好收收了"
    Base.metadata.drop_all(eng)
    eng.dispose()


@requires_mysql
def test_mysql_unique_constraints_enforced():
    """unique 约束在 MySQL 上真实生效（users.phone、recordings(user_id,text_id)）"""
    from sqlalchemy.exc import IntegrityError
    from app.core.database import Base
    from app.models import Recording, Text, User

    eng = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        s.add(Text(content="上盘镇", dialect="台州话", category="日常用语",
                   region_code="331004"))
        s.flush()
        s.add(Recording(user_id=1, text_id=1, file_path="/x/1.wav", file_size=1,
                        duration=1.0, region_code="331004", dialect_code="dh331004"))
        s.commit()
        s.add(Recording(user_id=1, text_id=1, file_path="/x/2.wav", file_size=1,
                        duration=1.0, region_code="331004", dialect_code="dh331004"))
        with pytest.raises(IntegrityError):
            s.commit()
    Base.metadata.drop_all(eng)
    eng.dispose()


@requires_mysql()
def test_mysql_charset_and_phone_index():
    """连接字符集 utf8mb4 + users.phone 唯一索引在 MySQL 上存在"""
    from app.core.database import Base

    eng = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT @@character_set_client").scalar() == "utf8mb4"
    phone_idx = [ix for ix in inspect(eng).get_indexes("users")
                 if ix["column_names"] == ["phone"]]
    assert phone_idx and phone_idx[0]["unique"] is True
    Base.metadata.drop_all(eng)
    eng.dispose()


@requires_mysql
def test_mysql_copy_database_end_to_end(tmp_path):
    """搬迁脚本 sqlite→mysql 全链路：行数/主键保留 + 自增计数器顶到 max+1"""
    from app.core.database import Base
    from app.models import Region, User
    from scripts.sqlite_to_mysql import copy_database

    src = create_engine(f"sqlite:///{tmp_path}/src.db")
    Base.metadata.create_all(src)
    with sessionmaker(bind=src)() as s:
        s.add(Region(code="330000", name="浙江省", level="province"))
        s.add(User(phone="33100400002", password_hash="x", real_name="测试民警",
                   region_code="331004"))
        s.commit()

    dst = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(dst)
    counts = copy_database(src, dst)
    assert counts["regions"] == 1 and counts["users"] == 1
    with sessionmaker(bind=dst, expire_on_commit=False)() as s:
        assert s.get(User, 1).real_name == "测试民警"  # 主键 id 保留
        s.add(User(phone="33100400003", password_hash="x", real_name="民警二",
                   region_code="331004"))
        s.commit()
        assert s.query(User).filter_by(phone="33100400003").one().id == 2  # AUTO_INCREMENT 已顶起
    Base.metadata.drop_all(dst)
    src.dispose()
    dst.dispose()
```

Run: `cd server && python -m pytest tests/test_mysql_integration.py -v`
Expected: 1 passed, 4 skipped（第 4 个门控测试此刻 ImportError 属预期——scripts 包 Task 2 才建，SKIP 状态不触发导入）

- [ ] **Step 6: 全量回归 + commit**

Run: `cd server && python -m pytest -q`
Expected: 152 passed, 4 skipped（151 + 新 1；4 个门控 SKIP）

```bash
git add server/app/core/database.py server/tests/test_mysql_integration.py
git commit -m "MySQL 改造①：database.py 抽 build_engine 方言分支（SQLite 跨线程复用、MySQL 加 pool_recycle=3600 防 wait_timeout 断连）；新增 TEST_MYSQL_URL 门控集成测试骨架（无库环境 SKIP 不拖累常规套件）"
```

---

### Task 2: `scripts/sqlite_to_mysql.py` 整库搬迁脚本（TDD：sqlite→sqlite 常跑覆盖）

**Files:**
- Create: `server/scripts/__init__.py`（空文件）
- Create: `server/scripts/sqlite_to_mysql.py`
- Create: `server/tests/test_sqlite_to_mysql.py`

**Interfaces:**
- Consumes: `app.core.database.Base`（元数据 `sorted_tables` 拓扑序）
- Produces:
  - `copy_database(src: Engine, dst: Engine, batch_size: int = 500, force: bool = False) -> dict[str, int]`——整库搬迁，返回 {表名: 行数}；目标非空抛 `RuntimeError`（除非 `force=True` 先清空）
  - CLI：`python -m scripts.sqlite_to_mysql --sqlite ./data/app.db --mysql "mysql+pymysql://..." [--batch-size 500] [--force]`
  - Task 1 的门控测试 `test_mysql_copy_database_end_to_long` 直接调用 `copy_database`

- [ ] **Step 1: 写失败的 4 个测试**

新建 `server/tests/test_sqlite_to_mysql.py`：

```python
# tests/test_sqlite_to_mysql.py —— 搬迁脚本逻辑用 sqlite→sqlite 覆盖（方言无关），
# MySQL 侧的 ALTER TABLE AUTO_INCREMENT 分支由 test_mysql_integration.py 门控覆盖
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Region, User
from scripts.sqlite_to_mysql import copy_database


@pytest.fixture()
def src_engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        s.add(Region(code="330000", name="浙江省", level="province"))
        s.add(User(phone="33100400002", password_hash="x", real_name="测试民警",
                   region_code="331004"))
        s.commit()
    return eng


@pytest.fixture()
def dst_engine():
    return create_engine("sqlite://")  # 全新空库：create_all 由 copy_database 负责


def test_copy_preserves_rows_and_ids(src_engine, dst_engine):
    counts = copy_database(src_engine, dst_engine)
    assert counts["regions"] == 1 and counts["users"] == 1
    assert set(counts) >= {"regions", "users", "recordings", "qc_logs"}  # 元数据全部表都在
    with sessionmaker(bind=dst_engine)() as s:
        assert s.get(Region, "330000").name == "浙江省"  # 字符串主键保留
        assert s.get(User, 1).real_name == "测试民警"     # 整型主键 id 保留
        s.add(User(phone="33100400003", password_hash="x", real_name="民警二",
                   region_code="331004"))
        s.commit()
        assert s.query(User).count() == 2                 # 搬迁后可续插


def test_copy_refuses_nonempty_target(src_engine, dst_engine):
    copy_database(src_engine, dst_engine)
    with pytest.raises(RuntimeError, match="非空"):
        copy_database(src_engine, dst_engine)


def test_copy_force_overwrites(src_engine, dst_engine):
    copy_database(src_engine, dst_engine)
    counts = copy_database(src_engine, dst_engine, force=True)
    assert counts["users"] == 1                          # 清空重搬，不翻倍
    with sessionmaker(bind=dst_engine)() as s:
        assert s.query(User).count() == 1


def test_copy_empty_source_is_noop():
    src = create_engine("sqlite://")                     # 空源（无表）
    dst = create_engine("sqlite://")
    assert copy_database(src, dst) == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && python -m pytest tests/test_sqlite_to_mysql.py -v`
Expected: FAIL（collection error：`ModuleNotFoundError: No module named 'scripts'`）

- [ ] **Step 3: 实现 scripts 包**

新建空文件 `server/scripts/__init__.py`。

新建 `server/scripts/sqlite_to_mysql.py`：

```python
"""一次性数据搬迁：把 SQLite app.db 全部数据灌进 MySQL（实现方言无关，源/目标 URL 均可）。

用法（server 目录下）：
  python -m scripts.sqlite_to_mysql --sqlite ./data/app.db \
      --mysql "mysql+pymysql://zjpdt:密码@db:3306/zjpdt?charset=utf8mb4" [--force]

规则：
- 只搬"源库实际存在 且 在 Base 元数据中"的表，按元数据拓扑序逐表整搬；
- 目标缺失的表由脚本补建（fresh MySQL 库直接灌）；
- 显式带主键插入（保 id），整型自增主键搬完执行 ALTER TABLE ... AUTO_INCREMENT = max+1
  （sqlite 目标 rowid 自动跟随，跳过）；
- 目标任一表非空即中止（--force 先清空目标表再搬）。
"""
import argparse

from sqlalchemy import create_engine, func, inspect, select

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
            for name, table in pairs:  # 逆拓扑序删也无外键约束，顺序不敏感
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
                pk = list(table.primary_key.columns)
                if len(pk) == 1 and pk[0].autoincrement:
                    max_id = conn.execute(select(func.max(pk[0]))).scalar() or 0
                    conn.execute(__import__("sqlalchemy").text(
                        f"ALTER TABLE {name} AUTO_INCREMENT = {int(max_id) + 1}"))
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
```

注意：`__import__("sqlalchemy").text` 这种写法不可接受——实现时在文件头直接 `from sqlalchemy import text` 并用 `text(...)`（计划写作时的笔误，以本条为准）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd server && python -m pytest tests/test_sqlite_to_mysql.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 全量回归 + commit**

Run: `cd server && python -m pytest -q`
Expected: 156 passed, 4 skipped（152 + 4；门控 4 个仍 SKIP）

```bash
git add server/scripts/__init__.py server/scripts/sqlite_to_mysql.py server/tests/test_sqlite_to_mysql.py
git commit -m "MySQL 改造②：新增方言无关整库搬迁脚本 scripts/sqlite_to_mysql（显式主键保 id、目标非空守卫、MySQL 自增计数器顶 max+1、批量插入），sqlite→sqlite 四例常跑覆盖"
```

---

### Task 3: compose 加 db 服务 + .env.docker 切换 + 文档跟进

**Files:**
- Modify: `docker-compose.yml`
- Modify: `server/.env.docker:2`
- Modify: `deploy/README.md:50`
- Modify: `README.md:33`

**Interfaces:**
- Consumes: Task 1 的 `pool_recycle`（backend 容器对 db 的长连接）；Task 2 的搬迁脚本（deploy 文档引用其用法）。
- Produces: compose 服务 `db`（主机名 `db`，库名/用户 `zjpdt`）；卷 `mysql-data`；环境变量 `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD`（默认 `change-me-in-prod`，可用 shell 注入覆盖——沿用 SECRET_KEY 模式）。

- [ ] **Step 1: docker-compose.yml 加 db 服务**

在 `services:` 下 `backend:` 之前插入，并给 backend 加 `depends_on`（完整改动）：

```yaml
  db:
    image: mysql:8.0
    container_name: zjpdt-db
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-change-me-in-prod}
      MYSQL_DATABASE: zjpdt
      MYSQL_USER: zjpdt
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-change-me-in-prod}
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_general_ci
    volumes:
      - mysql-data:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h localhost -u root -p$$MYSQL_ROOT_PASSWORD --silent"]
      interval: 5s
      timeout: 3s
      retries: 30
    restart: unless-stopped
```

backend 服务追加：

```yaml
    depends_on:
      db:
        condition: service_healthy
```

文件末尾 `volumes:` 段追加一行：

```yaml
volumes:
  app-data:
  mysql-data:
```

- [ ] **Step 2: .env.docker 切 DATABASE_URL**

`server/.env.docker` 第 2 行 `DATABASE_URL=sqlite:////data/app.db` 改为：

```
# MySQL（主机名 db = compose 服务名；改 MYSQL_PASSWORD 时此处须同步）
DATABASE_URL=mysql+pymysql://zjpdt:change-me-in-prod@db:3306/zjpdt?charset=utf8mb4
```

- [ ] **Step 3: 文档跟进**

`deploy/README.md`（数据备份行附近）追加小节：

```markdown
### 存量数据搬迁（SQLite → MySQL，一次性）

老部署的 `/data/app.db`（app-data 卷内）数据搬入 MySQL：

```bash
docker compose up -d db                                # 先只起库
docker compose run --rm backend python -m scripts.sqlite_to_mysql \
    --sqlite /data/app.db --mysql "$DATABASE_URL"
docker compose up -d                                   # 起全家并验证登录
```

- 数据备份卷新增 `mysql-data`（MySQL 数据目录）；`app-data` 卷仍存音频/导出包/侧车台账。
- 改 MySQL 密码：`MYSQL_PASSWORD` 与 `.env.docker` 的 `DATABASE_URL` 两处必须同步。
```

`README.md:33` 技术栈行 `SQLite` 改为 `MySQL 8（开发默认 SQLite）`。

- [ ] **Step 4: 静态校验 compose**

Run: `cd e:/project/zj_police_dialect_trans && docker compose config >/dev/null && echo OK`
Expected: 输出 `OK`（无 YAML/插值错误；本机无 docker 时跳过本步，Task 4 真机验证）

- [ ] **Step 5: 全量回归（确认纯配置改动零影响）+ commit**

Run: `cd server && python -m pytest -q`
Expected: 156 passed, 4 skipped

```bash
git add docker-compose.yml server/.env.docker deploy/README.md README.md
git commit -m "MySQL 改造③：compose 加 mysql:8.0 服务（utf8mb4 强制、healthcheck、mysql-data 卷、backend 依赖就绪序）；.env.docker 切 MySQL URL；部署文档补存量搬迁步骤与备份卷变更"
```

---

### Task 4: 真机演练（一次性 MySQL 容器）+ 存量搬迁演练 + 全量验证

**Files:**
- 无代码改动（纯验证；若演练暴露问题，修复后重跑本任务各步并按仓库风格单独 commit）

**Interfaces:**
- Consumes: Task 1 门控测试（`TEST_MYSQL_URL`）、Task 2 搬迁脚本、Task 3 compose。
- Produces: 验证证据（测试输出、搬迁行数清单），作为「MySQL 改造完成」的判定依据。

- [ ] **Step 1: 起一次性 MySQL 测试库**

```bash
docker run -d --name zjpdt-mysql-test \
  -e MYSQL_ROOT_PASSWORD=root123 -e MYSQL_DATABASE=zjpdt_test -p 33061:3306 mysql:8.0
export TEST_MYSQL_URL='mysql+pymysql://root:root123@127.0.0.1:33061/zjpdt_test?charset=utf8mb4'
```

- [ ] **Step 2: 跑门控集成测试**

Run: `cd server && python -m pytest tests/test_mysql_integration.py -v`
Expected: **5 passed, 0 skipped**（含搬迁 E2E：中文往返 / unique 生效 / utf8mb4+索引 / 自增顶起）

- [ ] **Step 3: 存量搬迁演练（真实 schema + 真实种子数据）**

```bash
cd server && python - <<'EOF'
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.utils.seed import run_seed
eng = create_engine("sqlite:///./data/migrate_rehearsal.db")
Base.metadata.create_all(eng)
with sessionmaker(bind=eng)() as s:
    run_seed(s)
EOF
python -m scripts.sqlite_to_mysql --sqlite ./data/migrate_rehearsal.db --mysql "$TEST_MYSQL_URL" --force
```

Expected: 输出各表行数；其中 `regions`/`dialects`/`police_stations` 与 seed 数据一致，`users: 282`（1 超管 + 11 市管 + 90 县管 + 180 民警）。

清理：`rm server/data/migrate_rehearsal.db && docker rm -f zjpdt-mysql-test`

- [ ] **Step 4: 全量回归收尾**

Run: `cd server && python -m pytest -q`（清掉 `TEST_MYSQL_URL` 后跑，验证常规路径）
Expected: **156 passed, 4 skipped, 0 failed**

- [ ] **Step 5: （可选）compose 全家桶冒烟**

有 docker 环境时：`docker compose up -d --build` → `curl -k https://localhost/api/health` 返回 `{"status":"ok"}` → 用种子账号 `33000000001/123456` 登录成功（seed 在 MySQL 上幂等灌入）。无 docker 则留待部署机执行，deploy/README 冒烟清单一节已覆盖。

---

## Self-Review 记录

- **覆盖度**：代码层（Task 1）、数据层（Task 2）、部署层（Task 3）、验证层（Task 4）闭环；模型/查询层经摸排确认零改动，无对应任务（正确）。
- **占位符**：Task 2 Step 3 有一处笔误已在正文内显式更正（`text` 导入），无其他 TBD。
- **类型一致性**：`build_engine(url: str) -> Engine`、`copy_database(src, dst, batch_size=500, force=False) -> dict[str, int]`、`TEST_MYSQL_URL` 环境变量名在各任务间一致；测试计数链：151 → 152(+1) → 156(+4) → MySQL 环境下 160。
- **已知取舍**：DATETIME 秒级精度（亚秒截断对 120/180s 分配锁无害，不引入 fsp=6）；不自建 Alembic（沿用 create_all + 搬迁脚本，与仓库现状一致）。
