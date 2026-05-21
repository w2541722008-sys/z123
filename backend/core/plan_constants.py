"""会员档位常量与纯数据转换函数。

本模块不含 DB / HTTP 依赖，可被 core 层安全引用。
services/plan_service.py 从本模块 re-export 以保持向后兼容。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ── 档位常量 ──────────────────────────────────────────────────

GUEST_PLAN = "guest"
FREE_PLAN = "free"
VIP_PLAN = "vip"
SVIP_PLAN = "svip"

USER_PLAN_VALUES = (FREE_PLAN, VIP_PLAN, SVIP_PLAN)
CHARACTER_PLAN_VALUES = (GUEST_PLAN, FREE_PLAN, VIP_PLAN, SVIP_PLAN)

# 角色卡类型常量
CARD_TYPE_INTIMATE = "intimate"
CARD_TYPE_SCENARIO = "scenario"
DEFAULT_CARD_TYPE = CARD_TYPE_INTIMATE
VALID_CARD_TYPES = (CARD_TYPE_INTIMATE, CARD_TYPE_SCENARIO)

PLAN_LEVELS = {
    GUEST_PLAN: 0,
    FREE_PLAN: 1,
    VIP_PLAN: 2,
    SVIP_PLAN: 3,
}

PLAN_LABELS = {
    GUEST_PLAN: "游客",
    FREE_PLAN: "注册用户",
    VIP_PLAN: "VIP",
    SVIP_PLAN: "SVIP",
}

PLAN_MODEL_PROFILES = {
    GUEST_PLAN: "basic",
    FREE_PLAN: "basic",
    VIP_PLAN: "vip",
    SVIP_PLAN: "svip",
}

# 各档位每日 token 预算 → 已迁移至 core/config.py，通过 _int_env(minimum=, maximum=) 提供边界校验
# 如需引用请从 core.config 导入：from core.config import FREE_DAILY_TOKEN_LIMIT, ...


# ── 纯数据转换函数 ────────────────────────────────────────────

def normalize_user_plan(plan_type: str | None) -> str:
    """规范化用户会员档位。"""
    value = (plan_type or "").strip().lower()
    return value if value in USER_PLAN_VALUES else FREE_PLAN


def normalize_required_plan(required_plan: str | None) -> str:
    """规范化角色访问档位。"""
    value = (required_plan or "").strip().lower()
    return value if value in CHARACTER_PLAN_VALUES else GUEST_PLAN


def plan_display_name(plan_type: str | None) -> str:
    """返回档位中文名。"""
    return PLAN_LABELS.get(normalize_required_plan(plan_type), "游客")


def _parse_iso_datetime(raw_value: str | datetime | None) -> datetime | None:
    """解析数据库返回的 datetime 对象或 ISO 字符串。"""
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        value = str(raw_value).strip()
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_effective_plan(plan_type: str | None, plan_expires_at: str | datetime | None) -> str:
    """根据到期时间计算当前真正生效的档位。"""
    normalized = normalize_user_plan(plan_type)
    if normalized not in {VIP_PLAN, SVIP_PLAN}:
        return FREE_PLAN

    expires_at = _parse_iso_datetime(plan_expires_at)
    if expires_at is None:
        return normalized
    if expires_at <= datetime.now(timezone.utc):
        return FREE_PLAN
    return normalized


def get_plan_level(plan_type: str | None) -> int:
    """返回档位级别，方便比较访问权限。"""
    return PLAN_LEVELS.get(normalize_required_plan(plan_type), 0)


def can_access_required_plan(viewer_plan: str | None, required_plan: str | None) -> bool:
    """判断当前用户档位是否可访问指定角色。"""
    return get_plan_level(viewer_plan) >= get_plan_level(required_plan)


def serialize_plan_info(plan_type: str | None, plan_expires_at: str | datetime | None) -> dict[str, Any]:
    """统一序列化会员档位信息，方便接口复用。"""
    raw_plan = normalize_user_plan(plan_type)
    effective_plan = resolve_effective_plan(raw_plan, plan_expires_at)
    if plan_expires_at is None:
        expires_str = ""
    elif isinstance(plan_expires_at, datetime):
        expires_str = plan_expires_at.isoformat()
    else:
        expires_str = str(plan_expires_at).strip()
    return {
        "plan_type": raw_plan,
        "effective_plan": effective_plan,
        "plan_expires_at": expires_str,
        "plan_display_name": plan_display_name(effective_plan),
        "is_paid_plan": effective_plan in {VIP_PLAN, SVIP_PLAN},
        "membership_expired": raw_plan in {VIP_PLAN, SVIP_PLAN} and effective_plan == FREE_PLAN,
    }
