"""T16 文本管理测试：scope 列表筛选（category/q/日期/区域）、批量删除跳过被录音引用项并回显 {deleted, skipped}"""
from datetime import datetime, timedelta

from app.core.security import create_token
from app.models import Recording, Region, Text, User  # 模块级导入：conftest 建表前须已注册模型
from tests.conftest import make_user


def seed_regions(db):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="路桥区", level="district", parent_code="331000"),
        Region(code="331082", name="三门县", level="district", parent_code="331000"),
        Region(code="330100", name="杭州市", level="city", parent_code="330000"),
        Region(code="330105", name="拱墅区", level="district", parent_code="330100"),
    ])
    db.commit()


def make_admins(db):
    tz_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    lq_admin = make_user(db, phone="33100400001", name="路桥管理员", role="admin", region="331004")
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    return tz_admin, lq_admin, super_admin


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def seed_texts(db):
    """today 文本 1 条（date 区间用），其余 4 条 10 天前；路桥 3 / 三门 1 / 杭州 1"""
    now = datetime.now()
    old = now - timedelta(days=10)
    texts = [
        Text(content="请出示您的身份证", dialect="路桥方言", category="police",
             region_code="331004", dialect_code="dh_lq", created_at=now),
        Text(content="请不要在公共场所吸烟", dialect="路桥方言", category="life",
             region_code="331004", dialect_code="dh_lq", created_at=old),
        Text(content="这里不能停车", dialect="路桥方言", category="dirty",
             region_code="331004", dialect_code="dh_lq", created_at=old),
        Text(content="请配合我们的调查", dialect="三门方言", category="police",
             region_code="331082", dialect_code="dh_sm", created_at=old),
        Text(content="请出示健康码", dialect="杭州方言", category="police",
             region_code="330105", dialect_code="dh_hz", created_at=old),
    ]
    db.add_all(texts)
    db.commit()
    return texts


# ---------- scope 与筛选 ----------

def test_texts_scope_and_filters(client, db, auth_header):
    seed_regions(db)
    seed_texts(db)
    tz_admin, lq_admin, super_admin = make_admins(db)

    # 民警访问管理端 → 403
    assert client.get("/api/admin/texts", headers=auth_header).status_code == 403

    # 超管不传区域 → 全量 5
    assert client.get("/api/admin/texts", headers=auth_of(super_admin)).json()["data"]["total"] == 5
    # 台州市管（scope=331000/331004/331082）→ 4
    assert client.get("/api/admin/texts", headers=auth_of(tz_admin)).json()["data"]["total"] == 4
    # 路桥区管 → 3
    assert client.get("/api/admin/texts", headers=auth_of(lq_admin)).json()["data"]["total"] == 3
    # 超管传 region_code=331000 展开整市 → 4
    r = client.get("/api/admin/texts", headers=auth_of(super_admin), params={"region_code": "331000"})
    assert r.json()["data"]["total"] == 4
    # category 过滤
    r = client.get("/api/admin/texts", headers=auth_of(super_admin), params={"category": "police"})
    assert r.json()["data"]["total"] == 3
    # q 内容搜索
    r = client.get("/api/admin/texts", headers=auth_of(super_admin), params={"q": "身份证"})
    assert r.json()["data"]["total"] == 1
    # 日期区间：最近一天 → 仅 today 那条
    start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    r = client.get("/api/admin/texts", headers=auth_of(super_admin), params={"date_start": start})
    assert r.json()["data"]["total"] == 1
    # 分页
    r = client.get("/api/admin/texts", headers=auth_of(super_admin), params={"page": 1, "page_size": 2})
    data = r.json()["data"]
    assert data["total"] == 5 and len(data["items"]) == 2 and data["page_size"] == 2


# ---------- 批量删除 ----------

def test_batch_delete_skips_referenced(client, db):
    seed_regions(db)
    texts = seed_texts(db)
    tz_admin, _, _ = make_admins(db)
    h = auth_of(tz_admin)

    officer = make_user(db, phone="33100400002", name="路桥民警", role="user", region="331004")
    db.add(Recording(user_id=officer.id, text_id=texts[0].id, file_path="", file_size=0,
                     duration=0.0, region_code="331004", dialect_code="dh_lq", qc_status="passed"))
    db.commit()

    # texts[0] 被引用 → skipped；texts[1] 未引用 → deleted；99999 不存在 → skipped
    r = client.request("DELETE", "/api/admin/texts/batch", headers=h,
                       json={"ids": [texts[0].id, texts[1].id, 99999]})
    assert r.status_code == 200 and r.json()["code"] == 0
    data = r.json()["data"]
    assert data["deleted"] == [texts[1].id]
    assert sorted(data["skipped"]) == sorted([texts[0].id, 99999])
    assert db.get(Text, texts[0].id) is not None  # 被引用仍在
    assert db.get(Text, texts[1].id) is None      # 已删


def test_batch_delete_scope_guard(client, db):
    seed_regions(db)
    texts = seed_texts(db)
    tz_admin, _, _ = make_admins(db)

    # 台州市管删杭州 text（scope 外）→ skipped 且不删
    r = client.request("DELETE", "/api/admin/texts/batch", headers=auth_of(tz_admin),
                       json={"ids": [texts[4].id]})
    assert r.json()["data"]["skipped"] == [texts[4].id]
    assert db.get(Text, texts[4].id) is not None