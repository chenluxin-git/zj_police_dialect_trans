# tests/test_deps_scope.py
from app.api.deps import resolve_scope
from app.models import User
from tests.conftest import make_user

def seed_regions(db):
    from app.models import Region
    db.add_all([Region(code="330000", name="浙江省", level="province", parent_code=""),
                Region(code="331000", name="台州市", level="city", parent_code="330000"),
                Region(code="331004", name="临海市", level="district", parent_code="331000"),
                Region(code="331082", name="三门县", level="district", parent_code="331000")])
    db.commit()

def test_super_admin_scope_none(db):
    seed_regions(db); make_user(db, phone="33000000001", role="super_admin", region="330000")
    u = db.query(User).filter_by(phone="33000000001").first()
    assert resolve_scope(db, u) is None

def test_province_admin_scope_none(db):
    seed_regions(db); make_user(db, phone="33000000002", role="admin", region="330000")
    u = db.query(User).filter_by(phone="33000000002").first()
    assert resolve_scope(db, u) is None

def test_city_admin_scope_city_plus_districts(db):
    seed_regions(db); make_user(db, phone="33100000001", role="admin", region="331000")
    u = db.query(User).filter_by(phone="33100000001").first()
    assert sorted(resolve_scope(db, u)) == ["331000", "331004", "331082"]

def test_district_admin_scope_single(db):
    seed_regions(db); make_user(db, phone="33100400001", role="admin", region="331004")
    u = db.query(User).filter_by(phone="33100400001").first()
    assert resolve_scope(db, u) == ["331004"]
