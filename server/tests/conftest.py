import os
os.environ["DATABASE_URL"] = "sqlite://"   # 内存库
os.environ["AUDIO_STORAGE_PATH"] = "./test_audio"
os.environ["ASR_UPSTREAM_BASE"] = ""   # 默认停用质检，QC 任务用例内再覆盖
os.environ["ZHIJING_AUDIT_QUEUE_ENABLED"] = "false"   # 审计队列默认开：queue_audit 走模块级 SessionLocal（导入时引擎无表），测试统一静默

import warnings
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.core.database import Base, get_db

# 已知第三方弃用告警过滤（锁定版本组合固有，与本仓库代码无关，仅按消息精确匹配）：
# 1) FastAPI 0.104.1 自带对 @app.on_event("startup") 的弃用提示（任务书规定保留 on_event 写法）
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=r"[\s\S]*on_event is deprecated", category=DeprecationWarning)
    from app.main import app
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
    # 2) httpx 0.27.2 对 starlette 0.27 TestClient 内部 app= 快捷参数的弃用提示
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"The 'app' shortcut is now deprecated", category=DeprecationWarning)
        tc = TestClient(app)
    yield tc
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def _mute_qc_trigger(monkeypatch):
    """适时质检副作用默认静默：上传端点会起真线程跑 _run_one，而模块级 SessionLocal
    绑的是另一套导入时内存引擎（无表）→ 线程内 no such table 刷 UnhandledThreadException。
    质检逻辑由 test_qc.py 直接同步调 _run_one/process_pending 覆盖，不依赖端点触发。"""
    monkeypatch.setattr("app.api.recordings.trigger_qc", lambda rec_id: None)

def make_user(db, phone="33100400002", name="测试民警", role="user", region="331004", station="临海市公安局××派出所"):
    from app.models.social import User  # T2 才落地该模块，必须函数体内延迟导入
    u = User(phone=phone, password_hash=hash_password("123456"), real_name=name,
             police_station=station, region_code=region, role=role)
    db.add(u); db.commit(); return u

@pytest.fixture()
def auth_header(db):
    make_user(db)
    from app.core.security import create_token
    return {"Authorization": f"Bearer {create_token('1')}"}
