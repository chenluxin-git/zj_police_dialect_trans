r"""语音转译后台泵（dome trans-work 定稿 → 真实实现，仿 qc.py 解剖）：
- trans_loop 每 trans_scan_interval(3s) 秒经 asyncio.to_thread 驱动 pump_pending
  （main.py startup 拉起；测试直接同步调 pump_pending，无需起线程）
- pump_pending：① processing 超 trans_stuck_minutes(20min，须 > asr_timeout×3≈15min)
  按 updated_at 回置 pending（进程崩溃/被杀自愈） ② 候选 = 「无 processing 在途用户」的
  最老 pending，按全局 created_at 最先挑用户 → 处理完一条重选 → 用户间轮转防饿死
  ③ 泵单线程顺序执行，每用户天然串行
- _process_one：置 processing 先提交（前端 3s 轮询立即见「识别中」）→ mock / call_asr
  → done + text_raw；异常 failed + error_message；处理期间行被删除容忍竞态
- 上游未配置（asr_upstream_base 空）且未开 mock → failed「转译服务未配置」——
  与 QC 的 pending 直通不同：转译本身是功能目的，没有上游就没有结果可言
- 不发站内信（工作台轮询在带内可见，与 QC 被动流不同）
注意：模块级 SessionLocal 供测试 monkeypatch 指向 TestingSession（同 qc.py 口径）
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from ..core.config import settings
from ..core.database import SessionLocal
from ..models import Transcription
from .qc import call_asr

logger = logging.getLogger(__name__)

# mock 识别文案（trans_asr_mock=True 演示/联调用，与 dome 工作台 MOCK_TEXTS 同源）
MOCK_TEXTS = [
    "侬好，我是社区民警，麻烦开开门头。",
    "莫慌莫慌，慢慢叫讲，到底啥个事体？",
    "钞票转出去了就麻烦了，先把手机关机。",
    "落雨了，衣裳好收收了。",
    "今朝天气蛮好，一道去外面走走伐。",
    "阿拉这个地方老早叫法不一样的。",
    "你莫跑，站牢！我是警察。",
    "隔壁阿婆人蛮好的，经常帮阿拉看门头。",
]


def _asr_or_mock(row: Transcription) -> str:
    if settings.trans_asr_mock:
        return MOCK_TEXTS[row.id % len(MOCK_TEXTS)]
    if not settings.asr_upstream_base:
        raise RuntimeError("转译服务未配置")
    return call_asr(row.file_path)


def _process_one(db, row: Transcription) -> None:
    row.status = "processing"
    db.commit()  # 先置识别中：前端轮询立即看到状态翻转
    try:
        text = _asr_or_mock(row)
    except Exception as e:  # 识别失败留 failed + error（工作台可重试）
        row.status = "failed"
        row.error_message = str(e)[:500]
        db.commit()
        logger.warning("transcription %s 识别失败: %s", row.id, e)
        return
    # 处理期间行被删除（DELETE 任意状态可删）：发真 SQL 探测，
    # 不能用 db.get（身份映射命中不会落库查询）
    alive = db.execute(select(Transcription.id).where(Transcription.id == row.id)).scalar()
    if alive is None:
        db.rollback()
        return
    row.text_raw = text
    row.status = "done"
    db.commit()


def _recover_stuck(db) -> None:
    cutoff = datetime.now() - timedelta(minutes=settings.trans_stuck_minutes)
    stuck = db.scalars(select(Transcription).where(
        Transcription.status == "processing",
        Transcription.updated_at < cutoff,
    )).all()
    for row in stuck:
        row.status = "pending"
        db.commit()
        logger.warning("transcription %s 卡死自愈：processing 超 %s 分钟回置 pending",
                       row.id, settings.trans_stuck_minutes)


def _next_candidate(db) -> Transcription | None:
    """候选 = 「无 processing 在途用户」的最老 pending（全局 created_at 最先者）。
    泵单线程：处理完一条重新选 → 同一用户的多条天然串行、多用户间轮转（A1→B1→A2→B2）。"""
    busy = set(db.scalars(select(Transcription.user_id)
                          .where(Transcription.status == "processing")).all())
    rows = db.scalars(select(Transcription).where(Transcription.status == "pending")
                      .order_by(Transcription.created_at.asc(), Transcription.id.asc())).all()
    for row in rows:
        if row.user_id not in busy:
            return row
    return None


def pump_pending() -> None:
    """一轮泵：自愈 → 循环取候选逐条处理，直到无可处理（同步体，测试可直接调用）"""
    with SessionLocal() as db:
        _recover_stuck(db)
        while True:
            row = _next_candidate(db)
            if row is None:
                break
            _process_one(db, row)


async def trans_loop() -> None:
    while True:
        await asyncio.sleep(settings.trans_scan_interval)
        try:
            await asyncio.to_thread(pump_pending)
        except Exception:
            logger.exception("trans loop iteration failed")
