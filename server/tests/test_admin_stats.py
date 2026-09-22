"""T20 数据总览测试：省→市→县下钻两级聚合 + total 汇总 + 任务维度 + category_counts
口径：录音数/时长/容量仅 qc_status='passed'；rows 为父区域子级行；total 为 scope 内全量汇总。
"""
import pytest

from app.core.security import create_token
from app.models import Recording, Region, Task, Text, User
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


def seed_overview_data(db):
    """市A(台州)两县各 1 民警 2 passed 录音；市B(温州) 1 民警 0 录音；含文本与类别分布"""
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    u2 = make_user(db, phone="33100200002", name="温岭民警", region="331002")
    u3 = make_user(db, phone="33200100002", name="乐清民警", region="332001")

    t1 = Text(content="请出示身份证", dialect="临海方言", category="police", region_code="331001")
    t2 = Text(content="今天天气不错", dialect="临海方言", category="life", region_code="331001")
    t3 = Text(content="请配合检查", dialect="温岭方言", category="police", region_code="331002")
    t4 = Text(content="注意安全", dialect="温岭方言", category="police", region_code="331002")
    t5 = Text(content="慢走不送", dialect="乐清方言", category="life", region_code="332001")
    db.add_all([t1, t2, t3, t4, t5])
    db.commit()

    recs = [
        Recording(user_id=u1.id, text_id=t1.id, file_path="x1.wav", file_size=100, duration=2.0,
                  region_code="331001", dialect_code="dh_lh", qc_status="passed"),
        Recording(user_id=u1.id, text_id=t2.id, file_path="x2.wav", file_size=200, duration=3.0,
                  region_code="331001", dialect_code="dh_lh", qc_status="passed"),
        Recording(user_id=u2.id, text_id=t3.id, file_path="x3.wav", file_size=300, duration=4.0,
                  region_code="331002", dialect_code="dh_wl", qc_status="passed"),
        Recording(user_id=u2.id, text_id=t4.id, file_path="x4.wav", file_size=400, duration=5.0,
                  region_code="331002", dialect_code="dh_wl", qc_status="passed"),
        # 一条 pending 不入统计（text_id 用无外键占位，避免 unique(user_id,text_id) 与上面冲突）
        Recording(user_id=u1.id, text_id=999999, file_path="x5.wav", file_size=999, duration=99.0,
                  region_code="331001", dialect_code="dh_lh", qc_status="pending"),
    ]
    db.add_all(recs)
    db.commit()
    return {"u1": u1, "u2": u2, "u3": u3}


# ---------- 省级聚合 + total + category_counts ----------

def test_overview_province_aggregation(client, db):
    seed_regions(db)
    seed_overview_data(db)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")

    r = client.get("/api/admin/stats/overview", headers=auth_of(super_admin))
    assert r.status_code == 200
    data = r.json()["data"]

    assert data["level"] == "province"
    rows = {row["code"]: row for row in data["rows"]}
    assert set(rows) == {"331000", "332000"}  # 两城市行

    tz = rows["331000"]
    assert tz["name"] == "台州市"
    assert tz["users"] == 2          # u1 + u2（管理员不在数内）
    assert tz["recordings"] == 4     # 4 条 passed（pending 不入）
    assert tz["seconds"] == 14.0     # 2+3+4+5
    assert tz["size_bytes"] == 1000  # 100+200+300+400
    assert tz["texts"] == 4          # t1..t4

    wz = rows["332000"]
    assert wz["recordings"] == 0
    assert wz["users"] == 1          # u3
    assert wz["texts"] == 1

    total = data["total"]
    assert total["users"] == 4       # u1 u2 u3 + 超管
    assert total["recordings"] == 4
    assert total["seconds"] == 14.0
    assert total["size_bytes"] == 1000

    # category_counts：scope 内 texts 按 category 聚合（police=3, life=2）
    assert data["category_counts"] == {"police": 3, "life": 2}


# ---------- 任务维度 ----------

def test_overview_tasks_dimension(client, db):
    seed_regions(db)
    u1 = make_user(db, phone="33100100002", name="临海民警", region="331001")
    u2 = make_user(db, phone="33100200002", name="温岭民警", region="331002")
    t = Text(content="请出示身份证", dialect="临海方言", category="police", region_code="331001")
    db.add(t); db.commit()
    # u1 有 1 条 passed（done=1）；u2 无录音（done=0）
    db.add(Recording(user_id=u1.id, text_id=t.id, file_path="y1.wav", file_size=10, duration=1.0,
                     region_code="331001", dialect_code="dh_lh", qc_status="passed"))
    db.add_all([
        Task(user_id=u1.id, type="recording", target_count=1, base_count=0, status="active",
             note="", created_by=0),
        Task(user_id=u2.id, type="recording", target_count=1, base_count=0, status="active",
             note="", created_by=0),
    ])
    db.commit()
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")

    data = client.get("/api/admin/stats/overview", headers=auth_of(super_admin)).json()["data"]
    tasks = data["tasks"]
    assert tasks["target_sum"] == 2
    assert tasks["done_sum"] == 1
    assert tasks["rate"] == 0.5
    assert tasks["started"] == 1
    assert tasks["not_started"] == 1


# ---------- 市管固定本市 + 超管下钻 ----------

def test_overview_city_fixed_and_drill(client, db):
    seed_regions(db)
    seed_overview_data(db)
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    city_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")

    # 市管固定本市 → 区县行
    r = client.get("/api/admin/stats/overview", headers=auth_of(city_admin))
    data = r.json()["data"]
    assert data["level"] == "city"
    rows = {row["code"]: row for row in data["rows"]}
    assert set(rows) == {"331001", "331002"}
    assert rows["331001"]["recordings"] == 2
    assert rows["331002"]["recordings"] == 2

    # 超管下钻到市 → 同样区县行
    r2 = client.get("/api/admin/stats/overview", headers=auth_of(super_admin),
                    params={"region_code": "331000"})
    data2 = r2.json()["data"]
    assert data2["level"] == "city"
    assert {row["code"] for row in data2["rows"]} == {"331001", "331002"}


# ---------- 县管单行 ----------

def test_overview_district_single_row(client, db):
    seed_regions(db)
    seed_overview_data(db)
    district_admin = make_user(db, phone="33100100001", name="临海管理员", role="admin", region="331001")

    r = client.get("/api/admin/stats/overview", headers=auth_of(district_admin))
    data = r.json()["data"]
    assert data["level"] == "district"
    assert len(data["rows"]) == 1
    assert data["rows"][0]["code"] == "331001"
    assert data["rows"][0]["recordings"] == 2          # 仅本县 passed（pending 不入）
    assert data["total"]["recordings"] == 2
