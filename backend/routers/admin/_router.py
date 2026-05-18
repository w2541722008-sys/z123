"""
管理后台 - 子模块（从 admin.py 自动拆分）
"""
from fastapi import APIRouter, Depends, Request

from core.auth import get_admin_user
from services.rate_limit import enforce_rate_limit, get_request_client_ip


def _admin_rate_limit(request: Request) -> None:
    """管理后台全局限流：每 IP 每分钟最多 60 次请求。"""
    enforce_rate_limit(
        "admin", get_request_client_ip(request),
        limit=60, window_seconds=60, detail="请求过于频繁",
    )


router = APIRouter(
    dependencies=[Depends(get_admin_user), Depends(_admin_rate_limit)],
    tags=["admin"],
)

from .characters_core import router as core_router
from .characters_memory import router as memory_router
from .characters_story import router as story_router
from .characters_rules_events import router as rules_events_router
from .characters_insights import router as insights_router

router.include_router(core_router)
router.include_router(memory_router)
router.include_router(story_router)
router.include_router(rules_events_router)
router.include_router(insights_router)
