r"""T9 录音异步质检服务（计划 2026-09-22-implementation-plan.md 任务 9 参考实现）：
- 相似度 = 1 - levenshtein/max(len)：normalize 去标点（只留数字/字母/汉字）+ 小写
- ≥阈值(默认0.5) passed；< 阈值 failed=删录音+删文件+站内信通知重录（unique 解除，同文本可重录）
- ASR 接口异常：记 qc_logs(result=error) 留 pending，绝不误删；error 计数 ≥ QC_MAX_RETRY(3) 跳过留人工
- asr_api_url 为空 = 质检停用：pending 直通 passed 且不写 qc_logs
- qc_loop 60s 扫一轮（asyncio.to_thread 跑同步 process_pending，不阻塞事件循环）
注意：模块级 SessionLocal 供测试 monkeypatch 指向 TestingSession（同引擎数据互通）
"""
import asyncio
import logging
import os
import re

import httpx
from sqlalchemy import func, select

from ..core.config import settings
from ..core.database import SessionLocal
from ..models import QCLog, Recording, Text
from .messaging import send_message

logger = logging.getLogger(__name__)
_PUNCT = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]")


def normalize(s: str) -> str:
    return _PUNCT.sub("", s).lower()


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
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
        db.commit()
        logger.warning("qc error rec=%s: %s", rec.id, e)
        return
    sim = similarity(content, asr)
    if sim >= settings.qc_similarity_threshold:
        rec.qc_status = "passed"
        db.add(QCLog(recording_id=rec.id, user_id=rec.user_id, text_id=rec.text_id,
                     text_content=content, asr_text=asr, similarity=sim, result="passed"))
        db.commit()
        return
    rid, uid, path = rec.id, rec.user_id, rec.file_path
    db.add(QCLog(recording_id=rid, user_id=uid, text_id=rec.text_id,
                 text_content=content, asr_text=asr, similarity=sim, result="failed"))
    db.delete(rec)  # unique 解除，同文本可重录
    send_message(db, [uid], "录音质检未通过",
                 f"你上传的录音「{content}」经方言转译接口比对，相似度 {sim:.0%}，"
                 f"低于 {settings.qc_similarity_threshold:.0%} 阈值，判定不合格。"
                 f"该录音已移除，请前往「录音采集」重新录制。", sender_id=None)
    db.commit()
    try:
        os.remove(path)
    except OSError:
        logger.warning("qc 删文件失败 %s", path)


def process_pending() -> None:
    if not settings.asr_api_url:  # 质检停用：pending 直通
        with SessionLocal() as db:
            for rec in db.scalars(select(Recording).where(Recording.qc_status == "pending")).all():
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
