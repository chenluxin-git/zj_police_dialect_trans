"""一次性数据生成工具：从旧省库导出 dialects / police_stations，合并权威区划表，产出 seed_data.py。

用法：cd server && python -m app.utils.gen_seed_data

数据来源与裁定（见 docs/plans/2026-09-22-parallel-dispatch.md P-seed 节）：
- REGIONS：权威浙江 11 市 90 县级行政区划（国家统计局 2023 统计用区划代码，
  与 china-division@2.7.0 数据集交叉核验一致），共 102 条 = 1 省 + 11 市 + 90 县。
  旧库 local_province.db 仅 33 区域（演示子集）且台州三码有误，故不采用。
- DIALECTS / POLICE_STATIONS：从 e:\\project\\record-web-test\\audio-server-test\\local_province.db
  （绝对路径只读）导出，剔除 id/created_at（新模型无此列，code 为主键）。
- 台州三码修正（单遍映射，防链式）：旧库 331021=玉环市(实为331083)、
  331083=温岭市(实为331081)、331025=三门县(实为331022)。
- 演示用伪区划引用（331004-my、331021-dmy、330400_SJ/SS/JC、330491/492、330971/972/999 等）
  原样保留（悬挂引用，不影响业务），手册裁定计数 dialects=11 / police_stations=696 保持不变。
"""
import os
import sqlite3
from pprint import pformat

# 旧省库只读绝对路径（手册裁定）
OLD_DB = r"e:\project\record-web-test\audio-server-test\local_province.db"

# 台州三码修正：旧库码 → 权威码（一次 get，不链式）
REMAP = {"331021": "331083", "331083": "331081", "331025": "331022"}

# 权威浙江区划表：(code, name, level, parent_code)，顺序即 sort_order（省 → 市及其属县依次排列）
_AUTHORITATIVE = [
    ("330000", "浙江省", "province", None),
    ("330100", "杭州市", "city", "330000"),
    ("330102", "上城区", "district", "330100"),
    ("330105", "拱墅区", "district", "330100"),
    ("330106", "西湖区", "district", "330100"),
    ("330108", "滨江区", "district", "330100"),
    ("330109", "萧山区", "district", "330100"),
    ("330110", "余杭区", "district", "330100"),
    ("330111", "富阳区", "district", "330100"),
    ("330112", "临安区", "district", "330100"),
    ("330113", "临平区", "district", "330100"),
    ("330114", "钱塘区", "district", "330100"),
    ("330122", "桐庐县", "district", "330100"),
    ("330127", "淳安县", "district", "330100"),
    ("330182", "建德市", "district", "330100"),
    ("330200", "宁波市", "city", "330000"),
    ("330203", "海曙区", "district", "330200"),
    ("330205", "江北区", "district", "330200"),
    ("330206", "北仑区", "district", "330200"),
    ("330211", "镇海区", "district", "330200"),
    ("330212", "鄞州区", "district", "330200"),
    ("330213", "奉化区", "district", "330200"),
    ("330225", "象山县", "district", "330200"),
    ("330226", "宁海县", "district", "330200"),
    ("330281", "余姚市", "district", "330200"),
    ("330282", "慈溪市", "district", "330200"),
    ("330300", "温州市", "city", "330000"),
    ("330302", "鹿城区", "district", "330300"),
    ("330303", "龙湾区", "district", "330300"),
    ("330304", "瓯海区", "district", "330300"),
    ("330305", "洞头区", "district", "330300"),
    ("330324", "永嘉县", "district", "330300"),
    ("330326", "平阳县", "district", "330300"),
    ("330327", "苍南县", "district", "330300"),
    ("330328", "文成县", "district", "330300"),
    ("330329", "泰顺县", "district", "330300"),
    ("330381", "瑞安市", "district", "330300"),
    ("330382", "乐清市", "district", "330300"),
    ("330383", "龙港市", "district", "330300"),
    ("330400", "嘉兴市", "city", "330000"),
    ("330402", "南湖区", "district", "330400"),
    ("330411", "秀洲区", "district", "330400"),
    ("330421", "嘉善县", "district", "330400"),
    ("330424", "海盐县", "district", "330400"),
    ("330481", "海宁市", "district", "330400"),
    ("330482", "平湖市", "district", "330400"),
    ("330483", "桐乡市", "district", "330400"),
    ("330500", "湖州市", "city", "330000"),
    ("330502", "吴兴区", "district", "330500"),
    ("330503", "南浔区", "district", "330500"),
    ("330521", "德清县", "district", "330500"),
    ("330522", "长兴县", "district", "330500"),
    ("330523", "安吉县", "district", "330500"),
    ("330600", "绍兴市", "city", "330000"),
    ("330602", "越城区", "district", "330600"),
    ("330603", "柯桥区", "district", "330600"),
    ("330604", "上虞区", "district", "330600"),
    ("330624", "新昌县", "district", "330600"),
    ("330681", "诸暨市", "district", "330600"),
    ("330683", "嵊州市", "district", "330600"),
    ("330700", "金华市", "city", "330000"),
    ("330702", "婺城区", "district", "330700"),
    ("330703", "金东区", "district", "330700"),
    ("330723", "武义县", "district", "330700"),
    ("330726", "浦江县", "district", "330700"),
    ("330727", "磐安县", "district", "330700"),
    ("330781", "兰溪市", "district", "330700"),
    ("330782", "义乌市", "district", "330700"),
    ("330783", "东阳市", "district", "330700"),
    ("330784", "永康市", "district", "330700"),
    ("330800", "衢州市", "city", "330000"),
    ("330802", "柯城区", "district", "330800"),
    ("330803", "衢江区", "district", "330800"),
    ("330822", "常山县", "district", "330800"),
    ("330824", "开化县", "district", "330800"),
    ("330825", "龙游县", "district", "330800"),
    ("330881", "江山市", "district", "330800"),
    ("330900", "舟山市", "city", "330000"),
    ("330902", "定海区", "district", "330900"),
    ("330903", "普陀区", "district", "330900"),
    ("330921", "岱山县", "district", "330900"),
    ("330922", "嵊泗县", "district", "330900"),
    ("331000", "台州市", "city", "330000"),
    ("331002", "椒江区", "district", "331000"),
    ("331003", "黄岩区", "district", "331000"),
    ("331004", "路桥区", "district", "331000"),
    ("331022", "三门县", "district", "331000"),
    ("331023", "天台县", "district", "331000"),
    ("331024", "仙居县", "district", "331000"),
    ("331081", "温岭市", "district", "331000"),
    ("331082", "临海市", "district", "331000"),
    ("331083", "玉环市", "district", "331000"),
    ("331100", "丽水市", "city", "330000"),
    ("331102", "莲都区", "district", "331100"),
    ("331121", "青田县", "district", "331100"),
    ("331122", "缙云县", "district", "331100"),
    ("331123", "遂昌县", "district", "331100"),
    ("331124", "松阳县", "district", "331100"),
    ("331125", "云和县", "district", "331100"),
    ("331126", "庆元县", "district", "331100"),
    ("331127", "景宁畲族自治县", "district", "331100"),
    ("331181", "龙泉市", "district", "331100"),
]


def build_regions() -> list[dict]:
    assert len(_AUTHORITATIVE) == 102, "权威区划必须 102 条"
    assert sum(1 for r in _AUTHORITATIVE if r[2] == "province") == 1
    assert sum(1 for r in _AUTHORITATIVE if r[2] == "city") == 11
    assert sum(1 for r in _AUTHORITATIVE if r[2] == "district") == 90
    return [
        {"code": c, "name": n, "level": lv, "parent_code": p, "sort_order": i}
        for i, (c, n, lv, p) in enumerate(_AUTHORITATIVE)
    ]


def export_old(table: str, cols: tuple[str, ...]) -> list[dict]:
    """从旧库导出指定列；region_code 过一遍 REMAP，parent_code None→''"""
    con = sqlite3.connect(f"file:{OLD_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY id").fetchall()
    finally:
        con.close()
    out = []
    for row in rows:
        d = dict(zip(cols, row))
        d["region_code"] = REMAP.get(d["region_code"], d["region_code"])
        if "parent_code" in d and d["parent_code"] is None:
            d["parent_code"] = ""
        out.append(d)
    return out


def main() -> None:
    regions = build_regions()
    region_codes = {r["code"] for r in regions}
    # 旧库真实 6 位县级码在修正后必须全部落在权威表内（伪码跳过）
    con = sqlite3.connect(f"file:{OLD_DB}?mode=ro", uri=True)
    old_district_codes = {c for (c,) in con.execute(
        "SELECT code FROM regions WHERE level='district'")}
    con.close()
    fixed = {REMAP.get(c, c) for c in old_district_codes}
    real = {c for c in fixed if len(c) == 6 and c.isdigit()}
    # 旧库中 6 位但不在 2023 权威县级名单的开发区类旧编码，按裁定原样保留为悬挂引用
    KNOWN_DANGLING = {"330491", "330492", "330971", "330972", "330999"}
    dangling = sorted(real - region_codes - KNOWN_DANGLING)
    assert not dangling, f"修正后仍有真实 6 位码不在权威表: {dangling}"

    dialects = export_old("dialects", ("code", "name", "region_code", "parent_code", "description"))
    stations = export_old("police_stations", ("code", "name", "region_code", "sort_order"))
    assert len(dialects) == 11, len(dialects)
    assert len(stations) == 696, len(stations)

    # station 主键唯一性（新模型 code 为主键，旧库可能存在重复）
    assert len({s["code"] for s in stations}) == 696, "police_stations.code 存在重复"
    assert len({d["code"] for d in dialects}) == 11, "dialects.code 存在重复"

    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "seed_data.py")
    with open(out, "w", encoding="utf-8") as f:
        f.write('"""自动生成：python -m app.utils.gen_seed_data 产出，勿手改。\n')
        f.write("REGIONS=权威浙江区划 102 条；DIALECTS=11 / POLICE_STATIONS=696 导自旧省库\n")
        f.write("（台州三码已修正；演示伪区划引用原样保留为悬挂引用）。\n")
        f.write('"""\n\n')
        f.write(f"REGIONS = {pformat(regions, width=100, sort_dicts=False)}\n\n")
        f.write(f"DIALECTS = {pformat(dialects, width=100, sort_dicts=False)}\n\n")
        f.write(f"POLICE_STATIONS = {pformat(stations, width=100, sort_dicts=False)}\n")
    print(f"seed_data.py written: {len(regions)} regions / {len(dialects)} dialects / {len(stations)} stations")


if __name__ == "__main__":
    main()
