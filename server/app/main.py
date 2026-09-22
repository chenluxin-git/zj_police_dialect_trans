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

app.include_router(auth_router, prefix="/api")
app.include_router(base_router, prefix="/api")
app.include_router(texts_router, prefix="/api")
app.include_router(recordings_router, prefix="/api")

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
