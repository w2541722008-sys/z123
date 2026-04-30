"""
services/character_state 模块单元测试

覆盖范围：
  - _calculate_affection_change: 好感度变化计算（三防机制 + 负向事件）
  - _update_anti_abuse_counters: 三防计数器更新
  - _auto_advance_story_phase: 阶段自动推进
  - _sanitize_state_delta: 状态增量白名单校验
"""

from unittest.mock import patch
from datetime import datetime, timedelta, timezone

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

    def test_negative_event_applies_phase_multiplier(self):
        """负向事件应用阶段系数（关系越好伤害越大）。"""
        rules = {"insult": -10}

        state_stranger = {"story_phase": "stranger"}
        ch, _ = _calculate_affection_change("insult", rules, state_stranger)
        assert ch < 0
        assert ch >= -10

        state_lover = {"story_phase": "lover"}
        ch2, _ = _calculate_affection_change("insult", rules, state_lover)
        assert ch2 < 0
        assert ch2 <= ch

    def test_negative_event_not_limited_by_daily_cap(self):
        """负向事件不受日上限限制。"""
        rules = {"bad_action": -5}
        state = {
            "story_phase": "friend",
            "_daily_affection_gained": 9999,
        }
        change, reason = _calculate_affection_change("bad_action", rules, state)
        assert change < 0

    def test_cooldown_blocks_positive_event(self):
        """冷却期内正向事件归零。"""
        rules = {"chat": 5}
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(seconds=30)).isoformat()

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
            "_daily_affection_gained": _DAILY_AFFECTION_CAP,
        }
        change, reason = _calculate_affection_change("chat", rules, state)
        assert change == 0
        assert "daily_cap" in reason

    def test_diminishing_returns_on_repeat(self):
        """同类事件多次触发时递减。"""
        rules = {"chat": 20}
        state = {
            "story_phase": "friend",
            "_daily_event_counts": {},
        }
        ch1, _ = _calculate_affection_change("chat", rules, state)

        state["_daily_event_counts"] = {"chat": 3}
        ch2, _ = _calculate_affection_change("chat", rules, state)
        assert ch2 <= ch1


# ============================================================
# 2. _update_anti_abuse_counters 测试
# ============================================================

class TestUpdateAntiAbuseCounters:
    """三防计数器更新。"""

    def test_updates_timestamp_for_event(self):
        state = {}
        updated = _update_anti_abuse_counters(state, "chat", 5)
        assert "_last_event_timestamps" in updated
        assert "chat" in updated["_last_event_timestamps"]
