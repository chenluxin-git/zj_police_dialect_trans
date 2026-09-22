"""T6 基础数据 API：regions（平铺 + 三级 tree）/ dialects / police_stations
移植自旧 app/api/{regions,dialects,police_stations}.py 合并为单文件（只保留查询，裁掉建改）；
注册页未登录也要拉区域级联，按旧项目口径保持公开；tree 一次查全表两遍分桶构建（O(n)）
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import Dialect, PoliceStation, Region
from ..schemas import ok

router = APIRouter(tags=["基础数据"])


def _dialect_dict(d: Dialect) -> dict:
    return {"code": d.code, "name": d.name, "region_code": d.region_code,
            "parent_code": d.parent_code, "description": d.description}


def _station_dict(s: PoliceStation) -> dict:
    return {"code": s.code, "name": s.name, "region_code": s.region_code, "sort_order": s.sort_order}


@router.get("/regions")
def list_regions(db: Session = Depends(get_db)):
    rows = db.scalars(select(Region).order_by(Region.sort_order, Region.code)).all()
    return ok([{"code": r.code, "name": r.name, "level": r.level,
                "parent_code": r.parent_code, "sort_order": r.sort_order} for r in rows])


@router.get("/regions/tree")
def regions_tree(db: Session = Depends(get_db)):
    rows = db.scalars(select(Region).order_by(Region.sort_order, Region.code)).all()
    nodes = {r.code: {"code": r.code, "name": r.name, "level": r.level, "children": []} for r in rows}
    roots: list[dict] = []
    for r in rows:
        parent = nodes.get(r.parent_code) if r.parent_code else None
        (parent["children"] if parent else roots).append(nodes[r.code])
    return ok(roots)


@router.get("/dialects")
def list_dialects(db: Session = Depends(get_db)):
    rows = db.scalars(select(Dialect).order_by(Dialect.code)).all()
    return ok([_dialect_dict(d) for d in rows])


@router.get("/dialects/by-region/{region_code}")
def dialects_by_region(region_code: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(Dialect).where(Dialect.region_code == region_code)
                      .order_by(Dialect.code)).all()
    return ok([_dialect_dict(d) for d in rows])


@router.get("/police_stations")
def list_police_stations(db: Session = Depends(get_db)):
    rows = db.scalars(select(PoliceStation).order_by(PoliceStation.sort_order, PoliceStation.code)).all()
    return ok([_station_dict(s) for s in rows])


@router.get("/police_stations/by-region/{region_code}")
def police_stations_by_region(region_code: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(PoliceStation).where(PoliceStation.region_code == region_code)
                      .order_by(PoliceStation.sort_order, PoliceStation.name)).all()
    return ok([_station_dict(s) for s in rows])
