"""T23 数据集导出：两源清单 + 后台 ZIP_STORED 打包 + dataset.txt 清单 + 下载即焚 + 逐条 scope 校验
移植自旧项目 app/api/admin/export.py（机制见规格 §6.8/§9），差异叠加：
- 两源口径：recordings 仅 qc_status='passed'；audio_files 仅已判方言（annotated=false 反向取未判音频）
- 权限由 resolve_scope 统一推导（替代旧 if-else 分支），打包时逐条再校验一次（防清单与打包之间越界）
- 台账用本项目 ExportTask（status/total_count/processed_count/file_path/created_by；无 error_message 列，
  失败细节进 error.log）
- 后台执行沿用 BackgroundTasks（TestClient 下响应返回即任务完成，天然可测）
"""
import logging
import os
import re
import zipfile
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import SessionLocal, get_db
from ...models import Annotation, AudioFile, ExportTask, Recording, Region, Text, User
from ...schemas.export import (ApiResponse, ExportAllBody, ExportCreatedData,
                               ExportPostBody, ExportTaskStatusData, PageData, TwoSourceItem)
from ..deps import require_admin, resolve_scope, scope_filter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/export", tags=["管理端-数据集导出"])

_session_factory = SessionLocal  # 后台任务会话工厂（请求级依赖覆盖不可用于后台，测试重定向至此）


# ---------- 工具 ----------

def _expand_region_codes(db: Session, code: str) -> list[str]:
    """code 及其全部下级（BFS：省/市码可整域导出）"""
    result, queue = [code], [code]
    while queue:
        children = db.scalars(select(Region.code).where(Region.parent_code.in_(queue))).all()
        queue = [c for c in children if c not in result]
        result.extend(queue)
    return result


def _user_folder(user: User) -> str:
    """与 T8 录音落盘同规则 {姓名}_{手机尾4}（该助手在 P-media 分支，此处本地等价实现）"""
    safe = re.sub(r"[^\w\u4e00-\u9fff]", "", user.real_name)
    tail4 = user.phone[-4:] if len(user.phone) >= 4 else user.phone
    return f"{safe or 'user'}_{tail4}"


def _dialect_annotated_exists():
    return exists().where(and_(Annotation.file_id == AudioFile.id, Annotation.is_dialect == True))  # noqa: E712


def _collect_items(db: Session, admin: User, region: str | None, category: str | None,
                   dialect: str | None, annotated: bool | None) -> list[TwoSourceItem]:
    """两源合并收集（scope 必过滤；region 为传入区域及其下级 ∩ scope）"""
    scope = resolve_scope(db, admin)
    region_filter = None
    if region:
        expanded = _expand_region_codes(db, region)
        region_filter = expanded if scope is None else [c for c in expanded if c in scope]
        if not region_filter:  # 请求区域整体越界
            return []

    items: list[TwoSourceItem] = []

    # 源 1：采集录音（仅质检通过）
    q = (db.query(Recording)
         .outerjoin(Text, Recording.text_id == Text.id)
         .filter(Recording.qc_status == "passed", scope_filter(Recording.region_code, scope)))
    if region_filter is not None:
        q = q.filter(Recording.region_code.in_(region_filter))
    if category:
        q = q.filter(Text.category == category)
    if dialect:
        q = q.filter(Recording.dialect_code == dialect)
    for rec in q.all():
        text = db.get(Text, rec.text_id)
        user = db.get(User, rec.user_id)
        items.append(TwoSourceItem(
            id=rec.id, source="recording",
            text_or_name=text.content if text else "（文本已删除）",
            category=text.category if text else "",
            region_code=rec.region_code or "",
            dialect_code=rec.dialect_code or "",
            user_real_name=user.real_name if user else "",
            duration=rec.duration, created_at=rec.created_at))

    # 源 2：音频库（默认已判方言；annotated=false 反向取未判方言音频；音频无类别，类别筛选时跳过该源）
    if category is None:
        ann_exists = _dialect_annotated_exists()
        q2 = db.query(AudioFile).filter(scope_filter(AudioFile.region_code, scope))
        q2 = q2.filter(ann_exists if annotated is not False else ~ann_exists)
        if region_filter is not None:
            q2 = q2.filter(AudioFile.region_code.in_(region_filter))
        if dialect:
            q2 = q2.filter(AudioFile.dialect_code == dialect)
        for af in q2.all():
            translation = None
            if annotated is not False:
                ann = db.query(Annotation).filter_by(file_id=af.id, is_dialect=True).first()
                translation = ann.translation if ann else None
            items.append(TwoSourceItem(
                id=af.id, source="audio_file",
                text_or_name=af.file_name or os.path.basename(af.file_path),
                region_code=af.region_code or "",
                dialect_code=af.dialect_code or "",
                translation=translation,
                duration=af.duration, created_at=af.created_at))

    items.sort(key=lambda x: x.created_at, reverse=True)
    return items


# ---------- 清单 ----------

@router.get("/audio-list", response_model=ApiResponse[PageData[TwoSourceItem]])
def audio_list(
    region: str | None = Query(None, description="区域码：省/市码展开整域，区县码精确"),
    category: str | None = Query(None, description="文本类别（仅录音源）"),
    dialect: str | None = Query(None, description="方言编码"),
    annotated: bool | None = Query(None, description="音频库源：默认/true=已判方言，false=未判方言"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    items = _collect_items(db, admin, region, category, dialect, annotated)
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start:start + page_size]
    return ApiResponse[PageData[TwoSourceItem]](data=PageData(
        total=total, page=page, page_size=page_size, items=page_items))


# ---------- 导出任务 ----------

def _create_task(db: Session, admin: User, raw_items: list[dict], background_tasks: BackgroundTasks) -> int:
    task = ExportTask(status="pending", total_count=len(raw_items), processed_count=0,
                      file_path="", created_by=admin.id)
    db.add(task)
    db.commit()
    background_tasks.add_task(run_export_task, task.id, admin.id, raw_items)
    return task.id


@router.post("/audio", response_model=ApiResponse[ExportCreatedData])
def export_selected(payload: ExportPostBody,
                    background_tasks: BackgroundTasks,
                    admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="未选择导出项")
    raw = [{"source": i.source, "id": i.id} for i in payload.items]
    task_id = _create_task(db, admin, raw, background_tasks)
    return ApiResponse[ExportCreatedData](data=ExportCreatedData(task_id=task_id))


@router.post("/audio-all", response_model=ApiResponse[ExportCreatedData])
def export_all(payload: ExportAllBody,
               background_tasks: BackgroundTasks,
               admin: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    """按当前筛选全量导出（与 audio-list 同筛同源）"""
    items = _collect_items(db, admin, payload.region, payload.category, payload.dialect, payload.annotated)
    if not items:
        raise HTTPException(status_code=400, detail="没有符合条件的音频")
    raw = [{"source": i.source, "id": i.id} for i in items]
    task_id = _create_task(db, admin, raw, background_tasks)
    return ApiResponse[ExportCreatedData](data=ExportCreatedData(task_id=task_id))


def _pack_one(db: Session, zf: zipfile.ZipFile, item: dict, scope: list[str] | None,
              dataset_lines: list[str]) -> bool:
    """打包单条（逐条 scope 校验；缺失/越界/文件丢失返回 False 不入包）"""
    if item["source"] == "recording":
        rec = db.get(Recording, item["id"])
        if rec is None:
            return False
        if scope is not None and rec.region_code not in scope:
            logger.warning("导出越界跳过 recording=%s region=%s", rec.id, rec.region_code)
            return False
        if not rec.file_path or not os.path.exists(rec.file_path):
            return False
        user = db.get(User, rec.user_id)
        folder = _user_folder(user) if user else f"user_{rec.user_id}"
        arcname = f"录音/{folder}/{os.path.basename(rec.file_path)}"
        zf.write(rec.file_path, arcname)
        text = db.get(Text, rec.text_id)
        text_or_trans = text.content if text else "（文本已删除）"
        region_code, dialect_code = rec.region_code, rec.dialect_code
    else:
        af = db.get(AudioFile, item["id"])
        if af is None:
            return False
        if scope is not None and af.region_code not in scope:
            logger.warning("导出越界跳过 audio_file=%s region=%s", af.id, af.region_code)
            return False
        if not af.file_path or not os.path.exists(af.file_path):
            return False
        arcname = f"标注音频/{os.path.basename(af.file_path)}"
        zf.write(af.file_path, arcname)
        ann = db.query(Annotation).filter_by(file_id=af.id, is_dialect=True).first()
        text_or_trans = ann.translation if ann else "（无翻译）"
        region_code, dialect_code = af.region_code, af.dialect_code

    dataset_lines.append(f"{arcname}\t{region_code}\t{dialect_code}\t{text_or_trans}")
    return True


def run_export_task(task_id: int, admin_id: int, items: list[dict]) -> None:
    """后台打包：ZIP_STORED + dataset.txt（每行 文件名\t区域\t方言\t文本或译文），逐条更新进度"""
    db = _session_factory()
    task: ExportTask | None = None
    try:
        task = db.get(ExportTask, task_id)
        if task is None:
            return
        admin = db.get(User, admin_id)
        scope = resolve_scope(db, admin) if admin else []
        task.status = "processing"
        db.commit()

        os.makedirs(settings.export_path, exist_ok=True)
        filename = f"export_{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        file_path = os.path.join(settings.export_path, filename)
        dataset_lines: list[str] = []
        with zipfile.ZipFile(file_path, "w", zipfile.ZIP_STORED) as zf:
            for item in items:
                try:
                    _pack_one(db, zf, item, scope, dataset_lines)
                except Exception:
                    logger.exception("导出单条失败 task=%s item=%s", task_id, item)
                task.processed_count += 1
                db.commit()
            zf.writestr("dataset.txt", "\n".join(dataset_lines).encode("utf-8"))

        task.status = "completed"
        task.file_path = file_path
        db.commit()
        logger.info("导出任务 %s 完成：%s 项入包 %s", task_id, len(dataset_lines), file_path)
    except Exception:
        logger.exception("导出任务 %s 失败", task_id)
        if task is not None:
            try:
                task.status = "failed"
                db.commit()
            except Exception:
                logger.exception("导出任务 %s 状态落库失败", task_id)
    finally:
        db.close()


# ---------- 轮询与下载 ----------

@router.get("/task/{task_id}", response_model=ApiResponse[ExportTaskStatusData])
def task_status(task_id: int,
                admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    task = db.get(ExportTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    file_url = None
    if task.status == "completed" and task.file_path and os.path.exists(task.file_path):
        file_url = f"/api/admin/export/download/{task.id}"
    return ApiResponse[ExportTaskStatusData](data=ExportTaskStatusData(
        status=task.status, total_count=task.total_count,
        processed_count=task.processed_count, file_url=file_url))


def _burn_file(file_path: str) -> None:
    """下载即焚：响应送达后删除 ZIP 文件（任务台账保留供追溯）"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info("导出文件即焚: %s", file_path)
    except OSError:
        logger.warning("导出文件即焚失败: %s", file_path)


@router.get("/download/{task_id}")
def download(task_id: int,
             background_tasks: BackgroundTasks,
             admin: User = Depends(require_admin),
             db: Session = Depends(get_db)):
    task = db.get(ExportTask, task_id)
    if task is None or task.status != "completed":
        raise HTTPException(status_code=404, detail="文件不存在或未完成")
    if not task.file_path or not os.path.exists(task.file_path):
        raise HTTPException(status_code=404, detail="文件已删除")  # 即焚后二次下载
    background_tasks.add_task(_burn_file, task.file_path)
    return FileResponse(task.file_path, media_type="application/zip",
                        filename=os.path.basename(task.file_path))
