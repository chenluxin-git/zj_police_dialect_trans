"""T19 管理端音频上传：多文件（UUID 重命名 + convert_to_wav + ffprobe 时长），区域随管理员归属、超管可指定
复用 T8 契约 convert_to_wav / _ffmpeg_sem（from ..recordings，签名勿偏）；落盘 audio_storage/library/{uuid}.wav。
"""
import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import get_db
from ...models import AudioFile, Dialect, Region, User
from ...schemas import ok
from ..deps import require_admin, resolve_scope
from ..recordings import _ffmpeg_sem, convert_to_wav

router = APIRouter(prefix="/audio", tags=["管理端-音频上传"])


def _resolve_region(db: Session, admin: User, region_code: str | None) -> str:
    """导入归属区域裁定（规格裁定 2026-09-22：导入强制落区县级）。
    用户侧领取为"本区/空区"精确匹配，市/省级码（331000/330000）会成为县级用户领不到的死数据，故：
    - 县级管理员不传 → 默认本区（表单零摩擦）
    - 市/省/超管不传 → 400（必须显式选定区县）
    - 传入值须为 Region 表 district 级行（400），且 ∈ 本人 scope（403）
    """
    own = admin.region_code or ""
    own_row = db.get(Region, own)
    if not region_code:
        if own_row is not None and own_row.level == "district":
            return own
        raise HTTPException(400, "市/省级管理员导入必须指定区县级 region_code（市/省级归属县级用户无法领取）")
    row = db.get(Region, region_code)
    if row is None or row.level != "district":
        raise HTTPException(400, "region_code 必须是区县级（市级/省级码会导致县级用户无法领取）")
    scope = resolve_scope(db, admin)
    if scope is not None and region_code not in scope:
        raise HTTPException(403, "指定的区域不在你的辖区")
    return region_code


def _dialect_code(db: Session, region_code: str) -> str:
    d = db.query(Dialect).filter(Dialect.region_code == region_code).first()
    return d.code if d else ""


@router.post("/upload")
async def upload_audio(
    files: list[UploadFile] = File(...),
    region_code: str | None = Form(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    region = _resolve_region(db, admin, region_code)
    dialect_code = _dialect_code(db, region)
    lib_dir = os.path.join(settings.audio_storage_path, "library")
    os.makedirs(lib_dir, exist_ok=True)

    imported = 0
    results: list[dict] = []
    for f in files:
        fname = f.filename or "audio"
        try:
            src = await f.read()
            dst = os.path.join(lib_dir, f"{uuid.uuid4().hex}.wav")
            async with _ffmpeg_sem:
                duration = await asyncio.to_thread(convert_to_wav, src, dst)
            af = AudioFile(file_path=os.path.abspath(dst), file_name=fname, duration=duration,
                           region_code=region, dialect_code=dialect_code)
            db.add(af)
            db.commit()
            imported += 1
            results.append({"file_name": fname, "id": af.id})
        except Exception as e:  # noqa: BLE001
            results.append({"file_name": fname, "error": str(e)[:200]})
    return ok({"imported": imported, "results": results})