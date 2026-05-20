"""会员档位、角色访问权限与模型策略选择。

常量与纯数据转换函数已迁移至 core/plan_constants.py，
本模块 re-export 以保持向后兼容。
"""

from __future__ import annotations

from typing import Any

from core.exceptions import ForbiddenError
from core.plan_constants import (
    GUEST_PLAN,
    SVIP_PLAN,
    VIP_PLAN,
    FREE_PLAN,
    PLAN_MODEL_PROFILES,
    FREE_DAILY_TOKEN_LIMIT,
    GUEST_DAILY_TOKEN_LIMIT,
    SVIP_DAILY_TOKEN_LIMIT,
    VIP_DAILY_TOKEN_LIMIT,
    can_access_required_plan,
    normalize_required_plan,
    plan_display_name,
)

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS


def ensure_plan_access(
    viewer_plan: str | None,
    required_plan: str | None,
    *,
    detail: str | None = None,
) -> None:
    """没有访问权限时抛出 403。"""
    required = normalize_required_plan(required_plan)
    if can_access_required_plan(viewer_plan, required):
        return
    raise ForbiddenError(
        detail=detail or f"当前内容仅 {plan_display_name(required)} 可访问",
    )


def get_plan_policy(plan_type: str | None) -> dict[str, Any]:
    """按档位返回每日额度与模型策略。"""
    normalized = normalize_required_plan(plan_type)
    if normalized == GUEST_PLAN:
        token_limit = GUEST_DAILY_TOKEN_LIMIT
    elif normalized == VIP_PLAN:
        token_limit = VIP_DAILY_TOKEN_LIMIT
    elif normalized == SVIP_PLAN:
        token_limit = SVIP_DAILY_TOKEN_LIMIT
    else:
        normalized = FREE_PLAN
        token_limit = FREE_DAILY_TOKEN_LIMIT

    return {
        "plan_type": normalized,
        "display_name": plan_display_name(normalized),
        "token_limit": token_limit,
        "model_profile": PLAN_MODEL_PROFILES[normalized],
        "max_output_tokens": AI_CHAT_MAX_OUTPUT_TOKENS,
    }
