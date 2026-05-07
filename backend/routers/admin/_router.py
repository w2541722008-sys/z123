"""
管理后台 - 子模块（从 admin.py 自动拆分）
"""
from fastapi import APIRouter, Depends

from core.auth import get_admin_user

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])

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
