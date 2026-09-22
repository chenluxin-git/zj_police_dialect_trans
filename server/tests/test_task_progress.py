"""T12 我的任务进度测试（Spec §5.2 口径全覆盖）：
实时统计不记流水、passed-only、base 快照、删除自动回退、下限 0 超额如实、重复下达调整 target 保 base
progress_map 返回原始有效数（未扣 base_count）；done=max(0, 有效数-base_count) 由 /api/tasks/my 计算
"""
from app.models import Task, Recording, Annotation
from tests.conftest import make_user


def _rec(db, uid: int, text_id: int, qc: str = "passed") -> Recording:
    r = Recording(user_id=uid, text_id=text_id, file_path=f"{uid}_{text_id}.wav",
                  file_size=1, duration=1.0, region_code="331004", dialect_code="dh1",
                  qc_status=qc)
    db.add(r)
    return r


def _anno(db, uid: int, file_id: int) -> Annotation:
    a = Annotation(file_id=file_id, annotator_id=uid, is_dialect=True,
                   translation="普通话译文", region_code="331004")
    db.add(a)
    return a


def _task(db, uid: int, ttype: str, target: int, base: int = 0) -> Task:
    t = Task(user_id=uid, type=ttype, target_count=target, base_count=base,
             status="active", note="", created_by=99)
    db.add(t)
    return t


def test_progress_counts_passed_only(db):
    """待质检（pending）录音不计入；标注按 annotator_id 计数"""
    from app.services.task_progress import progress_map
    make_user(db)  # id=1
    _rec(db, 1, 101)
    _rec(db, 1, 102)
    _rec(db, 1, 103, qc="pending")  # 待质检不计
    _anno(db, 1, 201)
    db.commit()
    pm = progress_map(db, [1])
    assert pm[1]["recording_done"] == 2
    assert pm[1]["annotation_done"] == 1
    # 未传的用户也返回零值结构
    pm2 = progress_map(db, [])
    assert pm2 == {}


def test_progress_base_snapshot(client, db, auth_header):
    """下达时刻存量快照：先有 3 条 passed 再下达 → base_count==3、done==0"""
    _rec(db, 1, 101)
    _rec(db, 1, 102)
    _rec(db, 1, 103)
    db.commit()
    _task(db, 1, "recording", target=100, base=3)  # T21 下达时的存量快照
    db.commit()
    r = client.get("/api/tasks/my", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    rec = body["data"]["recording"]
    assert rec["base_count"] == 3
    assert rec["done"] == 0
    assert rec["target_count"] == 100
    assert rec["status"] == "active"
    # 未下达标注任务 → annotation 为 null
    assert body["data"]["annotation"] is None


def test_progress_rollback_on_delete(client, db, auth_header):
    """删除 passed 录音自动回退；进度下限 0"""
    _task(db, 1, "recording", target=100, base=0)
    r1 = _rec(db, 1, 101)
    _rec(db, 1, 102)
    db.commit()
    data = client.get("/api/tasks/my", headers=auth_header).json()["data"]
    assert data["recording"]["done"] == 2
    db.delete(r1)  # 删 1 条 passed → 回退
    db.commit()
    data = client.get("/api/tasks/my", headers=auth_header).json()["data"]
    assert data["recording"]["done"] == 1
    # 下限：base=5 有效 3 → done==0
    task = db.query(Task).filter_by(user_id=1, type="recording").one()
    task.base_count = 5
    db.commit()
    data = client.get("/api/tasks/my", headers=auth_header).json()["data"]
    assert data["recording"]["done"] == 0


def test_progress_over_quota_shown(client, db, auth_header):
    """超额如实显示：target=3 完成 5 → done==5"""
    _task(db, 1, "recording", target=3, base=0)
    for tid in (101, 102, 103, 104, 105):
        _rec(db, 1, tid)
    db.commit()
    data = client.get("/api/tasks/my", headers=auth_header).json()["data"]
    assert data["recording"]["done"] == 5


def test_reassign_adjusts_target_keeps_base(client, db, auth_header):
    """重复下达（T21 口径模拟）：target 100→120，base 不变，仍一条 active"""
    t = _task(db, 1, "recording", target=100, base=7)
    db.commit()
    t.target_count = 120  # 重复下达 = 调整 target，base_count 不变
    db.commit()
    data = client.get("/api/tasks/my", headers=auth_header).json()["data"]
    assert data["recording"]["target_count"] == 120
    assert data["recording"]["base_count"] == 7
    assert db.query(Task).filter_by(user_id=1, type="recording", status="active").count() == 1


def test_my_tasks_null_when_no_active(client, db, auth_header):
    """无任务两类均 null；cancelled 视同无 active"""
    r = client.get("/api/tasks/my", headers=auth_header)
    assert r.json()["data"] == {"recording": None, "annotation": None}
    t = _task(db, 1, "recording", target=10)
    db.commit()
    t.status = "cancelled"
    db.commit()
    assert client.get("/api/tasks/my", headers=auth_header).json()["data"]["recording"] is None


def test_annotation_done_subtracts_base(client, db, auth_header):
    """标注线同样口径：3 条标注 - base 1 = done 2"""
    _task(db, 1, "annotation", target=10, base=1)
    _anno(db, 1, 201)
    _anno(db, 1, 202)
    _anno(db, 1, 203)
    db.commit()
    data = client.get("/api/tasks/my", headers=auth_header).json()["data"]
    assert data["annotation"]["done"] == 2
    assert data["recording"] is None


def test_tasks_requires_login(client, db):
    """/api/tasks/my 未登录 401"""
    assert client.get("/api/tasks/my").status_code == 401
