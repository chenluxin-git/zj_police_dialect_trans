"""T14 管理端用户管理：scope 列表（录音/标注/任务进度列）+ 增删改 + Excel 导出
移植自旧项目 app/api/admin/users.py，差异叠加：
- 权限由 resolve_scope 统一推导（替代旧 role==admin 的 if-else 本区域判断）；
  admin 仅 scope 内用户可操作，且不可创建/修改/删除 super_admin（Spec §6.6）
- 创建初始密码 = 手机号后 6 位（旧版前端传明文密码，改为服务端生成）
- 统计列复用 progress_map（录音仅 passed，Spec §5.2 口径）；任务进度列 = 本人最近 active 任务
- 导出改平铺清单（手机号/姓名/角色/区域/单位/录音数/标注数——T14 接口定义，
  旧版按地区/派出所分组小计的报表不再保留）
"""
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.security import hash_password
from ...models import Recording, Region, Task, User
from ...schemas import ok
from ...schemas.admin import UserCreateIn, UserUpdateIn
from ...services.task_progress import progress_map
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/users", tags=["管理端-用户管理"])

PHONE_RE = re.compile(r"^\d{11}$")
VALID_ROLES = {"user", "admin", "super_admin"}
_DONE_KEY = {"recording": "recording_done", "annotation": "annotation_done"}
EXPORT_HEADERS = ["手机号", "姓名", "角色", "区域", "单位", "录音数", "标注数"]


def _expand_region_codes(db: Session, code: str) -> list[str]:
    """code 及其全部下级（BFS；省/市码可整域筛选）"""
    result, queue = [code], [code]
    while queue:
        children = list(db.scalars(select(Region.code).where(Region.parent_code.in_(queue))).all())
        queue = [c for c in children if c not in result]
        result.extend(queue)
    return result


def _filtered_query(db: Session, admin: User, real_name, phone, role, region_code, station):
    """scope + 各筛选；region_code 展开下级后 ∩ scope。region 越界返回 None（空结果）"""
    scope = resolve_scope(db, admin)
    q = db.query(User).filter(scope_filter(User.region_code, scope))
    if region_code:
        expanded = _expand_region_codes(db, region_code)
        codes = expanded if scope is None else [c for c in expanded if c in scope]
        if not codes:
            return None
        q = q.filter(User.region_code.in_(codes))
    if real_name:
        q = q.filter(User.real_name.contains(real_name))
    if phone:
        q = q.filter(User.phone.contains(phone))
    if role:
        q = q.filter(User.role == role)
    if station:
        q = q.filter(User.police_station == station)
    return q


def _region_names(db: Session) -> dict[str, str]:
    return {r.code: r.name for r in db.scalars(select(Region)).all()}


def _task_progress(db: Session, progress, user_id: int) -> dict | None:
    """本人最近一条 active 任务的进度（done = max(0, 有效数 - base_count)，Spec §5.2）"""
    task = db.scalars(select(Task).where(Task.user_id == user_id, Task.status == "active")
                      .order_by(Task.id.desc())).first()
    if task is None:
        return None
    valid = progress[user_id][_DONE_KEY[task.type]]
    return {"type": task.type, "target_count": task.target_count, "base_count": task.base_count,
            "done": max(0, valid - task.base_count), "status": task.status, "note": task.note}


def _user_item(db: Session, u: User, progress, names) -> dict:
    return {
        "id": u.id, "phone": u.phone, "real_name": u.real_name, "role": u.role,
        "region_code": u.region_code, "region_name": names.get(u.region_code, u.region_code),
        "police_station": u.police_station,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "recording_count": progress[u.id]["recording_done"],
        "annotation_count": progress[u.id]["annotation_done"],
        "task_progress": _task_progress(db, progress, u.id),
    }


@router.get("")
def list_users(
    real_name: str | None = Query(None),
    phone: str | None = Query(None),
    role: str | None = Query(None),
    region_code: str | None = Query(None, description="区域码：省/市码展开整域，区县码精确"),
    station: str | None = Query(None, description="派出所精确筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = _filtered_query(db, admin, real_name, phone, role, region_code, station)
    if q is None:
        return ok({"total": 0, "page": page, "page_size": page_size, "items": []})
    total = q.count()
    users = q.order_by(User.id).offset((page - 1) * page_size).limit(page_size).all()
    progress = progress_map(db, [u.id for u in users])
    names = _region_names(db)
    return ok({"total": total, "page": page, "page_size": page_size,
               "items": [_user_item(db, u, progress, names) for u in users]})


@router.post("")
def create_user(body: UserCreateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not PHONE_RE.fullmatch(body.phone):
        raise HTTPException(400, "手机号必须为11位数字")
    if body.role not in VALID_ROLES:
        raise HTTPException(400, "角色不合法")
    if db.query(User).filter(User.phone == body.phone).first() is not None:
        raise HTTPException(400, "手机号已注册")
    if db.get(Region, body.region_code) is None:
        raise HTTPException(400, "区域代码不存在")
    scope = resolve_scope(db, admin)
    if scope is not None and body.region_code not in scope:
        raise HTTPException(403, "无权创建管理范围外的用户")
    if admin.role != "super_admin" and body.role == "super_admin":
        raise HTTPException(403, "无权创建超级管理员")
    user = User(phone=body.phone, password_hash=hash_password(body.phone[-6:]),
                real_name=body.real_name, police_station=body.police_station,
                region_code=body.region_code, role=body.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok({"id": user.id, "phone": user.phone, "real_name": user.real_name,
               "role": user.role, "region_code": user.region_code,
               "police_station": user.police_station,
               "created_at": user.created_at.isoformat() if user.created_at else None})


@router.put("/{user_id}")
def update_user(user_id: int, body: UserUpdateIn,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    scope = resolve_scope(db, admin)
    if scope is not None and user.region_code not in scope:
        raise HTTPException(403, "无权修改管理范围外的用户")
    if admin.role != "super_admin" and user.role == "super_admin":
        raise HTTPException(403, "无权修改超级管理员")
    if body.real_name is not None:
        user.real_name = body.real_name
    if body.police_station is not None:
        user.police_station = body.police_station
    if body.region_code is not None:
        if db.get(Region, body.region_code) is None:
            raise HTTPException(400, "区域代码不存在")
        if scope is not None and body.region_code not in scope:
            raise HTTPException(403, "无权将用户调整到管理范围外")
        user.region_code = body.region_code
    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise HTTPException(400, "角色不合法")
        if admin.role != "super_admin" and body.role == "super_admin":
            raise HTTPException(403, "无权将用户设为超级管理员")
        user.role = body.role
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    db.commit()
    db.refresh(user)
    return ok({"id": user.id, "phone": user.phone, "real_name": user.real_name,
               "role": user.role, "region_code": user.region_code,
               "police_station": user.police_station})


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    scope = resolve_scope(db, admin)
    if scope is not None and user.region_code not in scope:
        raise HTTPException(403, "无权删除管理范围外的用户")
    if admin.role != "super_admin" and user.role == "super_admin":
        raise HTTPException(403, "无权删除超级管理员")
    if db.query(Recording).filter(Recording.user_id == user_id).count() > 0:
        raise HTTPException(400, "该用户已有录音记录，无法删除")
    db.delete(user)
    db.commit()
    return ok(msg="删除成功")


@router.get("/export")
def export_users(
    real_name: str | None = Query(None),
    phone: str | None = Query(None),
    role: str | None = Query(None),
    region_code: str | None = Query(None),
    station: str | None = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = _filtered_query(db, admin, real_name, phone, role, region_code, station)
    users = [] if q is None else q.order_by(User.id).all()
    progress = progress_map(db, [u.id for u in users])
    names = _region_names(db)

    wb = Workbook()
    ws = wb.active
    ws.title = "用户清单"
    ws.append(EXPORT_HEADERS)
    for col in range(1, len(EXPORT_HEADERS) + 1):
        c = ws.cell(row=1, column=col)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
    for u in users:
        ws.append([u.phone, u.real_name, u.role, u.region_code,
                   u.police_station, progress[u.id]["recording_done"],
                   progress[u.id]["annotation_done"]])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=users_export.xlsx"})
