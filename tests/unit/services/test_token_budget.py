"""token_budget 单元测试 — 预算分配与换算逻辑。"""
from __future__ import annotations

import pytest

from services.token_budget import TokenBudget, DEFAULT_BUDGET, wi_max_triggered, wi_max_chars_per_entry


class TestTokenBudgetConstruction:
    def test_default_construction(self):
        b = TokenBudget()
        assert b.context_tokens == 64000
        assert b.output_reserve == 2048
        assert b._available_tokens == 64000 - 2048

    def test_custom_construction(self):
        b = TokenBudget(context_tokens=32000, output_reserve=1024)
        assert b._available_tokens == 32000 - 1024

    def test_minimum_available_tokens(self):
        b = TokenBudget(context_tokens=100, output_reserve=5000)
        # 至少 4000
        assert b._available_tokens == 4000

    def test_output_reserve_equals_context(self):
        b = TokenBudget(context_tokens=64000, output_reserve=64000)
        assert b._available_tokens == 4000


class TestUnitConversion:
    def test_chars_to_tokens_round_up(self):
        b = TokenBudget(chars_per_token=1.6)
        # 1600 chars → ~1000 tokens
        assert b.chars_to_tokens(1600) >= 999

    def test_tokens_to_chars(self):
        b = TokenBudget(chars_per_token=1.6)
        # 1000 tokens → 1600 chars
        assert b.tokens_to_chars(1000) == 1600

    def test_chars_to_tokens_minimum_1(self):
        b = TokenBudget()
        assert b.chars_to_tokens(0) == 1
        assert b.chars_to_tokens(-100) == 1

    def test_tokens_to_chars_minimum_1(self):
        b = TokenBudget()
        assert b.tokens_to_chars(0) == 1
        assert b.tokens_to_chars(-10) == 1


class TestBudgetAllocation:
    def test_system_max_chars(self):
        b = TokenBudget(context_tokens=64000, output_reserve=2048)
        # 55% of (64000-2048) tokens, then converted to chars
        expected_tokens = int(61952 * 0.55)
        expected_chars = int(expected_tokens * 1.6)
        assert b.system_max_chars() == expected_chars

    def test_memory_max_chars(self):
        b = TokenBudget()
        assert b.memory_max_chars() > 0

    def test_history_max_chars(self):
        b = TokenBudget()
        assert b.history_max_chars() > 0

    def test_reserve_max_chars_minimum_800(self):
        b = TokenBudget(context_tokens=1000, output_reserve=100)
        assert b.reserve_max_chars() >= 800

    def test_single_layer_max_is_30_pct_of_system(self):
        b = TokenBudget()
        assert b.single_layer_max_chars() == int(b.system_max_chars() * 0.30)

    def test_primary_system_max_is_25_pct_of_system(self):
        b = TokenBudget()
        assert b.primary_system_max_chars() == int(b.system_max_chars() * 0.25)

    def test_wi_max_chars_is_25_pct(self):
        b = TokenBudget()
        assert b.wi_max_chars() == b.tokens_to_chars(int(b._available_tokens * 0.25))

    def test_ratios_sum_to_100_pct(self):
        """验证各区块比例之和为 100%。"""
        assert abs(TokenBudget._SYSTEM_RATIO + TokenBudget._MEMORY_RATIO + TokenBudget._HISTORY_RATIO + TokenBudget._RESERVE_RATIO - 1.0) < 0.01


class TestSummary:
    def test_summary_has_all_keys(self):
        b = TokenBudget()
        s = b.summary()
        expected_keys = {
            "context_tokens", "available_tokens",
            "system_max_chars", "memory_max_chars",
            "history_max_chars", "reserve_max_chars",
            "single_layer_max", "primary_system_max",
            "wi_max_chars",
        }
        assert set(s.keys()) == expected_keys


class TestConvenienceFunctions:
    def test_wi_max_triggered_range(self):
        result = wi_max_triggered()
        assert 4 <= result <= 20

    def test_wi_max_triggered_custom_budget(self):
        big = TokenBudget(context_tokens=200000)
        result = wi_max_triggered(big)
        assert result <= 20

    def test_wi_max_chars_per_entry_minimum(self):
        result = wi_max_chars_per_entry()
        assert result >= 300

    def test_default_budget_constants(self):
        """验证向下兼容常量与 DEFAULT_BUDGET 一致。"""
        from services.token_budget import LAYER_MAX_CHARS, PRIMARY_SYSTEM_MAX_CHARS, TOTAL_SYSTEM_MAX_CHARS
        assert LAYER_MAX_CHARS == DEFAULT_BUDGET.single_layer_max_chars()
        assert PRIMARY_SYSTEM_MAX_CHARS == DEFAULT_BUDGET.primary_system_max_chars()
        assert TOTAL_SYSTEM_MAX_CHARS == DEFAULT_BUDGET.system_max_chars()
