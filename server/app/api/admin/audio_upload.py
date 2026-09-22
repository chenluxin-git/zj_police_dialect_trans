"""T19 管理端音频上传：多文件（UUID 重命名 + convert_to_wav + ffprobe 时长），区域随管理员归属、超管可指定
复用 T8 契约 convert_to_wav / _ffmpeg_sem（from ..recordings，签名勿偏）；落盘 audio_storage/library/{uuid}.wav。
"""
import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import get_db
from ...models import AudioFile, Dialect, User
from ...schemas import ok
from ..deps import require_admin
from ..recordings import _ffmpeg_sem, convert_to_wav

router = APIRouter(prefix="/audio", tags=["管理端-音频上传"])


def _resolve_region(admin: User, region_code: str | None) -> str:
    if admin.role == "super_admin" and region_code:
        return region_code
    return admin.region_code or ""


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
    region = _resolve_region(admin, region_code)
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