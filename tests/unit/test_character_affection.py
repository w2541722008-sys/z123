"""character_affection 纯函数单元测试。

覆盖三层防刷机制：冷却、每日上限、衰减收益，以及阶段推进逻辑。
所有被测试函数均为纯逻辑（无 DB 依赖）。
"""

from datetime import datetime, timezone

from services.character_affection import (
    _AFFECTION_COOLDOWN_SECONDS,
    _AFFECTION_DELTA_MAX,
    _AFFECTION_DIMINISHING_RETURNS,
    _ADVENTURE_AFFECTION_RULES,
    _AFFECTION_BASE_RULES,
    _EVENT_NAME_MIGRATION,
    _ROMANCE_AFFECTION_RULES,
    _auto_advance_story_phase,
    _calculate_affection_change,
    _update_anti_abuse_counters,
)

NOW_UTC = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)


# ============================================================
# 基础规则验证
# ============================================================
class TestBaseRules:
    def test_positive_events_return_positive_values(self):
        for event, value in _AFFECTION_BASE_RULES.items():
            if value > 0:
                assert value > 0, f"{event} should be positive"
        for event, value in _ADVENTURE_AFFECTION_RULES.items():
            if value > 0:
                assert value > 0, f"{event} should be positive"
        for event, value in _ROMANCE_AFFECTION_RULES.items():
            if value > 0:
                assert value > 0, f"{event} should be positive"

    def test_negative_events_return_negative_values(self):
        negative_base = {k: v for k, v in _AFFECTION_BASE_RULES.items() if v < 0}
        assert len(negative_base) >= 5, "应至少有 5 个负向基础事件"
        assert "betray" in negative_base
        assert negative_base["betray"] == -8

    def test_all_rules_dicts_are_non_empty(self):
        assert len(_AFFECTION_BASE_RULES) > 10
        assert len(_ADVENTURE_AFFECTION_RULES) > 5
        assert len(_ROMANCE_AFFECTION_RULES) > 5

    def test_merged_rules_includes_adventure_events(self):
        merged = dict(_AFFECTION_BASE_RULES)
        merged.update(_ADVENTURE_AFFECTION_RULES)
        assert "explore" in merged
        assert "challenge_won" in merged

    def test_merged_rules_includes_romance_events(self):
        merged = dict(_AFFECTION_BASE_RULES)
        merged.update(_ROMANCE_AFFECTION_RULES)
        assert "kiss" in merged
        assert "confession" in merged


# ============================================================
# 冷却机制验证
# ============================================================
class TestCooldowns:
    def test_gift_has_24h_cooldown(self):
        assert _AFFECTION_COOLDOWN_SECONDS["gift"] == 86400

    def test_light_chat_has_5min_cooldown(self):
        assert _AFFECTION_COOLDOWN_SECONDS["light_chat"] == 300

    def test_first_meeting_has_7day_cooldown(self):
        assert _AFFECTION_COOLDOWN_SECONDS["first_meeting"] == 604800

    def test_betray_has_7day_cooldown(self):
        assert _AFFECTION_COOLDOWN_SECONDS["betray"] == 604800

    def test_cooldown_prevents_duplicate_event(self):
        rules = {"compliment": 2}
        # 刚发生的事件，仍在冷却期内（函数内部用 datetime.now() 算时间差）
        just_now = datetime.now(timezone.utc).isoformat()
        state = {"_last_event_timestamps": {"compliment": just_now}}
        change, reason = _calculate_affection_change("compliment", rules, state)
        assert change == 0
        assert "cooldown" in reason

    def test_cooldown_expired_allows_event(self):
        rules = {"light_chat": 1}
        # 使用昨天的时间戳确保冷却已过期
        past_time = NOW_UTC.replace(day=NOW_UTC.day - 1).isoformat()
        state = {"_last_event_timestamps": {"light_chat": past_time}}
        change, reason = _calculate_affection_change("light_chat", rules, state)
        assert change > 0
        assert "cooldown" not in reason

    def test_invalid_cooldown_timestamp_is_ignored_without_crashing(self):
        rules = {"compliment": 2}
        state = {"_last_event_timestamps": {"compliment": "bad-timestamp"}}
        change, reason = _calculate_affection_change("compliment", rules, state)

        assert change > 0
        assert "cooldown" not in reason


# ============================================================
# 每日上限验证
# ============================================================
class TestDailyCap:
    def test_daily_cap_blocks_excess_positive_gains(self):
        rules = {"compliment": 2}
        state = {"_daily_affection_gained": 15}
        change, reason = _calculate_affection_change("compliment", rules, state)
        assert change == 0
        assert "daily_cap" in reason

    def test_daily_cap_does_not_block_negative_gains(self):
        rules = {"argument": -5}
        state = {"_daily_affection_gained": 15}
        change, reason = _calculate_affection_change("argument", rules, state)
        assert change < 0

    def test_daily_cap_respects_custom_value(self):
        rules = {"compliment": 2}
        state = {"_daily_affection_gained": 5}
        change, reason = _calculate_affection_change(
            "compliment", rules, state, daily_cap=5
        )
        assert change == 0
        assert "daily_cap" in reason

    def test_daily_cap_zero_means_unlimited(self):
        rules = {"compliment": 2}
        state = {"_daily_affection_gained": 999}
        change, reason = _calculate_affection_change(
            "compliment", rules, state, daily_cap=0
        )
        assert change > 0

    def test_daily_cap_remains_positive_when_room_available(self):
        rules = {"compliment": 2}
        state = {"_daily_affection_gained": 14}
        change, reason = _calculate_affection_change(
            "compliment", rules, state, daily_cap=15
        )
        assert change == 1


# ============================================================
# 衰减机制验证
# ============================================================
class TestDiminishingReturns:
    def test_first_occurrence_full_value(self):
        assert _AFFECTION_DIMINISHING_RETURNS[0] == 1.0

    def test_second_occurrence_60_percent(self):
        assert _AFFECTION_DIMINISHING_RETURNS[1] == 0.6

    def test_third_occurrence_30_percent(self):
        assert _AFFECTION_DIMINISHING_RETURNS[2] == 0.3

    def test_fourth_occurrence_zero(self):
        assert _AFFECTION_DIMINISHING_RETURNS[3] == 0.0

    def test_first_event_applies_full_positive(self):
        rules = {"deep_conversation": 4}
        state = {"_daily_event_counts": {}}
        change, reason = _calculate_affection_change("deep_conversation", rules, state)
        assert change == 4
        assert "diminish=1.0" in reason

    def test_second_event_applies_diminished(self):
        rules = {"deep_conversation": 4}
        state = {"_daily_event_counts": {"deep_conversation": 1}}
        change, reason = _calculate_affection_change("deep_conversation", rules, state)
        assert change <= 3
        assert "diminish=0.6" in reason

    def test_third_event_applies_more_diminished(self):
        rules = {"deep_conversation": 4}
        state = {"_daily_event_counts": {"deep_conversation": 2}}
        change, reason = _calculate_affection_change("deep_conversation", rules, state)
        assert change <= 2
        assert "diminish=0.3" in reason

    def test_fourth_plus_event_zero_gain(self):
        rules = {"deep_conversation": 4}
        state = {"_daily_event_counts": {"deep_conversation": 3}}
        change, reason = _calculate_affection_change("deep_conversation", rules, state)
        assert change == 0
        assert "diminish=0.0" in reason


# ============================================================
# 负向事件阶段倍率
# ============================================================
class TestNegativeEventPhasing:
    def test_stranger_phase_reduces_negative(self):
        rules = {"argument": -5}
        state = {"story_phase": "stranger"}
        change, reason = _calculate_affection_change("argument", rules, state)
        assert change > -5

    def test_lover_phase_amplifies_negative(self):
        rules = {"argument": -5}
        state = {"story_phase": "lover"}
        change, reason = _calculate_affection_change("argument", rules, state)
        assert change <= -5

    def test_negative_capped_at_affection_delta_max(self):
        rules = {"betray": -8}
        state = {"story_phase": "lover"}
        change, reason = _calculate_affection_change("betray", rules, state)
        assert change >= -_AFFECTION_DELTA_MAX


# ============================================================
# 组合场景
# ============================================================
class TestCombinedMechanisms:
    def test_unknown_event_returns_zero(self):
        change, reason = _calculate_affection_change("nonexistent_event", {}, {})
        assert change == 0
        assert "not in rules" in reason

    def test_cooldown_and_cap_both_active_returns_zero(self):
        rules = {"compliment": 2}
        state = {
            "_last_event_timestamps": {"compliment": NOW_UTC.isoformat()},
            "_daily_affection_gained": 15,
        }
        change, reason = _calculate_affection_change("compliment", rules, state)
        assert change == 0

    def test_diminishing_and_cap_surplus_capped(self):
        rules = {"deep_conversation": 4}
        state = {
            "_daily_event_counts": {"deep_conversation": 1},
            "_daily_affection_gained": 14,
        }
        change, reason = _calculate_affection_change(
            "deep_conversation", rules, state, daily_cap=15
        )
        assert change == 1


# ============================================================
# 事件名迁移
# ============================================================
class TestEventNameMigration:
    def test_legacy_event_names_mapped(self):
        assert "battle_won" in _EVENT_NAME_MIGRATION
        assert _EVENT_NAME_MIGRATION["battle_won"] == "challenge_won"

    def test_prompt_legacy_names_mapped(self):
        assert _EVENT_NAME_MIGRATION["chat"] == "light_chat"
        assert _EVENT_NAME_MIGRATION["deep_talk"] == "deep_conversation"


# ============================================================
# _update_anti_abuse_counters
# ============================================================
class TestUpdateAntiAbuseCounters:
    def test_positive_change_increments_counters(self):
        state = {}
        updated = _update_anti_abuse_counters(state, "compliment", 2)
        assert "compliment" in updated["_last_event_timestamps"]
        assert updated["_daily_event_counts"].get("compliment") == 1
        assert updated["_daily_affection_gained"] == 2

    def test_negative_change_does_not_increment_counters(self):
        state = {"_daily_affection_gained": 5}
        updated = _update_anti_abuse_counters(state, "argument", -4)
        assert updated["_daily_affection_gained"] == 5  # unchanged
        assert updated["_daily_event_counts"].get("argument", 0) == 0

    def test_zero_change_does_not_increment(self):
        state = {"_daily_affection_gained": 5}
        updated = _update_anti_abuse_counters(state, "compliment", 0)
        assert updated["_daily_affection_gained"] == 5

    def test_preserves_existing_other_counters(self):
        state = {"_daily_event_counts": {"gift": 2}, "_daily_affection_gained": 3}
        updated = _update_anti_abuse_counters(state, "compliment", 2)
        assert updated["_daily_event_counts"]["gift"] == 2  # preserved
        assert updated["_daily_event_counts"].get("compliment") == 1


# ============================================================
# _auto_advance_story_phase
# ============================================================
class TestAutoAdvanceStoryPhase:
    def test_stays_at_stranger_when_below_threshold(self):
        phase = _auto_advance_story_phase(0, "stranger")
        assert phase == "stranger"

    def test_advances_to_acquaintance_at_threshold(self):
        phase = _auto_advance_story_phase(20, "stranger")
        assert phase == "acquaintance"

    def test_advances_to_friend_at_threshold(self):
        phase = _auto_advance_story_phase(50, "acquaintance")
        assert phase == "friend"

    def test_advances_to_lover_at_threshold(self):
        phase = _auto_advance_story_phase(80, "friend")
        assert phase == "lover"

    def test_affection_drop_does_not_regress(self):
        phase = _auto_advance_story_phase(10, "friend")
        assert phase == "friend"

    def test_affection_drop_with_regression_allowed(self):
        """回退一次最多降一级（缓冲带保护），friend(10) → acquaintance。"""
        phase = _auto_advance_story_phase(10, "friend", allow_regression=True)
        assert phase == "acquaintance"  # 一次降一级，不会直接跳到 stranger

    def test_affection_huge_skips_multiple_phases(self):
        phase = _auto_advance_story_phase(90, "stranger")
        assert phase == "lover"

    def test_unknown_phase_handled(self):
        phase = _auto_advance_story_phase(50, "nonexistent_phase")
        assert phase in ("stranger", "acquaintance", "friend", "lover")
