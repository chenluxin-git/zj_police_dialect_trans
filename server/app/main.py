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

# 路由注册位：T5 起在此逐任务 include_router
from .api.auth import router as auth_router
from .api.base import router as base_router
from .api.texts import router as texts_router
from .api.recordings import router as recordings_router
from .api.tasks import router as tasks_router  # P-social(T12)：我的任务进度
from .api.messages import router as messages_router  # P-social(T13)：站内消息
from .api.annotations import router as annotations_router
from .api.audio_files import router as audio_files_router
from .api.admin.export import router as admin_export_router  # P-export(T23)
from .api.admin import admin_recordings_router, admin_annotations_router  # P-admin-data(T18)
from .api.admin import admin_stats_router  # P-admin-data(T20)
from .api.admin import admin_tasks_router  # P-admin-data(T21)

app.include_router(auth_router, prefix="/api")
app.include_router(base_router, prefix="/api")
app.include_router(texts_router, prefix="/api")
app.include_router(recordings_router, prefix="/api")
app.include_router(tasks_router)
app.include_router(messages_router)
app.include_router(annotations_router, prefix="/api")
app.include_router(audio_files_router, prefix="/api")
app.include_router(admin_export_router, prefix="/api/admin")
app.include_router(admin_recordings_router, prefix="/api/admin")  # P-admin-data(T18)
app.include_router(admin_annotations_router, prefix="/api/admin")  # P-admin-data(T18)
app.include_router(admin_stats_router, prefix="/api/admin")  # P-admin-data(T20)
app.include_router(admin_tasks_router, prefix="/api/admin")  # P-admin-data(T21)

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

@app.on_event("startup")
def on_startup() -> None:
    _setup_logging()
    # T4: 先建存储目录再建表（修 fresh-checkout 无 data/ 时 sqlite 建库失败）
    import os
    os.makedirs("data", exist_ok=True)
    os.makedirs(settings.audio_storage_path, exist_ok=True)
    os.makedirs(settings.export_path, exist_ok=True)
    from . import models  # noqa: F401  # T4: 注册全部表元数据（须在 init_db 前导入，否则 fresh 启动建 0 表）
    init_db()
    from .core.database import SessionLocal
    from .utils.seed import run_seed
    with SessionLocal() as db:
        run_seed(db)
    # T9 接入: asyncio.create_task(qc_loop())
