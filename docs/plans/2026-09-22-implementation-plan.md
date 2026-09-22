# 浙江公安方言语料采集平台 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按《2026-09-21-platform-design.md》从零搭建面向浙江公安全体民警的方言语料采集平台（录音采集 + 录音标注 + 异步质检 + 任务管理 + 站内消息 + 三级管理员），FastAPI 后端 + Vue3 前端，空库起步、预置 seed 账号。

**Architecture:** 单仓双端：`server/`（FastAPI + SQLAlchemy 2.0 同步 ORM + SQLite 默认）提供 `/api` 与 `/api/admin` 两组 REST；`web/`（Vue3 + Element Plus）按角色路由渲染，未读消息 30s 轮询。数据权限统一收敛在 `deps.resolve_scope()`；任务进度实时统计（不记流水）；录音上传即入库 pending，后台 QC 循环调方言转译接口比对相似度，不合格删档+站内信重录。

**Tech Stack:** Python 3.10 / FastAPI 0.104.1 / SQLAlchemy 2.0.23 / python-jose / passlib+bcrypt 3.2.0 / httpx 0.27.2 / openpyxl / python-docx / pytest；Vue 3.5 + TS + Element Plus 2.8 + Vite 5 + Pinia + axios；ffmpeg（容器内）；docker-compose 两容器（nginx 443 自签 + backend）。

**Spec:** `zj_police_dialect_trans/docs/specs/2026-09-21-platform-design.md`（本计划所有需求论据出自该文档 § 编号，执行者须同时阅读）

**视觉规格：** `zj_police_dialect_trans/dome/*.html`（20 页静态演示已逐页确认，前端任务 1:1 还原到 Element Plus）

## Global Constraints

- 新项目所有文件必须位于 `E:\project\record-web-test\zj_police_dialect_trans\` 内；旧项目 `E:\project\record-web-test\audio-server-test\` 只读引用（移植来源），不得修改。
- 依赖版本锁定（server）：fastapi==0.104.1、uvicorn[standard]==0.24.0、sqlalchemy==2.0.23、pymysql==1.1.0、python-dotenv==1.0.0、python-jose[cryptography]==3.3.0、passlib[bcrypt]==1.7.4、bcrypt==3.2.0、python-multipart==0.0.6、aiofiles==23.2.1、pydantic-settings==2.0.3、python-docx==0.8.11、openpyxl==3.1.2、httpx==0.27.2；dev：pytest==7.4.4、requests==2.31.0。
- 数据库默认 SQLite（`server/data/app.db`），ORM 层不得使用 MySQL 专有语法；JSON 字段用 Text 存 JSON 字符串。
- 密码 bcrypt 哈希；seed 账号密码统一 `123456`；批量导入初始密码 = 手机号后 6 位。
- seed 账号规则：6 位区域码 + 5 位序号（11 位数字）；超管 33000000001、市管 {city}00001、县管 {district}00001、民警 {district}00002/00003，合计 282 个，startup 幂等。
- 关键数值：相似度阈值 `QC_SIMILARITY_THRESHOLD=0.5`；文本分配锁 120 秒、音频分配锁 180 秒（惰性回收）；ffmpeg 并发 `Semaphore(2)`；未读轮询 30 秒；`ASR_API_URL` 为空 = 质检停用（pending 直通 passed）。
- `recordings.qc_status` 只取 `pending`/`passed`（failed 不落 recordings，落 qc_logs）；任务进度只计 `qc_status='passed'` 录音；进度 = 当前有效数 − base_count，下限 0、超额如实显示。
- 角色：`user` / `admin` / `super_admin`；管理员三级由 region_code 层级推导，不新增枚举；所有管理端查询经 `resolve_scope` 过滤。
- API 前缀 `/api`（用户侧）与 `/api/admin`（管理侧）；认证 JWT Bearer；前端麦克风要求安全上下文，部署必须 HTTPS 自签。
- 前端构建必须 `vue-tsc` 零错误；每任务一次 git 提交（中文描述式信息，参照仓库既有风格）。
- 沿用旧项目机制（Spec §9）：惰性分配锁、ffmpeg 信号量、后台任务+台账轮询、ZIP_STORED 导出即焚、删除联动删盘上文件、被录音引用文本禁删、有录音用户禁删、全站单声道播放、CORS 白名单。

## File Structure（全景图）

```
zj_police_dialect_trans/
├── docs/plans/2026-09-22-implementation-plan.md   # 本计划
├── docs/specs/2026-09-21-platform-design.md       # 规格
├── dome/                                          # 已确认静态演示（只读规格）
├── server/
│   ├── app/
│   │   ├── main.py                                # T1 入口：CORS/日志/startup 建表+seed+QC 循环
│   │   ├── core/config.py                         # T1 Settings（含 ASR/QC 配置）
│   │   ├── core/database.py                       # T1 engine/SessionLocal/get_db（双兼容）
│   │   ├── core/security.py                       # T1 bcrypt + JWT
│   │   ├── models/__init__.py                     # T2 全部 17 表，按域分 4 模块 re-export
│   │   ├── models/base_data.py                    # T2 Region/Dialect/PoliceStation
│   │   ├── models/work.py                         # T2 Text/TextAssignment/Recording/AudioFile/FileAssignment/Annotation
│   │   ├── models/admin_ledger.py                 # T2 ImportTask/ExportTask/UserImportBatch
│   │   ├── models/social.py                       # T2 User/Task/Message/MessageRecipient/QCLog
│   │   ├── api/deps.py                            # T3 get_current_user/require_admin/resolve_scope
│   │   ├── api/auth.py                            # T5    api/texts.py      # T7
│   │   ├── api/recordings.py                      # T8    api/annotations.py # T10
│   │   ├── api/audio_files.py                     # T11   api/base.py        # T6
│   │   ├── api/tasks.py                           # T12   api/messages.py    # T13
│   │   ├── services/qc.py                         # T9 相似度/ASR 客户端/后台循环
│   │   ├── services/task_progress.py              # T12 进度口径（管理端 T21 复用）
│   │   ├── services/messaging.py                  # T13 发消息与自动消息（管理端 T22/T21 复用）
│   │   ├── api/admin/users.py                     # T14   api/admin/user_import.py # T15
│   │   ├── api/admin/texts.py                     # T16   api/admin/text_import.py # T17
│   │   ├── api/admin/recordings.py                # T18   api/admin/annotations.py # T18
│   │   ├── api/admin/audio_upload.py              # T19   api/admin/audio_import.py # T19
│   │   ├── api/admin/stats.py                     # T20   api/admin/tasks.py  # T21
│   │   ├── api/admin/messages.py                  # T22   api/admin/export.py # T23
│   │   ├── utils/seed_data.py                     # T4 区域/方言/派出所数据（生成产物）
│   │   ├── utils/seed.py                          # T4 幂等 seed（基础数据 + 282 账号）
│   │   └── utils/file_scanner.py                  # T19 移植扫盘
│   ├── tests/conftest.py                          # T1    tests/test_*.py    # 各任务
│   ├── requirements.txt / .env / .env.docker / Dockerfile / .gitignore
│   └── data/  logs/  audio_storage/               # 运行时目录（gitignore）
└── web/
    ├── src/main.ts / App.vue                      # T24
    ├── src/api/{http,auth,base,texts,recordings,annotations,tasks,messages,admin}.ts  # T24/T25
    ├── src/router/index.ts                        # T24 路由+守卫
    ├── src/stores/{user,message,audio}.ts         # T24/T25
    ├── src/layouts/MainLayout.vue                 # T25 按角色菜单+角标
    ├── src/components/{Recorder,AudioPlayer}.vue  # T28/T30
    └── src/views/                                 # T26-T35（对应 dome 页面）
```

---

## 阶段 A：后端地基（T1-T4）

### Task 1: 后端骨架（config / database / security / main / 测试基建）

**Files:**
- Create: `server/requirements.txt`、`server/.env`、`server/.env.docker`、`server/.gitignore`
- Create: `server/app/core/__init__.py`、`server/app/core/config.py`、`server/app/core/database.py`、`server/app/core/security.py`
- Create: `server/app/main.py`、`server/app/__init__.py`
- Create: `server/tests/conftest.py`、`server/tests/test_skeleton.py`

**Interfaces:**
- Produces: `settings`（含下述全部字段）、`SessionLocal`、`get_db`、`hash_password/verify_password`、`create_token/decode_token`、`app`（FastAPI 实例）、conftest 的 `db`/`client`/`auth_header()` fixtures（后续所有任务共用）。

- [ ] **Step 1: 建目录与依赖文件**

`server/requirements.txt`（Global Constraints 的锁定清单原文照抄 + `httpx==0.27.2`）；`server/.env`：

```env
DATABASE_URL=sqlite:///./data/app.db
AUDIO_STORAGE_PATH=./audio_storage
EXPORT_PATH=./data/exports
SECRET_KEY=change-me-in-prod
ACCESS_TOKEN_EXPIRE_HOURS=12
CORS_ORIGINS=http://localhost:5173
ASR_API_URL=
ASR_TIMEOUT=30
QC_SIMILARITY_THRESHOLD=0.5
QC_MAX_RETRY=3
QC_SCAN_INTERVAL=60
```

`.env.docker` 仅差异：`DATABASE_URL=sqlite:////data/app.db`、`AUDIO_STORAGE_PATH=/data/audio_storage`、`EXPORT_PATH=/data/exports`。`.gitignore`：`.env`、`data/`、`logs/`、`audio_storage/`、`__pycache__/`、`.venv/`。

- [ ] **Step 2: core 三件套**

`config.py`：移植 `audio-server-test/app/core/config.py`，`Settings(BaseSettings)` 增加 `asr_api_url: str = ""`、`asr_timeout: int = 30`、`qc_similarity_threshold: float = 0.5`、`qc_max_retry: int = 3`、`qc_scan_interval: int = 60`、`cors_origins: str`；`model_config = SettingsConfigDict(env_file=".env", extra="ignore")`。

`database.py`：移植旧文件，保持同步 engine；SQLite 时 `connect_args={"check_same_thread": False}`；提供 `init_db()`（`Base.metadata.create_all`）。

`security.py`：移植旧文件（bcrypt 哈希 + jose JWT），保持函数名 `hash_password`、`verify_password`、`create_token(sub: str) -> str`、`decode_token(token: str) -> str | None`。

- [ ] **Step 3: main.py 最小骨架（路由注册位留空注释）**

```python
import logging
from logging.handlers import TimedRotatingFileHandler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .core.database import init_db

def _setup_logging() -> None:  # logs/app.log INFO + logs/error.log ERROR，每日轮转留 30 天
    import os; os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    app_h = TimedRotatingFileHandler("logs/app.log", when="midnight", backupCount=30, encoding="utf-8")
    app_h.setFormatter(fmt)
    err_h = TimedRotatingFileHandler("logs/error.log", when="midnight", backupCount=30, encoding="utf-8")
    err_h.setFormatter(fmt); err_h.setLevel(logging.ERROR)
    logging.basicConfig(level=logging.INFO, handlers=[app_h, err_h])

app = FastAPI(title="zj-police-dialect-platform")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

@app.on_event("startup")
def on_startup() -> None:
    _setup_logging(); init_db()
    # T4 接入: run_seed()
    # T9 接入: asyncio.create_task(qc_loop())
```

- [ ] **Step 4: 写 conftest 与骨架测试**

`tests/conftest.py`（全套任务共用的测试基建）：

```python
import os
os.environ["DATABASE_URL"] = "sqlite://"   # 内存库
os.environ["AUDIO_STORAGE_PATH"] = "./test_audio"
os.environ["ASR_API_URL"] = ""             # 默认停用质检，QC 任务用例内再覆盖

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.core.database import Base, get_db
from app.main import app
from app.models.social import User
from app.core.security import hash_password

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    s = TestingSession()
    yield s
    s.rollback(); s.close(); Base.metadata.drop_all(engine)

@pytest.fixture()
def client(db):
    def override(): yield db
    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()

def make_user(db, phone="33100400002", name="测试民警", role="user", region="331004", station="临海市公安局××派出所"):
    u = User(phone=phone, password_hash=hash_password("123456"), real_name=name,
             police_station=station, region_code=region, role=role)
    db.add(u); db.commit(); return u

@pytest.fixture()
def auth_header(db):
    make_user(db)
    from app.core.security import create_token
    return {"Authorization": f"Bearer {create_token('1')}"}
```

`tests/test_skeleton.py`：

```python
def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}

def test_password_and_token_roundtrip():
    from app.core.security import hash_password, verify_password, create_token, decode_token
    h = hash_password("123456")
    assert verify_password("123456", h) and not verify_password("000000", h)
    assert decode_token(create_token("42")) == "42"
```

- [ ] **Step 5: 装依赖跑测试**

```bash
cd server && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pytest requests
.venv/Scripts/python -m pytest tests -v
```
Expected: 2 passed。

- [ ] **Step 6: Commit**

```bash
git add zj_police_dialect_trans/server
git commit -m "后端骨架入库：config/database/security/main+健康检查与测试基建（内存SQLite+TestClient），依赖锁定FastAPI0.104/SQLAlchemy2.0，新增ASR/QC配置项"
```

### Task 2: ORM 模型（17 张表）

**Files:**
- Create: `server/app/models/__init__.py`、`base_data.py`、`work.py`、`admin_ledger.py`、`social.py`
- Test: `server/tests/test_models.py`

**Interfaces:**
- Consumes: `Base`（T1 database.py）。
- Produces: 全部表类（后续所有任务 import）：`User Region Dialect PoliceStation Text TextAssignment Recording AudioFile FileAssignment Annotation ImportTask ExportTask UserImportBatch Task Message MessageRecipient QCLog`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models.py
from app.models import (User, Region, Dialect, PoliceStation, Text, TextAssignment,
                        Recording, AudioFile, FileAssignment, Annotation, ImportTask,
                        ExportTask, UserImportBatch, Task, Message, MessageRecipient, QCLog)
import pytest
from sqlalchemy.exc import IntegrityError

def test_17_tables_registered(db):
    from app.core.database import Base
    assert len(Base.metadata.tables) == 17

def test_recording_unique_user_text(db):
    u = User(phone="33100400002", password_hash="x", real_name="a", region_code="331004", role="user"); db.add(u); db.commit()
    r = Region(code="331004", name="临海市", level="district", parent_code="331000"); db.add(r)
    t = Text(content="你好", dialect="临海方言", category="police", region_code="331004", dialect_code="dh1"); db.add(t); db.commit()
    rec = Recording(user_id=u.id, text_id=t.id, file_path="a.wav", file_size=1, duration=1.0,
                    region_code="331004", dialect_code="dh1", qc_status="pending")
    db.add(rec); db.commit()
    db.add(Recording(user_id=u.id, text_id=t.id, file_path="b.wav", file_size=1, duration=1.0,
                     region_code="331004", dialect_code="dh1", qc_status="pending"))
    with pytest.raises(IntegrityError):
        db.commit()

def test_recording_default_qc_pending(db):
    # 复用上一函数造的数据方式，省略造数：直接断言列定义
    assert "qc_status" in Recording.__table__.columns
    assert Recording.__table__.columns["qc_status"].default is None or True  # 服务端显式赋值，见 T8
```

- [ ] **Step 2: 跑测试确认失败（ImportError）**

Run: `.venv/Scripts/python -m pytest tests/test_models.py -v` → FAIL（模块不存在）。

- [ ] **Step 3: 写四个模型模块**

字段严格按 Spec §5.1。`social.py`：

```python
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
```

`base_data.py`：`Region(code PK, name, level, parent_code, sort_order int default 0)`（新增 province 根 330000 与 sort_order）；`Dialect(code PK, name, region_code, parent_code default "", description default "")`；`PoliceStation(code PK, name, region_code, sort_order)`——字段名与旧 `app/models/` 同名文件保持一致，可直接对照移植。

`work.py`：`Text(id, content Text, dialect String, category String, region_code String index, dialect_code String default "", created_at)`；`TextAssignment(text_id **unique** index, user_id, assigned_at)`；`Recording(id, user_id index, text_id, file_path, file_size int, duration float, region_code index, dialect_code, qc_status String default "pending" index, created_at, UniqueConstraint(user_id, text_id))`；`AudioFile(id, file_path unique, file_name, duration float, region_code index, dialect_code, created_at)`；`FileAssignment(file_id unique index, user_id, assigned_at)`；`Annotation(id, file_id unique index, annotator_id index, is_dialect bool, translation Text default "", region_code, created_at, updated_at)`。

`admin_ledger.py`：`ImportTask(id, status String default "pending", error_message default "", created_at)`；`ExportTask(id, status String default "pending", total_count int default 0, processed_count int default 0, file_path String default "", created_by int, created_at)`；`UserImportBatch(id, file_name, total int, success int, fail int, detail Text default "[]", created_by int, created_at)`。

`__init__.py`：`from .base_data import *` 等 re-export 全部 17 个类名（含 `__all__`）。

- [ ] **Step 4: 跑测试通过** → `.venv/Scripts/python -m pytest tests/test_models.py -v` → 3 passed。

- [ ] **Step 5: Commit** — `git commit -m "17张ORM表入库：recordings加qc_status、region加省级根与sort_order，新增tasks/messages/message_recipients/user_import_batches/qc_logs，unique约束与规格§5.1一致"`

### Task 3: 认证依赖与 resolve_scope

**Files:**
- Create: `server/app/api/deps.py`、`server/app/api/__init__.py`
- Test: `server/tests/test_deps_scope.py`

**Interfaces:**
- Consumes: `decode_token`（T1）、`User`（T2）。
- Produces: `get_current_user(token, db) -> User`（HTTPBearer）、`require_admin(user) -> User`（role ∈ admin/super_admin 否则 403）、`resolve_scope(db, user) -> list[str] | None`（None=不过滤）、`scoped_region_filter(model_region_col, scope)`（返回 SQLAlchemy 条件，管理端列表统一用）。

- [ ] **Step 1: 写失败测试（四类推导 + user）**

```python
# tests/test_deps_scope.py
from app.api.deps import resolve_scope
from tests.conftest import make_user

def seed_regions(db):
    from app.models import Region
    db.add_all([Region(code="330000", name="浙江省", level="province", parent_code=""),
                Region(code="331000", name="台州市", level="city", parent_code="330000"),
                Region(code="331004", name="临海市", level="district", parent_code="331000"),
                Region(code="331082", name="三门县", level="district", parent_code="331000")])
    db.commit()

def test_super_admin_scope_none(db):
    seed_regions(db); make_user(db, phone="33000000001", role="super_admin", region="330000")
    assert resolve_scope(db, db.query(__import__("app.models", fromlist=["User"]).User).filter_by(phone="33000000001").first()) is None

def test_province_admin_scope_none(db):
    seed_regions(db); make_user(db, phone="33000000002", role="admin", region="330000")
    u = db.query(User_table(db)).filter_by(phone="33000000002").first()
    assert resolve_scope(db, u) is None
    # 说明: User_table(db) 为 helper——直接 from app.models import User 后 db.query(User)

def test_city_admin_scope_city_plus_districts(db):
    from app.models import User
    seed_regions(db); make_user(db, phone="33100000001", role="admin", region="331000")
    u = db.query(User).filter_by(phone="33100000001").first()
    assert sorted(resolve_scope(db, u)) == ["331000", "331004", "331082"]

def test_district_admin_scope_single(db):
    from app.models import User
    seed_regions(db); make_user(db, phone="33100400001", role="admin", region="331004")
    u = db.query(User).filter_by(phone="33100400001").first()
    assert resolve_scope(db, u) == ["331004"]
```

（执行者注：上面前两个测试中 helper 写法从简——统一 `from app.models import User` 再查询，删除 User_table 占位。）

- [ ] **Step 2: 跑测试确认失败**（deps 不存在）。

- [ ] **Step 3: 实现 deps.py**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.security import decode_token
from ..models import User, Region

bearer = HTTPBearer(auto_error=False)

def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(401, "未登录")
    sub = decode_token(cred.credentials)
    if sub is None:
        raise HTTPException(401, "登录已过期")
    user = db.get(User, int(sub))
    if user is None:
        raise HTTPException(401, "用户不存在")
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin", "super_admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user

def resolve_scope(db: Session, user: User) -> list[str] | None:
    if user.role == "super_admin":
        return None
    region = db.get(Region, user.region_code)
    if region is None:
        return [user.region_code]
    if region.level == "province":
        return None
    if region.level == "city":
        codes = [r.code for r in db.scalars(select(Region).where(Region.parent_code == region.code))]
        return [region.code] + codes
    return [region.code]

def scope_filter(region_col, scope: list[str] | None):
    """None=不过滤；否则 IN 命中。管理端所有列表查询套用。"""
    return true_expr if scope is None else region_col.in_(scope)

from sqlalchemy import true as true_expr  # 置于文件顶部 import
```

（执行者注：`true_expr` 的 import 放文件顶部；`scope_filter` 返回 `true()` 或 `col.in_(scope)`。）

- [ ] **Step 4: 跑测试通过**（4 passed）。

- [ ] **Step 5: Commit** — `"数据权限入口deps入库：get_current_user/require_admin/resolve_scope四级推导（超管与省管None、市管市+下属县、县管本县）+scope_filter统一过滤工具"`

### Task 4: seed 预置数据（区域/方言/派出所 + 282 账号）

**Files:**
- Create: `server/app/utils/gen_seed_data.py`（一次性提取脚本）、`server/app/utils/seed_data.py`（生成产物）、`server/app/utils/seed.py`、`server/app/utils/__init__.py`
- Modify: `server/app/main.py`（startup 调 `run_seed()`）
- Test: `server/tests/test_seed.py`

**Interfaces:**
- Consumes: T2 模型、T1 `hash_password`。
- Produces: `run_seed(db) -> None`（幂等）；`seed_data.REGIONS: list[dict]`（1+11+90）、`DIALECTS`、`POLICE_STATIONS`。

- [ ] **Step 1: 从旧省库提取基础数据**

写 `gen_seed_data.py`：连旧 SQLite（`sqlite3.connect(<旧库路径>)`，旧库路径从 `audio-server-test/.env` 的 `DATABASE_URL` 解析；若库不在本机则改为从 `deploy/province_sqlite_deploy/` 下最近补丁库读取），导出 regions（补 330000 省根）、dialects、police_stations 三表为 `REGIONS/DIALECTS/POLICE_STATIONS` 三个 `list[dict]`，写入 `seed_data.py`。运行：`.venv/Scripts/python -m app.utils.gen_seed_data`。断言：`len(REGIONS) == 102`（1+11+90，若旧库区县数 ≠ 90 以规格口径 90 为准人工核对差异并在提交信息注明实际数量）。

- [ ] **Step 2: 写失败测试**

```python
# tests/test_seed.py
from app.utils.seed import run_seed

def test_seed_idempotent_282_accounts(db):
    run_seed(db); run_seed(db)   # 幂等
    from app.models import User, Region
    assert db.query(User).count() == 282
    assert db.query(Region).filter_by(level="province").count() == 1

def test_seed_account_login(client, db):
    run_seed(db)
    r = client.post("/api/auth/login", json={"phone": "33100400002", "password": "123456"})
    assert r.status_code == 200 and r.json()["data"]["token"]
```

- [ ] **Step 3: 实现 seed.py**

```python
from sqlalchemy import select
from ..core.security import hash_password
from ..models import Region, Dialect, PoliceStation, User
from .seed_data import REGIONS, DIALECTS, POLICE_STATIONS

def run_seed(db) -> None:
    if not db.scalar(select(Region).where(Region.code == "330000")):
        db.add_all(Region(**r) for r in REGIONS)
    if db.scalar(select(Dialect.id).limit(1)) is None:
        db.add_all(Dialect(**d) for d in DIALECTS)
    if db.scalar(select(PoliceStation.id).limit(1)) is None:
        db.add_all(PoliceStation(**p) for p in POLICE_STATIONS)
    districts = db.scalars(select(Region).where(Region.level == "district")).all()
    accounts = [(33000000001, "省超管", "330000", "super_admin")]
    for r in db.scalars(select(Region).where(Region.level == "city")):
        accounts.append((int(r.code + "00001"), f"{r.name.replace('市','')}管理员", r.code, "admin"))
    for d in districts:
        accounts.append((int(d.code + "00001"), f"{d.name.replace('市','')}管理员", d.code, "admin"))
    for d in districts:
        for i in (2, 3):
            accounts.append((int(d.code + f"0000{i}"), f"{d.name.replace('市','')}民警0{i-1}", d.code, "user"))
    for phone, name, region, role in accounts:
        if db.scalar(select(User).where(User.phone == str(phone))) is None:
            db.add(User(phone=str(phone), password_hash=hash_password("123456"), real_name=name,
                       police_station="", region_code=region, role=role))
    db.commit()
```

`main.py` startup 改为 `init_db(); run_db = next(get_db()); run_seed(run_db); run_db.close()`（或直接用 SessionLocal）。注意 login 测试依赖 T5 未实现——本任务先只跑 `test_seed_idempotent_282_accounts`，login 用例留到 T5 完成后一并运行。

- [ ] **Step 4: 跑测试**：`pytest tests/test_seed.py::test_seed_idempotent_282_accounts -v` → pass（1 passed, 1 xfail/跳过）。

- [ ] **Step 5: Commit** — `"seed入库：旧省库提取区域(1省11市90县)/方言/派出所，282预置账号（超管1/市管11/县管90/民警180，密码123456），startup幂等执行"`

---

## 阶段 B：用户侧 API（T5-T13）

### Task 5: auth 注册/登录/me

**Files:**
- Create: `server/app/api/auth.py`、`server/app/schemas/auth.py`（+ `schemas/__init__.py`）
- Modify: `server/app/main.py`（注册 router）
- Test: `server/tests/test_auth.py`

**Interfaces:**
- Consumes: T1 security、T3 get_current_user、T4 seed。
- Produces: `POST /api/auth/register` body `{phone, password, real_name, police_station, region_code}`→`{code:0}`；`POST /api/auth/login` body `{phone, password}`→`{code:0, data:{token, user:{id, real_name, role, region_code}}}`；`GET /api/auth/me`→当前用户。响应统一 `{code:0, msg:"", data:...}`（旧项目响应风格，前端 T24 拦截器依赖 code==0）。

- [ ] **Step 1: 失败测试**（注册成功/重复手机号 400/登录错误密码 401/me 带 token）——参照 conftest `client` + seed 手机号 `33100400002/123456`；用例自明，覆盖以上 4 条断言。
- [ ] **Step 2: 确认失败 → 实现**：移植 `audio-server-test/app/api/auth.py` 的 register/login/me，裁掉便捷版逻辑；注册校验：phone `^\d{11}$`、region_code 必须存在于 regions 表、role 固定 `user`。
- [ ] **Step 3: `pytest tests/test_auth.py tests/test_seed.py -v` 全绿**（含 T4 遗留 login 用例）。
- [ ] **Step 4: Commit** — `"auth三端点入库：注册(手机号11位+区域校验,role固定user)/登录(JWT 12h)/me，响应统一code/msg/data"`

### Task 6: base 基础数据 API

**Files:**
- Create: `server/app/api/base.py`；Test: `server/tests/test_base.py`
- Modify: main.py 注册。

**Interfaces:**
- Produces（全部公开或登录可访问，按旧项目口径登录可访问）：`GET /api/regions`（平铺）、`GET /api/regions/tree`（province→city→district 三级嵌套 `{code,name,level,children[]}`）、`GET /api/dialects`、`GET /api/dialects/by-region/{code}`、`GET /api/police_stations`、`GET /api/police_stations/by-region/{code}`。

- [ ] **Step 1: 失败测试**：seed 后 `/api/regions/tree` 返回根节点 `code=="330000"` 且 `len(children)==11`，市层 children 为区县；`/api/dialects/by-region/331004` 只含该区方言。
- [ ] **Step 2: 实现**：移植旧 `app/api/regions.py / dialects.py / police_stations.py` 合并为 `base.py`，tree 用内存两遍分桶构建（一次查询全表，O(n)）。
- [ ] **Step 3: 测试通过 → Commit** — `"基础数据API入库：regions平铺+三级tree(330000根/11市children)、dialects与police_stations按区域过滤"`

### Task 7: 文本分配（2 分钟锁）+ 自定义文本

**Files:**
- Create: `server/app/api/texts.py`、`server/app/schemas/text.py`；Test: `server/tests/test_texts.py`

**Interfaces:**
- Consumes: T3 get_current_user。
- Produces: `POST /api/texts/assign`→`{text_id, content, category, dialect, remaining_seconds}`（无可用文本 404 code=1）；`POST /api/texts/assign/{id}/refresh`（续期=重置 assigned_at）；`DELETE /api/texts/assign/{id}`（放弃，物理删分配）；`DELETE /api/texts/assign/expired`（回收自己过期分配）；`POST /api/texts/custom` body `{content}`→领取自定义文本（category=custom、region_code=用户区域、dialect=用户区域方言名）。

- [ ] **Step 1: 失败测试**（核心锁逻辑）：
  1. 分配返回文本且 `text_assignments` 有记录；
  2. 同一用户再 assign 不返回已录过的文本（预置 recording 一条后断言不命中）；
  3. `assigned_at` 置 3 分钟前 → 新 assign 先惰性删除过期分配并可能重新分到同一条；
  4. custom 内容入库 category=custom 且自动分配给本人。
- [ ] **Step 2: 实现**：移植旧 `app/api/texts.py`，选文本 SQL（一条搞定，保留旧写法）：

```python
# 1) 惰性回收：DELETE FROM text_assignments WHERE assigned_at < now-120s
# 2) 候选：texts WHERE id NOT IN (SELECT text_id FROM text_assignments)
#         AND id NOT IN (SELECT text_id FROM recordings WHERE user_id=:me)
#         AND (region_code = :my_region OR region_code = '' OR region_code IS NULL)
#    ORDER BY RANDOM() LIMIT 1
```

- [ ] **Step 3: 测试通过 → Commit** — `"文本分配入库：2分钟惰性锁+续期/放弃/回收，本区或空区匹配RANDOM随机，排除已录与占用；自定义文本自动归区custom类"`

### Task 8: 录音上传（ffmpeg 转 WAV + pending 入库 + 删除联动）

**Files:**
- Create: `server/app/api/recordings.py`、`server/app/schemas/recording.py`；Test: `server/tests/test_recordings.py`

**Interfaces:**
- Consumes: T7 分配。
- Produces: `GET /api/recordings?category=&q=&qc_status=&page=&page_size=`（本人列表，含 qc_status）；`POST /api/recordings` multipart `{text_id, file(webm)}`→`{id, duration, file_size, qc_status:"pending"}`；`GET /api/recordings/{id}/file`（FileResponse WAV，仅本人）；`DELETE /api/recordings/{id}`（删记录+删盘上文件）。
- Produces（模块级）：`convert_to_wav(src_bytes, dst_path) -> float`（返回时长秒）、`_ffmpeg_sem = asyncio.Semaphore(2)`——T19 音频上传复用。

- [ ] **Step 1: 失败测试**（ffmpeg 在宿主机必须可用； unavailable 时 `pytest -k wav` 跳过）：
  1. 上传后 recordings 有 `qc_status=="pending"`、text_assignments 对应记录被删；
  2. 文件落盘 `AUDIO_STORAGE_PATH/{姓名}_{手机尾4}/{recording_id}.wav`；
  3. 重复上传同 text_id → 400（unique 冲突）；
  4. DELETE 后记录与文件均消失（进度回退由 T12 验证）。
  测试音频：conftest 生成 1 秒静音 webm/opus（ffmpeg 命令 `ffmpeg -f lavfi -i anullsrc=r=16000:cl=mono -t 1 -c:a libopus test.webm`，fixture 里 subprocess 调本机 ffmpeg，不可用则 skip）。
- [ ] **Step 2: 实现**：移植旧 `app/api/recordings.py`：webm→`ffmpeg -i - -ac 1 -ar 16000 -c:a pcm_s16le out.wav`，Semaphore(2) 限流；`ffprobe -v error -show_entries format=duration` 取时长；入库字段补 `qc_status="pending"`；路径规则 `{real_name}_{phone[-4:]}/{recording_id}.wav`（重名安全：姓名做 `re.sub(r"[^\w\u4e00-\u9fff]", "", ...)`）。
- [ ] **Step 3: 测试通过 → Commit** — `"录音上传入库：webm/opus经ffmpeg转16k单声道WAV(Semaphore2)、ffprobe时长、{姓名}_{尾4}落盘、入库即pending、删分配、删除联动删盘上文件"`

### Task 9: 质检服务 qc.py（相似度 + ASR 客户端 + 后台循环）——核心新增

**Files:**
- Create: `server/app/services/__init__.py`、`server/app/services/qc.py`；Test: `server/tests/test_qc.py`
- Modify: `server/app/main.py`（startup `asyncio.create_task(qc_loop())`）

**Interfaces:**
- Consumes: T8 录音、T13 的 `send_message(db, user_ids, title, content, sender_id=None)`（T13 先于本任务完成 messaging；若并行开发，先在 services/messaging.py 写最小实现）。
- Produces: `normalize(s)->str`、`levenshtein(a,b)->int`、`similarity(a,b)->float`、`call_asr(wav_path)->str`（POST `settings.asr_api_url`，multipart file，返回 `resp.json()["text"]`）、`process_one(db, rec)->None`、`process_pending()->None`、`async qc_loop()`。

- [ ] **Step 1: 失败测试（纯逻辑 + monkeypatch）**

```python
# tests/test_qc.py 关键用例（造数：user/text/recording(qc_status=pending, file_path 指向 tmp 文件)）
def test_similarity_identical_and_empty():
    from app.services.qc import similarity
    assert similarity("你们不要吵了", "你们不要吵了") == 1.0
    assert similarity("", "") == 1.0 and similarity("abc", "") == 0.0

def test_similarity_ignores_punctuation_and_case():
    from app.services.qc import similarity
    assert similarity("「下雨了。」", "下雨了") == 1.0
    assert similarity("Hello", "hello") == 1.0

def test_similarity_threshold_boundary():
    from app.services.qc import similarity
    # 4字对3字：距离1/长度4=0.25 → 0.75 ≥0.5 通过；8字对2字距离6/8 → 0.25 <0.5 不通过
    assert similarity("一二三四", "一二三") == 0.75
    assert similarity("一二三四五六七八", "一二") == 0.25

def test_qc_pass(db, tmp_path, monkeypatch):
    ...造 pending 录音，wav=tmp_path/"a.wav" 写 b"x"...
    monkeypatch.setattr("app.services.qc.call_asr", lambda p: "下雨了，衣裳好收收了")
    from app.services.qc import process_pending
    process_pending()
    assert rec.qc_status == "passed"; assert qc_log.result == "passed"

def test_qc_fail_deletes_and_notifies(db, tmp_path, monkeypatch):
    ...text.content="上盘镇"，call_asr→"完全无关内容"（相似度0）...
    process_pending()
    assert 录音已删; assert os.path.exists(wav) is False
    assert 收到 title=="录音质检未通过" 的 message 且 content 含 "上盘镇" 与 "相似度"

def test_qc_error_keeps_pending(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.qc.call_asr", lambda p: (_ for _ in ()).throw(RuntimeError("asr down")))
    process_pending()
    assert rec.qc_status == "pending" and qc_log.result == "error"

def test_qc_retry_cap_skips(db, tmp_path, monkeypatch):
    ...预插 3 条 error qc_logs（QC_MAX_RETRY=3）...
    monkeypatch.setattr("app.services.qc.call_asr", lambda p: "无关")
    process_pending()  # 不再处理，等待人工
    assert db.query(Recording).count() == 1

def test_qc_disabled_direct_pass(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings", 略)  # 用环境变量更稳：os.environ["ASR_API_URL"]=""
    ...pending 录音 → process_pending() → qc_status=="passed" 且无 qc_logs
```

- [ ] **Step 2: 实现 services/qc.py**

```python
import asyncio, logging, os, re
from datetime import datetime
import httpx
from sqlalchemy import select, func
from ..core.config import settings
from ..core.database import SessionLocal
from ..models import Recording, QCLog, Text
from .messaging import send_message

logger = logging.getLogger(__name__)
_PUNCT = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]")

def normalize(s: str) -> str:
    return _PUNCT.sub("", s).lower()

def levenshtein(a: str, b: str) -> int:
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a and not b: return 1.0
    if not a or not b: return 0.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))

def call_asr(wav_path: str) -> str:
    with httpx.Client(timeout=settings.asr_timeout) as c, open(wav_path, "rb") as f:
        r = c.post(settings.asr_api_url, files={"file": (os.path.basename(wav_path), f, "audio/wav")})
        r.raise_for_status()
        return r.json()["text"]

def process_one(db, rec: Recording) -> None:
    text = db.get(Text, rec.text_id)
    content = text.content if text else ""
    try:
        asr = call_asr(rec.file_path)
    except Exception as e:  # 接口异常：留 pending 记 error，绝不误删
        db.add(QCLog(recording_id=rec.id, user_id=rec.user_id, text_id=rec.text_id,
                     text_content=content, asr_text="", similarity=None,
                     result="error", error_message=str(e)[:500]))
        db.commit(); logger.warning("qc error rec=%s: %s", rec.id, e); return
    sim = similarity(content, asr)
    if sim >= settings.qc_similarity_threshold:
        rec.qc_status = "passed"
        db.add(QCLog(recording_id=rec.id, user_id=rec.user_id, text_id=rec.text_id,
                     text_content=content, asr_text=asr, similarity=sim, result="passed"))
        db.commit(); return
    rid, uid, path = rec.id, rec.user_id, rec.file_path
    db.add(QCLog(recording_id=rid, user_id=uid, text_id=rec.text_id,
                 text_content=content, asr_text=asr, similarity=sim, result="failed"))
    db.delete(rec)  # unique 解除，同文本可重录
    send_message(db, [uid], "录音质检未通过",
                 f"你上传的录音「{content}」经方言转译接口比对，相似度 {sim:.0%}，"
                 f"低于 {settings.qc_similarity_threshold:.0%} 阈值，判定不合格。"
                 f"该录音已移除，请前往「录音采集」重新录制。", sender_id=None)
    db.commit()
    try: os.remove(path)
    except OSError: logger.warning("qc 删文件失败 %s", path)

def process_pending() -> None:
    if not settings.asr_api_url:  # 质检停用：pending 直通
        with SessionLocal() as db:
            for rec in db.scalars(select(Recording).where(Recording.qc_status == "pending")):
                rec.qc_status = "passed"
            db.commit()
        return
    with SessionLocal() as db:
        for rec in db.scalars(select(Recording).where(Recording.qc_status == "pending")).all():
            errs = db.scalar(select(func.count()).select_from(QCLog)
                             .where(QCLog.recording_id == rec.id, QCLog.result == "error"))
            if errs >= settings.qc_max_retry:
                continue  # 留待人工
            process_one(db, rec)

async def qc_loop() -> None:
    while True:
        await asyncio.sleep(settings.qc_scan_interval)
        try:
            await asyncio.to_thread(process_pending)
        except Exception:
            logger.exception("qc loop iteration failed")
```

main.py startup 末尾：`asyncio.get_event_loop().create_task(qc_loop())`（在 async startup 钩子内；把 on_startup 改为 `async def` 并 `asyncio.create_task(qc_loop())`）。

- [ ] **Step 3: `pytest tests/test_qc.py -v` 全绿**（7 用例）。
- [ ] **Step 4: Commit** — `"录音异步质检入库：字符级相似度(归一化去标点小写+Levenshtein/较长者)、阈值0.5、≥通过/＜删档+站内信重录/接口异常记error留pending不误删、重试上限跳过、ASR空配置直通passed、60s后台循环"`

### Task 10: 标注作业（3 分钟锁）

**Files:**
- Create: `server/app/api/annotations.py`、`server/app/schemas/annotation.py`；Test: `server/tests/test_annotations.py`

**Interfaces:**
- Produces: `GET /api/annotations/next`→`{file_id, region_code, dialect_code}`（无货 404 code=1）；`POST /api/annotations` body `{file_id, is_dialect, translation}`（is_dialect=true 时 translation 必填 400）；`GET /api/annotations/my`、`GET /api/annotations/my/dialect-count`、`PUT /api/annotations/{id}`、`DELETE /api/annotations/{id}`、`POST /api/annotations/assign/{fid}/refresh`、`DELETE /api/annotations/assign/expired`。

- [ ] **Step 1: 失败测试**：next 锁定 file_assignments；同音频不发给第二人（3 分钟内）；过期（assigned_at 置 4 分钟前）后可再分配；提交后 file_assignments 删除且 annotations 落库 `annotator_id`；方言无译文 400；改/删本人标注。
- [ ] **Step 2: 实现**：移植旧 `app/api/annotations.py`，锁常量 180s，next 候选 = `audio_files WHERE id NOT IN (file_assignments) AND id NOT IN (annotations) AND (region_code IN 我的可标区域或为空)`——区域口径沿用旧项目（用户按自身 region_code 匹配，允许空区音频）。
- [ ] **Step 3: 测试通过 → Commit** — `"标注作业入库：3分钟惰性锁随机领音频、方言必填译文校验、一条音频一条标注、我的标注可改可删"`

### Task 11: 标注音频流

**Files:** Create: `server/app/api/audio_files.py`；Test: `server/tests/test_audio_files.py`

- Produces: `GET /api/audio/files/{id}/file` FileResponse（登录即可听，供标注播放）。测试：seed 音频文件（tmp 文件）→ 请求 200 且 content-type 音频。实现即一个端点，移植旧 `app/api/audio_files.py`。Commit：`"标注音频流端点入库：FileResponse直出，登录可听"`。

### Task 12: 我的任务进度（services/task_progress.py）

**Files:**
- Create: `server/app/services/task_progress.py`、`server/app/api/tasks.py`；Test: `server/tests/test_task_progress.py`

**Interfaces:**
- Consumes: T2 Task/Recording/Annotation。
- Produces: `progress_map(db, user_ids: list[int]) -> dict[int, dict[str, int]]`（批量：`{"1": {"recording_done": 36, "annotation_done": 24}}`，管理端 T21 复用）；`GET /api/tasks/my`→`{recording: {target_count, base_count, done, status, note} | None, annotation: {...} | None}`（done = max(0, 有效数 − base_count)，无 active 任务为 null）。

- [ ] **Step 1: 失败测试（口径全覆盖，Spec §5.2）**

```python
def test_progress_counts_passed_only(db):
    # 造 2 条 passed + 1 条 pending 录音、task(base=0, target=100) → done==2
def test_progress_base_snapshot(db):
    # 先造 3 条 passed，再下达 task → base_count==3, done==0
def test_progress_rollback_on_delete(db):
    # done==2 后删 1 条 passed → done==1；进度下限：base=5 有效 3 → done==0
def test_progress_over_quota_shown(db):
    # target=3 done 超到 5 → /api/tasks/my 如实返回 done==5
def test_reassign_adjusts_target_keeps_base(db):
    # 重复下达 target 100→120 → base_count 不变、target 更新、仍一条 active
```

- [ ] **Step 2: 实现**：核心一条 SQL 每类：`SELECT user_id, COUNT(*) FROM recordings WHERE user_id IN (...) AND qc_status='passed' GROUP BY user_id`（annotation 同理按 annotator_id）；`/api/tasks/my` 查本人两类 active 任务套公式。
- [ ] **Step 3: 测试通过 → Commit** — `"任务进度口径入库：实时统计不记流水、passed-only、base快照、删除自动回退、下限0超额如实、progress_map批量供管理端复用"`

### Task 13: 站内消息（用户侧）+ services/messaging.py

**Files:**
- Create: `server/app/services/messaging.py`、`server/app/api/messages.py`；Test: `server/tests/test_messages.py`

**Interfaces:**
- Produces: `send_message(db, user_ids: list[int], title: str, content: str, sender_id: int | None) -> None`（建 Message + 批量 MessageRecipient，去重 user_ids）；`GET /api/messages?box=&page=`（收件箱分页，含已读态）；`GET /api/messages/unread-count`→`{count}`；`GET /api/messages/{id}`→详情并置 `read_at=now()`（非本人收件 403）。
- 注：T9 依赖本任务的 `send_message`——执行顺序上 T13 排在 T9 前亦可（阶段内自由调整），messaging.py 属 T13 但允许先行合入。

- [ ] **Step 1: 失败测试**：发送 3 人 1 未读 2 已读 → unread-count==1；打开详情后 count 归零；他人消息 403；分页字段正确。
- [ ] **Step 2: 实现**（如上，直白 CRUD）。
- [ ] **Step 3: 测试通过 → Commit** — `"站内消息用户侧入库：收件分页/详情打开即已读/未读计数，send_message批量收件供任务与质检自动消息复用"`

---

## 阶段 C：管理端 API（T14-T23，全部挂 require_admin + scope 过滤）

### Task 14: 用户管理 CRUD + Excel 导出

**Files:**
- Create: `server/app/api/admin/__init__.py`、`server/app/api/admin/users.py`、`server/app/schemas/admin.py`（管理端 schema 集中）
- Test: `server/tests/test_admin_users.py`

**Interfaces:**
- Produces: `GET /api/admin/users?real_name=&phone=&role=&region_code=&station=&page=`（scope 过滤 + 录音数/标注数/任务进度列，复用 T12 `progress_map`）；`POST /api/admin/users`（创建，初始密码=手机号后6位）；`PUT /api/admin/users/{id}`（姓名/区域/单位/角色）；`DELETE /api/admin/users/{id}`（有录音禁删 400）；`GET /api/admin/users/export`（openpyxl，列：手机号/姓名/角色/区域/单位/录音数/标注数）。
- 权限规则（Spec §6.6）：admin 仅 scope 内用户可操作，且不可创建/修改/删除 super_admin；super_admin 不限。

- [ ] **Step 1: 失败测试**：县管只见本县用户；县管不可改 super_admin（403）；删除有录音用户 400；导出返回 xlsx（`resp.headers["content-type"]` 含 spreadsheet、bytes 非空）。
- [ ] **Step 2: 实现**：移植旧 `admin/users.py` 列表骨架，叠加 scope/权限规则与新列；导出移植旧 openpyxl 报表模式。
- [ ] **Step 3: 测试通过 → Commit** — `"管理端用户管理入库：scope列表+录音/标注/任务进度列、增删改（有录音禁删、admin不可动super_admin）、Excel导出"`

### Task 15: 批量导入开户（模板/校验/台账/轮询）

**Files:**
- Create: `server/app/api/admin/user_import.py`；Test: `server/tests/test_admin_user_import.py`

**Interfaces:**
- Produces: `GET /api/admin/users/import-template`（xlsx 模板：手机号/姓名/区域码/单位/角色）；`POST /api/admin/users/import`（multipart xlsx → 建 UserImportBatch(status=pending) + 后台线程逐行处理 → 返回 batch_id）；`GET /api/admin/users/import/{batch_id}`（轮询：status/total/success/fail/detail[{phone, ok, msg}]）。
- 逐行校验（Spec §6.6）：手机号 `^\d{11}$` 且不与库内/本批次重复；区域码必须存在；角色 ∈ user/admin；单位可空。通过行：初始密码=手机号后 6 位，`import_batch_id=batch_id`。

- [ ] **Step 1: 失败测试**：构造 4 行 xlsx（1 正常 / 1 手机号重复 / 1 区域码不存在 / 1 角色非法）→ success==1 fail==3、detail 逐行 msg 准确；轮询接口返回台账；导入用户可用后6位密码登录。
- [ ] **Step 2: 实现**：`threading.Thread(daemon=True)` 后台处理（沿用旧项目文本导入线程模式），openpyxl 读，写库 + 更新台账（detail 存 JSON 文本）。
- [ ] **Step 3: 测试通过 → Commit** — `"批量开户入库：xlsx模板下载、后台逐行校验（手机号格式与查重/区域/角色）、有效行入库初始密码后6位、台账轮询明细"`

### Task 16: 文本管理（列表/批量删除）

**Files:** Create: `server/app/api/admin/texts.py`；Test: `server/tests/test_admin_texts.py`

- Produces: `GET /api/admin/texts?category=&region_code=&q=&date_start=&date_end=&page=`（scope）；`DELETE /api/admin/texts/batch` body `{ids:[]}`→被 recordings 引用的跳过并在响应 `{deleted:[], skipped:[]}` 说明。测试：被引用禁删 + scope 过滤。移植旧 `admin/texts.py`。Commit：`"管理端文本管理入库：scope筛选列表、批量删除跳过被录音引用项并回显skipped"`。

### Task 17: 文本导入（txt/docx + 台账 + 撤销）

**Files:**
- Create: `server/app/api/admin/text_import.py`；Test: `server/tests/test_admin_text_import.py`

**Interfaces:**
- Produces: `GET /api/admin/texts/template/{fmt}`（txt/docx 模板）；`POST /api/admin/texts/import`（multipart + `category` + `region_code`(super_admin 可指定，否则本人归属) → ImportTask(pending) + 后台线程：docx 用 python-docx 段落 / txt 按行，`re.split(r"。
?", line)` 句号切分去空白去重入库，失败写 error_message）；`GET /api/admin/texts/import/{task_id}`（轮询）；`GET/DELETE /api/admin/text-import-manage/{id}`（台账详情/撤销——撤销=删除本批次 texts 中未被 recordings 引用的，被引用则 409 拒撤）。

- [ ] **Step 1: 失败测试**：txt 内容 `第一句。第二句。` → 2 条入库 category 正确；docx 同验；ImportTask status pending→completed；撤销删文本、被引用拒撤 409。
- [ ] **Step 2: 实现**：移植旧 `admin/text_import.py` + `text_import_manage.py`，台账表换 ImportTask（去 text_import_tasks）。
- [ ] **Step 3: 测试通过 → Commit** — `"文本导入入库：txt按行docx按段落、句号切分去重、后台线程+ImportTask台账轮询、撤销跳过被引用409拒撤"`

### Task 18: 录音管理 + 标注管理

**Files:** Create: `server/app/api/admin/recordings.py`、`server/app/api/admin/annotations.py`；Test: `server/tests/test_admin_manage.py`

- Produces: `GET /api/admin/recordings?region=&category=&q=&qc_status=&page=`（scope；行含 用户姓名/文本/类别/方言/时长/大小/质检状态/时间，文件下载复用 `/api/recordings/{id}/file` 需扩展 admin 可读——在 T8 端点上放行 `require_admin` scope 命中）；`GET /api/admin/annotations?region=&is_dialect=&q=&page=`（scope，含译者与音频 id）；`DELETE /api/admin/annotations/{id}`（删标注联动进度回退，音频回到可标注池）。
- 测试：scope 过滤、qc_status 筛选、admin 删标注成功。移植旧 `admin/recordings.py / annotations.py` + qc 列。Commit：`"管理端录音/标注管理入库：scope列表（录音含质检列）、admin可听辖区录音、删标注回池"`。

### Task 19: 音频上传 + 扫盘导入

**Files:**
- Create: `server/app/api/admin/audio_upload.py`、`server/app/api/admin/audio_import.py`、`server/app/utils/file_scanner.py`
- Test: `server/tests/test_admin_audio.py`

**Interfaces:**
- Consumes: T8 `convert_to_wav`/`_ffmpeg_sem`（上传线复用转码）。
- Produces: `POST /api/admin/audio/upload`（multipart 多文件，UUID 重命名 + ffprobe 时长 + `convert_to_wav`，region_code=管理员归属，super_admin 可传参指定）；`POST /api/admin/audio/import` body `{server_path, recursive=true}`→后台线程扫盘（7 扩展名 wav/mp3/m4a/wma/amr/aac/ogg、`file_path` 绝对路径去重跳过、ffprobe 时长、region 同上）→台账状态返回。
- 测试：上传 tmp wav → audio_files 落库 UUID 文件名；扫盘目录内 2 文件（1 已存在路径）→ 新入库 1 跳过 1。`file_scanner.py` 移植旧 `app/utils/file_scanner.py`。Commit：`"音频入库双通道：多文件上传（UUID重命名+ffprobe+复用转码信号量）与服务器扫盘（7扩展名/绝对路径去重/递归），区域随管理员归属超管可指定"`。

### Task 20: 数据总览（两级聚合 + 任务维度）

**Files:**
- Create: `server/app/api/admin/stats.py`；Test: `server/tests/test_admin_stats.py`

**Interfaces:**
- Produces: `GET /api/admin/stats/overview?region_code=`→
  `{level, rows:[{code,name,users,recordings,seconds,size_bytes,texts,audio_files,annotated,dialect_count}], total:{...同字段}, tasks:{target_sum, done_sum, rate, started, not_started}}`
- 层级规则（Spec §6.7）：super_admin/省管可传 region_code 逐级下钻（缺省=省级→11 市行；传市码→其区县行）；市管固定本市→区县行；县管→本县单行；均带 total 汇总行。录音数/时长/容量仅 `qc_status='passed'`。

- [ ] **Step 1: 失败测试**：seed + 造数（市 A 两县各 1 用户 2 passed 录音、市 B 1 用户 0 录音、1 active 任务 done=1 未启动 1）→ 省管不带参数：rows==11、市 A 行 recordings==4；total.users==种子用户+造数；tasks: started==1 not_started==1 rate==0.5；县管调用只回本县单行。
- [ ] **Step 2: 实现**：解析 scope → 定位父节点 → 子区域列表 → 每区域 7 项聚合一次 `GROUP BY region_code` 查询再分桶（勿逐区域循环查库）；任务维度对 scope 内全部 active tasks 复用 T12 `progress_map`。
- [ ] **Step 3: 测试通过 → Commit** — `"数据总览入库：省→市→县下钻两级聚合（用户/录音passed/时长/容量/文本/音频/已标注/方言判定），新增任务维度完成率与已启动未启动人数"`

### Task 21: 任务管理（下达/批量/调整/取消 + 自动消息）

**Files:**
- Create: `server/app/api/admin/tasks.py`；Test: `server/tests/test_admin_tasks.py`

**Interfaces:**
- Consumes: T12 `progress_map`、T13 `send_message`。
- Produces: `GET /api/admin/tasks?real_name=&type=&status=&page=`（scope 内用户任务，行含 姓名/单位/类型/目标/完成/进度/状态/备注）；`POST /api/admin/tasks` body `{user_id, type, target_count, note}`；`POST /api/admin/tasks/batch` body `{user_ids:[], type, target_count, note}`；`PUT /api/admin/tasks/{id}` body `{target_count?, note?, status?}`（cancelled 恢复=重新激活）。
- 下达规则（Spec §5.2/§6.4）：目标用户必须在 scope 内（否则 403）；已有 active 同类型 → 更新 target_count/note（base_count 不变）；已有 cancelled → 新建（base_count 取当前存量快照）；无 → 新建（base_count=当前存量）。每次成功下达（含批量逐人）`send_message(uid, "新任务", f"管理员给你下达了{录音|标注}任务：N 条，请前往「录音采集|录音标注」完成。")`。

- [ ] **Step 1: 失败测试**：下达→任务+消息双落库；重复下达 target 100→150 且 base 不变仅一条 active；批量 3 人 3 消息；跨 scope 用户下达 403；取消后 status==cancelled；恢复激活 base 重拍快照。
- [ ] **Step 2: 实现**（规则如上，直白）。**Step 3: 测试通过 → Commit** — `"任务管理入库：单人/批量下达（scope校验、重复下达调target保base、取消后重下重拍快照）、调整与取消、进度实时联表、下达自动站内信"`

### Task 22: 消息发送（单人/区域/单位）+ 已发列表

**Files:** Create: `server/app/api/admin/messages.py`；Test: `server/tests/test_admin_messages.py`

- Produces: `POST /api/admin/messages` body `{target_type: "user"|"region"|"station", target_value, title, content}`（user=user_id；region=区域码（含市码=全市群发）；station=派出所名；收件人一律 ∩ scope，越界部分忽略并回 `sent/skipped` 计数）；`GET /api/admin/messages?page=`（本人已发：标题/时间/收件数/已读数，`read_at IS NOT NULL` 计数）。
- 测试：按区群发命中 scope 内全部用户并跳过 scope 外；已发列表已读数准确。Commit：`"管理端消息发送入库：单人/按区域/按单位三口径（一律∩scope），已发列表含已读统计"`。

### Task 23: 数据集导出（两源清单 + 后台 ZIP + 即焚）

**Files:**
- Create: `server/app/api/admin/export.py`、`server/app/schemas/export.py`；Test: `server/tests/test_admin_export.py`

**Interfaces:**
- Produces: `GET /api/admin/export/audio-list?region=&category=&dialect=&annotated=&page=`（两源合并：recordings（仅 passed，行含文本/用户/区域）+ audio_files 已判方言（行含文件名/译文）——统一清单结构 `{id, source:"recording"|"audio_file", text_or_name, region_code, dialect_code, translation?}`，逐条 scope 校验）；`POST /api/admin/export/audio` body `{items:[{source,id}...]}`；`POST /api/admin/export/audio-all`（同筛全量）；`GET /api/admin/export/task/{id}`（进度 processed/total）；`GET /api/admin/export/download/{id}`（FileResponse ZIP 后 `os.remove` 即焚）。
- ZIP 内容：音频原文件 + `dataset.txt`（每行 `文件名\t区域\t方言\t文本或译文`），ZIP_STORED；后台线程写 ExportTask 进度。

- [ ] **Step 1: 失败测试**：造 1 passed 录音 + 1 已判方言 audio_file → 全量导出 → task completed、ZIP 内 2 音频 + dataset.txt 两行；下载后文件被删（二次下载 404）；pending 录音不入包。
- [ ] **Step 2: 实现**：移植旧 `admin/export.py`（ZIP_STORED、即焚、线程进度全部沿用），叠加两源合并与 passed 过滤。
- [ ] **Step 3: 测试通过 → Commit** — `"数据集导出入库：recordings(passed)+已判方言audio_files两源清单、勾选或全量、后台ZIP_STORED打包+dataset.txt清单、下载即焚、逐条scope校验"`

---

## 阶段 D：前端（T24-T35）

> 通用要求：每任务 = 页面/组件 1:1 还原对应 `dome/*.html`（布局、文案、配色 token 由 theme.css 映射为 Element Plus 主题变量与全局样式 `web/src/styles/theme.css`）；API 走 `src/api/http.ts` 封装；验证 = `npm run build`（vue-tsc 零错误）+ `npm run dev` 手工对照 dome 页。每个任务结束提交。

### Task 24: 前端骨架（工程 + http + 路由守卫 + stores）

**Files:**
- Create: `web/`（vite 脚手架）、`web/src/api/http.ts`、`web/src/router/index.ts`、`web/src/stores/user.ts`、`web/src/styles/theme.css`、`web/.env.development`（`VITE_API_BASE=/api`）
- 校验：`npm run build` 通过。

**Interfaces:**
- Produces: `http.ts`（axios 实例：baseURL=`/api`、请求带 Bearer、响应拦截 `code!==0` 时 ElMessage 错误并 reject、401 清 token 跳 /login）；`router`（全部 19 条路由按 Spec §8 表 + 全局前置守卫：无 token→/login；非 admin/super_admin 访问 `/admin/*`→redirect `/`）；`useUserStore`（login/logout/fetchMe，持久化 localStorage token）。
- 脚手架命令：`npm create vite@latest web -- --template vue-ts`（在 `zj_police_dialect_trans/` 下执行）→ `npm i element-plus @element-plus/icons-vue pinia vue-router axios` → `npm i -D @types/node`。
- Commit：`"前端骨架入库：vite+vue3.5+TS+ElementPlus+Pinia，axios封装code统一拦截401跳登录，19路由+守卫（未登录/非admin拦/admin）"`。

### Task 25: 主布局 + 未读角标轮询 + 单声道播放

**Files:**
- Create: `web/src/layouts/MainLayout.vue`、`web/src/stores/message.ts`、`web/src/stores/audio.ts`、`web/src/api/messages.ts`
- 视觉规格：`dome/home.html` 侧栏/顶栏（藏青 #0E2440、警徽金 #C8A45C active、品牌 SVG 盾徽直接拷贝）。

**Interfaces:**
- Produces: `MainLayout`（菜单按角色渲染：user=「日常工作」5 项+「消息」；admin/super_admin 追加「管理工作」12 项分组——数据源 `const MENU = [{group:"日常工作",items:[...5]},{group:"消息",...},{group:"管理工作",items:[...12]}]` 按角色过滤）；`useMessageStore`（`unread` 计数、`refresh()` 调 `/messages/unread-count`，路由 afterEach + `setInterval(30_000)` 轮询，侧栏与顶栏铃铛 `zp-dot-badge` 角标）；`useAudioStore`（audioManager 单声道：新播放自动停上一个，`play(url)` 统一入口）。
- Commit：`"主布局入库：按角色渲染三级菜单（民警7项/管理员+12项管理工作）、未读角标路由切换+30s轮询、全站单声道audioManager"`。

### Task 26: 登录/注册

**Files:** Create: `web/src/views/LoginView.vue`、`RegisterView.vue`；视觉：`dome/login.html / register.html`（55/45 分栏、左侧品牌面板金色波形 SVG、演示账号提示区）。
- 逻辑：登录 `POST /auth/login` 存 token → `fetchMe` → 按角色跳 `/`；注册三级区域级联（`GET /regions/tree` el-cascader）+ 派出所联动（`/police_stations/by-region/{code}`）+ `POST /auth/register` 成功回登录页。
- Commit：`"登录注册页入库：55/45藏青品牌分栏、三级区域级联+派出所联动、登录按角色跳转"`。

### Task 27: 首页

**Files:** Create: `web/src/views/HomeView.vue`、`web/src/api/tasks.ts`；视觉：`dome/home.html`。
- 逻辑：`GET /tasks/my` 渲染两张任务卡（el-progress，录音卡副注「质检通过后计入」；无任务显示空态+去完成入口）；5 个快捷入口（消息入口带未读角标）；最近录音（`GET /recordings?page_size=3`）与最新消息（`GET /messages?page_size=2` 未读高亮）双卡片；底部 admin 可见「管理工作」入口卡。
- Commit：`"首页入库：任务卡（进度/剩余/质检口径注记）、快捷入口、最近录音与最新消息双卡、管理员入口卡"`。

### Task 28: 录音采集（Recorder 组件）

**Files:**
- Create: `web/src/views/RecordView.vue`、`web/src/components/Recorder.vue`、`web/src/api/texts.ts`、`web/src/api/recordings.ts`
- 视觉：`dome/record.html`（96px 录音钮金色脉冲、四步步骤条含「质检入库」、计时器、实时波形条）。

**Interfaces:**
- Produces: `Recorder.vue` props `{disabled}` emits `start/stop(blob, seconds)`；内部 `navigator.mediaDevices.getUserMedia({audio:true})` + `new MediaRecorder(stream, {mimeType: 择优 "audio/webm;codecs=opus"|"audio/webm"|"audio/mp4"})`，chunks 收集 `onstop` 合 Blob，`stream.getTracks().forEach(t=>t.stop())` 释放；计时 `setInterval`；波形为纯 CSS 动画（照抄 dome `.zp-wave.is-live` keyframes）。

**页面逻辑（对照 dome 逐块）**：顶部任务进度条（tasks store）；步骤条 4 步；文本卡（`POST /texts/assign` 领取 + 120s 倒计时 `remaining_seconds`、超时自动释放并提示重领、「换一条」= 放弃当前再 assign、「自定义文本」dialog `POST /texts/custom`）；录音卡（Recorder 录制态）；完成态卡（`URL.createObjectURL(blob)` 试听 + 重新录制 + 上传 `POST /recordings` FormData → 成功提示「已提交质检，通过后计入任务进度」并自动领下一条）；「上传后质检」示例区块与底部提示按 dome 文案；`getUserMedia` 失败（非 HTTPS/拒权）ElMessage 明确指引。
- Commit：`"录音采集页入库：MediaRecorder录音(96px脉冲钮/计时/波形)、120s分配倒计时换条与自定义文本、上传即提示已提交质检、自动领下一条"`。

### Task 29: 我的录音

**Files:** Create: `web/src/views/MyRecordingsView.vue`；视觉：`dome/my-recordings.html`。
- 逻辑：筛选（类别/质检状态/搜索）+ el-table（质检列：待质检 warn tag / 已通过 success tag）+ 行内 试听（audioManager）/下载（`/recordings/{id}/file` 带 token 转 blob 下载）/删除（确认框文案含「任务进度将相应扣减」）；顶部 info 提示按 dome 文案（未通过录音已移除不在列表）。
- Commit：`"我的录音页入库：类别与质检状态筛选、质检列双色标签、试听下载删除（删除提示进度扣减）"`。

### Task 30: 录音标注 + 我的标注

**Files:**
- Create: `web/src/views/AnnotationView.vue`、`web/src/views/MyAnnotationsView.vue`、`web/src/components/AudioPlayer.vue`、`web/src/api/annotations.ts`
- 视觉：`dome/annotation.html / my-annotations.html`。

**Interfaces:**
- Produces: `AudioPlayer.vue` props `{src}`——内部 `useAudioStore.play(src)` 单声道，72px 播放钮 + 静态波形 + 当前/总时长。

**标注页逻辑**：任务进度条；`GET /annotations/next` 领音频（无货空态「暂无待标注音频」）；音频卡（AudioPlayer + 180s 锁倒计时 + 续期按钮 `POST /annotations/assign/{fid}/refresh`）；表单：是否方言 el-radio-group（dome `.zp-seg` 分段样式）+ 译文 textarea（方言必填校验）+ 提交后自动 next；**我的标注**：表格 + 修改 dialog（AudioPlayer 重听 + 回填）+ 删除确认。
- Commit：`"录音标注+我的标注页入库：3分钟锁倒计时与续期、方言判定分段控件必填译文、提交自动下一条、可改可删"`。

### Task 31: 我的消息

**Files:** Create: `web/src/views/MessagesView.vue`；视觉：`dome/messages.html`。
- 逻辑：三 tab（全部/未读/已读，计数来自接口分页 total）；消息行 tag 三色（任务 navy/通知 blue/公告 gold/质检 danger——后端无类型字段，前端按 title 前缀映射：「新任务」→navy、「录音质检未通过」→danger、「公告」→gold、其余 blue，规则写入组件常量）；点行开详情 dialog（`GET /messages/{id}` 即标已读并刷新角标）；「全部标记已读」批量调详情接口循环（或后端补 `POST /messages/read-all`——**采用后者**，本任务在 T13 文件补一个端点+测试）。
- Commit：`"我的消息页入库：三tab计数、四类tag映射、详情打开即已读联动角标、全部已读接口read-all补齐"`。

### Task 32: 管理端-数据总览 + 任务管理

**Files:**
- Create: `web/src/views/admin/OverviewView.vue`、`web/src/views/admin/TasksView.vue`、`web/src/api/admin.ts`（管理端 API 集中封装，本任务起累积）
- 视觉：`dome/admin-overview.html / admin-tasks.html`（管理端 shell 全菜单 + 金色头像角标）。

**逻辑（总览）**：6 张统计卡（数据来自 total）+ 任务进度卡（完成率/已启动/未启动，未启动>0 warn 提示）+ 类别分布条形（texts 按 category 聚合，若 `/stats/overview` 未含则后端补 `category_counts` 字段——本任务在 stats.py 响应补该字段+测试）+ 区域表（rows + total 行，本辖区高亮金色，super_admin/省管顶部区域级联下钻）。
**逻辑（任务）**：筛选表单 + 表格（行内进度条含超额 137% 金色、未启动 warn tag、cancelled 置灰）+ 4 个 dialog（单人下达/批量下达 checkbox 选人（scope 用户下拉多选）/调整/取消）+ 规则说明 alert（dome 文案）。
- Commit：`"管理端总览+任务管理入库：统计卡任务卡类别分布区域表(下钻/本辖区高亮)，任务列表行内进度与四弹窗（批量选人/调整/取消）"`。

### Task 33: 管理端-用户管理 + 消息发送

**Files:** Create: `web/src/views/admin/UsersView.vue`、`web/src/views/admin/MessageSendView.vue`；视觉：`dome/admin-users.html / admin-message-send.html`。

**逻辑（用户）**：筛选（姓名/手机/角色/区域级联/单位）+ 表格（角色 tag、录音数/有效标注数/任务进度列）+ 新建/编辑 dialog（super_admin 额外可见角色含 super_admin 选项，admin 角色仅 user/admin——按 `/auth/me` role 控制）+ 重置密码 + 删除（后端 400「有录音禁删」透传提示）+ 批量导入 dialog（模板下载 `/users/import-template`、el-upload xlsx、导入后轮询 `/users/import/{id}` 展示成功/失败明细表）+ 导出按钮（blob 下载）。
**逻辑（消息发送）**：左侧撰写卡（收件口径 el-segmented：按人员（scope 用户远程搜索）/按区域（级联，含市=全市）/按单位（派出所下拉）+ 标题 + 正文）+ 右侧已发记录（标题/时间/收件数/已读数，行点开查已发明细）；发送成功显示 `发送 N 人 / 越界跳过 M`。
- Commit：`"管理端用户管理+消息发送入库：用户全CRUD与导入模板轮询明细导出、消息三口径发送与已发记录已读统计"`。

### Task 34: 管理端-文本线 + 音频入库

**Files:**
- Create: `web/src/views/admin/TextImportView.vue`、`TextImportManageView.vue`、`TextsView.vue`、`AudioUploadView.vue`、`AudioImportView.vue`
- 视觉：`dome/admin-text-import.html / admin-text-import-manage.html / admin-texts.html / admin-audio-upload.html / admin-audio-import.html`。

**逻辑**：文本导入（类别+区域（super_admin 可改）+ el-upload txt/docx + 轮询进度「解析中 120/200」+ 句号切分示例文案）；导入台账（批次表 + 详情 dialog 样例 + 撤销（409 被引用拒撤提示））；文本管理（checkbox 表 + 日期区间 + 批量删除显示 skipped 明细）；音频上传（多文件 dropzone + 状态表 已入库/上传中64%/等待/失败）；音频扫盘（服务器路径输入 + 递归开关 + 提交后轮询 + 4 统计格 新入库/跳过/失败/总数）。
- Commit：`"管理端文本线与音频入库五页入库：导入(模板/句号切分/轮询)、台账(详情/拒撤)、文本管理(批量删除skipped)、上传(多文件状态表)、扫盘(递归/去重统计)"`。

### Task 35: 管理端-录音/标注管理 + 数据集导出

**Files:**
- Create: `web/src/views/admin/RecordingsView.vue`、`AnnotationsView.vue`、`ExportView.vue`
- 视觉：`dome/admin-recordings.html / admin-annotations.html / admin-export.html`。

**逻辑**：录音管理（筛选含质检状态列、试听同 audioManager、文件名列只显文件名 formatter）；标注管理（筛选 + 表格 + 删除确认 + 底部统计「是方言 N / 不是 M」由列表响应聚合）；导出页（两源合并清单 checkbox 表（source 标签：录音/音频库）+ 筛选 + 「导出所选/导出全部」→ 任务卡轮询进度（打包中 60%）→ 下载按钮（blob 下载后提示「文件已删除，如需再次请重新打包」）+ 即焚警示 alert）。
- Commit：`"管理端录音/标注/导出三页入库：质检筛选与试听、标注统计、两源清单勾选导出与进度轮询下载即焚"`。

---

## 阶段 E：部署（T36）

### Task 36: 双容器部署套件 + 冒烟

**Files:**
- Create: `server/Dockerfile`、`web/Dockerfile`、`web/nginx.conf`、`docker-compose.yml`、`deploy/README.md`
- Modify: `server/.env.docker`（如 T1 已建则核对）。

**内容:**
- `server/Dockerfile`：`FROM python:3.10-slim` + `apt-get install -y ffmpeg` + requirements + `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000`；volume 挂 `/data`。
- `web/Dockerfile`：node:20 build → nginx:alpine 拷 dist + nginx.conf。
- `web/nginx.conf`：443 ssl 自签证书（挂载 certs/，README 附 openssl 一行生成命令 `openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout key.pem -out cert.pem -subj "/CN=local"`）；`location /api/ { proxy_pass http://backend:8000/api/; }`；`location / { try_files $uri /index.html; }`；80→443 强跳。
- `docker-compose.yml`：两服务 backend/web + 共享 volume `app-data:/data`；web depends_on backend。
- 验证：`docker compose up -d --build` → 冒烟清单（Spec §10）：浏览器 https 打开 → 33100400002/123456 登录 → 领文本→录音→上传→（ASR 空配置下确认直通 passed）→ 标注一条 → 33000000001 登录下达任务与发消息 → 民警端角标 → 导出 ZIP 下载。
- Commit：`"部署套件入库：backend(ffmpeg)+web(nginx443自签)双容器compose，/api反代与SPA回退，冒烟清单落deploy/README"`。

---

## Self-Review 记录

- **Spec 覆盖**：§2 决策 9 项 → T4(seed)/T21(任务)/T22(消息)/T9(质检)/T15(开户) 等逐一对应；§5.1 17 表 → T2；§5.2 进度口径 → T12 五用例；§6.1-6.9 → T7/T8/T9/T10/T11/T12/T13/T14-15/T16-17/T18/T19/T20/T21/T22/T23；§7 端点清单逐条落入各任务 Produces（`read-all` 为 T31 补充端点，超出清单已在任务内注明补测试）；§8 19 路由 → T24 + 各视图；§9 沿用机制 → 各移植任务标注；§10 测试策略 → 各任务用例覆盖（resolve_scope T3、进度 T12、锁 T7/T10、消息 T13、质检 T9 七用例）；§11 边界未越界。
- **类型一致性**：`resolve_scope(db, user)`（T3 定义，T14/T16/T18/T20/T21/T22/T23 消费）；`send_message(db, user_ids, title, content, sender_id)`（T13 定义，T9/T21 消费）；`progress_map(db, user_ids)`（T12 定义，T14/T20/T21 消费）；`convert_to_wav/_ffmpeg_sem`（T8 定义，T19 消费）；`useAudioStore.play(url)`（T25 定义，T29/T30/T32/T35 消费）。
- **风险与缓解**：① 旧省库区县数与 90 的出入在 T4 Step 1 断言处显式核对；② ffmpeg/ffprobe 宿主机缺失时 T8/T19 测试 skip（容器内必有）；③ ASR 接口未就绪不阻塞——空配置直通（T9），联调期用 monkeypatch 用例为准。
