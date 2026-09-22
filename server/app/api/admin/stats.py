"""T20 数据总览（Spec §6.7）：省→市→县下钻两级聚合 + total 汇总 + 任务维度 + category_counts
- 每类指标一次 GROUP BY region_code 查询再在内存分桶到子区域行（勿逐区域循环查库）
- 录音数/时长/容量仅 qc_status='passed'
- 任务维度：scope 内全部 active tasks 复用 progress_map，done=max(0,有效数-base)，started=done>0
- category_counts：scope 内 texts 按 category 聚合（FE-4 类别分布条形图依赖）
2026-09-22 三级展开：市县管亦可传 region_code 下钻（须 ∈ 本人 scope）；
by=station 返回区县下派出所行（User.police_station 按单位名称聚合，texts/audio_files 无单位维度恒 0）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Annotation, AudioFile, PoliceStation, Recording, Region, Task, Text, User
from ...schemas import ok
from ...services.task_progress import progress_map
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/stats", tags=["管理端-数据总览"])


def _load_region_tree(db: Session):
    regions = {r.code: r for r in db.query(Region).all()}
    children: dict[str, list[str]] = {code: [] for code in regions}
    for code, r in regions.items():
        if r.parent_code in children:
            children[r.parent_code].append(code)
    return regions, children


def _descendants(code: str, children: dict[str, list[str]]) -> list[str]:
    out = [code]
    for c in children.get(code, []):
        out.extend(_descendants(c, children))
    return out


def _bucket(agg: dict, row_of_code: dict, row_codes: list[str], default=0):
    out = {rc: default for rc in row_codes}
    for code, val in agg.items():
        rc = row_of_code.get(code)
        if rc is not None:
            out[rc] += val
    return out


def _task_dimension(db: Session, task_rows: list[Task]) -> dict:
    prog = progress_map(db, [t.user_id for t in task_rows])
    target_sum = done_sum = started = not_started = 0
    for t in task_rows:
        key = "recording_done" if t.type == "recording" else "annotation_done"
        done = max(0, prog[t.user_id][key] - t.base_count)
        target_sum += t.target_count
        done_sum += done
        if done > 0:
            started += 1
        else:
            not_started += 1
    return {
        "target_sum": target_sum,
        "done_sum": done_sum,
        "rate": round(done_sum / target_sum, 4) if target_sum else 0.0,
        "started": started,
        "not_started": not_started,
    }


def _station_overview(db: Session, parent: Region):
    """by=station：区县下派出所行。User.police_station 存单位名称（非 code），按名称聚合归属；
    名称未落到 police_stations 表（含空串）的用户归入「未指定单位」行；
    texts / audio_files 无单位归属维度，行内恒 0（前端展示为 —）。"""
    stations = db.scalars(
        select(PoliceStation).where(PoliceStation.region_code == parent.code)
        .order_by(PoliceStation.sort_order, PoliceStation.code)).all()
    rows = [
        {"code": s.code, "name": s.name, "users": 0, "recordings": 0, "seconds": 0.0,
         "size_bytes": 0, "texts": 0, "audio_files": 0, "annotated": 0}
        for s in stations
    ]
    by_name = {r["name"]: r for r in rows}

    user_agg = dict(db.execute(
        select(User.police_station, func.count())
        .where(User.region_code == parent.code)
        .group_by(User.police_station)).all())
    rec_agg = {
        name: (int(n), float(secs or 0), int(sz or 0))
        for name, n, secs, sz in db.execute(
            select(User.police_station, func.count(), func.sum(Recording.duration), func.sum(Recording.file_size))
            .select_from(Recording)
            .join(User, Recording.user_id == User.id)
            .where(Recording.qc_status == "passed", User.region_code == parent.code)
            .group_by(User.police_station)).all()
    }
    ann_agg = dict(db.execute(
        select(User.police_station, func.count())
        .select_from(Annotation)
        .join(User, Annotation.annotator_id == User.id)
        .where(User.region_code == parent.code)
        .group_by(User.police_station)).all())

    rest = {"code": "_unassigned", "name": "未指定单位", "users": 0, "recordings": 0,
            "seconds": 0.0, "size_bytes": 0, "texts": 0, "audio_files": 0, "annotated": 0}
    for name, n in user_agg.items():
        r = by_name.get(name)
        if r is not None:
            r["users"] += n
        else:
            rest["users"] += n
    for name, (n, secs, sz) in rec_agg.items():
        r = by_name.get(name)
        if r is not None:
            r["recordings"] += n
            r["seconds"] += secs
            r["size_bytes"] += sz
        else:
            rest["recordings"] += n
            rest["seconds"] += secs
            rest["size_bytes"] += sz
    for name, n in ann_agg.items():
        r = by_name.get(name)
        if r is not None:
            r["annotated"] += n
        else:
            rest["annotated"] += n
    if any(rest[k] for k in ("users", "recordings", "annotated")):
        rows.append(rest)

    total = {
        "code": parent.code,
        "name": parent.name,
        "users": sum(user_agg.values()),
        "recordings": sum(v[0] for v in rec_agg.values()),
        "seconds": sum(v[1] for v in rec_agg.values()),
        "size_bytes": sum(v[2] for v in rec_agg.values()),
        "texts": db.scalar(select(func.count()).select_from(Text)
                           .where(Text.region_code == parent.code)) or 0,
        "audio_files": db.scalar(select(func.count()).select_from(AudioFile)
                                 .where(AudioFile.region_code == parent.code)) or 0,
        "annotated": sum(ann_agg.values()),
    }

    task_rows = db.execute(
        select(Task).join(User, Task.user_id == User.id)
        .where(Task.status == "active", User.region_code == parent.code)
    ).scalars().all()
    category_counts = dict(db.execute(
        select(Text.category, func.count())
        .where(Text.region_code == parent.code).group_by(Text.category)).all())

    return ok({"level": "station", "rows": rows, "total": total,
               "tasks": _task_dimension(db, task_rows), "category_counts": category_counts})


@router.get("/overview")
def overview(
    region_code: str | None = Query(None),
    by: str = Query("region"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if by not in ("region", "station"):
        raise HTTPException(400, "by 仅支持 region / station")
    scope = resolve_scope(db, admin)
    regions, children = _load_region_tree(db)

    # 定位视图父区域（省/市/县）：省/超管可传 region_code 下钻；市/县管传值须 ∈ 本人 scope，缺省自身区域
    parent = None
    if region_code:
        if scope is not None and region_code not in scope:
            raise HTTPException(403, "指定的区域不在你的辖区")
        parent = regions.get(region_code)
        if parent is None:
            raise HTTPException(status_code=404, detail="区域不存在")
    elif scope is None:  # super_admin / 省管缺省 → 省级
        parent = next((r for r in regions.values() if r.level == "province"), None)
    else:  # 市管/县管缺省 → 自身区域
        parent = regions.get(admin.region_code)

    if parent is None:
        empty = {"users": 0, "recordings": 0, "seconds": 0.0, "size_bytes": 0,
                 "texts": 0, "audio_files": 0, "annotated": 0}
        return ok({"level": None, "rows": [], "total": empty,
                   "tasks": {"target_sum": 0, "done_sum": 0, "rate": 0.0, "started": 0, "not_started": 0},
                   "category_counts": {}})

    if by == "station":
        if parent.level != "district":
            raise HTTPException(400, "by=station 仅支持区县区域（市/省无派出所归属）")
        return _station_overview(db, parent)

    level = parent.level
    if level in ("province", "city"):
        row_codes = children.get(parent.code, [])
    else:  # district（或 town）：本县单行
        row_codes = [parent.code]

    row_of_code: dict[str, str] = {}
    for rc in row_codes:
        for dc in _descendants(rc, children):
            row_of_code[dc] = rc

    # 每类指标一次 GROUP BY region_code 查询
    user_counts = dict(db.execute(
        select(User.region_code, func.count())
        .where(scope_filter(User.region_code, scope)).group_by(User.region_code)).all())
    rec_rows = db.execute(
        select(Recording.region_code, func.count(), func.sum(Recording.duration), func.sum(Recording.file_size))
        .where(Recording.qc_status == "passed", scope_filter(Recording.region_code, scope))
        .group_by(Recording.region_code)).all()
    rec_counts = {c: n for c, n, _, _ in rec_rows}
    rec_seconds = {c: float(s or 0) for c, _, s, _ in rec_rows}
    rec_sizes = {c: int(sz or 0) for c, _, _, sz in rec_rows}
    text_counts = dict(db.execute(
        select(Text.region_code, func.count())
        .where(scope_filter(Text.region_code, scope)).group_by(Text.region_code)).all())
    audio_counts = dict(db.execute(
        select(AudioFile.region_code, func.count())
        .where(scope_filter(AudioFile.region_code, scope)).group_by(AudioFile.region_code)).all())
    ann_counts = dict(db.execute(
        select(Annotation.region_code, func.count())
        .where(scope_filter(Annotation.region_code, scope)).group_by(Annotation.region_code)).all())

    b_users = _bucket(user_counts, row_of_code, row_codes, 0)
    b_recordings = _bucket(rec_counts, row_of_code, row_codes, 0)
    b_seconds = _bucket(rec_seconds, row_of_code, row_codes, 0.0)
    b_sizes = _bucket(rec_sizes, row_of_code, row_codes, 0)
    b_texts = _bucket(text_counts, row_of_code, row_codes, 0)
    b_audio = _bucket(audio_counts, row_of_code, row_codes, 0)
    b_annotated = _bucket(ann_counts, row_of_code, row_codes, 0)

    rows = [
        {
            "code": rc,
            "name": regions[rc].name if rc in regions else rc,
            "users": b_users[rc],
            "recordings": b_recordings[rc],
            "seconds": b_seconds[rc],
            "size_bytes": b_sizes[rc],
            "texts": b_texts[rc],
            "audio_files": b_audio[rc],
            "annotated": b_annotated[rc],
        }
        for rc in row_codes
    ]

    total = {
        "code": parent.code,
        "name": parent.name,
        "users": sum(user_counts.values()),
        "recordings": sum(rec_counts.values()),
        "seconds": sum(rec_seconds.values()),
        "size_bytes": sum(rec_sizes.values()),
        "texts": sum(text_counts.values()),
        "audio_files": sum(audio_counts.values()),
        "annotated": sum(ann_counts.values()),
    }

    # 任务维度：scope 内全部 active tasks
    task_rows = db.execute(
        select(Task).join(User, Task.user_id == User.id)
        .where(Task.status == "active", scope_filter(User.region_code, scope))
    ).scalars().all()

    category_counts = dict(db.execute(
        select(Text.category, func.count())
        .where(scope_filter(Text.region_code, scope)).group_by(Text.category)).all())

    return ok({"level": level, "rows": rows, "total": total,
               "tasks": _task_dimension(db, task_rows), "category_counts": category_counts})
