# tests/test_mysql_integration.py —— MySQL 改造：引擎分支单测（常跑）+ TEST_MYSQL_URL 门控集成测试
# 集成测试起库：docker run -d --name zjpdt-mysql-test -e MYSQL_ROOT_PASSWORD=root123 \
#   -e MYSQL_DATABASE=zjpdt_test -p 33061:3306 mysql:8.0
# export TEST_MYSQL_URL='mysql+pymysql://root:root123@127.0.0.1:33061/zjpdt_test?charset=utf8mb4'
import os

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

MYSQL_URL = os.environ.get("TEST_MYSQL_URL", "")
requires_mysql = pytest.mark.skipif(
    not MYSQL_URL, reason="TEST_MYSQL_URL 未设置，跳过 MySQL 集成测试")


def test_build_engine_branches():
    """SQLite 分支允许跨线程复用连接；MySQL 分支带 pool_recycle 防 wait_timeout 断连"""
    import threading
    from app.core.database import build_engine

    sq = build_engine("sqlite://")
    assert sq.dialect.name == "sqlite"
    conn = sq.connect()
    result = {}

    def use_in_thread():
        try:
            conn.exec_driver_sql("SELECT 1")
            result["ok"] = True
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=use_in_thread)
    t.start()
    t.join()
    conn.close()
    sq.dispose()
    assert result["ok"] is True  # check_same_thread=False 生效

    my = build_engine("mysql+pymysql://u:p@127.0.0.1:3306/x?charset=utf8mb4")
    assert my.dialect.name == "mysql"
    assert my.pool._recycle == 3600  # QueuePool 回收参数（防 MySQL server has gone away）
    my.dispose()


@requires_mysql
def test_mysql_create_all_and_chinese_roundtrip():
    """建表 + utf8mb4 中文往返（出现问号/乱码即 charset 配错）"""
    from app.core.database import Base
    from app.models import Text, User

    eng = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        s.add(User(phone="33100400002", password_hash="x", real_name="测试民警",
                   region_code="331004"))
        s.add(Text(content="下雨了，衣裳好收收了", dialect="台州话",
                   category="日常用语", region_code="331004"))
        s.commit()
        assert s.query(User).one().real_name == "测试民警"
        assert s.query(Text).one().content == "下雨了，衣裳好收收了"
    Base.metadata.drop_all(eng)
    eng.dispose()


@requires_mysql
def test_mysql_unique_constraints_enforced():
    """unique 约束在 MySQL 上真实生效（users.phone、recordings(user_id,text_id)）"""
    from sqlalchemy.exc import IntegrityError
    from app.core.database import Base
    from app.models import Recording, Text, User

    eng = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        s.add(Text(content="上盘镇", dialect="台州话", category="日常用语",
                   region_code="331004"))
        s.flush()
        s.add(User(phone="33100400002", password_hash="x", real_name="测试民警",
                   region_code="331004"))
        s.commit()
        s.add(Recording(user_id=1, text_id=1, file_path="/x/1.wav", file_size=1,
                        duration=1.0, region_code="331004", dialect_code="dh331004"))
        s.commit()
        s.add(Recording(user_id=1, text_id=1, file_path="/x/2.wav", file_size=1,
                        duration=1.0, region_code="331004", dialect_code="dh331004"))
        with pytest.raises(IntegrityError):
            s.commit()
    Base.metadata.drop_all(eng)
    eng.dispose()


@requires_mysql
def test_mysql_charset_and_phone_index():
    """连接字符集 utf8mb4 + users.phone 唯一索引在 MySQL 上存在"""
    from app.core.database import Base

    eng = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT @@character_set_client").scalar() == "utf8mb4"
    phone_idx = [ix for ix in inspect(eng).get_indexes("users")
                 if ix["column_names"] == ["phone"]]
    assert phone_idx and phone_idx[0]["unique"] is True
    Base.metadata.drop_all(eng)
    eng.dispose()


@requires_mysql
def test_mysql_copy_database_end_to_end(tmp_path):
    """搬迁脚本 sqlite→mysql 全链路：行数/主键保留 + 自增计数器顶到 max+1"""
    from app.core.database import Base
    from app.models import Region, User
    from scripts.sqlite_to_mysql import copy_database

    src = create_engine(f"sqlite:///{tmp_path}/src.db")
    Base.metadata.create_all(src)
    with sessionmaker(bind=src)() as s:
        s.add(Region(code="330000", name="浙江省", level="province"))
        s.add(User(phone="33100400002", password_hash="x", real_name="测试民警",
                   region_code="331004"))
        s.commit()

    dst = create_engine(MYSQL_URL, pool_pre_ping=True)
    Base.metadata.drop_all(dst)
    counts = copy_database(src, dst)
    assert counts["regions"] == 1 and counts["users"] == 1
    with sessionmaker(bind=dst, expire_on_commit=False)() as s:
        assert s.get(User, 1).real_name == "测试民警"  # 主键 id 保留
        s.add(User(phone="33100400003", password_hash="x", real_name="民警二",
                   region_code="331004"))
        s.commit()
        assert s.query(User).filter_by(phone="33100400003").one().id == 2  # AUTO_INCREMENT 已顶起
    Base.metadata.drop_all(dst)
    src.dispose()
    dst.dispose()
