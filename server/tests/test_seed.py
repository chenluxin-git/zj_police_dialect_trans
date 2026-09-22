"""T4 seed 预置数据测试"""
import pytest
from sqlalchemy import select
from app.utils.seed import run_seed
from app.utils.seed_data import REGIONS, DIALECTS, POLICE_STATIONS


def test_seed_data_constants():
    """静态数据规模：102 区划（1省+11市+90县）、11 方言、696 派出所"""
    assert len(REGIONS) == 102
    assert len([r for r in REGIONS if r["level"] == "province"]) == 1
    assert len([r for r in REGIONS if r["level"] == "city"]) == 11
    assert len([r for r in REGIONS if r["level"] == "district"]) == 90
    assert len(DIALECTS) == 11
    assert len(POLICE_STATIONS) == 696
    # 抽查（手册原载 330283 经核不存在，按国家统计局 2023 改为 330383 龙港市）
    by_code = {r["code"]: r for r in REGIONS}
    assert by_code["330105"]["name"] == "拱墅区"
    assert by_code["330383"]["name"] == "龙港市"
    assert by_code["331004"]["name"] == "路桥区"
    # 台州三码修正后与权威一致
    assert by_code["331083"]["name"] == "玉环市"
    assert by_code["331081"]["name"] == "温岭市"
    assert by_code["331022"]["name"] == "三门县"


def test_seed_idempotent_282_accounts(db):
    run_seed(db)
    run_seed(db)  # 幂等
    from app.models import User, Region, Dialect, PoliceStation
    assert db.query(User).count() == 282
    assert db.query(Region).count() == 102
    assert db.query(Region).filter_by(level="province").count() == 1
    assert db.query(Dialect).count() == 11
    assert db.query(PoliceStation).count() == 696
    # 账号构成：超管1 / 市管11 / 县管90 / 民警180
    assert db.query(User).filter_by(role="super_admin").count() == 1
    assert db.query(User).filter_by(role="admin").count() == 101
    assert db.query(User).filter_by(role="user").count() == 180
    # 抽查账号
    su = db.scalar(select(User).where(User.phone == "33000000001"))
    assert su and su.role == "super_admin" and su.region_code == "330000"
    city_admin = db.scalar(select(User).where(User.phone == "33100000001"))
    assert city_admin and city_admin.role == "admin" and city_admin.region_code == "331000"
    county_admin = db.scalar(select(User).where(User.phone == "33100400001"))
    assert county_admin and county_admin.role == "admin" and county_admin.region_code == "331004"
    police = db.scalar(select(User).where(User.phone == "33100400002"))
    assert police and police.role == "user" and police.real_name == "路桥区民警01"


def test_seed_single_run_on_autoflush_off_session():
    """回归：生产 SessionLocal 是 autoflush=False，单次 run_seed 必须一次灌齐 282 账号
    （曾缺陷：add_all 后未 flush，districts 查询打空表只建出省超管 1 个账号）"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.core.database import Base
    import app.models  # noqa: F401  注册全部表
    from app.models import User, Region
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()  # 与生产 SessionLocal 一致
    try:
        run_seed(s)
        assert s.query(User).count() == 282
        assert s.query(Region).count() == 102
    finally:
        s.close()


def test_seed_password_verifiable(db):
    run_seed(db)
    from app.models import User
    from app.core.security import verify_password
    u = db.query(User).filter_by(phone="33100400003").first()
    assert verify_password("123456", u.password_hash)


@pytest.mark.skip(reason="依赖 auth 端点，集成包启用")
def test_seed_account_login(client, auth_header):
    """预置账号可登录（P-auth-base 合并后由集成包解除 skip）"""
    resp = client.post("/api/auth/login", json={"phone": "33100400002", "password": "123456"})
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
