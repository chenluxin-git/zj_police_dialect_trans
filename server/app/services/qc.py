r"""T9 录音异步质检服务（计划 2026-09-22-implementation-plan.md 任务 9 参考实现）：
- 相似度 = 1 - levenshtein/max(len)：normalize 去标点（只留数字/字母/汉字）+ 小写
- ≥阈值(默认0.5) passed；< 阈值 failed=标记未通过并保留（行/文件都在，可试听对比），站内信通知重录
  （文本回池由 texts.assign 按 qc_status 排除实现；重录时上传端删旧 failed 行再插新行，unique 不动）
- ASR 接口异常：记 qc_logs(result=error) 留 pending，绝不误删；error 计数 ≥ QC_MAX_RETRY(3) 跳过留人工
- asr_upstream_base 为空 = 质检停用：pending 直通 passed 且不写 qc_logs
- qc_loop 60s 扫一轮（asyncio.to_thread 跑同步 process_pending，不阻塞事件循环）
注意：模块级 SessionLocal 供测试 monkeypatch 指向 TestingSession（同引擎数据互通）
"""
import asyncio
import logging
import os
import re
import threading
import time

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


# 仅网络类异常 / 上游 5xx 值得即时重试（4xx 重试无意义，对齐 new_tailect asr_upstream 策略）
_RETRYABLE_ASR = (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError)


def _asr_retryable(err: Exception) -> bool:
    if isinstance(err, _RETRYABLE_ASR):
        return True
    return isinstance(err, httpx.HTTPStatusError) and 500 <= err.response.status_code < 600


def call_asr(wav_path: str) -> str:
    """调上游转译（契约对齐 new_tailect）：POST {base}/asr?diarization=false，
    multipart 字段 file（纯二进制），响应 {"text": "..."}；网络/5xx 即时重试 2 次。"""
    for attempt in range(3):  # 1 次原始 + 2 次重试
        try:
            with httpx.Client(timeout=settings.asr_timeout,
                              verify=settings.asr_verify_ssl) as c, open(wav_path, "rb") as f:
                r = c.post(f"{settings.asr_upstream_base}/asr?diarization=false",
                           files={"file": (os.path.basename(wav_path), f)})
                r.raise_for_status()
                return r.json().get("text", "")
        except Exception as e:
            if not _asr_retryable(e) or attempt == 2:
                raise
            if attempt > 0:  # 首次失败立即重试，第二次起退避 2s（对齐参考项目策略）
                time.sleep(2)
    raise RuntimeError("unreachable")  # pragma: no cover


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
    rid, uid = rec.id, rec.user_id
    db.add(QCLog(recording_id=rid, user_id=uid, text_id=rec.text_id,
                 text_content=content, asr_text=asr, similarity=sim, result="failed"))
    rec.qc_status = "failed"  # 保留行+文件（可试听对比）；文本回池见 texts.assign
    send_message(db, [uid], "录音质检未通过",
                 f"你上传的录音「{content}」经方言转译接口比对，相似度 {sim:.0%}，"
                 f"低于 {settings.qc_similarity_threshold:.0%} 阈值，判定不合格。"
                 f"该录音已保留在「历史录音」中并标记为未通过，对应文本已释放，"
                 f"请前往「录音采集」重新领取该文本录制。", sender_id=None)
    db.commit()


def process_pending() -> None:
    if not settings.asr_upstream_base:  # 质检停用：pending 直通
        with SessionLocal() as db:
            for rec in db.scalars(select(Recording).where(Recording.qc_status == "pending")).all():
                rec.qc_status = "passed"
            db.commit()
        return
    with SessionLocal() as db:
        for rec in db.scalars(select(Recording).where(Recording.qc_status == "pending")).all():
            _process_guarded(db, rec)


# ---------- 适时质检（录完即发起）：trigger_qc 立即单条处理，qc_loop 仍兜底 ----------

_inflight: set[int] = set()          # 正在处理的 recording id，防两条路径同条双跑（双删/双信）
_inflight_lock = threading.Lock()


def _acquire(rid: int) -> bool:
    with _inflight_lock:
        if rid in _inflight:
            return False
        _inflight.add(rid)
        return True


def _release(rid: int) -> None:
    with _inflight_lock:
        _inflight.discard(rid)


def _process_guarded(db, rec: Recording) -> None:
    """带在制防重入的单条处理：适时触发与 qc_loop 扫描共用"""
    if not _acquire(rec.id):
        return
    try:
        errs = db.scalar(select(func.count()).select_from(QCLog)
                         .where(QCLog.recording_id == rec.id, QCLog.result == "error"))
        if errs < settings.qc_max_retry:  # ≥ 上限留待人工
            process_one(db, rec)
    finally:
        _release(rec.id)


def _run_one(rec_id: int) -> None:
    """适时质检执行体（trigger_qc 的线程目标；测试亦可直接同步调用）"""
    with SessionLocal() as db:
        rec = db.get(Recording, rec_id)
        if rec is None or rec.qc_status != "pending":
            return
        if not settings.asr_upstream_base:  # 停用：单条直通，不必等扫描轮
            rec.qc_status = "passed"
            db.commit()
            return
        _process_guarded(db, rec)


def trigger_qc(rec_id: int) -> None:
    """录音登记完成后由接口层调用：后台线程立即质检该条，不等 60s 扫描轮"""
    threading.Thread(target=_run_one, args=(rec_id,), daemon=True).start()


async def qc_loop() -> None:
    while True:
        await asyncio.sleep(settings.qc_scan_interval)
        try:
            await asyncio.to_thread(process_pending)
        except Exception:
            logger.exception("qc loop iteration failed")
