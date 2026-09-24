"""演示数据生成器（离线脚本，不走 HTTP、不需要 ffmpeg）

为什么需要它：`utils/seed.py` 只灌区划/方言/派出所/账号，**不产生任何业务数据**，
所以数据总览除了「民警总数」之外全是 0，省级/市级总览、排行、覆盖率这类需要在界面上
看效果的改动都无法验收。

本脚本按现有业务规则直接落库，并生成真实的占位 WAV 文件（录音试听/导出可用）：
- texts：按区县生成朗读文本（类别覆盖 警情/生活/俚语/地名）
- recordings：民警已通过质检的采集录音（qc_status='passed'）+ 少量待质检积压
  + 少量质检未通过（qc_status='failed'，附 qc_logs 原文/转译比对流水，供对比弹窗演示）
- audio_files：从本地录音派生素材（保证标注译文与音频内容对应）+ annotations
- tasks：按区县给民警下达录音/标注指标，各市完成率刻意拉开差距
- transcriptions：工作台语音转译记录（多数 done 其中部分带人工修正 / 少量 failed 可重试 /
  少量 pending 在途，识别文本取当区朗读语料原文，文件名混用工作台演示词汇）

执行：
    cd server
    .venv/Scripts/python -m app.utils.demo_data --reset     # 清空业务数据后生成
    .venv/Scripts/python -m app.utils.demo_data --seed 1234 # 固定随机种子

安全：只删/写 texts / text_assignments / recordings / audio_files / file_assignments /
annotations / tasks / qc_logs / transcriptions 九张业务表，**不动 users / regions /
dialects / police_stations**。
"""
from __future__ import annotations

import argparse
import math
import os
import random
import re
import struct
import sys
import wave
from datetime import datetime, timedelta

from ..core.config import settings
from ..core.database import SessionLocal
from ..models import (
    Annotation,
    AudioFile,
    Dialect,
    FileAssignment,
    QCLog,
    Recording,
    Region,
    Task,
    Text,
    TextAssignment,
    Transcription,
    User,
)

# ---------------------------------------------------------------- 语料素材
# (方言原文, 普通话译文) 成对维护，保证「标注译文」与音频内容语义对应
PAIRS_POLICE = [
    ("你们不要吵了，都先坐下来，有话好好讲。", "请大家不要争吵了，先坐下来好好说。"),
    ("我是社区民警，麻烦开下门，做个入户登记。", "我是社区民警，请开一下门做入户登记。"),
    ("你把事情的经过再讲一遍，从头说，别急。", "你把事情经过再讲一遍，从头说，不要着急。"),
    ("这个路口不能停车，你把车挪一挪。", "这个路口不能停车，请把车挪开。"),
    ("身份证带了吗？给我看一下。", "带身份证了吗？请给我看一下。"),
    ("这个事我们已经在处理了，你先回去等消息。", "这件事我们正在处理，你先回去等候消息。"),
    ("邻里之间低头不见抬头见，各让一步算了。", "邻里之间天天见面，各让一步就算了。"),
    ("你反映的情况我记下来了，回头有人跟你联系。", "你反映的情况我记下了，会有人跟你联系。"),
    ("手机收到这种短信不要点，直接删掉。", "这类短信不要点击，直接删除。"),
    ("钱转出去了就麻烦了，先把手机关机。", "钱转出去就麻烦了，先把手机关机。"),
    ("工地晚上不要施工，周边居民反映休息不好。", "工地晚上不要施工，周边居民反映休息不好。"),
    ("你这个手续还差一份材料，补齐了我给你办。", "你这个手续还差一份材料，补齐了我给你办。"),
]
PAIRS_LIFE = [
    ("今朝天气蛮好，一道去外面走走伐。", "今天天气很好，一起到外面走走。"),
    ("这个菜咸了点，下趟少放点盐。", "这个菜咸了点，下次少放点盐。"),
    ("饭吃过了没有？没吃就一道吃一点。", "吃过饭了吗？没吃就一起吃一点。"),
    ("天要落雨了，出门记得带把伞。", "天要下雨了，出门记得带把伞。"),
    ("小囡读书成绩怎么样？", "孩子读书成绩怎么样？"),
    ("屋里厢都还好伐？", "家里都还好吗？"),
    ("这个西瓜甜得很，你尝一块试试看。", "这个西瓜很甜，你尝一块试试。"),
    ("路上车子多，慢点走，注意安全。", "路上车多，走慢一点，注意安全。"),
    ("隔壁阿婆人蛮好的，经常帮我们看门。", "隔壁奶奶人很好，经常帮我们看门。"),
    ("现在菜价贵了不少。", "现在菜价贵了不少。"),
]
PAIRS_PLACE = [
    ("过了前面那座桥，往右手边拐就到了。", "过了前面那座桥，往右拐就到了。"),
    ("这个地方老早叫法不一样。", "这个地方以前的叫法不一样。"),
    ("镇上那条老街，以前是最热闹的地方。", "镇上那条老街，以前是最热闹的地方。"),
    ("从这个村到那个村，骑车子大概二十分钟。", "从这个村到那个村，骑车大概二十分钟。"),
    ("山背后还有个水库，路不太好走。", "山后面还有一个水库，路不太好走。"),
    ("码头那边在修路，绕一下走新桥。", "码头那边在修路，绕行走新桥。"),
    ("这条河以前可以撑船的。", "这条河以前可以行船的。"),
    ("村口那棵大树有几百年了。", "村口那棵大树有几百年的树龄了。"),
]
PAIRS_DIRTY = [
    ("你这个小鬼头，皮得很。", "你这个小孩子，非常调皮。"),
    ("做事体毛毛躁躁，要沉住气。", "做事毛手毛脚，要沉住气。"),
    ("这个东西破破烂烂的，还好用啊？", "这个东西破破烂烂的，还能用吗？"),
    ("他这个人嘴巴碎，什么话都往外讲。", "他这个人嘴碎，什么话都往外说。"),
    ("弄成这个样子，真是难看得很。", "弄成这个样子，实在太难看了。"),
    ("慢吞吞的，什么时候才做得完。", "慢吞吞的，什么时候才能做完。"),
]
PAIRS_BY_CATEGORY = {
    "police": PAIRS_POLICE,
    "life": PAIRS_LIFE,
    "place": PAIRS_PLACE,
    "dirty": PAIRS_DIRTY,
}
# 与该类别不同的句子池：给 failed 演示行凑一个低相似度的"转译文本"
_OTHER_PAIRS = {
    cat: [p for c, ps in PAIRS_BY_CATEGORY.items() if c != cat for p in ps]
    for cat in PAIRS_BY_CATEGORY
}
FAILED_RATIO = 0.06  # 已质检录音中"未通过"占比（演示红 tag + 对比弹窗）
# 转译记录文件名词汇（dome 工作台演示稿同源，混用音视频扩展名）
TRANS_NAMES = [
    ("rec_0047.webm", "webm"), ("调解录音_0923.wav", "wav"),
    ("接处警_20260921.mp3", "mp3"), ("走访记录.m4a", "m4a"),
    ("执法记录_0922.mp4", "mp4"), ("纠纷现场.wav", "wav"),
]

# ---------------------------------------------------------------- 各市投放强度
# 刻意拉开差距，好让「分市排行 / 红黑榜」在界面上有内容
# 市码 -> (参与民警比例, 人均录音数, 待质检积压比例, 标注完成比例)
CITY_INTENSITY = {
    "330100": (1.00, 24, 0.06, 0.82),   # 杭州
    "330200": (0.95, 21, 0.08, 0.76),   # 宁波
    "330300": (0.90, 19, 0.10, 0.70),   # 温州
    "330400": (0.85, 17, 0.12, 0.62),   # 嘉兴
    "330500": (0.80, 15, 0.14, 0.55),   # 湖州
    "330600": (0.78, 14, 0.16, 0.48),   # 绍兴
    "330700": (0.70, 12, 0.18, 0.40),   # 金华
    "330800": (0.62, 10, 0.20, 0.32),   # 衢州
    "330900": (0.55, 8, 0.24, 0.24),    # 舟山
    "331000": (0.45, 6, 0.28, 0.16),    # 台州
    "331100": (0.30, 4, 0.34, 0.08),    # 丽水（进度最落后）
}
DEFAULT_INTENSITY = (0.50, 8, 0.20, 0.30)

SPAN_DAYS = 60           # 数据分布在最近 60 天
WAV_SAMPLE_RATE = 16000  # 与后端 ffmpeg 转码目标一致（16k 单声道）
TEXTS_PER_CATEGORY = (8, 13)  # 每区县每类文本条数区间（决定录音上限）


# ---------------------------------------------------------------- 工具

def _write_wav(path: str, seconds: float, freq: float = 220.0) -> int:
    """写一个真实可播放的 16k 单声道 WAV（低幅正弦，便于试听时确认播放链路）。

    返回文件字节数。16k/16bit 与后端转码目标一致，导出 ZIP 与浏览器播放都能用。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = max(1, int(WAV_SAMPLE_RATE * seconds))
    amp = 3000  # 幅度压低，避免刺耳
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(WAV_SAMPLE_RATE)
        frames = bytearray()
        for i in range(n):
            v = int(amp * math.sin(2 * math.pi * freq * i / WAV_SAMPLE_RATE))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return os.path.getsize(path)


def _user_folder(user: User) -> str:
    """与 app/api/recordings.py::_user_folder 保持一致，保证落盘布局真实。"""
    safe = re.sub(r"[^\w\u4e00-\u9fff]", "", user.real_name or "")
    tail4 = user.phone[-4:] if len(user.phone) >= 4 else user.phone
    return f"{safe or 'user'}_{tail4}"


def _spread_time(rng: random.Random, now: datetime) -> datetime:
    """在最近 SPAN_DAYS 天内随机取一个时刻，越近的日子权重略高（模拟持续推进）。"""
    frac = min(rng.random(), rng.random())  # 两次取小 → 向"最近"倾斜
    return now - timedelta(days=SPAN_DAYS * frac, seconds=rng.randint(0, 86399))


# ---------------------------------------------------------------- 主流程

def reset_business_data(db) -> None:
    """只清业务表，保留账号与基础数据。"""
    for model in (Annotation, FileAssignment, AudioFile, QCLog, Recording,
                  Transcription, TextAssignment, Text, Task):
        db.query(model).delete()
    db.commit()


def run(db, rng: random.Random, reset: bool) -> dict:
    now = datetime.now()
    st = {"texts": 0, "recordings": 0, "pending": 0, "failed": 0, "audio_files": 0,
          "annotations": 0, "tasks": 0, "users_active": 0, "wav": 0,
          "trans": 0, "trans_fixed": 0}

    if reset:
        reset_business_data(db)
        print("已清空业务表（texts/recordings/audio_files/annotations/tasks 等）")

    regions = {r.code: r for r in db.query(Region).all()}
    dialect_by_region: dict[str, str] = {}
    for d in db.query(Dialect).all():
        dialect_by_region.setdefault(d.region_code, d.code)

    cities = [r for r in regions.values() if r.level == "city"]
    districts_by_city: dict[str, list[Region]] = {c.code: [] for c in cities}
    for r in regions.values():
        if r.level == "district" and r.parent_code in districts_by_city:
            districts_by_city[r.parent_code].append(r)

    users_by_district: dict[str, list[User]] = {}
    for u in db.query(User).filter(User.role == "user").all():
        users_by_district.setdefault(u.region_code, []).append(u)

    storage = settings.audio_storage_path

    # ---------------- 1) 文本 ----------------
    # 注意：text_assignments.text_id 是 unique（一条文本只分给一人），
    # 所以下面每县只挑一条文本建一条分配记录用于演示锁定，其余不建——否则唯一约束冲突。
    texts_by_district: dict[str, list[Text]] = {}
    # (区县码, 原文) -> 译文，供后面的标注使用
    translation_of: dict[tuple[str, str], str] = {}
    for city in cities:
        for d in districts_by_city.get(city.code, []):
            dcode = dialect_by_region.get(d.code, "")
            dname = next((x.name for x in db.query(Dialect).all()
                          if x.code == dcode), "通用")
            pool: list[Text] = []
            for cat, pairs in PAIRS_BY_CATEGORY.items():
                for _ in range(rng.randint(*TEXTS_PER_CATEGORY)):
                    src, dst = rng.choice(pairs)
                    pool.append(Text(
                        content=src, dialect=dname, category=cat,
                        region_code=d.code, dialect_code=dcode,
                        created_at=_spread_time(rng, now),
                    ))
                    translation_of[(d.code, src)] = dst
            db.add_all(pool)
            texts_by_district[d.code] = pool
    db.flush()
    st["texts"] = db.query(Text).count()

    # ---------------- 2) 录音 ----------------
    rec_translation: dict[tuple[str, int], str] = {}  # (区县码, recording_id) -> 译文
    for city in cities:
        ratio, per_capita, pending_ratio, _ = CITY_INTENSITY.get(city.code, DEFAULT_INTENSITY)
        for d in districts_by_city.get(city.code, []):
            officers = users_by_district.get(d.code, [])
            pool = texts_by_district.get(d.code, [])
            if not officers or not pool:
                continue
            dcode = dialect_by_region.get(d.code, "")
            n_active = max(1, int(round(len(officers) * ratio)))
            active = officers[:n_active]
            st["users_active"] += len(active)

            for u in active:
                # 人均条数按强度浮动，但受「本县文本池」上限约束（unique(user_id, text_id)）
                want = max(1, int(rng.gauss(per_capita, per_capita * 0.4)))
                cnt = min(want, len(pool))
                for t in rng.sample(pool, cnt):
                    dur = round(rng.uniform(4.0, 18.0), 2)
                    is_pending = rng.random() < pending_ratio
                    is_failed = (not is_pending) and rng.random() < FAILED_RATIO
                    path = os.path.join(storage, _user_folder(u), f"demo_{u.id}_{t.id}.wav")
                    size = _write_wav(path, dur, freq=rng.choice([180, 220, 260, 300]))
                    st["wav"] += 1
                    qc_status = "pending" if is_pending else ("failed" if is_failed else "passed")
                    rec = Recording(
                        user_id=u.id, text_id=t.id, file_path=path, file_size=size,
                        duration=dur, region_code=d.code, dialect_code=dcode,
                        qc_status=qc_status,
                        created_at=_spread_time(rng, now),
                    )
                    db.add(rec)
                    db.flush()
                    if is_pending:
                        st["pending"] += 1
                    elif is_failed:
                        # 配套质检流水：转译文本取"别的类别"的句子凑低相似，演示对比弹窗
                        st["failed"] += 1
                        asr_text = rng.choice(
                            _OTHER_PAIRS.get(t.category, PAIRS_LIFE))[0]
                        db.add(QCLog(
                            recording_id=rec.id, user_id=u.id, text_id=t.id,
                            text_content=t.content, asr_text=asr_text,
                            similarity=round(rng.uniform(0.2, 0.4), 2),
                            result="failed",
                            created_at=rec.created_at + timedelta(seconds=rng.randint(5, 120)),
                        ))
                    else:
                        rec_translation[(d.code, rec.id)] = translation_of.get(
                            (d.code, t.content), "（未提供译文）")
            # 每县一条文本分配记录（演示领取锁；受 unique(text_id) 限制只能建一条）
            db.add(TextAssignment(text_id=pool[0].id, user_id=active[0].id,
                                  assigned_at=_spread_time(rng, now)))
    db.flush()
    st["recordings"] = db.query(Recording).count()

    # ---------------- 3) 标注素材库（从本地已通过录音派生）+ 标注 ----------------
    # 派生而非独立生成：保证素材的 dialect/region 与本地一致，且译文与音频内容语义对应
    for city in cities:
        _, _, _, ann_rate = CITY_INTENSITY.get(city.code, DEFAULT_INTENSITY)
        for d in districts_by_city.get(city.code, []):
            officers = users_by_district.get(d.code, [])
            if not officers:
                continue
            dcode = dialect_by_region.get(d.code, "")
            passed = (db.query(Recording)
                      .filter(Recording.region_code == d.code,
                              Recording.qc_status == "passed")
                      .order_by(Recording.id).all())
            if not passed:
                continue
            # 约 55% 的已通过录音进入素材库
            n_audio = max(1, int(len(passed) * 0.55))
            picked = passed[:n_audio]
            files: list[AudioFile] = []
            for i, rec in enumerate(picked):
                fname = f"zj_{d.code}_{i:04d}.wav"
                path = os.path.join(storage, "library", fname)
                size = _write_wav(path, rec.duration, freq=rng.choice([170, 240, 310]))
                st["wav"] += 1
                af = AudioFile(
                    file_path=path, file_name=fname, duration=rec.duration,
                    region_code=d.code, dialect_code=dcode,
                    created_at=rec.created_at,
                )
                db.add(af)
                files.append(af)
                _ = size
            db.flush()
            # 按比例标注，未标注的留作积压
            n_ann = int(len(files) * ann_rate)
            for af, rec in zip(files[:n_ann], picked[:n_ann]):
                db.add(Annotation(
                    file_id=af.id,
                    annotator_id=rng.choice(officers).id,
                    is_dialect=True,
                    translation=rec_translation.get((d.code, rec.id), "（未提供译文）"),
                    region_code=d.code,
                    created_at=af.created_at,
                ))
    db.flush()
    st["audio_files"] = db.query(AudioFile).count()
    st["annotations"] = db.query(Annotation).count()

    # ---------------- 4) 任务 ----------------
    # base_count=0 使 done 直接等于当前有效数，界面上能直观看到各市完成率拉开差距
    for city in cities:
        ratio, _, _, _ = CITY_INTENSITY.get(city.code, DEFAULT_INTENSITY)
        for d in districts_by_city.get(city.code, []):
            officers = users_by_district.get(d.code, [])
            if not officers:
                continue
            n_active = max(1, int(round(len(officers) * ratio)))
            for u in officers[:n_active]:
                done = (db.query(Recording)
                        .filter(Recording.user_id == u.id,
                                Recording.qc_status == "passed").count())
                db.add(Task(
                    user_id=u.id, type="recording",
                    target_count=max(5, int(done / rng.uniform(0.55, 0.98))),
                    base_count=0, status="active", note="省级演示数据",
                    created_by=1, created_at=_spread_time(rng, now),
                ))
                st["tasks"] += 1
            if rng.random() < 0.55:   # 只有部分区县下达了标注任务
                for u in officers[:n_active]:
                    done = (db.query(Annotation)
                            .filter(Annotation.annotator_id == u.id).count())
                    if done == 0:
                        continue
                    db.add(Task(
                        user_id=u.id, type="annotation",
                        target_count=max(3, int(done / rng.uniform(0.5, 0.95))),
                        base_count=0, status="active", note="省级演示数据",
                        created_by=1, created_at=_spread_time(rng, now),
                    ))
                    st["tasks"] += 1

    # ---------------- 5) 语音转译（工作台） ----------------
    # 每区县 2~6 条，随机落在活跃民警名下：~72% done（识别文本取当区朗读语料原文，
    # 其中约 1/4 带人工修正金标）、~10% failed（可重试演示）、~18% pending（刷新后在途可水化）
    for city in cities:
        ratio = CITY_INTENSITY.get(city.code, DEFAULT_INTENSITY)[0]
        for d in districts_by_city.get(city.code, []):
            officers = users_by_district.get(d.code, [])
            pool = texts_by_district.get(d.code, [])
            if not officers or not pool:
                continue
            active_officers = officers[:max(1, int(round(len(officers) * ratio)))]
            for _ in range(rng.randint(2, 6)):
                u = rng.choice(active_officers)
                fname, fext = TRANS_NAMES[rng.randrange(len(TRANS_NAMES))]
                dur = round(rng.uniform(3.0, 30.0), 2)
                roll = rng.random()
                row = Transcription(
                    user_id=u.id, region_code=d.code, file_name=fname, file_ext=fext,
                    file_path="", file_size=int(dur * 32000), duration=dur,
                    status="pending", created_at=_spread_time(rng, now),
                )
                db.add(row)
                db.flush()
                # 占位 wav 与真实上传同布局 {用户目录}/trans/{id}.wav，播放链路可走通
                path = os.path.join(storage, _user_folder(u), "trans",
                                    f"demo_t_{u.id}_{row.id}.wav")
                _write_wav(path, dur, freq=rng.choice([190, 240, 300]))
                st["wav"] += 1
                row.file_path = path
                if roll < 0.10:
                    row.status = "failed"
                    row.error_message = "转写接口超时，可重试"
                elif roll >= 0.18:
                    src = rng.choice(pool)
                    row.status = "done"
                    row.text_raw = src.content
                    if rng.random() < 0.25:  # 人工修正金标（译文来自语料配对）
                        row.text_fixed = translation_of.get(
                            (d.code, src.content), rng.choice(PAIRS_LIFE)[1])
                        st["trans_fixed"] += 1
                st["trans"] += 1

    db.commit()
    return st


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成方言平台演示数据（离线、不需要 ffmpeg）")
    ap.add_argument("--reset", action="store_true",
                    help="先清空业务表（texts/recordings/audio_files/annotations/tasks 等）再生成")
    ap.add_argument("--seed", type=int, default=20260923, help="随机种子，默认 20260923")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    with SessionLocal() as db:
        existing = db.query(Recording).count()
        if existing and not args.reset:
            print(f"检测到已有 {existing} 条录音；不加 --reset 会继续追加，可能产生重复数据。",
                  file=sys.stderr)
        st = run(db, rng, reset=args.reset)

    print("\n演示数据生成完成：")
    print(f"  文本        {st['texts']:>7} 条")
    print(f"  录音        {st['recordings']:>7} 条（待质检积压 {st['pending']} / 未通过 {st['failed']}）")
    print(f"  音频素材    {st['audio_files']:>7} 条")
    print(f"  标注        {st['annotations']:>7} 条")
    print(f"  任务        {st['tasks']:>7} 条")
    print(f"  转译记录    {st['trans']:>7} 条（人工修正 {st['trans_fixed']}）")
    print(f"  参与民警    {st['users_active']:>7} 人")
    print(f"  生成 WAV    {st['wav']:>7} 个（{settings.audio_storage_path}）")
    print("\n提示：录音/素材均为低幅正弦占位 WAV，试听与导出链路可正常走通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
