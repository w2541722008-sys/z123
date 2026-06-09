"""usage_guard 单元测试 — 成本防护与消耗记录。

覆盖范围：
    - estimate_tokens_from_chars: 字符→Token 估算
    - estimate_messages_tokens: 消息组 Token 估算
    - estimate_text_tokens: 文本 Token 估算
    - _day_range_utc: UTC 日期范围
    - get_daily_usage: 每日用量查询
    - enforce_daily_budget: 预算检查（含 429 抛出）
    - log_ai_request: 请求日志记录
"""

import pytest
from unittest.mock import MagicMock

from services.usage_guard import (
    estimate_tokens_from_chars,
    estimate_messages_tokens,
    estimate_text_tokens,
    get_daily_usage,
    enforce_daily_budget,
    log_ai_request,
)
from repositories.usage_repository import ERROR_DETAIL_MAX_LENGTH, SUCCESS_STATUSES
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


# ── estimate_tokens_from_chars ──────────────────────────────────

class TestEstimateTokensFromChars:
    """纯函数，零依赖。"""

    def test_zero_returns_zero(self):
        assert estimate_tokens_from_chars(0) == 0

    def test_negative_returns_zero(self):
        assert estimate_tokens_from_chars(-10) == 0

    def test_small_value_returns_at_least_one(self):
        # 1 char / 1.6 ≈ 0.625, round → 1
        assert estimate_tokens_from_chars(1) == 1

    def test_exact_ratio(self):
        # 1600 chars / 1.6 = 1000 tokens
        assert estimate_tokens_from_chars(1600) == 1000

    def test_rounding_half(self):
        # 800 / 1.6 = 500.0 → 500
        assert estimate_tokens_from_chars(800) == 500

    def test_rounding_up(self):
        # 801 / 1.6 = 500.625, +0.5 → 501.125, int → 501
        assert estimate_tokens_from_chars(801) == 501


# ── estimate_messages_tokens ────────────────────────────────────

class TestEstimateMessagesTokens:
    """纯函数，零依赖。"""

    def test_empty_list(self):
        result = estimate_messages_tokens([])
        assert result["chars"] == 0
        assert result["tokens"] == 0

    def test_single_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = estimate_messages_tokens(msgs)
        # chars = len("user") + len("hello") + 12 = 21, 英文用 Latin 系数
        assert result["chars"] == 21
        assert result["tokens"] == 5  # 21/4.0 ≈ 5

    def test_chinese_content_uses_cjk_coefficient(self):
        msgs = [{"role": "user", "content": "你好世界"}]
        result = estimate_messages_tokens(msgs)
        assert result["chars"] == 20  # 4+4+12=20
        assert result["tokens"] == 13  # 20/1.6 ≈ 13

    def test_multiple_messages(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello there"},
        ]
        result = estimate_messages_tokens(msgs)
        expected_chars = len("user") + len("hi") + 12 + len("assistant") + len("hello there") + 12
        assert result["chars"] == expected_chars

    def test_missing_keys_default_empty(self):
        msgs = [{"content": "test"}]
        result = estimate_messages_tokens(msgs)
        # chars = len("") + len("test") + 12 = 0 + 4 + 12 = 16
        assert result["chars"] == 16

    def test_empty_content(self):
        msgs = [{"role": "user", "content": ""}]
        result = estimate_messages_tokens(msgs)
        # chars = 4 + 0 + 12 = 16
        assert result["chars"] == 16


# ── estimate_text_tokens ───────────────────────────────────────

class TestEstimateTextTokens:

    def test_normal_text(self):
        # 纯英文 "hello world" 11 chars → 11/4.0 ≈ 3
        assert estimate_text_tokens("hello world") == 3

    def test_chinese_text(self):
        # 纯中文 "你好世界" 4 chars → 4/1.6 ≈ 3
        assert estimate_text_tokens("你好世界") == 3

    def test_mixed_text(self):
        # 混合 "hi你好" 4 chars: 2 Latin + 2 CJK → ratio=0.5
        # coefficient = 0.5*1.6 + 0.5*4.0 = 2.8 → 4/2.8 ≈ 1
        result = estimate_text_tokens("hi你好")
        assert result >= 1

    def test_empty_string(self):
        assert estimate_text_tokens("") == 0

    def test_none_returns_zero(self):
        assert estimate_text_tokens(None) == 0


# ── get_daily_usage ────────────────────────────────────────────

class TestGetDailyUsage:

    def test_requires_user_id_or_guest_ip(self):
        conn = FakeSequenceConn([])
        with pytest.raises(ValueError, match="至少需要一个"):
            get_daily_usage(conn)

    def test_by_user_id(self):
        result = FakeQueryResult(
            one=FakeRow({"request_count": 5, "total_tokens": 10000})
        )
        conn = FakeSequenceConn([result])
        usage = get_daily_usage(conn, user_id=42)
        assert usage["request_count"] == 5
        assert usage["total_tokens"] == 10000
        # 验证 SQL 用了 user_id
        sql = conn.executed[0][0]
        assert "user_id" in sql

    def test_by_guest_ip(self):
        result = FakeQueryResult(
            one=FakeRow({"request_count": 2, "total_tokens": 3000})
        )
        conn = FakeSequenceConn([result])
        usage = get_daily_usage(conn, guest_ip="1.2.3.4")
        assert usage["request_count"] == 2
        assert usage["total_tokens"] == 3000
        sql = conn.executed[0][0]
        assert "guest_ip" in sql

    def test_empty_result_returns_zeros(self):
        result = FakeQueryResult(one=None)
        conn = FakeSequenceConn([result])
        usage = get_daily_usage(conn, user_id=1)
        assert usage["request_count"] == 0
        assert usage["total_tokens"] == 0

    def test_null_values_return_zeros(self):
        result = FakeQueryResult(
            one=FakeRow({"request_count": None, "total_tokens": None})
        )
        conn = FakeSequenceConn([result])
        usage = get_daily_usage(conn, user_id=1)
        assert usage["request_count"] == 0
        assert usage["total_tokens"] == 0


# ── enforce_daily_budget ───────────────────────────────────────

class TestEnforceDailyBudget:

    @staticmethod
    def _lock_result():
        """pg_advisory_xact_lock 调用的占位结果。"""
        return FakeQueryResult(one=FakeRow({"pg_advisory_xact_lock": ""}))

    def test_under_budget_passes(self):
        result = FakeQueryResult(
            one=FakeRow({"request_count": 3, "total_tokens": 5000})
        )
        conn = FakeSequenceConn([self._lock_result(), result])
        usage = enforce_daily_budget(
            conn,
            user_id=1,
            planned_tokens=1000,
            token_limit=10000,
            token_limit_detail="超出限制",
        )
        assert usage["total_tokens"] == 5000

    def test_over_budget_raises_429(self):
        from core.exceptions import BudgetExceededError

        result = FakeQueryResult(
            one=FakeRow({"request_count": 10, "total_tokens": 9000})
        )
        conn = FakeSequenceConn([self._lock_result(), result])
        with pytest.raises(BudgetExceededError) as exc_info:
            enforce_daily_budget(
                conn,
                user_id=1,
                planned_tokens=2000,
                token_limit=10000,
                token_limit_detail="每日额度已用完",
            )
        assert "每日额度已用完" in exc_info.value.detail

    def test_exact_budget_passes(self):
        result = FakeQueryResult(
            one=FakeRow({"request_count": 5, "total_tokens": 8000})
        )
        conn = FakeSequenceConn([self._lock_result(), result])
        # 8000 + 2000 == 10000, 刚好等于限额，不抛出
        usage = enforce_daily_budget(
            conn,
            user_id=1,
            planned_tokens=2000,
            token_limit=10000,
            token_limit_detail="超限",
        )
        assert usage["total_tokens"] == 8000

    def test_zero_limit_means_unlimited(self):
        """token_limit=0 时，条件 token_limit > 0 为 False，不做预算检查。"""
        result = FakeQueryResult(
            one=FakeRow({"request_count": 0, "total_tokens": 0})
        )
        conn = FakeSequenceConn([self._lock_result(), result])
        # token_limit=0 → 不检查预算，即使 planned_tokens 很大也不超限
        usage = enforce_daily_budget(
            conn,
            user_id=1,
            planned_tokens=999999,
            token_limit=0,
            token_limit_detail="不应出现",
        )
        assert usage["total_tokens"] == 0

    def test_negative_limit_never_blocks(self):
        """token_limit < 0 同样表示无限制（不会进入 if 分支）。"""
        result = FakeQueryResult(
            one=FakeRow({"request_count": 100, "total_tokens": 999999})
        )
        conn = FakeSequenceConn([self._lock_result(), result])
        usage = enforce_daily_budget(
            conn,
            user_id=1,
            planned_tokens=100000,
            token_limit=-1,
            token_limit_detail="不应出现",
        )
        assert usage["total_tokens"] == 999999


# ── log_ai_request ─────────────────────────────────────────────

class TestLogAiRequest:

    def test_basic_insert_with_commit(self):
        conn = FakeSequenceConn([FakeQueryResult(rowcount=1)])
        log_ai_request(
            conn,
            user_id=1,
            guest_ip="",
            character_id="char1",
            endpoint="/api/chat/send",
            request_chars=100,
            estimated_input_tokens=50,
            estimated_output_tokens=30,
            total_estimated_tokens=80,
            used_fallback=False,
            status="success",
            commit=True,
        )
        assert conn.committed is True
        sql, params = conn.executed[0]
        assert "INSERT INTO ai_request_logs" in sql
        assert params[0] == 1  # user_id
        assert params[3] == "/api/chat/send"
        assert params[8] == 0  # used_fallback=False → 0

    def test_fallback_sets_flag(self):
        conn = FakeSequenceConn([FakeQueryResult(rowcount=1)])
        log_ai_request(
            conn,
            user_id=None,
            guest_ip="1.2.3.4",
            character_id="char2",
            endpoint="/api/chat/guest-stream",
            request_chars=50,
            estimated_input_tokens=20,
            estimated_output_tokens=10,
            total_estimated_tokens=30,
            used_fallback=True,
            status="fallback",
            commit=False,
        )
        assert conn.committed is False  # commit=False
        sql, params = conn.executed[0]
        assert params[0] is None  # user_id=None
        assert params[1] == "1.2.3.4"  # guest_ip
        assert params[8] == 1  # used_fallback=True → 1

    def test_error_detail_truncated(self):
        conn = FakeSequenceConn([FakeQueryResult(rowcount=1)])
        long_error = "x" * 1000
        log_ai_request(
            conn,
            user_id=1,
            guest_ip="",
            character_id="c",
            endpoint="/api/chat/send",
            request_chars=0,
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            total_estimated_tokens=0,
            used_fallback=False,
            status="error",
            error_detail=long_error,
        )
        _, params = conn.executed[0]
        assert len(params[10]) == ERROR_DETAIL_MAX_LENGTH

    def test_none_error_detail_becomes_empty(self):
        conn = FakeSequenceConn([FakeQueryResult(rowcount=1)])
        log_ai_request(
            conn,
            user_id=1,
            guest_ip="",
            character_id="c",
            endpoint="/api/chat/send",
            request_chars=0,
            estimated_input_tokens=0,
            estimated_output_tokens=0,
            total_estimated_tokens=0,
            used_fallback=False,
            status="success",
            error_detail=None,
        )
        _, params = conn.executed[0]
        assert params[10] == ""

    def test_success_statuses_contains_expected(self):
        assert "success" in SUCCESS_STATUSES
        assert "fallback" in SUCCESS_STATUSES
        assert "error" not in SUCCESS_STATUSES
