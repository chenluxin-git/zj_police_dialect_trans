import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.database import init_db

# 日志必须**在其它模块 import 之前**就绪：否则 import 期的异常（配置错、依赖缺失）
# 只会打到 stderr，容器重启即丢——恰恰是内网首次部署最容易踩的坑。
# 注意：这里必须放在 `from .api...` 之前，不能只在 startup 事件里做。
from .core.logsetup import setup_logging, startup_report, write_startup_report
setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title="zj-police-dialect-platform")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                   # 必须 expose：否则浏览器 JS 读不到 X-Trace-Id（CORS 默认只暴露 6 个安全响应头），
                   # 前端就无法把错误与后端 app.request.log 的那一行对上
                   expose_headers=["X-Trace-Id"])

# 请求级日志与 trace_id（要在业务路由之前注册，才能覆盖全部请求）
from .core.reqlog import RequestLogMiddleware
app.add_middleware(RequestLogMiddleware)

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
from .api.admin.users import router as admin_users_router  # P-admin-users(T14)
from .api.admin.user_import import router as admin_user_import_router  # P-admin-users(T15)
from .api.admin.texts import router as admin_texts_router  # P-admin-content(T16)
from .api.admin.text_import import router as admin_text_import_router, manage_router as admin_text_import_manage_router  # P-admin-content(T17)
from .api.admin.audio_upload import router as admin_audio_upload_router  # P-admin-content(T19)
from .api.admin.audio_import import router as admin_audio_import_router  # P-admin-content(T19)
from .api.admin import admin_recordings_router, admin_annotations_router  # P-admin-data(T18)
from .api.admin import admin_stats_router  # P-admin-data(T20)
from .api.admin import admin_tasks_router  # P-admin-data(T21)
from .api.admin import admin_messages_router  # P-admin-data(T22)
from .api.admin import admin_org_sync_router  # 浙警智治：组织同步初始化/状态
from .api.rzzx import router as rzzx_router  # 浙警智治：零信任联动服务
from .api.client_logs import router as client_logs_router  # 前端日志上报（排障）

app.include_router(auth_router, prefix="/api")
app.include_router(base_router, prefix="/api")
app.include_router(texts_router, prefix="/api")
app.include_router(recordings_router, prefix="/api")
app.include_router(tasks_router)
app.include_router(messages_router)
app.include_router(annotations_router, prefix="/api")
app.include_router(audio_files_router, prefix="/api")
app.include_router(admin_export_router, prefix="/api/admin")
app.include_router(admin_users_router, prefix="/api/admin")
app.include_router(admin_user_import_router, prefix="/api/admin")
app.include_router(admin_texts_router, prefix="/api/admin")
app.include_router(admin_text_import_router, prefix="/api/admin")
app.include_router(admin_text_import_manage_router, prefix="/api/admin")
app.include_router(admin_audio_upload_router, prefix="/api/admin")
app.include_router(admin_audio_import_router, prefix="/api/admin")
app.include_router(admin_recordings_router, prefix="/api/admin")  # P-admin-data(T18)
app.include_router(admin_annotations_router, prefix="/api/admin")  # P-admin-data(T18)
app.include_router(admin_stats_router, prefix="/api/admin")  # P-admin-data(T20)
app.include_router(admin_tasks_router, prefix="/api/admin")  # P-admin-data(T21)
app.include_router(admin_messages_router, prefix="/api/admin")  # P-admin-data(T22)
app.include_router(admin_org_sync_router, prefix="/api/admin")  # 浙警智治：/api/admin/org-sync/*
app.include_router(rzzx_router, prefix="/api")  # 浙警智治：/api/rzzx/linkage（零信任侧回调本系统）
app.include_router(client_logs_router, prefix="/api")  # 前端日志：/api/client-logs（匿名，见模块注释）

@app.get("/api/health")
def health() -> dict:
    """联通性探针：不查库、不打外部服务，避免误判（docker healthcheck 用它）。"""
    return {"status": "ok"}


@app.get("/api/diag")
def diag(refresh: bool = False) -> dict:
    """运行期自检（内网排障用）：日志路径、库连接、外部服务可达性、后台任务状态。

    与 `/api/zhijing/info`（对接口径）互补：这个是"我这边现在活着吗、卡在哪"。
    默认返回启动时算好的报告（快）；`?refresh=1` 重新探测外部服务（慢，含超时）。
    """
    import glob as _glob

    from .core.logsetup import startup_report as _report

    logs_dir = os.path.abspath("logs")
    files = {}
    for path in _glob.glob(os.path.join(logs_dir, "*")):
        if os.path.isfile(path):
            try:
                files[os.path.basename(path)] = os.path.getsize(path)
            except OSError:
                files[os.path.basename(path)] = -1

    db_ok, db_err = True, ""
    try:
        from sqlalchemy import text
        from .core.database import SessionLocal
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok, db_err = False, f"{type(exc).__name__}: {exc}"

    from .services import audit as audit_svc
    return {
        "日志目录": logs_dir,
        "日志文件字节数": files,
        "数据库可用": db_ok,
        "数据库错误": db_err,
        "审计台账积压": audit_svc.audit_self_check(),
        "自检报告": _report(probe_network=bool(refresh)),
    }


@app.get("/api/zhijing/info")
def zhijing_info() -> dict:
    """对接信息（只读）：给省厅/联调同学一份"我这边的参数是什么"的口径，便于对方配置"""
    from .core.config import settings as s
    from .services import audit as audit_svc
    from .services import zero_trust

    return {
        "callback_path": s.zhijing_callback_path,
        "linkage_path": "/api/rzzx/linkage",
        "mode": s.zhijing_mode,
        "login_source": s.zhijing_login_source,
        "self_check": {"zero_trust": zero_trust.self_check(), "audit": audit_svc.audit_self_check()},
    }

@app.on_event("startup")
async def on_startup() -> None:
    # 日志已在模块级初始化（见文件头），这里只做目录/建表/自检/后台循环
    # T4: 先建存储目录再建表（修 fresh-checkout 无 data/ 时 sqlite 建库失败）
    os.makedirs("data", exist_ok=True)
    os.makedirs(settings.audio_storage_path, exist_ok=True)
    os.makedirs(settings.export_path, exist_ok=True)
    logger.info("启动中：模式=%s 身份来源=%s 数据库=%s",
                settings.zhijing_mode, settings.zhijing_login_source,
                settings.database_url.split("://", 1)[0])

    # 启动自检（配置齐备性 + 外部服务可达性）放后台：探测含超时，不能阻塞启动
    async def _self_check() -> None:
        try:
            report = await asyncio.to_thread(startup_report, probe_network=True)
            write_startup_report(report)
        except Exception:  # noqa: BLE001 —— 自检本身失败不能影响启动
            logger.exception("启动自检失败（不影响服务启动）")
    asyncio.create_task(_self_check())

    from . import models  # noqa: F401  # T4: 注册全部表元数据（须在 init_db 前导入，否则 fresh 启动建 0 表）
    try:
        init_db()
    except Exception:
        logger.exception("建表失败 —— 数据库不可用，请检查 DATABASE_URL 与库权限")
        raise
    # 浙警智治接入新增列（users.cert_id/police_no/org_code/... 及审计、联动、票据表）：
    # create_all 不会为已存在的表补列，这里做一次"只加列"的轻量迁移
    from .core.migrate import ensure_columns
    ensure_columns()
    from .core.database import SessionLocal
    from .utils.seed import run_seed
    with SessionLocal() as db:
        run_seed(db)
    # T9 接入: 后台质检循环（60s 一轮；asr_upstream_base 空时直通，见 services/qc.py）
    from .services.qc import qc_loop
    asyncio.create_task(qc_loop())
    # 浙警智治接入：审计上报循环（失败本地缓存重推）+ 统一用户增量同步循环
    from .services.audit import audit_loop
    from .services.org_sync import org_sync_loop
    asyncio.create_task(audit_loop())
    asyncio.create_task(org_sync_loop())
    logger.info("启动完成：后台循环已拉起（质检 / 审计上报 / 组织同步）")
