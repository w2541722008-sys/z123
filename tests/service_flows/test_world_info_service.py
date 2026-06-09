"""world_info_service 单元测试 — 覆盖关键词匹配、状态机、预算控制等核心逻辑。"""

from __future__ import annotations

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from services.world_info_service import (
    resolve_triggered_memories,
    resolve_post_rules,
    _build_position_lists,
    _advance_states,
    _make_entry,
)


# ── FakeSequenceConn / FakeRow 辅助 ─────────────────────────
# 统一使用 conftest.py 中定义的测试辅助类，避免重复定义

from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


# ── 记忆条目工厂 ─────────────────────────────────────────────


def _mem_row(
    mid=1,
    keywords="hello,hi",
    trigger_logic="any",
    content="Hello World",
    position="before",
    priority=100,
    selective=1,
    constant=0,
    sticky=0,
    cooldown=0,
):
    return FakeRow({
        "id": mid,
        "keywords": keywords,
        "trigger_logic": trigger_logic,
        "content": content,
        "position": position,
        "priority": priority,
        "selective": selective,
        "constant": constant,
        "sticky": sticky,
        "cooldown": cooldown,
    })


# ── resolve_triggered_memories 测试 ──────────────────────────


class TestBasicKeywordMatching:
    """基础关键词匹配。"""

    def test_matches_any_keyword(self):
        conn = FakeSequenceConn([FakeQueryResult([_mem_row(keywords="hello,world")])])
        before, after, sticky, cooldown = resolve_triggered_memories(
            conn, "c1", "hello there",
        )
        assert len(before) == 1
        assert "Hello World" in before[0]

    def test_no_match_when_no_keyword_hits(self):
        conn = FakeSequenceConn([FakeQueryResult([_mem_row(keywords="zzz")])])
        before, after, sticky, cooldown = resolve_triggered_memories(
            conn, "c1", "hello there",
        )
        assert len(before) == 0
        assert len(after) == 0

    def test_match_is_case_insensitive(self):
        conn = FakeSequenceConn([FakeQueryResult([_mem_row(keywords="HELLO")])])
        before, after, _, _ = resolve_triggered_memories(
            conn, "c1", "Hello there",
        )
        assert len(before) == 1


class TestTriggerLogic:
    """any vs all 触发逻辑。"""

    def test_all_logic_all_must_match(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello,world", trigger_logic="all")])
        ])
        before, _, _, _ = resolve_triggered_memories(conn, "c1", "hello")
        assert len(before) == 0  # 缺少 "world"

        conn2 = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello,world", trigger_logic="all")])
        ])
        before2, _, _, _ = resolve_triggered_memories(conn2, "c1", "hello world")
        assert len(before2) == 1

    def test_any_logic_one_is_enough(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello,world", trigger_logic="any")])
        ])
        before, _, _, _ = resolve_triggered_memories(conn, "c1", "hello")
        assert len(before) == 1


class TestConstantAndSelective:
    """constant 和 selective=0 条目始终注入。"""

    def test_constant_no_keyword_needed(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="zzz", constant=1)])
        ])
        before, _, _, _ = resolve_triggered_memories(conn, "c1", "unrelated text")
        assert len(before) == 1

    def test_selective_false_no_keyword_needed(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="zzz", selective=0)])
        ])
        before, _, _, _ = resolve_triggered_memories(conn, "c1", "unrelated text")
        assert len(before) == 1

    def test_constant_does_not_set_cooldown(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello", constant=1, cooldown=3)])
        ])
        _, _, _, cooldown = resolve_triggered_memories(conn, "c1", "hello")
        assert len(cooldown) == 0  # constant 不设置冷却

    def test_selective_false_does_set_cooldown(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="zzz", selective=0, cooldown=3)])
        ])
        _, _, _, cooldown = resolve_triggered_memories(conn, "c1", "hello")
        assert 1 in cooldown  # selective=0 设置冷却


class TestStickyState:
    """粘性状态机。"""

    def test_sticky_auto_triggers_next_turn(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello", sticky=2)])
        ])
        # 第一轮：关键词触发，设置 sticky=2，然后 _advance_states 立即减 1 → 剩余 1
        _, _, new_sticky, _ = resolve_triggered_memories(conn, "c1", "hello")
        assert new_sticky.get(1) == 1

        # 第二轮：sticky 延续，无需关键词
        conn2 = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="unrelated", sticky=2)])
        ])
        before, _, new_sticky2, _ = resolve_triggered_memories(
            conn2, "c1", "unrelated text", sticky_state=new_sticky,
        )
        assert len(before) == 1  # sticky 延续触发
        assert 1 not in new_sticky2  # sticky 耗尽（1→0）

    def test_sticky_expires_when_reaches_zero(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="unrelated", sticky=1)])
        ])
        _, _, new_sticky, _ = resolve_triggered_memories(
            conn, "c1", "unrelated text", sticky_state={1: 1},
        )
        assert 1 not in new_sticky  # sticky 耗尽

    def test_sticky_state_accepts_json_string_keys(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(mid=1, keywords="unrelated", sticky=2)])
        ])
        before, _, new_sticky, _ = resolve_triggered_memories(
            conn, "c1", "unrelated text", sticky_state={"1": 2},
        )
        assert len(before) == 1
        assert new_sticky == {1: 1}


class TestCooldownState:
    """冷却状态机。"""

    def test_cooldown_blocks_trigger(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello")])
        ])
        before, _, _, _ = resolve_triggered_memories(
            conn, "c1", "hello", cooldown_state={1: 2},
        )
        assert len(before) == 0  # 在冷却中，不触发

    def test_cooldown_decrements_each_turn(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello")])
        ])
        _, _, _, new_cooldown = resolve_triggered_memories(
            conn, "c1", "hello", cooldown_state={1: 3},
        )
        assert new_cooldown.get(1) == 2

    def test_cooldown_expires_re_enables_trigger(self):
        # cooldown=1 表示本轮仍在冷却中，本轮不会触发
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello")])
        ])
        before, _, _, new_cooldown = resolve_triggered_memories(
            conn, "c1", "hello", cooldown_state={1: 1},
        )
        assert len(before) == 0  # 本轮仍在冷却中
        assert 1 not in new_cooldown  # 但冷却会在本轮结束后到期

        # 下一轮：cooldown 已清除，可以正常触发
        conn2 = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello")])
        ])
        before2, _, _, _ = resolve_triggered_memories(conn2, "c1", "hello")
        assert len(before2) == 1

    def test_cooldown_state_accepts_json_string_keys(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(mid=1, keywords="hello")])
        ])
        before, _, _, new_cooldown = resolve_triggered_memories(
            conn, "c1", "hello", cooldown_state={"1": 2},
        )
        assert before == []
        assert new_cooldown == {1: 1}

    def test_invalid_state_entries_are_ignored(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(mid=1, keywords="hello")])
        ])
        before, _, sticky, cooldown = resolve_triggered_memories(
            conn,
            "c1",
            "hello",
            sticky_state={"bad": 9, "1": "not-int"},
            cooldown_state={"bad": 9, "1": 0},
        )
        assert len(before) == 1
        assert sticky == {}
        assert cooldown == {}


class TestStorylineFilter:
    """@storyline: 前缀解析和过滤。"""

    def test_storyline_filter_blocks_non_matching(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="@storyline:5,hello")])
        ])
        before, _, _, _ = resolve_triggered_memories(
            conn, "c1", "hello", current_storyline_id=3,
        )
        assert len(before) == 0  # storyline 不匹配

    def test_storyline_filter_allows_match(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="@storyline:5,hello")])
        ])
        before, _, _, _ = resolve_triggered_memories(
            conn, "c1", "hello", current_storyline_id=5,
        )
        assert len(before) == 1

    def test_no_storyline_filter_matches_any(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello")])
        ])
        before, _, _, _ = resolve_triggered_memories(
            conn, "c1", "hello", current_storyline_id=5,
        )
        assert len(before) == 1


class TestBudgetAndTruncation:
    """预算控制和内容截断。"""

    def test_per_entry_truncation(self):
        long_content = "A" * 100
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello", content=long_content)])
        ])
        before, _, _, _ = resolve_triggered_memories(
            conn, "c1", "hello", max_per_entry=50,
        )
        assert len(before[0]) <= 50 + len("\n…（内容已截断）")

    def test_wi_max_budget_stops_adding(self):
        conn = FakeSequenceConn([
            FakeQueryResult([
                _mem_row(mid=1, keywords="a", content="HelloX"),
                _mem_row(mid=2, keywords="b", content="WorldX"),
            ])
        ])
        before, _, _, _ = resolve_triggered_memories(
            conn, "c1", "a b", wi_max=7,
        )
        # "HelloX" = 6 chars, 6 ≤ 7 → 第一个加入；第二个 "WorldX" 会超出
        assert len(before) == 1

    def test_max_triggered_cap(self):
        rows = [_mem_row(mid=i, keywords="test", priority=i) for i in range(10)]
        conn = FakeSequenceConn([FakeQueryResult(rows)])
        before, _, _, _ = resolve_triggered_memories(
            conn, "c1", "test", max_triggered=3,
        )
        assert len(before) <= 3


class TestPositionRouting:
    """position 字段路由。"""

    def test_before_vs_after_routing(self):
        conn = FakeSequenceConn([
            FakeQueryResult([
                _mem_row(mid=1, keywords="a", position="before"),
                _mem_row(mid=2, keywords="b", position="after"),
            ])
        ])
        before, after, _, _ = resolve_triggered_memories(conn, "c1", "a b")
        assert len(before) == 1
        assert len(after) == 1

    def test_default_position_is_before(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello", position=None)])
        ])
        before, after, _, _ = resolve_triggered_memories(conn, "c1", "hello")
        assert len(before) == 1
        assert len(after) == 0


class TestEmptyEdgeCases:
    """边界条件。"""

    def test_empty_rows(self):
        conn = FakeSequenceConn([FakeQueryResult([])])
        before, after, sticky, cooldown = resolve_triggered_memories(
            conn, "c1", "hello",
        )
        assert before == []
        assert after == []
        assert sticky == {}
        assert cooldown == {}

    def test_empty_content_skipped(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_mem_row(keywords="hello", content="   ")])
        ])
        before, _, _, _ = resolve_triggered_memories(conn, "c1", "hello")
        assert len(before) == 0


# ── resolve_post_rules 测试 ──────────────────────────────────


def _post_rule_row(content="Rule text", priority=100):
    return FakeRow({"content": content, "priority": priority})


class TestPostRules:
    """后置规则查询与截断。"""

    def test_basic_fetch(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_post_rule_row("Rule 1"), _post_rule_row("Rule 2")])
        ])
        rules = resolve_post_rules(conn, "c1", max_chars=100)
        assert len(rules) == 2
        assert "Rule 1" in rules[0]

    def test_empty_rows(self):
        conn = FakeSequenceConn([FakeQueryResult([])])
        rules = resolve_post_rules(conn, "c1")
        assert rules == []

    def test_truncation_when_over_budget(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_post_rule_row("A" * 300)])
        ])
        # max_chars=150: remaining=150 > 100，会截断保留 150 字符
        rules = resolve_post_rules(conn, "c1", max_chars=150)
        assert len(rules) == 1
        assert len(rules[0]) <= 150 + len("\n…（内容已截断）")

    def test_empty_content_skipped(self):
        conn = FakeSequenceConn([
            FakeQueryResult([_post_rule_row("   "), _post_rule_row("Valid")])
        ])
        rules = resolve_post_rules(conn, "c1", max_chars=100)
        assert len(rules) == 1


# ── 内部辅助函数测试 ────────────────────────────────────────


class TestBuildPositionLists:
    def test_basic_routing(self):
        entries = [
            {"id": 1, "content": "Before", "position": "before", "priority": 100},
            {"id": 2, "content": "After", "position": "after", "priority": 100},
        ]
        before, after, ids = _build_position_lists(entries, 500, 8000)
        assert len(before) == 1
        assert len(after) == 1
        assert ids == {1, 2}

    def test_wi_max_cutoff(self):
        content = "A" * 1000
        entries = [
            {"id": 1, "content": content, "position": "before", "priority": 100},
            {"id": 2, "content": content, "position": "before", "priority": 100},
        ]
        before, after, ids = _build_position_lists(entries, 500, 600)
        assert len(before) == 1  # 第二个超出预算被截断


class TestAdvanceStates:
    def test_both_decrement(self):
        sticky, cooldown = _advance_states({1: 3, 2: 1}, {3: 2}, {1})
        assert sticky == {1: 2}
        assert cooldown == {3: 1}

    def test_expired_removed(self):
        sticky, cooldown = _advance_states({1: 1}, {2: 1}, set())
        assert sticky == {}
        assert cooldown == {}
