# tests/test_auth.py —— T5 auth：注册/登录/me（自造 region 数据，不依赖 seed）
from app.models import Region, User
from tests.conftest import make_user
from app.core.security import create_token


def _region(db):
    db.add(Region(code="331004", name="临海市", level="district", parent_code="331000"))
    db.commit()


REG = {"phone": "13900000001", "password": "123456", "real_name": "张三",
       "police_station": "临海市公安局××派出所", "region_code": "331004"}


def test_register_ok(client, db):
    _region(db)
    r = client.post("/api/auth/register", json=REG)
    assert r.status_code == 200 and r.json()["code"] == 0
    u = db.query(User).filter_by(phone="13900000001").first()
    assert u is not None and u.role == "user" and u.real_name == "张三"


def test_register_duplicate_phone(client, db):
    _region(db)
    make_user(db, phone="13900000001")
    r = client.post("/api/auth/register", json=REG)
    assert r.status_code == 400


def test_register_bad_phone(client, db):
    _region(db)
    r = client.post("/api/auth/register", json={**REG, "phone": "12345"})
    assert r.status_code == 400


def test_register_region_not_exist(client, db):
    r = client.post("/api/auth/register", json={**REG, "region_code": "999999"})
    assert r.status_code == 400


def test_login_ok(client, db):
    _region(db)
    make_user(db, phone="33100400002")
    r = client.post("/api/auth/login", json={"phone": "33100400002", "password": "123456"})
    body = r.json()
    assert r.status_code == 200 and body["code"] == 0
    assert body["data"]["token"]
    user = body["data"]["user"]
    assert user["id"] == 1 and user["real_name"] == "测试民警"
    assert user["role"] == "user" and user["region_code"] == "331004"


def test_login_wrong_password(client, db):
    make_user(db)
    r = client.post("/api/auth/login", json={"phone": "33100400002", "password": "wrong"})
    assert r.status_code == 401


def test_login_unknown_phone(client, db):
    r = client.post("/api/auth/login", json={"phone": "13900000000", "password": "123456"})
    assert r.status_code == 401


def test_me_with_token(client, db):
    make_user(db)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {create_token('1')}"})
    body = r.json()
    assert r.status_code == 200 and body["code"] == 0
    assert body["data"]["real_name"] == "测试民警"
    assert body["data"]["region_code"] == "331004"


def test_me_without_token(client, db):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
