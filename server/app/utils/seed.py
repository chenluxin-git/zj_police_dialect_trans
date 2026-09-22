"""T4 seed：幂等预置基础数据（区划/方言/派出所）与 282 个账号。

账号规则（区划码 6 位 + 5 位序号 = 11 位手机号，密码统一 123456）：
- 超管 1：33000000001（省超管，region 330000）
- 市管 11：{市码}00001，县管 90：{县码}00001
- 民警 180：每县 {县码}00002 / {县码}00003
幂等性：按"表是否已有数据/账号是否已存在"逐段判重，重复调用无副作用。
"""
from sqlalchemy import select
from ..core.security import hash_password
from ..models import Region, Dialect, PoliceStation, User
from .seed_data import REGIONS, DIALECTS, POLICE_STATIONS


def run_seed(db) -> None:
    # 1) 基础数据：三表各按"空表才灌"判重
    if db.scalar(select(Region).where(Region.code == "330000")) is None:
        db.add_all(Region(**r) for r in REGIONS)
    if db.scalar(select(Dialect.code).limit(1)) is None:
        db.add_all(Dialect(**d) for d in DIALECTS)
    if db.scalar(select(PoliceStation.code).limit(1)) is None:
        db.add_all(PoliceStation(**p) for p in POLICE_STATIONS)
    db.flush()  # 生产 SessionLocal 为 autoflush=False：必须先刷入，下方 districts/cities 查询才能看到本批数据

    # 2) 预置账号（计划参考实现用 Dialect.id/PoliceStation.id 判重，新模型主键为 code，故改判 code）
    districts = db.scalars(select(Region).where(Region.level == "district")).all()
    accounts: list[tuple[str, str, str, str]] = [("33000000001", "省超管", "330000", "super_admin")]
    for r in db.scalars(select(Region).where(Region.level == "city")):
        accounts.append((r.code + "00001", f"{r.name.replace('市', '')}管理员", r.code, "admin"))
    for d in districts:
        accounts.append((d.code + "00001", f"{d.name.replace('市', '')}管理员", d.code, "admin"))
    for d in districts:
        for i in (2, 3):
            accounts.append((d.code + f"0000{i}", f"{d.name.replace('市', '')}民警0{i - 1}", d.code, "user"))
    for phone, name, region, role in accounts:
        if db.scalar(select(User).where(User.phone == phone)) is None:
            db.add(User(phone=phone, password_hash=hash_password("123456"), real_name=name,
                       police_station="", region_code=region, role=role))
    db.commit()
