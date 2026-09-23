# tests/test_sqlite_to_mysql.py —— 搬迁脚本逻辑用 sqlite→sqlite 覆盖（方言无关），
# MySQL 侧的 ALTER TABLE AUTO_INCREMENT 分支由 test_mysql_integration.py 门控覆盖
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Region, User
from scripts.sqlite_to_mysql import copy_database


@pytest.fixture()
def src_engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        s.add(Region(code="330000", name="浙江省", level="province"))
        s.add(User(phone="33100400002", password_hash="x", real_name="测试民警",
                   region_code="331004"))
        s.commit()
    return eng


@pytest.fixture()
def dst_engine():
    return create_engine("sqlite://")  # 全新空库：create_all 由 copy_database 负责


def test_copy_preserves_rows_and_ids(src_engine, dst_engine):
    counts = copy_database(src_engine, dst_engine)
    assert counts["regions"] == 1 and counts["users"] == 1
    assert set(counts) >= {"regions", "users", "recordings", "qc_logs"}  # 元数据全部表都在
    with sessionmaker(bind=dst_engine)() as s:
        assert s.get(Region, "330000").name == "浙江省"  # 字符串主键保留
        assert s.get(User, 1).real_name == "测试民警"     # 整型主键 id 保留
        s.add(User(phone="33100400003", password_hash="x", real_name="民警二",
                   region_code="331004"))
        s.commit()
        assert s.query(User).count() == 2                 # 搬迁后可续插


def test_copy_refuses_nonempty_target(src_engine, dst_engine):
    copy_database(src_engine, dst_engine)
    with pytest.raises(RuntimeError, match="非空"):
        copy_database(src_engine, dst_engine)


def test_copy_force_overwrites(src_engine, dst_engine):
    copy_database(src_engine, dst_engine)
    counts = copy_database(src_engine, dst_engine, force=True)
    assert counts["users"] == 1                          # 清空重搬，不翻倍
    with sessionmaker(bind=dst_engine)() as s:
        assert s.query(User).count() == 1


def test_copy_empty_source_is_noop():
    src = create_engine("sqlite://")                     # 空源（无表）
    dst = create_engine("sqlite://")
    assert copy_database(src, dst) == {}
