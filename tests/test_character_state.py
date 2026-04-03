"""
services/character_state 模块单元测试

覆盖范围：
  - _calculate_affection_change: 好感度变化计算（三防机制 + 负向事件）
  - _update_anti_abuse_counters: 三防计数器更新
  - _auto_advance_story_phase: 阶段自动推进
  - _sanitize_state_delta: 状态增量白名单校验
"""

import sys
import os
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.dirname(__file__))

from services.character_state import (
    _auto_advance_story_phase,
    _calculate_affection_change,
    _sanitize_state_delta,
    _update_anti_abuse_counters,
)


# ============================================================
# 1. _calculate_affection_change 测试（三防机制核心）
# ============================================================

class TestCalculateAffectionChange:
    """
    三防机制：
      1. 冷却检测：同类事件在冷却期内 → 加分归零
      2. 日上限检测：今日涨幅达上限 → 正向加分归零
      3. 边际递减：同类事件多次触发 → 按衰减系数折减
    
    负向事件特殊处理：不受三防限制，但受阶段系数影响。
    """

    def test_unknown_event_returns_zero(self):
        """规则中不存在的事件返回 0。"""
        rules = {"chat": 5}
        state = {}
        change, reason = _calculate_affection_change("unknown_event", rules, state)
        assert change == 0
        assert "not in rules" in reason

    def test_positive_event_basic_calculation(self):
        """正向事件基础计算。"""
        rules = {"deep_chat": 10}
        state = {"story_phase": "friend"}
        change, reason = _calculate_affection_change("deep_chat", rules, state)
        assert change > 0
        assert "deep_chat" in reason

    def negative_event_applies_phase_multiplier(self):
        """负向事件应用阶段系数（关系越好伤害越大）。"""
        rules = {"insult": -10}
        
        state_stranger = {"story_phase": "stranger"}
        ch, _ = _calculate_affection_change("insult", rules, state_stranger)
        assert ch < 0  # 负值
        assert ch >= -10  # stranger 系数 0.8 → -8
        
        state_lover = {"story_phase": "lover"}
        ch2, _ = _calculate_affection_change("insult", rules, state_lover)
        assert ch2 < 0  # 仍为负
        assert ch2 <= ch  # lover 受伤 >= stranger

    def test_negative_event_not_limited_by_daily_cap(self):
        """负向事件不受日上限限制。"""
        rules = {"bad_action": -5}
        state = {
            "story_phase": "friend",
            "_daily_affection_gained": 9999,  # 已达上限
        }
        change, reason = _calculate_affection_change("bad_action", rules, state)
        assert change < 0  # 负向事件仍生效

    def test_cooldown_blocks_positive_event(self):
        """冷却期内正向事件归零。"""
        from services.character_state import utc_now_iso
        
        rules = {"chat": 5}
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(seconds=30)).isoformat()  # 30秒前（冷却期通常600秒）
        
        state = {
            "story_phase": "friend",
            "_last_event_timestamps": {"chat": recent_ts},
        }
        with patch("services.character_state.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            change, reason = _calculate_affection_change("chat", rules, state)
            assert change == 0
            assert "cooldown" in reason

    def test_daily_cap_blocks_positive_event(self):
        """今日已达上限时正向事件归零。"""
        from services.character_state import _DAILY_AFFECTION_CAP
        
        rules = {"chat": 5}
        state = {
            "story_phase": "friend",
            "_daily_affection_gained": _DAILY_AFFECTION_CAP,  # 达到上限
        }
        change, reason = _calculate_affection_change("chat", rules, state)
        assert change == 0
        assert "daily_cap" in reason

    def test_diminishing_returns_on_repeat(self):
        """同类事件多次触发时递减。"""
        rules = {"chat": 20}
        state = {
            "story_phase": "friend",
            "_daily_event_counts": {},  # 第1次触发
        }
        ch1, _ = _calculate_affection_change("chat", rules, state)
        
        state["_daily_event_counts"] = {"chat": 3}  # 第4次触发
        ch2, _ = _calculate_affection_change("chat", rules, state)
        
        # 后续触发应该 <= 首次（边际递减）
        assert ch2 <= ch1


# ============================================================
# 2. _update_anti_abuse_counters 测试
# ============================================================

class TestUpdateAntiAbuseCounters:
    """三防计数器更新。"""

    def test_updates_timestamp_for_event(self):
        from services.character_state import utc_now_iso
        
        state = {}
        updated = _update_anti_abuse_counters(state, "chat", 5)
        assert "chat" in updated.get("_last_event_timestamps", {})

    def test_increments_daily_count_for_positive(self):
        state = {"_daily_event_counts": {"chat": 2}}
        updated = _update_anti_abuse_counters(state, "chat", 5)
        assert updated["_daily_event_counts"]["chat"] == 3

    def test_does_not_increment_count_for_zero_or_negative(self):
        state = {"_daily_event_counts": {"chat": 2}}
        updated = _update_anti_abuse_counters(state, "chat", 0)
        assert updated["_daily_event_counts"]["chat"] == 2  # 不变

        updated2 = _update_anti_abuse_counters(state, "chat", -3)
        assert updated2["_daily_event_counts"]["chat"] == 2  # 不变

    def test_accumulates_daily_gain(self):
        state = {"_daily_affection_gained": 10}
        updated = _update_anti_abuse_counters(state, "chat", 5)
        assert updated["_daily_affection_gained"] == 15

    def test_preserves_other_state_fields(self):
        state = {"mood": "happy", "affection": 50}
        updated = _update_anti_abuse_counters(state, "chat", 5)
        assert updated["mood"] == "happy"
        assert updated["affection"] == 50


# ============================================================
# 3. _auto_advance_story_phase 测试
# ============================================================

class TestAutoAdvanceStoryPhase:
    """
    阶段单向推进规则：
      stranger(0) → acquaintance(>=20) → friend(>=50) → lover(>=80)
    """

    def test_stranger_stays_at_low_affection(self):
        """好感度 < 20，保持陌生人阶段。"""
        result = _auto_advance_story_phase(10, "stranger")
        assert result == "stranger"

    def test_stranger_to_acquaintance_at_threshold(self):
        """好感度 >= 20，推进到熟人。"""
        result = _auto_advance_story_phase(20, "stranger")
        assert result == "acquaintance"

    def test_acquaintance_stays_below_threshold(self):
        """好感度 < 50，保持熟人阶段。"""
        result = _auto_advance_story_phase(40, "acquaintance")
        assert result == "acquaintance"

    def test_acquaintance_to_friend_at_threshold(self):
        """好感度 >= 50，推进到朋友。"""
        result = _auto_advance_story_phase(50, "acquaintance")
        assert result == "friend"

    def test_friend_to_lover_at_threshold(self):
        """好感度 >= 80，推进到恋人。"""
        result = _auto_advance_story_phase(80, "friend")
        assert result == "lover"

    def test_phase_never_downgrades(self):
        """即使好感度下降也不回退。"""
        result = _auto_advance_story_phase(10, "lover")
        assert result == "lover"  # 保持恋人，不回退

    def test_high_affection_jumps_directly(self):
        """高好感度直接跳到对应最高阶段。"""
        result = _auto_advance_story_phase(90, "stranger")
        assert result == "lover"  # 90 >= 80, 直接到恋人

    def test_unknown_current_phase_treated_as_stranger(self):
        """未知当前阶段视为陌生人。"""
        result = _auto_advance_story_phase(60, "unknown_phase")
        assert result in ("friend", "lover")  # 60 >= 50


# ============================================================
# 4. _sanitize_state_delta 测试
# ============================================================

class TestSanitizeStateDelta:
    """
    状态增量白名单校验：
      - 只保留 affection/event/story_phase/mood/custom 字段
      - custom 内部过滤黑名单键
      - 数值范围限制 / 字符串长度限制
    """

    def test_keeps_allowed_fields(self):
        delta = {"affection": 5, "mood": "happy", "event": "chat"}
        result = _sanitize_state_delta(delta)
        assert "affection" in result
        assert "mood" in result
        assert "event" in result

    def test_strips_disallowed_fields(self):
        delta = {"affection": 5, "hacked_field": "evil"}
        result = _sanitize_state_delta(delta)
        assert "hacked_field" not in result

    def test_empty_delta_returns_empty(self):
        assert _sanitize_state_delta({}) == {}

    def test_none_input_returns_empty(self):
        assert _sanitize_state_delta(None) == {}

    def test_story_phase_validated(self):
        delta = {"story_phase": "lover"}
        result = _sanitize_state_delta(delta)
        assert result.get("story_phase") == "lover"

    def test_invalid_story_phase_filtered_or_defaulted(self):
        delta = {"story_phase": "hacker_phase"}
        result = _sanitize_state_delta(delta)
        # 应该被过滤或替换为默认值
        assert result.get("story_phase") != "hacker_phase"

    def test_custom_dict_preserved_with_blacklist_filtering(self):
        delta = {"custom": {"valid_key": "data"}}
        result = _sanitize_state_delta(delta)
        assert "custom" in result
        assert "valid_key" in result.get("custom", {})

    def test_custom_blacklist_keys_removed(self):
        delta = {"custom": {"_triggered_events": ["hack"], "safe_key": "ok"}}
        result = _sanitize_state_delta(delta)
        assert "_triggered_events" not in result.get("custom", {})
        assert "safe_key" in result.get("custom", {})
