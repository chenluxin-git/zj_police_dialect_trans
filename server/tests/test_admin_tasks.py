"""T21 任务管理测试：单人/批量下达（scope 校验、重复下达调 target 保 base、取消后重下重拍快照）、
调整与取消、进度实时联表、下达自动站内信。
"""
import pytest

from app.core.security import create_token
from app.models import Message, MessageRecipient, Recording, Region, Task, Text, User
from tests.conftest import make_user


def seed_regions(db):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331001", name="临海区", level="district", parent_code="331000"),
        Region(code="331002", name="温岭区", level="district", parent_code="331000"),
        Region(code="332000", name="温州市", level="city", parent_code="330000"),
        Region(code="332001", name="乐清区", level="district", parent_code="332000"),
    ])
    db.commit()


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def add_passed_rec(db, user, region, text_no):
    t = Text(content=f"测试文本{text_no}", dialect="临海方言", category="police", region_code=region)
    db.add(t); db.commit()
    db.add(Recording(user_id=user.id, text_id=t.id, file_path=f"r{text_no}.wav", file_size=10,
                     duration=1.0, region_code=region, dialect_code="dh_lh", qc_status="passed"))
    db.commit()


def msg_count(db, user_id):
    return db.query(MessageRecipient).filter_by(user_id=user_id).count()


# ---------- 单人下达：任务+消息双落库 ----------

def test_assign_creates_task_and_message(client, db):
    seed_regions(db)
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(super_admin)

    r = client.post("/api/admin/tasks", headers=h,
                    json={"user_id": u1.id, "type": "recording", "target_count": 100, "note": "月底前完成"})
    assert r.status_code == 200 and r.json()["code"] == 0

    task = db.query(Task).filter_by(user_id=u1.id, type="recording").first()
    assert task is not None
    assert task.status == "active"
    assert task.target_count == 100
    assert task.base_count == 0          # u1 无 passed 录音
    assert task.note == "月底前完成"
    assert task.created_by == super_admin.id

    assert msg_count(db, u1.id) == 1
    msg = db.query(Message).filter_by(title="新任务").first()
    assert msg is not None and msg.sender_id == super_admin.id
    assert "录音任务" in msg.content and "100 条" in msg.content


# ---------- 重复下达：调 target 保 base，仍仅一条 active ----------

def test_reassign_updates_target_keeps_base(client, db):
    seed_regions(db)
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    add_passed_rec(db, u1, "331001", 1)  # 1 条 passed → 存量 1
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(super_admin)

    client.post("/api/admin/tasks", headers=h,
                json={"user_id": u1.id, "type": "recording", "target_count": 100})
    first = db.query(Task).filter_by(user_id=u1.id, type="recording", status="active").first()
    base0 = first.base_count
    assert base0 == 1

    client.post("/api/admin/tasks", headers=h,
                json={"user_id": u1.id, "type": "recording", "target_count": 150})
    actives = db.query(Task).filter_by(user_id=u1.id, type="recording", status="active").all()
    assert len(actives) == 1
    assert actives[0].target_count == 150
    assert actives[0].base_count == base0  # base 不变


# ---------- 批量下达：3 人 3 任务 3 消息 ----------

def test_batch_assign(client, db):
    seed_regions(db)
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    u2 = make_user(db, phone="33100200002", name="温岭民警", region="331002")
    u3 = make_user(db, phone="33200100002", name="乐清民警", region="332001")
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(super_admin)

    r = client.post("/api/admin/tasks/batch", headers=h,
                    json={"user_ids": [u1.id, u2.id, u3.id], "type": "annotation",
                          "target_count": 50, "note": "批量下达"})
    assert r.status_code == 200 and r.json()["code"] == 0

    for u in (u1, u2, u3):
        assert db.query(Task).filter_by(user_id=u.id, type="annotation", status="active").count() == 1
        assert msg_count(db, u.id) == 1
    msg = db.query(Message).filter_by(title="新任务").first()
    assert "标注任务" in msg.content


# ---------- 跨 scope 下达 403 ----------

def test_assign_out_of_scope_403(client, db):
    seed_regions(db)
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    u3 = make_user(db, phone="33200100002", name="乐清民警", region="332001")
    tz_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")

    r = client.post("/api/admin/tasks", headers=auth_of(tz_admin),
                    json={"user_id": u3.id, "type": "recording", "target_count": 10})
    assert r.status_code == 403

    r2 = client.post("/api/admin/tasks", headers=auth_of(tz_admin),
                     json={"user_id": u1.id, "type": "recording", "target_count": 10})
    assert r2.status_code == 200


# ---------- 取消 + 恢复激活重拍快照 ----------

def test_cancel_and_reactivate_resnap_base(client, db):
    seed_regions(db)
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    add_passed_rec(db, u1, "331001", 1)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(super_admin)

    client.post("/api/admin/tasks", headers=h,
                json={"user_id": u1.id, "type": "recording", "target_count": 10})
    task = db.query(Task).filter_by(user_id=u1.id, type="recording", status="active").first()
    assert task.base_count == 1

    r = client.put(f"/api/admin/tasks/{task.id}", headers=h, json={"status": "cancelled"})
    assert r.status_code == 200
    db.refresh(task)
    assert task.status == "cancelled"

    add_passed_rec(db, u1, "331001", 2)  # 存量变 2
    r2 = client.put(f"/api/admin/tasks/{task.id}", headers=h, json={"status": "active"})
    assert r2.status_code == 200
    db.refresh(task)
    assert task.status == "active"
    assert task.base_count == 2          # 重拍快照


# ---------- 列表：scope 过滤 + 行字段 ----------

def test_list_tasks_scope_and_fields(client, db):
    seed_regions(db)
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    u3 = make_user(db, phone="33200100002", name="乐清民警", region="332001")
    add_passed_rec(db, u1, "331001", 1)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    tz_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")

    client.post("/api/admin/tasks", headers=auth_of(super_admin),
                json={"user_id": u1.id, "type": "recording", "target_count": 5})
    client.post("/api/admin/tasks", headers=auth_of(super_admin),
                json={"user_id": u3.id, "type": "annotation", "target_count": 8})

    # 超管见 2 条
    r = client.get("/api/admin/tasks", headers=auth_of(super_admin))
    assert r.json()["data"]["total"] == 2
    item = r.json()["data"]["items"][0]
    assert "real_name" in item and "police_station" in item and "type" in item
    assert "target_count" in item and "done" in item and "status" in item and "note" in item

    # 台州市管只见辖区内 u1 的 1 条
    r2 = client.get("/api/admin/tasks", headers=auth_of(tz_admin))
    assert r2.json()["data"]["total"] == 1
    assert r2.json()["data"]["items"][0]["real_name"] == "临海民警"

    # type/status 筛选
    r3 = client.get("/api/admin/tasks", headers=auth_of(super_admin), params={"type": "annotation"})
    assert r3.json()["data"]["total"] == 1
