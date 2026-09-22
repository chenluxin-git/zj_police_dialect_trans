"""T20 数据总览（Spec §6.7）：省→市→县下钻两级聚合 + total 汇总 + 任务维度 + category_counts
- 每类指标一次 GROUP BY region_code 查询再在内存分桶到子区域行（勿逐区域循环查库）
- 录音数/时长/容量仅 qc_status='passed'
- 任务维度：scope 内全部 active tasks 复用 progress_map，done=max(0,有效数-base)，started=done>0
- category_counts：scope 内 texts 按 category 聚合（FE-4 类别分布条形图依赖）
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Annotation, AudioFile, Recording, Region, Task, Text, User
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


@router.get("/overview")
def overview(
    region_code: str | None = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scope = resolve_scope(db, admin)
    regions, children = _load_region_tree(db)

    # 定位视图父区域（省/市/县）与行区域码
    parent = None
    if scope is None:  # super_admin / 省管：可传 region_code 下钻，缺省省级
        if region_code:
            parent = regions.get(region_code)
            if parent is None:
                raise HTTPException(status_code=404, detail="区域不存在")
        else:
            parent = next((r for r in regions.values() if r.level == "province"), None)
    else:  # 市管/县管：固定自身区域
        parent = regions.get(admin.region_code)

    if parent is None:
        empty = {"users": 0, "recordings": 0, "seconds": 0.0, "size_bytes": 0,
                 "texts": 0, "audio_files": 0, "annotated": 0, "dialect_count": 0}
        return ok({"level": None, "rows": [], "total": empty,
                   "tasks": {"target_sum": 0, "done_sum": 0, "rate": 0.0, "started": 0, "not_started": 0},
                   "category_counts": {}})

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
    dialect_counts = dict(db.execute(
        select(Annotation.region_code, func.count())
        .where(Annotation.is_dialect == True, scope_filter(Annotation.region_code, scope))  # noqa: E712
        .group_by(Annotation.region_code)).all())

    b_users = _bucket(user_counts, row_of_code, row_codes, 0)
    b_recordings = _bucket(rec_counts, row_of_code, row_codes, 0)
    b_seconds = _bucket(rec_seconds, row_of_code, row_codes, 0.0)
    b_sizes = _bucket(rec_sizes, row_of_code, row_codes, 0)
    b_texts = _bucket(text_counts, row_of_code, row_codes, 0)
    b_audio = _bucket(audio_counts, row_of_code, row_codes, 0)
    b_annotated = _bucket(ann_counts, row_of_code, row_codes, 0)
    b_dialect = _bucket(dialect_counts, row_of_code, row_codes, 0)

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
            "dialect_count": b_dialect[rc],
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
        "dialect_count": sum(dialect_counts.values()),
    }

    # 任务维度：scope 内全部 active tasks
    task_rows = db.execute(
        select(Task).join(User, Task.user_id == User.id)
        .where(Task.status == "active", scope_filter(User.region_code, scope))
    ).scalars().all()
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
    tasks = {
        "target_sum": target_sum,
        "done_sum": done_sum,
        "rate": round(done_sum / target_sum, 4) if target_sum else 0.0,
        "started": started,
        "not_started": not_started,
    }

    category_counts = dict(db.execute(
        select(Text.category, func.count())
        .where(scope_filter(Text.region_code, scope)).group_by(Text.category)).all())

    return ok({"level": level, "rows": rows, "total": total,
               "tasks": tasks, "category_counts": category_counts})
