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
from .api.admin.export import router as admin_export_router  # noqa: E402

app.include_router(admin_export_router, prefix="/api/admin")

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

@app.on_event("startup")
def on_startup() -> None:
    _setup_logging(); init_db()
    # T4 接入: run_seed()
    # T9 接入: asyncio.create_task(qc_loop())
