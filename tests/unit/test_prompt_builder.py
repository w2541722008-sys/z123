"""prompt_builder 纯函数单元测试。

覆盖文本截断、System Prompt 组装、行为倾向、模式 Section、World Info 等核心工具函数。
"""

import pytest

from services.prompt_builder import (
    _clip,
    _build_single_system_prompt,
    _related_assets_text,
    _alternate_samples_text,
    _get_behavior_tendency,
    _split_last_user_message,
    _world_info_layer_pairs,
    _append_runtime_text_layers,
    _append_world_info_after,
    _mode_sections,
    _append_post_history_then_user,
    _append_runtime_tail,
)


# ============================================================
# _clip — 文本截断
# ============================================================
class TestClip:
    def test_short_text_unchanged(self):
        assert _clip("hello", max_chars=100) == "hello"

    def test_long_text_truncated_with_marker(self):
        text = "A" * 200
        result = _clip(text, max_chars=50)
        assert len(result) <= 80
        assert "截断" in result

    def test_unicode_multibyte_preserved(self):
        text = "你好世界" * 30
        result = _clip(text, max_chars=20)
        assert "你好" in result
        assert "截断" in result

    def test_emoji_preserved_not_split(self):
        text = "🎉🎉🎉🎉🎉🎉🎉🎉🎉🎉" * 10
        result = _clip(text, max_chars=20)
        assert "🎉" in result
        assert "截断" in result

    def test_empty_string_unchanged(self):
        assert _clip("", max_chars=100) == ""

    def test_exactly_at_limit_unchanged(self):
        text = "ABCDE"
        assert _clip(text, max_chars=5) == "ABCDE"

    def test_one_over_limit_truncated(self):
        text = "ABCDEF"
        result = _clip(text, max_chars=5)
        assert "截断" in result

    def test_whitespace_only_stripped(self):
        assert _clip("   ", max_chars=100) == ""


# ============================================================
# _build_single_system_prompt — System Prompt 组装
# ============================================================
class TestBuildSingleSystemPrompt:
    def test_primary_only(self):
        result = _build_single_system_prompt("main prompt", [])
        assert result == "main prompt"

    def test_with_single_layer(self):
        result = _build_single_system_prompt("main", [("Title", "content")])
        assert "main" in result
        assert "Title" in result
        assert "content" in result

    def test_with_multiple_layers_ordered(self):
        layers = [("A", "a"), ("B", "b")]
        result = _build_single_system_prompt("main", layers)
        a_pos = result.index("a")
        b_pos = result.index("b")
        assert a_pos < b_pos

    def test_layer_with_empty_content_skipped(self):
        layers = [("Title", "")]
        result = _build_single_system_prompt("main", layers)
        assert "Title" not in result

    def test_layer_title_only_with_empty_content_skipped(self):
        layers = [("Title", "  ")]
        result = _build_single_system_prompt("main", layers)
        assert "Title" not in result

    def test_total_exceeds_budget_truncated_from_end(self):
        primary = "p" * 50000
        result = _build_single_system_prompt(primary, [], total_max=100)
        assert "截断" in result

    def test_empty_primary_layers_still_included(self):
        layers = [("Title", "content")]
        result = _build_single_system_prompt("", layers)
        assert "Title" in result
        assert "content" in result

    def test_custom_token_budget_applies(self):
        from services.token_budget import TokenBudget
        budget = TokenBudget(context_tokens=4096, output_reserve=512)
        result = _build_single_system_prompt("main prompt", [], budget=budget)
        assert "main prompt" in result

    def test_layer_without_title(self):
        layers = [("", "just content")]
        result = _build_single_system_prompt("main", layers)
        assert "just content" in result


# ============================================================
# _related_assets_text — 关联资产文本
# ============================================================
class TestRelatedAssetsText:
    def test_no_assets_returns_empty(self):
        assert _related_assets_text({}) == ""

    def test_empty_list_returns_empty(self):
        assert _related_assets_text({"related_assets": []}) == ""

    def test_assets_with_names_included(self):
        bundle = {"related_assets": [
            {"asset_type": "scenario", "name": "Quest"},
            {"asset_type": "character", "name": "Alice"},
        ]}
        result = _related_assets_text(bundle)
        assert "Quest" in result
        assert "Alice" in result

    def test_asset_without_name_skipped(self):
        bundle = {"related_assets": [
            {"asset_type": "scenario"},
            {"asset_type": "character", "name": "Alice"},
        ]}
        result = _related_assets_text(bundle)
        assert "scenario" not in result  # 无 name 的项不应出现
        assert "Alice" in result


# ============================================================
# _alternate_samples_text — 备选开场白样本
# ============================================================
class TestAlternateSamplesText:
    def test_empty_list_returns_empty(self):
        assert _alternate_samples_text([]) == ""

    def test_none_returns_empty(self):
        assert _alternate_samples_text(None) == ""

    def test_non_list_returns_empty(self):
        assert _alternate_samples_text("not a list") == ""

    def test_samples_included(self):
        result = _alternate_samples_text(["hello", "world"])
        assert "hello" in result
        assert "world" in result

    def test_max_two_samples(self):
        result = _alternate_samples_text(["a", "b", "c"])
        assert "c" not in result


# ============================================================
# _get_behavior_tendency — 行为倾向提取
# ============================================================
class TestGetBehaviorTendency:
    def test_explicit_phase_behavior_returned(self):
        behaviors = {"stranger": "保持距离，不主动"}
        result = _get_behavior_tendency("stranger", "neutral", phase_behaviors=behaviors)
        assert result == "保持距离，不主动"

    def test_none_phase_behavior_falls_back_to_default(self):
        result = _get_behavior_tendency("stranger", "neutral", phase_behaviors=None)
        assert len(result) > 10

    def test_empty_dict_falls_back(self):
        result = _get_behavior_tendency("stranger", "neutral", phase_behaviors={})
        assert len(result) > 10

    def test_scenario_card_type_returns_scenario_tendency(self):
        result = _get_behavior_tendency("stranger", "neutral", card_type="scenario")
        assert "世界充满未知" in result or "氛围" in result

    def test_intimate_card_type_returns_companion_tendency(self):
        result = _get_behavior_tendency("stranger", "neutral", card_type="intimate")
        assert "刚认识" in result or "不越界" in result

    def test_cold_mood_includes_modifier(self):
        result = _get_behavior_tendency("stranger", "cold", card_type="intimate")
        assert "冷" in result

    def test_happy_mood_includes_modifier(self):
        result = _get_behavior_tendency("friend", "happy", card_type="intimate")
        assert "轻松" in result or "心情很好" in result or "主动" in result

    def test_unknown_phase_returns_empty_modifier_only(self):
        result = _get_behavior_tendency("nonexistent", "happy", card_type="intimate")
        assert isinstance(result, str)


# ============================================================
# _split_last_user_message — 分离最后一条用户消息
# ============================================================
class TestSplitLastUserMessage:
    def test_last_is_user_splits(self):
        msgs = [
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "hello"},
        ]
        history, last = _split_last_user_message(msgs)
        assert len(history) == 1
        assert last == {"role": "user", "content": "hello"}

    def test_last_is_not_user_no_split(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        history, last = _split_last_user_message(msgs)
        assert len(history) == 2
        assert last is None

    def test_empty_list(self):
        history, last = _split_last_user_message([])
        assert history == []
        assert last is None

    def test_does_not_mutate_original(self):
        msgs = [{"role": "user", "content": "hello"}]
        _split_last_user_message(msgs)
        assert len(msgs) == 1


# ============================================================
# _world_info_layer_pairs — 世界信息层对
# ============================================================
class TestWorldInfoLayerPairs:
    def test_both_before_and_after(self):
        pairs, before, after = _world_info_layer_pairs({
            "world_info_before": "前置世界信息",
            "world_info_after": "后置世界信息",
        })
        assert before == "前置世界信息"
        assert after == "后置世界信息"
        assert len(pairs) == 1
        assert pairs[0] == ("【世界信息-前置】", "前置世界信息")

    def test_only_before(self):
        pairs, before, after = _world_info_layer_pairs({
            "world_info_before": "只有前置",
        })
        assert before == "只有前置"
        assert after == ""

    def test_empty_bundle(self):
        pairs, before, after = _world_info_layer_pairs({})
        assert before == ""
        assert after == ""
        assert pairs == []


# ============================================================
# _append_runtime_text_layers — 运行时文本层拼接
# ============================================================
class TestAppendRuntimeTextLayers:
    def test_appends_titled_sections(self):
        pairs = [("A", "a")]
        sections = [("B", "b")]
        result = _append_runtime_text_layers(pairs, sections)
        assert len(result) == 2
        assert ("B", "b") in result

    def test_title_only_no_content(self):
        pairs = []
        sections = [("Title Only", "")]
        result = _append_runtime_text_layers(pairs, sections)
        assert ("", "Title Only") in result

    def test_both_empty_skipped(self):
        pairs = []
        sections = [("", "")]
        result = _append_runtime_text_layers(pairs, sections)
        assert len(result) == 0


# ============================================================
# _append_world_info_after — 后置世界信息
# ============================================================
class TestAppendWorldInfoAfter:
    def test_with_content_appends(self):
        pairs = [("A", "a")]
        result = _append_world_info_after(pairs, "后置世界信息")
        assert len(result) == 2
        assert result[-1] == ("【世界信息-后置】", "后置世界信息")

    def test_empty_content_no_change(self):
        pairs = [("A", "a")]
        result = _append_world_info_after(pairs, "")
        assert len(result) == 1


# ============================================================
# _mode_sections — 三种卡模式 Section 生成
# ============================================================
class TestModeSections:
    def _bundle(self, **overrides):
        defaults = {
            "base_profile": "角色底稿内容",
            "personality": "温柔善良",
            "scenario": "咖啡馆",
            "world_rules": "不能离开城市",
            "examples": "示例对话",
            "alternate_greetings": [],
            "related_assets": [],
        }
        defaults.update(overrides)
        return defaults

    def test_character_mode_includes_relationship_section(self):
        sections = _mode_sections(self._bundle(), {}, "character")
        titles = [s[0] for s in sections]
        assert "【角色底稿】" in titles
        assert "【性格与表达风格】" in titles
        assert "【当前关系与场景】" in titles
        assert "【世界规则/补充设定】" in titles

    def test_scenario_mode_includes_plot_section(self):
        sections = _mode_sections(self._bundle(), {}, "scenario")
        titles = [s[0] for s in sections]
        assert "【剧情入口/背景】" in titles
        assert "【角色身份与立场】" in titles
        assert "【当前剧情场景】" in titles

    def test_hybrid_mode_includes_both(self):
        sections = _mode_sections(self._bundle(), {}, "hybrid")
        titles = [s[0] for s in sections]
        assert "【角色底稿】" in titles
        assert "【当前关系与剧情场景】" in titles

    def test_character_mode_with_alternate_greetings(self):
        bundle = self._bundle(alternate_greetings=["备选开场白"])
        sections = _mode_sections(bundle, {}, "character")
        flat = " ".join(s[1] for s in sections if s[1])
        assert "备选开场白" in flat

    def test_unexpected_mode_falls_back_to_hybrid(self):
        sections = _mode_sections(self._bundle(), {}, "unknown_mode")
        titles = [s[0] for s in sections]
        assert "【角色底稿】" in titles


# ============================================================
# _append_post_history_then_user — 历史消息后追加用户消息
# ============================================================
class TestAppendPostHistoryThenUser:
    def test_appends_user_message(self):
        messages = []
        _append_post_history_then_user(messages, {"role": "user", "content": "hello"})
        assert len(messages) == 1

    def test_no_user_message_no_change(self):
        messages = []
        _append_post_history_then_user(messages, None)
        assert len(messages) == 0

    def test_merges_with_previous_user(self):
        messages = [{"role": "user", "content": "previous"}]
        _append_post_history_then_user(messages, {"role": "user", "content": "hello"})
        assert len(messages) == 1
        assert "previous" in messages[0]["content"]
        assert "hello" in messages[0]["content"]

    def test_after_assistant_not_merged(self):
        messages = [{"role": "assistant", "content": "hi"}]
        _append_post_history_then_user(messages, {"role": "user", "content": "hello"})
        assert len(messages) == 2


# ============================================================
# _append_runtime_tail — 运行时尾部完整组装
# ============================================================
class TestAppendRuntimeTail:
    def test_basic_assembly(self):
        messages = [{"role": "system", "content": "sys"}]
        result = _append_runtime_tail(
            messages,
            memory_summary="记忆摘要内容",
            history=[{"role": "assistant", "content": "历史回复"}],
            recent_message_window=10,
            depth_prompt=None,
            last_user_msg={"role": "user", "content": "当前问题"},
        )
        # 应包含: system, background_context(memory), assistant确认, history, user msg
        assert len(result) >= 4
        assert result[0]["role"] == "system"
        assert result[-1]["role"] == "user"
        assert result[-1]["content"] == "当前问题"

    def test_no_memory_summary_skips_context(self):
        messages = [{"role": "system", "content": "sys"}]
        result = _append_runtime_tail(
            messages,
            memory_summary="",
            history=[{"role": "assistant", "content": "reply"}],
            recent_message_window=10,
            depth_prompt=None,
            last_user_msg={"role": "user", "content": "hi"},
        )
        assert "background_context" not in " ".join(m.get("content", "") for m in result)

    def test_no_last_user_msg(self):
        messages = [{"role": "system", "content": "sys"}]
        result = _append_runtime_tail(
            messages,
            memory_summary="记忆",
            history=[],
            recent_message_window=10,
            depth_prompt=None,
            last_user_msg=None,
        )
        # 没有 user 消息，最后一条不是 user
        assert result[-1]["role"] != "user" or "background_context" in result[-1]["content"]
