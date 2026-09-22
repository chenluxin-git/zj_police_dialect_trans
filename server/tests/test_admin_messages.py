"""T22 管理端消息发送测试：单人/区域/单位三口径（一律 ∩ scope，越界跳过回 sent/skipped）+ 已发列表已读统计。
"""
from datetime import datetime

import pytest

from app.core.security import create_token
from app.models import Message, MessageRecipient, Region, User
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


def make_users(db):
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001", station="临海市公安局")
    u2 = make_user(db, phone="33100200002", name="温岭民警", region="331002", station="温岭市公安局")
    u3 = make_user(db, phone="33200100002", name="乐清民警", region="332001", station="乐清市公安局")
    return u1, u2, u3


# ---------- 单人 ----------

def test_send_user(client, db):
    seed_regions(db)
    u1, u2, u3 = make_users(db)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(super_admin)

    r = client.post("/api/admin/messages", headers=h,
                    json={"target_type": "user", "target_value": u1.id, "title": "通知", "content": "请参加培训"})
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"] == {"sent": 1, "skipped": 0}
    assert db.query(MessageRecipient).filter_by(user_id=u1.id).count() == 1
    assert db.query(MessageRecipient).filter_by(user_id=u2.id).count() == 0


# ---------- 按区域：市码=全市群发 ----------

def test_send_region_city_expands(client, db):
    seed_regions(db)
    u1, u2, u3 = make_users(db)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(super_admin)

    r = client.post("/api/admin/messages", headers=h,
                    json={"target_type": "region", "target_value": "331000", "title": "全市通知", "content": "..."})
    assert r.json()["data"] == {"sent": 2, "skipped": 0}   # 台州两县 u1+u2，不含温州 u3
    assert db.query(MessageRecipient).filter_by(user_id=u1.id).count() == 1
    assert db.query(MessageRecipient).filter_by(user_id=u2.id).count() == 1
    assert db.query(MessageRecipient).filter_by(user_id=u3.id).count() == 0


# ---------- 按区域：越界跳过回 sent/skipped ----------

def test_send_region_scope_skip(client, db):
    seed_regions(db)
    u1, u2, u3 = make_users(db)
    tz_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    h = auth_of(tz_admin)

    # 辖区外（乐清 332001）→ 全跳过
    r = client.post("/api/admin/messages", headers=h,
                    json={"target_type": "region", "target_value": "332001", "title": "t", "content": "c"})
    assert r.json()["data"] == {"sent": 0, "skipped": 1}

    # 辖区内（临海 331001）→ 命中 u1
    r2 = client.post("/api/admin/messages", headers=h,
                     json={"target_type": "region", "target_value": "331001", "title": "t", "content": "c"})
    assert r2.json()["data"] == {"sent": 1, "skipped": 0}


# ---------- 按单位 ----------

def test_send_station(client, db):
    seed_regions(db)
    u1, u2, u3 = make_users(db)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(super_admin)

    r = client.post("/api/admin/messages", headers=h,
                    json={"target_type": "station", "target_value": "临海市公安局", "title": "t", "content": "c"})
    assert r.json()["data"] == {"sent": 1, "skipped": 0}
    assert db.query(MessageRecipient).filter_by(user_id=u1.id).count() == 1
    assert db.query(MessageRecipient).filter_by(user_id=u2.id).count() == 0


# ---------- 已发列表：收件数/已读数 ----------

def test_list_sent_messages_read_count(client, db):
    seed_regions(db)
    u1, u2, u3 = make_users(db)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    tz_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    h = auth_of(super_admin)

    client.post("/api/admin/messages", headers=h,
                json={"target_type": "region", "target_value": "331000", "title": "通知", "content": "..."})
    msg = db.query(Message).first()
    rec = db.query(MessageRecipient).filter_by(message_id=msg.id, user_id=u1.id).first()
    rec.read_at = datetime.now()
    db.commit()

    r = client.get("/api/admin/messages", headers=h)
    data = r.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["title"] == "通知"
    # 区域 331000 展开 331000/331001/331002：收件人含 u1、u2 与台州管理员（region=331000）
    assert item["recipient_count"] == 3
    assert item["read_count"] == 1

    # 他人已发不串台（sender_id 过滤）
    r2 = client.get("/api/admin/messages", headers=auth_of(tz_admin))
    assert r2.json()["data"]["total"] == 0
