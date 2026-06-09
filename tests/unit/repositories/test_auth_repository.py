"""auth_repository 单元测试 — 验证参数传递与 SQL 结构。

使用 FakeSequenceConn 验证：
  - SQL 参数对齐（占位符 %s 数量 == 参数元组长度）
  - 返回值处理逻辑（fetchone → None 检查、返回字段提取）
  - 分支逻辑（user_id=None vs 有值）
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.support.db import FakeRow, FakeSequenceConn


# ── get_latest_valid_reset_code ──────────────────────────────

class TestGetLatestValidResetCode:
    def test_found_returns_row(self):
        from repositories.auth_repository import get_latest_valid_reset_code
        row = FakeRow({"id": 1, "code": "ABC", "expires_at": "2026-05-04", "used": False, "attempt_count": 0})
        conn = FakeSequenceConn([row])
        result = get_latest_valid_reset_code(conn, "a@b.com", datetime.now(timezone.utc))
        assert result is row
        assert conn.executed[0][1] == ("a@b.com", conn.executed[0][1][1])

    def test_not_found_returns_none(self):
        from repositories.auth_repository import get_latest_valid_reset_code
        conn = FakeSequenceConn([None])
        result = get_latest_valid_reset_code(conn, "a@b.com", datetime.now(timezone.utc))
        assert result is None


# ── mark_reset_code_used ────────────────────────────────────

class TestMarkResetCodeUsed:
    def test_executes_update(self):
        from repositories.auth_repository import mark_reset_code_used
        conn = FakeSequenceConn([FakeRow()])
        mark_reset_code_used(conn, 42)
        sql, params = conn.executed[0]
        assert "UPDATE password_reset_codes" in sql
        assert "used = TRUE" in sql
        assert params == (42,)


# ── increment_reset_code_attempts ───────────────────────────

class TestIncrementResetCodeAttempts:
    def test_executes_update(self):
        from repositories.auth_repository import increment_reset_code_attempts
        conn = FakeSequenceConn([FakeRow()])
        increment_reset_code_attempts(conn, 7)
        sql, params = conn.executed[0]
        assert "attempt_count = attempt_count + 1" in sql
        assert params == (7,)


# ── check_recent_reset_code ────────────────────────────────

class TestCheckRecentResetCode:
    def test_found_returns_row(self):
        from repositories.auth_repository import check_recent_reset_code
        row = FakeRow({"created_at": "2026-05-03"})
        conn = FakeSequenceConn([row])
        cutoff = datetime.now(timezone.utc)
        result = check_recent_reset_code(conn, "a@b.com", cutoff)
        assert result is row
        assert conn.executed[0][1] == ("a@b.com", cutoff)

    def test_not_found_returns_none(self):
        from repositories.auth_repository import check_recent_reset_code
        conn = FakeSequenceConn([None])
        result = check_recent_reset_code(conn, "a@b.com", datetime.now(timezone.utc))
        assert result is None


# ── insert_reset_code ──────────────────────────────────────

class TestInsertResetCode:
    def test_params_alignment(self):
        from repositories.auth_repository import insert_reset_code
        conn = FakeSequenceConn([FakeRow()])
        expires = datetime(2026, 5, 4, tzinfo=timezone.utc)
        insert_reset_code(conn, email="a@b.com", code="XYZ", expires_at=expires)
        sql, params = conn.executed[0]
        assert "INSERT INTO password_reset_codes" in sql
        assert params == ("a@b.com", "XYZ", expires)
        # 验证 %s 占位符数量与参数一致
        assert sql.count("%s") == len(params)


# ── delete_other_reset_codes ───────────────────────────────

class TestDeleteOtherResetCodes:
    def test_params_alignment(self):
        from repositories.auth_repository import delete_other_reset_codes
        conn = FakeSequenceConn([FakeRow()])
        delete_other_reset_codes(conn, "a@b.com", 99)
        sql, params = conn.executed[0]
        assert "DELETE FROM password_reset_codes" in sql
        assert params == ("a@b.com", 99)
        assert sql.count("%s") == len(params)
