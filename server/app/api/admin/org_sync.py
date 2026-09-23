"""管理端：统一用户/部门同步（首次初始化 + 状态查询）

真实触发链接要求（规范 2.1/2.2）：实时模式需要应用方提供同步触发链接，
形如 `http://****/***/yhbmtb?type=bm`。本模块对应该要求：

    POST /api/admin/org-sync/init?kind=dept|user[&token=...]

- `kind=dept` → 部门初始化（SJLX=1）；`kind=user` → 警员初始化（SJLX=3）
- 需要管理员令牌（Bearer）；若额外配置了触发口令，则 query 里还要带 `token`
- 初始化是幂等的，但**全量拉取较重，不要放进定时任务**（定时走增量，见 services/org_sync）

> 首次接入顺序：先 `kind=dept` 再 `kind=user`（警员要落部门名），然后打开 `ZHIJING_ORG_SYNC_ENABLED`。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.config import settings
from ...models import User
from ...schemas import ok
from ...services import org_sync
from ..deps import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/org-sync", tags=["管理端-组织同步"])


@router.get("/status")
def org_sync_status(_admin: User = Depends(require_admin)):
    """同步状态：开关、组件地址是否配好、两侧增量游标进度（不写库、不触发同步）"""
    return ok(org_sync.sync_status())


@router.post("/init")
def org_sync_init(
    kind: str = Query(..., description="dept=部门初始化(SJLX=1) / user=警员初始化(SJLX=3)"),
    token: str = Query("", description="触发口令（若平台侧约定）"),
    _admin: User = Depends(require_admin),
):
    """执行一次全量初始化（幂等）。失败时返回 502 并把错误原因透出，便于联调定位。"""
    if kind not in ("dept", "user"):
        raise HTTPException(400, "kind 只支持 dept / user")
    if not org_sync.ensure_configured():
        raise HTTPException(400, "未配置统一用户组件地址（ZHIJING_ORG_BASE_URL）")
    try:
        result = org_sync.initialize(kind, trigger_token=token)
    except Exception as exc:  # noqa: BLE001
        logger.exception("组织初始化失败 kind=%s", kind)
        raise HTTPException(502, f"初始化失败：{type(exc).__name__}: {str(exc)[:200]}") from exc
    return ok(result)
