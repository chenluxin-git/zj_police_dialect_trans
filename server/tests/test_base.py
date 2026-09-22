# tests/test_base.py —— T6 基础数据 API：regions（平铺+tree）/ dialects / police_stations（自造数据，不依赖 seed）
from app.models import Dialect, PoliceStation, Region

# 浙江 11 市（真实区划代码，仅用于 tree 结构断言，非完整 seed）
CITIES = [("330100", "杭州市"), ("330200", "宁波市"), ("330300", "温州市"), ("330400", "嘉兴市"),
          ("330500", "湖州市"), ("330600", "绍兴市"), ("330700", "金华市"), ("330800", "衢州市"),
          ("330900", "舟山市"), ("331000", "台州市"), ("331100", "丽水市")]


def seed_base(db):
    db.add(Region(code="330000", name="浙江省", level="province", parent_code=""))
    for i, (code, name) in enumerate(CITIES):
        db.add(Region(code=code, name=name, level="city", parent_code="330000", sort_order=i + 1))
    db.add(Region(code="331004", name="临海市", level="district", parent_code="331000", sort_order=1))
    db.add(Dialect(code="dh331004", name="临海话", region_code="331004", parent_code="dh331"))
    db.add(Dialect(code="dh331082", name="三门话", region_code="331082", parent_code="dh331"))
    db.add(PoliceStation(code="PS33100401", name="临海市公安局××派出所", region_code="331004", sort_order=1))
    db.add(PoliceStation(code="PS33108201", name="三门县公安局××派出所", region_code="331082", sort_order=2))
    db.commit()


def test_regions_flat(client, db):
    seed_base(db)
    r = client.get("/api/regions")
    body = r.json()
    assert r.status_code == 200 and body["code"] == 0
    codes = [x["code"] for x in body["data"]]
    assert "330000" in codes and "331004" in codes


def test_regions_tree(client, db):
    seed_base(db)
    r = client.get("/api/regions/tree")
    roots = r.json()["data"]
    assert len(roots) == 1
    root = roots[0]
    assert root["code"] == "330000" and root["level"] == "province"
    assert len(root["children"]) == 11
    tz = next(c for c in root["children"] if c["code"] == "331000")
    assert [d["code"] for d in tz["children"]] == ["331004"]


def test_dialects(client, db):
    seed_base(db)
    r = client.get("/api/dialects")
    assert r.status_code == 200 and len(r.json()["data"]) == 2


def test_dialects_by_region(client, db):
    seed_base(db)
    r = client.get("/api/dialects/by-region/331004")
    assert [d["code"] for d in r.json()["data"]] == ["dh331004"]


def test_police_stations(client, db):
    seed_base(db)
    r = client.get("/api/police_stations")
    assert r.status_code == 200 and len(r.json()["data"]) == 2


def test_police_stations_by_region(client, db):
    seed_base(db)
    r = client.get("/api/police_stations/by-region/331004")
    assert [s["name"] for s in r.json()["data"]] == ["临海市公安局××派出所"]
