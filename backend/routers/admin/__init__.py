"""
管理后台路由包 - 按业务域拆分为子模块

子模块：
    - characters: 角色管理（CRUD + 记忆/开场白/剧情线/规则/事件/分类）
    - users: 用户管理 + 会员
    - orders: 订单管理
    - dashboard: 仪表盘 / 统计 / 审计日志
"""

from fastapi import APIRouter, Depends

from core.auth import get_admin_user
from ._helpers import _ADMIN_EDITABLE_FIELDS, _transaction
from ._router import router as characters_router
from .users import router as users_router
from .orders import router as orders_router
from .dashboard import router as dashboard_router

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])
router.include_router(characters_router)
router.include_router(users_router)
router.include_router(orders_router)
router.include_router(dashboard_router)

__all__ = ["router", "_ADMIN_EDITABLE_FIELDS", "_transaction"]
