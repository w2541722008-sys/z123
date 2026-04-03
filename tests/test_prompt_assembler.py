"""
prompt_assembler 模块单元测试

覆盖范围：
  - TokenBudget: Token 预算分配器（字符/token 换算、各区块预算）
  - 工具函数：parse_json_object, _merge_text, _clip, _get_field, _split_last_user_message
  - World Info 关键词触发：resolve_world_info

不覆盖：
  - 需要数据库的函数（get_character_memories_from_db 等）
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from prompt_assembler import (
    TokenBudget,
    _clip,
    _get_field,
    _merge_alternate_greetings,
    _merge_text,
    _split_last_user_message,
    parse_json_object,
    resolve_world_info,
)


# ============================================================
# 1. TokenBudget 测试（Token 预算分配器）
# ============================================================

class TestTokenBudget:
    """
    TokenBudget 基于 MiniMax-M2.5 的 64K 上下文窗口设计。

    预算分配比例：
      - system prompt:   55%
      - 长期记忆摘要:     8%
      - 历史消息:        30%
      - post_history:     7%（最小 800 字）
    """

    def test_default_budget_values(self):
        """默认参数（64000 context, 2048 output reserve）的预算值。"""
        b = TokenBudget()
        assert b.context_tokens == 64000
        assert b.output_reserve == 2048
        assert b._available_tokens == 61952  # max(64000-2048, 4000)

    def test_system_max_chars_reasonable(self):
        """system 区块预算应在合理范围内。"""
        b = TokenBudget()
        sm = b.system_max_chars()
        # 55% of (64000-2048) tokens * 1.6 chars/token ≈ 54516 chars
        assert 50000 < sm < 60000

    def test_memory_max_chars_smaller_than_system(self):
        """记忆预算应远小于 system 预算。"""
        b = TokenBudget()
        assert b.memory_max_chars() < b.system_max_chars() / 4

    def test_history_max_chars_between_memory_and_system(self):
        """历史预算应介于记忆和 system 之间。"""
        b = TokenBudget()
        mem = b.memory_max_chars()
        hist = b.history_max_chars()
        sys_ = b.system_max_chars()
        assert mem < hist < sys_

    def test_reserve_min_800_chars(self):
        """reserve 至少 800 字符。"""
        b = TokenBudget()
        assert b.reserve_max_chars() >= 800

    def test_single_layer_capped_at_30_percent_of_system(self):
        """单层上限应为 system 的约 30%。"""
        b = TokenBudget()
        ratio = b.single_layer_max_chars() / b.system_max_chars()
        assert 0.25 < ratio < 0.35

    def test_primary_system_capped_at_15_percent(self):
        """primary system 上限应为 system 的约 15%。"""
        b = TokenBudget()
        ratio = b.primary_system_max_chars() / b.system_max_chars()
        assert 0.10 < ratio < 0.20

    def test_custom_context_window(self):
        """自定义上下文窗口大小。"""
        b = TokenBudget(context_tokens=32000, output_reserve=1024)
        assert b._available_tokens == 30976
        assert b.system_max_chars() > 0

    def test_small_context_minimum_protection(self):
        """极小上下文时 available 不低于 4000。"""
        b = TokenBudget(context_tokens=5000, output_reserve=2000)
        assert b._available_tokens == 4000  # min protection

    def test_chars_to_tokens_rounds_up(self):
        """chars_to_tokens 应向上取整。"""
        b = TokenBudget(chars_per_token=2.0)
        assert b.chars_to_tokens(3) == 2  # 3/2=1.5 → ceil → 2
        assert b.chars_to_tokens(1) == 1

    def test_tokens_to_chars_rounds_down(self):
        """tokens_to_chars 应向下取整。"""
        b = TokenBudget(chars_per_token=2.0)
        assert b.tokens_to_chars(3) == 6  # 3*2=6

    def test_summary_returns_all_keys(self):
        """summary() 应返回所有预算项。"""
        b = TokenBudget()
        s = b.summary()
        expected_keys = {
            "context_tokens", "available_tokens", "system_max_chars",
            "memory_max_chars", "history_max_chars", "reserve_max_chars",
            "single_layer_max", "primary_system_max", "wi_max_chars",
        }
        assert set(s.keys()) == expected_keys

    def test_wi_max_chars_is_25_percent(self):
        """World Info 预算约为全局的 25%。"""
        b = TokenBudget()
        wi = b.wi_max_chars()
        total_available = b._available_tokens * b.chars_per_token
        ratio = wi / total_available
        assert 0.20 < ratio < 0.30


# ============================================================
# 2. 工具函数测试
# ============================================================

class TestParseJsonObject:

    def test_valid_json_object(self):
        assert parse_json_object('{"a":1,"b":"x"}') == {"a": 1, "b": "x"}

    def test_empty_string_returns_fallback(self):
        fallback = {"default": True}
        result = parse_json_object("", fallback)
        assert result == fallback

    def test_none_input_returns_fallback(self):
        fallback = {"default": True}
        assert parse_json_object(None, fallback) == fallback

    def test_invalid_json_returns_fallback(self):
        fallback = {"default": True}
        assert parse_json_object("not json{", fallback) == fallback

    def test_valid_json_non_dict_returns_fallback(self):
        """JSON 是数组而非对象时返回 fallback。"""
        fallback = {"default": True}
        assert parse_json_object("[1,2,3]", fallback) == fallback

    def test_valid_json_string_returns_fallback(self):
        """JSON 是字符串时返回 fallback。"""
        fallback = {"default": True}
        assert parse_json_object('"hello"', fallback) == fallback

    def test_whitespace_string_returns_fallback(self):
        fallback = {"default": True}
        assert parse_json_object("   ", fallback) == fallback


class TestMergeText:

    def test_merges_multiple_parts(self):
        result = _merge_text("A", "B", "C")
        assert result == "A\n\nB\n\nC"

    def test_deduplicates_identical_texts(self):
        result = _merge_text("same", "same", "different")
        assert result.count("same") == 1

    def test_strips_whitespace(self):
        result = _merge_text("  A  ", "\nB\n", None)
        assert "A" in result
        assert "B" in result
        assert result == "A\n\nB"

    def test_ignores_none_and_empty(self):
        result = _merge_text("", None, "valid", "", "also_valid")
        assert result == "valid\n\nalso_valid"

    def test_all_empty_returns_empty(self):
        assert _merge_text("", None, "", None) == ""

    def test_preserves_order(self):
        result = _merge_text("first", "second", "third")
        assert result.index("first") < result.index("second") < result.index("third")


class TestClip:

    def test_text_within_limit_unchanged(self):
        text = "short"
        assert _clip(text, max_chars=100, label="test") == text

    def test_text_exceeding_limit_truncated(self):
        text = "A" * 50
        result = _clip(text, max_chars=20, label="test")
        assert len(result) <= 30  # 20 + 截断提示长度
        assert "截断" in result

    def test_empty_text_unchanged(self):
        assert _clip("", max_chars=100) == ""

    def test_exact_length_unchanged(self):
        text = "ABCDE"
        assert _clip(text, max_chars=5) == "ABCDE"

    def test_one_over_limit_gets_truncated(self):
        text = "ABCDEF"
        result = _clip(text, max_chars=5)
        assert len(result) <= 15


class TestGetField:

    def test_dict_access(self):
        source = {"name": "test", "value": 42}
        assert _get_field(source, "name") == "test"
        assert _get_field(source, "value") == 42

    def test_dict_missing_key_returns_default(self):
        assert _get_field({}, "missing", "fallback") == "fallback"

    def test_object_attribute_access(self):
        class Obj:
            name = "from_attr"

        assert _get_field(Obj(), "name") == "from_attr"

    def test_object_missing_attribute_returns_default(self):
        class Obj:
            pass

        assert _get_field(Obj(), "missing", "default") == "default"

    def test_none_value_returns_default(self):
        source = {"key": None}
        assert _get_field(source, "key", "fallback") == "fallback"


class TestSplitLastUserMessage:

    def test_splits_when_last_is_user(self):
        msgs = [
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Hello"},
        ]
        history, last = _split_last_user_message(msgs)
        assert history == [{"role": "assistant", "content": "Hi"}]
        assert last == {"role": "user", "content": "Hello"}

    def test_no_split_when_last_not_user(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        history, last = _split_last_user_message(msgs)
        assert history == msgs
        assert last is None

    def test_empty_list_returns_empty(self):
        history, last = _split_last_user_message([])
        assert history == []
        assert last is None

    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "only"}]
        history, last = _split_last_user_message(msgs)
        assert history == []
        assert last == msgs[0]


class TestMergeAlternateGreetings:

    def test_merges_and_deduplicates(self):
        result = _merge_alternate_greetings(["A", "B"], ["B", "C"])
        assert result == ["A", "B", "C"]

    def test_limits_to_6_items(self):
        many = [str(i) for i in range(10)]
        result = _merge_alternate_greetings(many)
        assert len(result) <= 6

    def test_handles_non_list_inputs(self):
        assert _merge_alternate_greetings("not a list", ["valid"]) == ["valid"]

    def test_filters_empty_strings(self):
        result = _merge_alternate_greetings(["", "valid", "", "also"])
        assert result == ["valid", "also"]


# ============================================================
# 3. resolve_world_info 测试（World Info 关键词触发）
# ============================================================

class TestResolveWorldInfo:

    def test_no_entries_returns_empty(self):
        before, after = resolve_world_info([], "hello world")
        assert before == []
        assert after == []

    def test_empty_context_returns_empty(self):
        entries = [
            {"keys": ["sword"], "content": "一把剑", "position": "before_char"},
        ]
        before, after = resolve_world_info(entries, "")
        assert before == []
        assert after == []

    def test_single_keyword_match(self):
        entries = [
            {"keys": ["剑", "sword"], "content": "锋利的剑", "position": "before_char", "insertion_order": 1},
        ]
        before, after = resolve_world_info(entries, "我拔出了剑")
        assert len(before) == 1
        assert "剑" in before[0]

    def test_case_insensitive_matching(self):
        entries = [
            {"keys": ["Magic"], "content": "魔法", "position": "after_char", "insertion_order": 1},
        ]
        before, after = resolve_world_info(entries, "I cast magic spell")
        assert len(after) == 1

    def test_position_routing(self):
        entries = [
            {"keys": ["forest"], "content": "森林信息", "position": "before_char", "insertion_order": 1},
            {"keys": ["forest"], "content": "森林后续", "position": "after_char", "insertion_order": 2},
        ]
        before, after = resolve_world_info(entries, "走进 forest")
        assert len(before) == 1
        assert len(after) == 1

    def test_insertion_order_sorting(self):
        entries = [
            {"keys": ["test"], "content": "second", "insertion_order": 2, "position": "before_char"},
            {"keys": ["test"], "content": "first", "insertion_order": 1, "position": "before_char"},
        ]
        before, _ = resolve_world_info(entries, "test context")
        assert before[0] == "[\nfirst" or "first" in before[0]

    def test_max_triggered_limit(self):
        """超过最大触发数量时应被截断。"""
        entries = [
            {"keys": [f"kw{i}"], "content": f"内容{i}", "position": "before_char", "insertion_order": i}
            for i in range(30)
        ]
        context = " ".join(f"kw{i}" for i in range(30))
        before, _ = resolve_world_info(entries, context)
        assert len(before) <= 20  # 默认上限 20

    def test_long_content_truncated(self):
        """超长词条内容应被截断。"""
        long_content = "X" * 2000
        entries = [
            {"keys": ["trigger"], "content": long_content, "position": "before_char", "insertion_order": 1},
        ]
        before, _ = resolve_world_info(entries, "trigger activated")
        assert len(before) == 1
        assert len(before[0]) < len(long_content)

    def test_any_key_matches_triggers(self):
        """多关键词中任意一个命中即触发。"""
        entries = [
            {"keys": ["apple", "banana", "cherry"], "content": "水果", "position": "before_char", "insertion_order": 1},
        ]
        before, _ = resolve_world_info(entries, "I like cherry pie")
        assert len(before) == 1

    def test_non_dict_entry_skipped(self):
        """非字典条目应被跳过。"""
        before, after = resolve_world_info(["not_a_dict"], "context")
        assert before == []
        assert after == []

    def test_empty_keys_entry_skipped(self):
        """空 keys 列表的条目不应触发。"""
        entries = [
            {"keys": [], "content": "should not trigger", "position": "before_char", "insertion_order": 1},
        ]
        before, _ = resolve_world_info(entries, "anything")
        assert before == []
