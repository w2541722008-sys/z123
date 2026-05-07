from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.config import utc_now
from core.database import ConnType
from constants import Mood, StoryPhase
from services.cache_service import cache_get, cache_set
from utils.json_utils import parse_json_object

_AFFECTION_BASE_RULES: dict[str, int] = {
    "deep_conversation": 4, "light_chat": 1, "compliment": 2, "gift": 6,
    "help": 3, "shared_secret": 5, "first_meeting": 3, "comfort": 3,
    "flirt": 2, "date": 5, "first_hug": 7, "kiss": 8, "confession": 10,
    "argument": -5, "rude": -3, "ignore": -2, "lie": -4, "betray": -8, "insult": -6,
    "explore": 2, "discover": 4, "problem_resolved": 5, "challenge_won": 6,
    "obstacle_cleared": 10, "choice_made": 3, "npc_helped": 3, "secret_found": 7,
    "milestone": 8, "setback": -4, "unexpected_danger": -3, "relationship_lost": -6, "opportunity_missed": -2,
}

_AFFECTION_COOLDOWN_SECONDS: dict[str, int] = {
    "deep_conversation": 3600, "light_chat": 300, "compliment": 1800, "gift": 86400,
    "help": 3600, "shared_secret": 7200, "first_meeting": 604800, "comfort": 1800,
    "flirt": 1200, "date": 43200, "first_hug": 604800, "kiss": 604800, "confession": 604800,
    "explore": 300, "discover": 1800, "problem_resolved": 86400, "challenge_won": 3600,
    "obstacle_cleared": 604800, "choice_made": 7200, "npc_helped": 3600,
    "secret_found": 86400, "milestone": 43200, "setback": 1800,
    "unexpected_danger": 1200, "relationship_lost": 86400, "opportunity_missed": 3600,
}

# 旧事件名→新事件名迁移映射（向后兼容：运营自定义规则中可能仍使用旧名）
_EVENT_NAME_MIGRATION: dict[str, str] = {
    "battle_won": "challenge_won",
    "boss_defeated": "obstacle_cleared",
    "battle_lost": "setback",
    "trap_triggered": "unexpected_danger",
    "puzzle_solved": "problem_resolved",
    "ally_lost": "relationship_lost",
    "clue_missed": "opportunity_missed",
}

_AFFECTION_DIMINISHING_RETURNS: list[float] = [1.0, 0.6, 0.3, 0.0]
_DAILY_AFFECTION_CAP_DEFAULT = 15  # 默认每日好感度上限
# daily_cap=0 表示不限制每日上限（适合剧情沙盒角色）
_PHASE_THRESHOLDS: dict[str, int] = {"acquaintance": 20, "friend": 50, "lover": 80}
_PHASE_GAIN_MULTIPLIER: dict[str, float] = {
    "stranger": 1.0, "acquaintance": 0.8, "friend": 0.6, "lover": 0.4,
}
_VALID_STORY_PHASES = tuple(phase.value for phase in StoryPhase)
_VALID_MOODS = tuple(mood.value for mood in Mood)
_AFFECTION_DELTA_MAX = 10


def _get_affection_rules(conn: ConnType, character_id: str) -> dict[str, int]:
    cache_key = f"affection_rules:{character_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return dict(cached)

    row = conn.execute(
        "SELECT affection_rules_json, affection_enabled FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    if not row:
        result = dict(_AFFECTION_BASE_RULES)
        cache_set(cache_key, result, ttl=300)
        return result

    merged = dict(_AFFECTION_BASE_RULES)
    card_rules = parse_json_object(row["affection_rules_json"] or "{}", fallback={})
    # 非事件名的配置键，跳过（不作为好感度事件处理）
    _META_KEYS = {"enabled", "daily_cap", "allow_regression", "show_bar"}
    for k, v in card_rules.items():
        if k in _META_KEYS:
            continue
        try:
            raw_val = int(v)
        except (ValueError, TypeError):
            continue
        # 迁移旧事件名（如 battle_won → challenge_won）
        effective_k = _EVENT_NAME_MIGRATION.get(k, k)
        if effective_k in _AFFECTION_BASE_RULES:
            base_original = _AFFECTION_BASE_RULES[k]
            if base_original >= 0:
                raw_val = max(0, min(raw_val, min(base_original * 2, 15)))
            else:
                raw_val = min(0, max(raw_val, max(base_original * 2, -15)))
        else:
            raw_val = max(-10, min(raw_val, 10))
        merged[k] = raw_val

    cache_set(cache_key, merged, ttl=300)
    return merged


def is_affection_enabled(conn: ConnType, character_id: str) -> bool:
    row = conn.execute(
        "SELECT affection_enabled, affection_rules_json FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    if not row:
        return True
    if int(row["affection_enabled"] or 1) == 0:
        return False
    card_rules = parse_json_object(row["affection_rules_json"] or "{}", fallback={})
    if "enabled" in card_rules:
        return bool(card_rules["enabled"])
    return True


def _get_daily_cap(conn: ConnType, character_id: str) -> int:
    """从角色卡的 affection_rules_json 中读取 daily_cap 配置。

    返回值含义：
        > 0  → 每日好感度涨幅上限
        = 0  → 不限制每日上限（适合剧情沙盒）
    未配置时返回默认值 15。
    """
    row = conn.execute(
        "SELECT affection_rules_json FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    if not row or not row["affection_rules_json"]:
        return _DAILY_AFFECTION_CAP_DEFAULT
    rules_json = parse_json_object(row["affection_rules_json"], fallback={})
    cap = rules_json.get("daily_cap")
    if cap is not None:
        try:
            return max(0, int(cap))  # 0=不限制
        except (ValueError, TypeError):
            pass
    return _DAILY_AFFECTION_CAP_DEFAULT


def _calculate_affection_change(
    event: str,
    rules: dict[str, int],
    current_state: dict[str, Any],
    *,
    daily_cap: int = _DAILY_AFFECTION_CAP_DEFAULT,
) -> tuple[int, str]:
    """计算好感度变化量，含三防机制。

    Args:
        daily_cap: 每日好感度涨幅上限。0 表示不限制（适合剧情沙盒角色）。
    """
    base_change = rules.get(event, 0)
    if base_change == 0:
        return 0, f"event={event} not in rules or base_change=0"

    if base_change < 0:
        phase = current_state.get("story_phase", "stranger")
        negative_multiplier = {
            "stranger": 0.8, "acquaintance": 1.0, "friend": 1.2, "lover": 1.5,
        }.get(phase, 1.0)
        actual = max(int(base_change * negative_multiplier), -_AFFECTION_DELTA_MAX)
        return actual, f"negative event, phase={phase}, multiplier={negative_multiplier}"

    cooldown_secs = _AFFECTION_COOLDOWN_SECONDS.get(event, 600)
    last_ts_map = current_state.get("_last_event_timestamps", {})
    last_ts = last_ts_map.get(event)
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed < cooldown_secs:
                return 0, f"cooldown: event={event}, remaining={int(cooldown_secs - elapsed)}s"
        except (ValueError, TypeError):
            pass

    # 日上限检查（daily_cap=0 时跳过，不限制）
    daily_gained = current_state.get("_daily_affection_gained", 0)
    if daily_cap > 0 and daily_gained >= daily_cap:
        return 0, f"daily_cap: already gained {daily_gained}/{daily_cap} today"

    daily_counts = current_state.get("_daily_event_counts", {})
    trigger_count = int(daily_counts.get(event, 0))
    diminish_rate = _AFFECTION_DIMINISHING_RETURNS[trigger_count] if trigger_count < len(_AFFECTION_DIMINISHING_RETURNS) else 0.0

    phase = current_state.get("story_phase", "stranger")
    phase_multiplier = _PHASE_GAIN_MULTIPLIER.get(phase, 1.0)
    raw = base_change * diminish_rate * phase_multiplier
    actual = min(max(0, int(round(raw)), 0), base_change)
    if daily_cap > 0:
        actual = min(actual, max(0, daily_cap - daily_gained))

    reason = (
        f"event={event}, base={base_change}, diminish={diminish_rate:.1f}, "
        f"phase={phase}×{phase_multiplier}, daily_cap={daily_cap}, actual={actual}"
    )
    return actual, reason


def _update_anti_abuse_counters(
    current_state: dict[str, Any],
    event: str,
    actual_change: int,
) -> dict[str, Any]:
    last_ts_map = dict(current_state.get("_last_event_timestamps", {}))
    last_ts_map[event] = utc_now().isoformat()
    daily_counts = dict(current_state.get("_daily_event_counts", {}))
    daily_gained = current_state.get("_daily_affection_gained", 0)
    if actual_change > 0:
        daily_counts[event] = int(daily_counts.get(event, 0)) + 1
        daily_gained = daily_gained + actual_change
    updated = dict(current_state)
    updated["_last_event_timestamps"] = last_ts_map
    updated["_daily_event_counts"] = daily_counts
    updated["_daily_affection_gained"] = daily_gained
    return updated


def _auto_advance_story_phase(
    affection: int,
    current_phase: str,
    *,
    allow_regression: bool = False,
) -> str:
    """
    根据好感度自动推进（或回退）剧情阶段。

    Args:
        affection: 当前好感度
        current_phase: 当前阶段
        allow_regression: 是否允许阶段回退（虐恋/悬疑等题材需要）
    """
    phases_order = list(_VALID_STORY_PHASES)
    current_idx = phases_order.index(current_phase) if current_phase in phases_order else 0

    if allow_regression:
        # 允许回退：直接根据好感度计算应该处于的阶段
        best_idx = 0  # 默 stranger
        for phase_name, threshold in _PHASE_THRESHOLDS.items():
            if affection >= threshold:
                candidate_idx = phases_order.index(phase_name) if phase_name in phases_order else 0
                if candidate_idx > best_idx:
                    best_idx = candidate_idx
        return phases_order[best_idx]

    # 不允许回退：只前进不后退
    best_idx = current_idx
    for phase_name, threshold in _PHASE_THRESHOLDS.items():
        if affection >= threshold:
            candidate_idx = phases_order.index(phase_name) if phase_name in phases_order else 0
            if candidate_idx > best_idx:
                best_idx = candidate_idx
    return phases_order[best_idx]
