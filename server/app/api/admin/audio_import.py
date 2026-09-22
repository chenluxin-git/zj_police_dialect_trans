"""T19 管理端扫盘导入：7 扩展名/绝对路径去重/递归，ffprobe 时长，区域随管理员归属、超管可指定
后台 BackgroundTasks + 侧车台账（kind:"audio"，统计格 found/imported/skipped/failed）；
复用 audio_upload 的区域/方言解析与 T8 _ffprobe_duration。
"""
import json
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import SessionLocal, get_db
from ...models import AudioFile, ImportTask, User
from ...schemas import ok
from ...utils.file_scanner import scan_audio_files
from ..deps import require_admin, resolve_scope
from ..recordings import _ffprobe_duration
from .audio_upload import _dialect_code, _resolve_region

router = APIRouter(prefix="/audio", tags=["管理端-音频扫盘"])

_session_factory = SessionLocal  # 后台任务会话工厂（测试重定向至此）


class ScanBody(BaseModel):
    server_path: str
    recursive: bool = True
    region_code: str | None = None


def _manifest_dir() -> str:
    return settings.audio_import_dir  # 容器内指向 /data 卷（.env.docker），防侧车台账落临时层


def _manifest_path(task_id: int) -> str:
    return os.path.join(_manifest_dir(), f"{task_id}.json")


def _save_manifest(task_id: int, data: dict) -> None:
    d = _manifest_dir()
    os.makedirs(d, exist_ok=True)
    with open(_manifest_path(task_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _load_manifest(task_id: int) -> dict:
    try:
        with open(_manifest_path(task_id), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _process_scan(task_id: int, server_path: str, recursive: bool,
                  region_code: str, dialect_code: str) -> None:
    db = _session_factory()
    try:
        task = db.get(ImportTask, task_id)
        if task is None:
            return
        task.status = "processing"
        db.commit()

        files = scan_audio_files(server_path, recursive)
        existing = {p for (p,) in db.query(AudioFile.file_path).all()}
        imported = 0
        skipped = 0
        failed: list[dict] = []
        for path in files:
            if path in existing:  # 绝对路径去重
                skipped += 1
                continue
            try:
                duration = _ffprobe_duration(path)
            except Exception as e:  # noqa: BLE001
                failed.append({"path": path, "error": str(e)[:200]})
                continue
            db.add(AudioFile(file_path=path, file_name=os.path.basename(path), duration=duration,
                             region_code=region_code, dialect_code=dialect_code))
            imported += 1

        _save_manifest(task_id, {"kind": "audio", "server_path": server_path,
                                 "region_code": region_code,
                                 "found": len(files), "imported": imported,
                                 "skipped": skipped, "failed": failed})
        task.status = "completed"
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        task = db.get(ImportTask, task_id)
        if task is not None:
            task.status = "failed"
            task.error_message = str(e)[:500]
        db.commit()
    finally:
        db.close()


@router.post("/import")
def import_scan(body: ScanBody, background: BackgroundTasks,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not os.path.isdir(body.server_path):
        raise HTTPException(400, "服务器路径不存在或不是目录")
    server_path = os.path.abspath(body.server_path)  # 去重按绝对路径比对
    root = settings.scan_root  # 终审 Important#4：扫盘白名单根目录（容器/生产必设），防任意目录枚举
    if root:
        norm_root = os.path.normcase(os.path.abspath(root))
        norm_path = os.path.normcase(server_path)
        if norm_path != norm_root and not norm_path.startswith(norm_root + os.sep):
            raise HTTPException(400, f"路径必须在扫盘根目录 {root} 内")
    region = _resolve_region(admin, body.region_code)
    dialect_code = _dialect_code(db, region)
    task = ImportTask(status="pending")
    db.add(task)
    db.commit()
    _save_manifest(task.id, {"kind": "audio", "server_path": server_path,
                             "region_code": region,
                             "found": 0, "imported": 0, "skipped": 0, "failed": []})
    background.add_task(_process_scan, task.id, server_path, body.recursive, region, dialect_code)
    return ok({"task_id": task.id})


@router.get("/import/{task_id}")
def poll_scan(task_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    task = db.get(ImportTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    m = _load_manifest(task_id)
    scope = resolve_scope(db, admin)  # 扫盘任务辖区隔离（同文本台账口径）
    if scope is not None and m.get("region_code", "") not in scope:
        raise HTTPException(403, "该导入任务不在你的辖区")
    return ok({"task_id": task.id, "status": task.status, "error_message": task.error_message,
               "found": m.get("found", 0), "imported": m.get("imported", 0),
               "skipped": m.get("skipped", 0), "failed": m.get("failed", [])})