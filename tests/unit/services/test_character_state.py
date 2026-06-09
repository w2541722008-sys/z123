"""character_state 纯函数单元测试。

覆盖：好感度计算（三防）、阶段自动推进、增量清理等核心逻辑。
"""

from datetime import datetime, timezone
from unittest.mock import patch

from services.character_state import (
    _calculate_affection_change,
    _auto_advance_story_phase,
    _sanitize_state_delta,
    _reset_daily_fields_if_needed,
    _update_anti_abuse_counters,
    _AFFECTION_BASE_RULES,
    _DAILY_AFFECTION_CAP_DEFAULT,
    _AFFECTION_DELTA_MAX,
    tick_passive_character_state,
    get_public_character_state,
)


# ============================================================
# _calculate_affection_change
# ============================================================
class TestCalculateAffectionChange:
    def _default_rules(self):
        return dict(_AFFECTION_BASE_RULES)

    def _default_state(self, **overrides):
        defaults = {
            "story_phase": "stranger",
            "_daily_event_counts": {},
            "_daily_affection_gained": 0,
            "_last_event_timestamps": {},
        }
        defaults.update(overrides)
        return defaults

    def test_positive_event_first_time(self):
        rules = self._default_rules()
        state = self._default_state()
        change, reason = _calculate_affection_change("deep_conversation", rules, state)
        assert change > 0
        assert "deep_conversation" in reason

    def test_unknown_event_zero_change(self):
        rules = self._default_rules()
        state = self._default_state()
        change, reason = _calculate_affection_change("nonexistent_event", rules, state)
        assert change == 0

    def test_negative_event_applies_phase_multiplier(self):
        rules = self._default_rules()
        # Stranger phase: multiplier 0.8
        state = self._default_state(story_phase="stranger")
        change, _ = _calculate_affection_change("argument", rules, state)
        base = rules["argument"]  # -5
        assert change == int(base * 0.8)  # -4

    def test_negative_event_lover_phase_higher(self):
        rules = self._default_rules()
        state = self._default_state(story_phase="lover")
        change, _ = _calculate_affection_change("argument", rules, state)
        base = rules["argument"]  # -5
        assert change == int(base * 1.0)  # -5

    def test_cooldown_blocks_positive(self):
        rules = self._default_rules()
        # Set last event timestamp to recent time
        recent = datetime.now(timezone.utc).isoformat()
        state = self._default_state(_last_event_timestamps={"gift": recent})
        change, reason = _calculate_affection_change("gift", rules, state)
        assert change == 0
        assert "cooldown" in reason

    def test_daily_cap_blocks_positive(self):
        rules = self._default_rules()
        state = self._default_state(
            _daily_affection_gained=_DAILY_AFFECTION_CAP_DEFAULT
        )
        change, reason = _calculate_affection_change("deep_conversation", rules, state)
        assert change == 0
        assert "daily_cap" in reason

    def test_daily_cap_zero_means_no_limit(self):
        """daily_cap=0 时不限制每日好感涨幅（适合剧情沙盒）。"""
        rules = self._default_rules()
        state = self._default_state(
            _daily_affection_gained=999,  # 已经涨了很多
        )
        # daily_cap=0 → 不限制，应该能正常加分
        change, reason = _calculate_affection_change(
            "deep_conversation", rules, state, daily_cap=0
        )
        assert change > 0
        # reason 中可能包含 daily_cap=0 作为调试信息，但不应包含 "daily_cap:" 拦截提示
        assert "daily_cap:" not in reason

    def test_daily_cap_custom_value(self):
        """角色卡自定义 daily_cap 生效。"""
        rules = self._default_rules()
        state = self._default_state(
            _daily_affection_gained=50,  # 已涨50
        )
        # daily_cap=100 → 还没到上限，应该能加分
        change, reason = _calculate_affection_change(
            "deep_conversation", rules, state, daily_cap=100
        )
        assert change > 0

        # daily_cap=50 → 刚好到上限，不应该加分
        change2, reason2 = _calculate_affection_change(
            "deep_conversation", rules, state, daily_cap=50
        )
        assert change2 == 0
        assert "daily_cap" in reason2

    def test_diminishing_returns(self):
        rules = self._default_rules()
        # 4th trigger: diminish rate = 0.0
        state = self._default_state(_daily_event_counts={"light_chat": 3})
        change, reason = _calculate_affection_change("light_chat", rules, state)
        assert change == 0

    def test_phase_multiplier_applied(self):
        rules = self._default_rules()
        state = self._default_state(story_phase="friend")
        change, _ = _calculate_affection_change("deep_conversation", rules, state)
        base = rules["deep_conversation"]  # 4
        # friend multiplier = 0.7, first time diminish = 1.0
        expected = int(round(base * 1.0 * 0.7))
        assert change == expected

    def test_change_capped_at_base(self):
        rules = self._default_rules()
        state = self._default_state(story_phase="stranger")
        change, _ = _calculate_affection_change("deep_conversation", rules, state)
        assert change <= rules["deep_conversation"]

    def test_negative_capped_at_max(self):
        rules = self._default_rules()
        state = self._default_state(story_phase="lover")
        change, _ = _calculate_affection_change("betray", rules, state)
        assert change >= -_AFFECTION_DELTA_MAX


# ============================================================
# get_public_character_state
# ============================================================
class TestPublicCharacterState:
    def test_serializes_show_bar_events_and_storyline_name(self):
        raw_state = {
            "affection": 12,
            "story_phase": "acquaintance",
            "mood": "warm",
            "custom_vars": {},
            "storyline_id": "7",
            "_triggered_events": [{"id": 1, "title": "初遇"}],
            "_daily_affection_gained": 3,
        }

        with patch(
            "services.character_state.get_character_state", return_value=raw_state
        ), patch(
            "services.character_state.char_repo.get_affection_config",
            return_value={"affection_rules_json": {"show_bar": False}},
        ), patch(
            "services.character_state.story_repo.get_storyline_name",
            return_value="主线",
        ):
            result = get_public_character_state(
                object(),
                user_id=1,
                character_id="c1",
            )

        assert result["affection"] == 12
        assert result["show_bar"] is False
        assert result["triggered_events"] == [{"id": 1, "title": "初遇"}]
        assert result["storyline_name"] == "主线"
        assert "_daily_affection_gained" not in result

    def test_show_bar_defaults_to_true_when_not_configured(self):
        raw_state = {
            "affection": 0,
            "story_phase": "stranger",
            "mood": "neutral",
            "custom_vars": {},
            "storyline_id": None,
        }

        with patch(
            "services.character_state.get_character_state", return_value=raw_state
        ), patch(
            "services.character_state.char_repo.get_affection_config",
            return_value={"affection_rules_json": {}},
        ):
            result = get_public_character_state(
                object(),
                user_id=1,
                character_id="c1",
            )

        assert result["show_bar"] is True


# ============================================================
# tick_passive_character_state
# ============================================================
class TestPassiveCharacterStateTick:
    def test_increments_silent_rounds_without_touching_affection_or_phase(self):
        raw_state = {
            "affection": 42,
            "story_phase": "friend",
            "mood": "warm",
            "custom_vars": {"topic": "tea", "_silent_rounds": 2},
            "storyline_id": None,
            "_daily_event_counts": {},
            "_daily_affection_gained": 0,
            "_last_event_timestamps": {},
            "_daily_reset_date": "2026-06-09",
        }
        persisted = {}

        with patch(
            "services.character_state.get_character_state", return_value=raw_state
        ), patch(
            "services.character_state.upsert_character_state",
            side_effect=lambda conn, snapshot, commit: persisted.update(snapshot.to_dict()),
        ), patch(
            "services.character_state.char_repo.get_affection_config",
            return_value={"affection_rules_json": {}},
        ):
            result = tick_passive_character_state(
                object(), user_id=1, character_id="c1"
            )

        assert persisted["affection"] == 42
        assert persisted["story_phase"] == "friend"
        assert result["mood"] == "warm"
        assert persisted["custom_vars"]["_silent_rounds"] == 3
        assert result["custom_vars"]["topic"] == "tea"

    def test_restores_decayable_mood_after_configured_quiet_rounds(self):
        raw_state = {
            "affection": 10,
            "story_phase": "stranger",
            "mood": "sad",
            "custom_vars": {"_mood_streak": 3, "_silent_rounds": 3},
            "storyline_id": None,
            "_daily_event_counts": {},
            "_daily_affection_gained": 0,
            "_last_event_timestamps": {},
            "_daily_reset_date": "2026-06-09",
        }
        persisted = {}

        with patch(
            "services.character_state.get_character_state", return_value=raw_state
        ), patch(
            "services.character_state.upsert_character_state",
            side_effect=lambda conn, snapshot, commit: persisted.update(snapshot.to_dict()),
        ), patch(
            "services.character_state.char_repo.get_affection_config",
            return_value={"affection_rules_json": {}},
        ):
            result = tick_passive_character_state(
                object(), user_id=1, character_id="c1"
            )

        assert result["mood"] == "neutral"
        assert persisted["custom_vars"]["_mood_streak"] == 0
        assert persisted["custom_vars"]["_silent_rounds"] == 4


# ============================================================
# _auto_advance_story_phase
# ============================================================
class TestAutoAdvanceStoryPhase:
    def test_stranger_below_20_stays(self):
        assert _auto_advance_story_phase(19, "stranger") == "stranger"

    def test_stranger_at_20_advances(self):
        assert _auto_advance_story_phase(20, "stranger") == "acquaintance"

    def test_acquaintance_at_50_advances(self):
        assert _auto_advance_story_phase(50, "acquaintance") == "friend"

    def test_friend_at_80_advances(self):
        assert _auto_advance_story_phase(80, "friend") == "lover"

    def test_phase_never_goes_back(self):
        """Phase only advances, never goes back even with low affection."""
        assert _auto_advance_story_phase(10, "friend") == "friend"

    def test_high_affection_advances_to_highest(self):
        assert _auto_advance_story_phase(99, "stranger") == "lover"

    def test_unknown_phase_stays_at_index_0(self):
        result = _auto_advance_story_phase(50, "unknown_phase")
        # Unknown phase defaults to index 0 (stranger), then advances based on affection
        assert result in ("acquaintance", "friend", "lover", "stranger")


# ============================================================
# _sanitize_state_delta
# ============================================================
class TestSanitizeStateDelta:
    def test_non_dict_returns_empty(self):
        assert _sanitize_state_delta("string") == {}
        assert _sanitize_state_delta(42) == {}
        assert _sanitize_state_delta(None) == {}

    def test_allowed_field_event(self):
        result = _sanitize_state_delta({"event": "Deep_Conversation"})
        assert result["event"] == "deep_conversation"

    def test_allowed_field_mood(self):
        result = _sanitize_state_delta({"mood": "Warm"})
        assert result["mood"] == "warm"

    def test_allowed_field_story_phase(self):
        result = _sanitize_state_delta({"story_phase": "Friend"})
        assert result["story_phase"] == "friend"

    def test_invalid_mood_filtered(self):
        result = _sanitize_state_delta({"mood": "invalid_mood"})
        assert "mood" not in result

    def test_invalid_story_phase_filtered(self):
        result = _sanitize_state_delta({"story_phase": "invalid_phase"})
        assert "story_phase" not in result

    def test_affection_numeric(self):
        result = _sanitize_state_delta({"affection": 5})
        assert result["affection"] == 5

    def test_affection_string(self):
        result = _sanitize_state_delta({"affection": "+3"})
        assert result["affection"] == "+3"

    def test_invalid_affection_strings_filtered(self):
        assert "affection" not in _sanitize_state_delta({"affection": "+开心"})
        assert "affection" not in _sanitize_state_delta({"affection": "+3分"})

    def test_affection_capped(self):
        result = _sanitize_state_delta({"affection": 999})
        assert result["affection"] == _AFFECTION_DELTA_MAX

    def test_custom_dict(self):
        result = _sanitize_state_delta({"custom": {"key1": "value1", "key2": 42}})
        assert result["custom"]["key1"] == "value1"
        assert result["custom"]["key2"] == 42

    def test_custom_blacklist_filtered(self):
        result = _sanitize_state_delta({"custom": {"_daily_event_counts": "hacked"}})
        assert "_daily_event_counts" not in result.get("custom", {})

    def test_unknown_fields_filtered(self):
        result = _sanitize_state_delta(
            {"unknown_field": "value", "event": "light_chat"}
        )
        assert "unknown_field" not in result
        assert result["event"] == "light_chat"

    def test_event_length_limited(self):
        result = _sanitize_state_delta({"event": "a" * 100})
        assert len(result["event"]) <= 50


# ============================================================
# _reset_daily_fields_if_needed
# ============================================================
class TestResetDailyFieldsIfNeeded:
    def test_same_day_no_reset(self):
        from services.character_state import _get_today_date
        from core.character_state_snapshot import CharacterStateSnapshot

        today = _get_today_date()
        snapshot = CharacterStateSnapshot(
            user_id=1,
            character_id="c1",
            daily_reset_date=today,
            daily_event_counts={"light_chat": 3},
            daily_affection_gained=10,
        )
        result = _reset_daily_fields_if_needed(snapshot)
        assert result.daily_event_counts == {"light_chat": 3}
        assert result.daily_affection_gained == 10

    def test_different_day_resets(self):
        from core.character_state_snapshot import CharacterStateSnapshot

        snapshot = CharacterStateSnapshot(
            user_id=1,
            character_id="c1",
            daily_reset_date="2020-01-01",
            daily_event_counts={"light_chat": 5},
            daily_affection_gained=15,
        )
        result = _reset_daily_fields_if_needed(snapshot)
        assert result.daily_event_counts == {}
        assert result.daily_affection_gained == 0
        assert result.daily_reset_date != "2020-01-01"

    def test_guest_dict_internal_daily_fields_reset(self):
        snapshot = {
            "_daily_reset_date": "2020-01-01",
            "_daily_event_counts": {"compliment": 2},
            "_daily_affection_gained": 8,
        }

        result = _reset_daily_fields_if_needed(snapshot)

        assert result["_daily_event_counts"] == {}
        assert result["_daily_affection_gained"] == 0
        assert result["_daily_reset_date"] != "2020-01-01"


# ============================================================
# _update_anti_abuse_counters
# ============================================================
class TestUpdateAntiAbuseCounters:
    def test_positive_change_increments(self):
        state = {
            "_last_event_timestamps": {},
            "_daily_event_counts": {},
            "_daily_affection_gained": 0,
        }
        result = _update_anti_abuse_counters(state, "light_chat", 2)
        assert result["_daily_event_counts"]["light_chat"] == 1
        assert result["_daily_affection_gained"] == 2
        assert "light_chat" in result["_last_event_timestamps"]

    def test_negative_change_no_increment(self):
        state = {
            "_last_event_timestamps": {},
            "_daily_event_counts": {},
            "_daily_affection_gained": 0,
        }
        result = _update_anti_abuse_counters(state, "argument", -3)
        assert "argument" not in result["_daily_event_counts"]
        assert result["_daily_affection_gained"] == 0
