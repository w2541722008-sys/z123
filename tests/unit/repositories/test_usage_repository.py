"""usage_repository 单元测试"""

import pytest
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn
from repositories.usage_repository import get_daily_usage, insert_request_log, ERROR_DETAIL_MAX_LENGTH


class TestGetDailyUsage:
    def test_requires_user_id_or_guest_ip(self):
        conn = FakeSequenceConn([])
        with pytest.raises(ValueError, match="至少需要一个"):
            get_daily_usage(conn, start_iso="2026-01-01", end_iso="2026-01-02")

    def test_by_user_id(self):
        result = FakeQueryResult(
            one=FakeRow({"request_count": 5, "total_tokens": 10000})
        )
        conn = FakeSequenceConn([result])
        usage = get_daily_usage(conn, user_id=42, start_iso="2026-01-01", end_iso="2026-01-02")
        assert usage["request_count"] == 5
        assert usage["total_tokens"] == 10000
        assert "user_id" in conn.executed[0][0]

    def test_by_guest_ip(self):
        result = FakeQueryResult(
            one=FakeRow({"request_count": 2, "total_tokens": 3000})
        )
        conn = FakeSequenceConn([result])
        usage = get_daily_usage(conn, guest_ip="1.2.3.4", start_iso="2026-01-01", end_iso="2026-01-02")
        assert usage["request_count"] == 2
        assert "guest_ip" in conn.executed[0][0]

    def test_null_result_returns_zeros(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        usage = get_daily_usage(conn, user_id=1, start_iso="2026-01-01", end_iso="2026-01-02")
        assert usage["request_count"] == 0
        assert usage["total_tokens"] == 0


class TestInsertRequestLog:
    def test_insert_log_basic(self):
        conn = FakeSequenceConn([FakeRow({})])
        insert_request_log(
            conn,
            user_id=1, guest_ip="1.2.3.4", character_id="char-1",
            endpoint="/api/chat/send", request_chars=100,
            estimated_input_tokens=50, estimated_output_tokens=60,
            total_estimated_tokens=110, used_fallback=False,
            status="success",
        )
        assert "INSERT INTO ai_request_logs" in conn.executed[0][0]

    def test_error_detail_truncation(self):
        conn = FakeSequenceConn([FakeRow({})])
        long_error = "x" * 1000
        insert_request_log(
            conn,
            user_id=1, guest_ip="", character_id="char-1",
            endpoint="/api/chat/send", request_chars=0,
            estimated_input_tokens=0, estimated_output_tokens=0,
            total_estimated_tokens=0, used_fallback=False,
            status="error", error_detail=long_error,
        )
        params = conn.executed[0][1]
        error_detail = params[-2 if len(params) > 1 else -1]
        assert len(error_detail) <= ERROR_DETAIL_MAX_LENGTH

    def test_used_fallback_converts_to_int(self):
        conn = FakeSequenceConn([FakeRow({})])
        insert_request_log(
            conn,
            user_id=1, guest_ip="", character_id="char-1",
            endpoint="/api/chat/send", request_chars=0,
            estimated_input_tokens=0, estimated_output_tokens=0,
            total_estimated_tokens=0, used_fallback=True,
            status="fallback",
        )
        params = conn.executed[0][1]
        used_fallback_idx = 8
        assert params[used_fallback_idx] == 1
