"""character_insights_service 单元测试 — 配置摘要、警告计算、关键词匹配。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── _split_csv_ids ──────────────────────────────────────

class TestSplitCsvIds:
    def test_normal_csv(self):
        from services.character_insights_service import _split_csv_ids
        assert _split_csv_ids("a, b, c") == ["a", "b", "c"]

    def test_empty_string(self):
        from services.character_insights_service import _split_csv_ids
        assert _split_csv_ids("") == []

    def test_none_input(self):
        from services.character_insights_service import _split_csv_ids
        assert _split_csv_ids(None) == []

    def test_whitespace_only(self):
        from services.character_insights_service import _split_csv_ids
        assert _split_csv_ids("  ,  ,  ") == []

    def test_single_value(self):
        from services.character_insights_service import _split_csv_ids
        assert _split_csv_ids("42") == ["42"]


# ── _affection_rules_use_default ────────────────────────

class TestAffectionRulesUseDefault:
    def test_empty_dict_is_default(self):
        from services.character_insights_service import _affection_rules_use_default
        assert _affection_rules_use_default({}) is True

    def test_non_empty_dict_not_default(self):
        from services.character_insights_service import _affection_rules_use_default
        assert _affection_rules_use_default({"base": 1}) is False

    def test_empty_string_is_default(self):
        from services.character_insights_service import _affection_rules_use_default
        assert _affection_rules_use_default("") is True

    def test_none_is_default(self):
        from services.character_insights_service import _affection_rules_use_default
        assert _affection_rules_use_default(None) is True

    def test_valid_json_dict_empty_is_default(self):
        from services.character_insights_service import _affection_rules_use_default
        assert _affection_rules_use_default("{}") is True

    def test_valid_json_dict_non_empty_not_default(self):
        from services.character_insights_service import _affection_rules_use_default
        assert _affection_rules_use_default('{"base": 1}') is False

    def test_invalid_json_not_default(self):
        """损坏的 JSON 不算空规则，应触发警告。"""
        from services.character_insights_service import _affection_rules_use_default
        assert _affection_rules_use_default("{bad") is False


# ── compute_config_warnings ─────────────────────────────

def _make_char(**overrides):
    base = {
        "name": "测试角色",
        "system_prompt": "你是一个助手",
        "opening_message": "你好",
        "subtitle": "副标题",
        "is_visible": True,
        "affection_enabled": False,
        "affection_rules_json": None,
    }
    base.update(overrides)
    return base


def _make_layers(**overrides):
    base = {"base_profile": "基础设定", "examples": "示例对话内容"}
    base.update(overrides)
    return base


class TestComputeConfigWarnings:
    def test_full_config_no_warnings(self):
        from services.character_insights_service import compute_config_warnings
        assert compute_config_warnings(_make_char(), _make_layers()) == []

    def test_empty_name(self):
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(_make_char(name=""), _make_layers())
        assert any("角色名为空" in x for x in w)

    def test_empty_system_prompt(self):
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(_make_char(system_prompt=""), _make_layers())
        assert any("system_prompt" in x for x in w)

    def test_empty_opening_message(self):
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(_make_char(opening_message=""), _make_layers())
        assert any("开场白为空" in x for x in w)

    def test_empty_base_profile(self):
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(_make_char(), _make_layers(base_profile=""))
        assert any("base_profile" in x for x in w)

    def test_empty_examples(self):
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(_make_char(), _make_layers(examples=""))
        assert any("examples" in x for x in w)

    def test_visible_no_subtitle(self):
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(
            _make_char(is_visible=True, subtitle=""), _make_layers(),
        )
        assert any("副标题为空" in x for x in w)

    def test_not_visible_no_subtitle_warning(self):
        """不可见时副标题空不警告。"""
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(
            _make_char(is_visible=False, subtitle=""), _make_layers(),
        )
        assert not any("副标题为空" in x for x in w)

    def test_affection_enabled_bad_json_warns(self):
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(
            _make_char(affection_enabled=True, affection_rules_json="{bad"),
            _make_layers(),
        )
        assert any("好感度规则" in x for x in w)

    def test_affection_enabled_empty_rules_no_warning(self):
        """空规则使用默认值，不警告。"""
        from services.character_insights_service import compute_config_warnings
        w = compute_config_warnings(
            _make_char(affection_enabled=True, affection_rules_json={}),
            _make_layers(),
        )
        assert not any("好感度规则" in x for x in w)


class TestStoryEventHealthStats:
    def test_counts_empty_enable_targets_and_empty_event_content(self):
        from services.character_insights_service import compute_story_event_health_stats

        stats = compute_story_event_health_stats([
            {
                "unlocked_memory_ids": "",
                "unlocked_greeting_ids": "",
                "unlocked_storyline_id": None,
                "event_content": "",
            },
            {
                "unlocked_memory_ids": "1",
                "unlocked_greeting_ids": "",
                "unlocked_storyline_id": None,
                "event_content": "推进剧情",
            },
        ])

        assert stats == {
            "empty_enable_events": 1,
            "empty_unlock_events": 1,
            "empty_event_content_events": 1,
        }


# ── compute_completeness_score ──────────────────────────

class TestComputeCompletenessScore:
    def test_perfect_score(self):
        from services.character_insights_service import compute_completeness_score
        row = {"name": "x", "system_prompt": "x", "opening_message": "x",
               "affection_enabled": False, "affection_rules_json": None}
        layers = {"base_profile": "x", "examples": "x"}
        score = compute_completeness_score(
            row, layers,
            stats={"memory_active": 3, "storyline_count": 1, "story_event_count": 0},
            active_greetings=2, greeting_phase_coverage=3,
            default_storyline_id=1, empty_unlock_event_count=0,
        )
        assert score == 100

    def test_empty_config_still_has_baseline_score(self):
        """完全空白的角色也能获得基础分（情感系统未启用、无剧情线/事件等豁免项）。"""
        from services.character_insights_service import compute_completeness_score
        row = {"name": "", "system_prompt": "", "opening_message": "",
               "affection_enabled": False, "affection_rules_json": None}
        layers = {"base_profile": "", "examples": ""}
        score = compute_completeness_score(
            row, layers,
            stats={"memory_active": 0, "storyline_count": 0, "story_event_count": 0},
            active_greetings=0, greeting_phase_coverage=0,
            default_storyline_id=None, empty_unlock_event_count=0,
        )
        # 3/11 项自动通过：情感未启用、无剧情线（跳过默认线检查）、无事件（跳过解锁检查）
        assert score == 27

    def test_partial_config_roughly_half(self):
        from services.character_insights_service import compute_completeness_score
        row = {"name": "x", "system_prompt": "", "opening_message": "",
               "affection_enabled": False, "affection_rules_json": None}
        layers = {"base_profile": "x", "examples": "x"}
        score = compute_completeness_score(
            row, layers,
            stats={"memory_active": 0, "storyline_count": 0, "story_event_count": 0},
            active_greetings=0, greeting_phase_coverage=0,
            default_storyline_id=None, empty_unlock_event_count=0,
        )
        assert 0 < score < 100


# ── test_character_keywords ─────────────────────────────

class TestCharacterKeywords:
    def test_keyword_match_any(self):
        from services.character_insights_service import test_character_keywords
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"id": 1, "keywords": "hello, world", "content": "记忆1",
             "trigger_logic": "any"},
        ]
        results = test_character_keywords(conn, "char1", "hello there")
        assert len(results) == 1
        assert results[0]["matched_keywords"] == ["hello"]

    def test_keyword_match_all(self):
        from services.character_insights_service import test_character_keywords
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"id": 2, "keywords": "hello, world", "content": "记忆2",
             "trigger_logic": "all"},
        ]
        results = test_character_keywords(conn, "char1", "hello world")
        assert len(results) == 1
        assert results[0]["matched_keywords"] == ["hello", "world"]

    def test_keyword_match_all_fails_partial(self):
        from services.character_insights_service import test_character_keywords
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"id": 3, "keywords": "hello, world", "content": "记忆3",
             "trigger_logic": "all"},
        ]
        results = test_character_keywords(conn, "char1", "only hello here")
        assert len(results) == 0

    def test_empty_keywords_skipped(self):
        from services.character_insights_service import test_character_keywords
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"id": 4, "keywords": "", "content": "空关键词",
             "trigger_logic": "any"},
        ]
        results = test_character_keywords(conn, "char1", "test")
        assert len(results) == 0

    def test_case_insensitive(self):
        from services.character_insights_service import test_character_keywords
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {"id": 5, "keywords": "Hello", "content": "大小写",
             "trigger_logic": "any"},
        ]
        results = test_character_keywords(conn, "char1", "HELLO")
        assert len(results) == 1
