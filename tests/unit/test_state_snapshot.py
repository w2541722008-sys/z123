"""state_snapshot 子函数单元测试。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from conftest import FakeRow, FakeSequenceConn


# ── _build_state_lines ─────────────────────────────────

class TestBuildStateLines:
    def test_intimate_card_type(self):
        from services.state_snapshot import _build_state_lines
        lines, instruction = _build_state_lines(
            "intimate", 50, "friend", "happy", {},
        )
        assert "好感度：50/100" in "\n".join(lines)
        assert "关系阶段" in "\n".join(lines)
        assert "当前心情" in "\n".join(lines)

    def test_scenario_card_type(self):
        from services.state_snapshot import _build_state_lines
        lines, instruction = _build_state_lines(
            "scenario", 70, "climax", "tense", {},
        )
        assert "剧情沉浸度：70/100" in "\n".join(lines)
        assert "剧情阶段" in "\n".join(lines)

    def test_returns_update_instruction(self):
        from services.state_snapshot import _build_state_lines
        from constants.prompt_templates import STATE_UPDATE_INSTRUCTION
        _, instruction = _build_state_lines(
            "intimate", 50, "friend", "happy", {},
        )
        assert instruction == STATE_UPDATE_INSTRUCTION

    def test_scenario_returns_scenario_instruction(self):
        from services.state_snapshot import _build_state_lines
        from constants.prompt_templates import SCENARIO_STATE_UPDATE_INSTRUCTION
        _, instruction = _build_state_lines(
            "scenario", 70, "climax", "tense", {},
        )
        assert instruction == SCENARIO_STATE_UPDATE_INSTRUCTION


# ── _append_time_context ───────────────────────────────

class TestAppendTimeContext:
    def test_adds_time_line(self):
        from services.state_snapshot import _append_time_context
        lines = []
        _append_time_context(lines)
        assert len(lines) == 1
        assert "当前时间" in lines[0]
        assert "不要主动提及时间" in lines[0]


# ── _append_custom_var_context ──────────────────────────

class TestAppendCustomVarContext:
    def test_adds_vars(self):
        from services.state_snapshot import _append_custom_var_context
        lines = []
        _append_custom_var_context(lines, {"location": "公园", "weather": "晴"})
        assert len(lines) == 2
        assert "location" in lines[0]
        assert "weather" in lines[1]

    def test_filters_internal_vars(self):
        from services.state_snapshot import _append_custom_var_context
        lines = []
        _append_custom_var_context(lines, {"_secret": "x", "visible": "y"})
        assert len(lines) == 1
        assert "visible" in lines[0]

    def test_max_five_vars(self):
        from services.state_snapshot import _append_custom_var_context
        lines = []
        _append_custom_var_context(lines, {
            "a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7,
        })
        assert len(lines) == 5

    def test_empty_vars(self):
        from services.state_snapshot import _append_custom_var_context
        lines = []
        _append_custom_var_context(lines, {})
        assert len(lines) == 0


# ── _append_pending_context ─────────────────────────────

class TestAppendPendingContext:
    def test_adds_pending_event(self):
        from services.state_snapshot import _append_pending_context
        lines = []
        _append_pending_context(lines, {
            "_pending_events": [
                {"title": "决战", "event_content": "敌人出现了"},
            ]
        })
        assert len(lines) == 1
        assert "决战" in lines[0]

    def test_max_two_pending_events(self):
        from services.state_snapshot import _append_pending_context
        lines = []
        _append_pending_context(lines, {
            "_pending_events": [
                {"title": "A", "event_content": "a"},
                {"title": "B", "event_content": "b"},
                {"title": "C", "event_content": "c"},
            ]
        })
        assert len(lines) == 2

    def test_adds_silence_reminder(self):
        from services.state_snapshot import _append_pending_context
        lines = []
        _append_pending_context(lines, {"_silent_rounds": 6})
        assert len(lines) == 1
        assert "已连续6轮" in lines[0]

    def test_no_silence_reminder_for_low_count(self):
        from services.state_snapshot import _append_pending_context
        lines = []
        _append_pending_context(lines, {"_silent_rounds": 2})
        assert len(lines) == 0

    def test_no_pending_events_empty_context(self):
        from services.state_snapshot import _append_pending_context
        lines = []
        _append_pending_context(lines, {})
        assert len(lines) == 0


# ── _finalize_state_snapshot ────────────────────────────

class TestFinalizeStateSnapshot:
    def test_no_truncation_needed(self):
        from services.state_snapshot import _finalize_state_snapshot
        budget = MagicMock()
        budget.wi_max_chars.return_value = 99999
        lines = ["line1", "line2", "line3"]
        instruction = ["【更新指引】"]
        result = _finalize_state_snapshot(lines, instruction, budget)
        assert "line1" in result
        assert "【更新指引】" in result

    def test_truncation_when_too_long(self):
        from services.state_snapshot import _finalize_state_snapshot
        budget = MagicMock()
        budget.wi_max_chars.return_value = 100  # _state_max = max(1000, 15) = 1000
        # 生成超过 1000 字符的行
        lines = ["X" * 200] * 8  # 1600 chars before instruction
        instruction = ["【更新指引】"]
        result = _finalize_state_snapshot(lines, instruction, budget)
        assert "已省略" in result
        assert "【更新指引】" in result

    def test_extends_with_instruction(self):
        from services.state_snapshot import _finalize_state_snapshot
        budget = MagicMock()
        budget.wi_max_chars.return_value = 99999
        lines = ["line1"]
        instruction = ["指引行1", "指引行2"]
        result = _finalize_state_snapshot(lines, instruction, budget)
        assert "指引行2" in result


# ── _inject_affection_anchor ────────────────────────────

class TestInjectAffectionAnchor:
    def test_empty_moments_does_nothing(self):
        from services.state_snapshot import _inject_affection_anchor
        bundle = {"world_info_after": ""}
        _inject_affection_anchor(bundle, [], None, "intimate")
        assert bundle["world_info_after"] == ""

    def test_adds_anchor_with_moments(self):
        from services.state_snapshot import _inject_affection_anchor
        bundle = {"world_info_after": ""}
        _inject_affection_anchor(bundle, ["一起看日落", "雨中漫步"], None, "intimate")
        assert "共同回忆" in bundle["world_info_after"]

    def test_adds_proactive_after_24h(self):
        from services.state_snapshot import _inject_affection_anchor
        bundle = {"world_info_after": ""}
        # 使用带时区的 ISO 格式字符串，确保与 datetime.now(timezone.utc) 兼容
        old_time = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        _inject_affection_anchor(bundle, ["一起看日落"], old_time, "intimate")
        assert "很久没和用户聊天" in bundle["world_info_after"] or "剧情回响" in bundle["world_info_after"]

    def test_scenario_card_type_anchor(self):
        from services.state_snapshot import _inject_affection_anchor
        bundle = {"world_info_after": ""}
        _inject_affection_anchor(bundle, ["冒险回忆"], None, "scenario")
        assert "共同回忆" in bundle["world_info_after"]

    def test_prepends_to_existing_content(self):
        from services.state_snapshot import _inject_affection_anchor
        bundle = {"world_info_after": "已有的内容"}
        _inject_affection_anchor(bundle, ["回忆"], None, "intimate")
        assert "已有的内容" in bundle["world_info_after"]
        assert bundle["world_info_after"].index("共同回忆") < bundle["world_info_after"].index("已有的内容")
