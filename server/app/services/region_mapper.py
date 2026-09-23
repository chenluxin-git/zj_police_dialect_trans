"""机构代码 → 行政区划代码映射（本项目三级数据权限的关键适配层）

背景：本平台的省/市/区县数据隔离全建立在 `regions.code`（6 位行政区划代码）上，
而浙警智治零信任/统一用户返回的是 **12 位公安机关机构代码**（`DM` / `BMCODE`）。

策略（可配置、可回退、绝不产生越权数据）：
1. 机构代码前 6 位命中 `regions` 表 → 直接采用；
2. 未命中时取**前 4 位 + "00"**（地市级区划码）再试；
3. 仍未命中 → 回退该用户所属省级根（默认 `330000`），保证能登录但看不到任何区县数据，
   同时在 `MappingMiss` 中回报，便于运维用 `org_units` 白名单修正。

> ⚠️ 上线前必须用真实机构代码样本（省厅/市局/区县分局/派出所各取一条）验证本映射，
> 否则省→市→区县的数据范围会失真。校验入口：见 `services/zero_trust.py::self_check`。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Region

PROVINCE_FALLBACK = "330000"


@dataclass
class RegionMapping:
    region_code: str
    matched: bool
    note: str = ""


def map_region_code(db: Session, org_code: str, *, fallback: str | None = None) -> RegionMapping:
    """把 12 位机构代码映射成 6 位行政区划代码"""
    code = (org_code or "").strip()
    fallback_code = fallback or PROVINCE_FALLBACK

    if len(code) >= 6:
        direct = code[:6]
        if db.get(Region, direct) is not None:
            return RegionMapping(direct, True, "机构代码前 6 位命中区划表")
        city = code[:4] + "00"
        if db.get(Region, city) is not None:
            return RegionMapping(city, True, "机构代码前 4 位按地市级命中区划表")
    if db.get(Region, fallback_code) is not None:
        return RegionMapping(fallback_code, False, f"未命中机构代码 {code}，回退 {fallback_code}（无区县数据权限）")
    return RegionMapping(fallback_code, False, f"未命中且无 {fallback_code} 根节点，沿用 {fallback_code}")


def resolve_region_code(db: Session, org_code: str, region_code_hint: str = "") -> str:
    """对外简化入口：优先用显式区划码，其次走机构代码映射"""
    if region_code_hint and db.get(Region, region_code_hint) is not None:
        return region_code_hint
    return map_region_code(db, org_code).region_code


def org_units_in_region(db: Session, region_code: str) -> list[str]:
    """反向查询：某区划下的全部机构代码（用于审计 organizationId 校验、报表）"""
    from ..models.org import OrgUnit

    return [u.code for u in db.scalars(select(OrgUnit).where(OrgUnit.region_code == region_code))]


def health_report(db: Session, sample_codes: list[str] | None = None) -> dict:
    """映射体检报告：上线前用它核对"机构码 → 区划码"是否符合预期

    本项目省/市/县三级数据隔离完全建立在 6 位区划码上，映射错了就会出现
    "某区县民警看不到自己辖区的任务"或"看到了别的区县数据"。
    联调时把省厅给的机构代码样本传进来（`sample_codes`），一次看清落点。
    """
    from ..models.org import OrgUnit

    units = db.scalars(select(OrgUnit)).all()
    items: list[dict] = []
    for unit in units:
        mapping = map_region_code(db, unit.code)
        region = db.get(Region, mapping.region_code)
        items.append({
            "org_code": unit.code,
            "org_name": unit.name,
            "region_code": mapping.region_code,
            "region_name": region.name if region else "",
            "region_level": region.level if region else "",
            "matched": mapping.matched,
            "note": mapping.note,
        })

    for code in sample_codes or []:
        mapping = map_region_code(db, code.strip())
        region = db.get(Region, mapping.region_code)
        items.append({
            "org_code": code.strip(),
            "org_name": "（联调样本，未入库）",
            "region_code": mapping.region_code,
            "region_name": region.name if region else "",
            "region_level": region.level if region else "",
            "matched": mapping.matched,
            "note": mapping.note,
        })

    total = len(items)
    matched = sum(1 for i in items if i["matched"])
    # 去重但保持顺序：同一机构码可能既在库里又被当成联调样本传入
    unmapped = list(dict.fromkeys(i["org_code"] for i in items if not i["matched"]))
    return {
        "total": total,
        "matched": matched,
        "unmapped": len(unmapped),
        "match_rate": round(matched / total, 4) if total else None,
        "unmapped_codes": unmapped[:50],
        "items": items[:500],
        "hint": ("全部命中，映射口径可用" if total and not unmapped
                 else "存在未命中机构代码：登录用户会回退到省级根（无区县数据权限），需核对区划表或补白名单"),
    }
