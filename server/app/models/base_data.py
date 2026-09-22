"""基础数据模型：regions / dialects / police_stations
字段名与旧项目 app/models/ 同名文件保持一致；code 直接作主键（不再用自增 id），
Region 新增省级根 330000（level 取值 province/city/district/town，用 String 而非旧 Enum）
"""
from sqlalchemy import String, Integer, Text
from ..core.database import Base
from sqlalchemy.orm import Mapped, mapped_column

class Region(Base):
    __tablename__ = "regions"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)   # 行政区划代码
    name: Mapped[str] = mapped_column(String(50))                     # 区域名称
    level: Mapped[str] = mapped_column(String(16))                    # province/city/district/town
    parent_code: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 省 roots 空
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

class Dialect(Base):
    __tablename__ = "dialects"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)   # 方言编码
    name: Mapped[str] = mapped_column(String(50))                     # 方言名称
    region_code: Mapped[str] = mapped_column(String(20))              # 主要使用区域
    parent_code: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(Text, default="")

class PoliceStation(Base):
    __tablename__ = "police_stations"
    code: Mapped[str] = mapped_column(String(20), primary_key=True)   # 单位代码
    name: Mapped[str] = mapped_column(String(50))                     # 单位名称
    region_code: Mapped[str] = mapped_column(String(20))              # 所属区域代码
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
