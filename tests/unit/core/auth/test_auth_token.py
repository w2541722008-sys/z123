"""Auth token sliding-extension behavior."""

import hashlib
import hmac
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.auth import (
    CurrentUser,
    get_admin_user,
    get_current_user,
    get_optional_user,
    _hash_token_value,
    _is_admin_email,
    _sha256_hash_password,
    _sliding_extend_token,
    hash_password_bcrypt,
    verify_password,
)
from core.exceptions import ForbiddenError, UnauthorizedError
from tests.support.db import (
    NOW_UTC,
    _LegacyFakeConn as FakeConn,
    make_fake_conn,
    sample_expires_soon,
    sample_token_hash,
)


class TestSlidingExtendToken:
    """
    _sliding_extend_token 测试用例。

    业务规则：
      - 剩余有效期 > 7 天 → 不续期
      - 剩余有效期 <= 7 天 → 续期至 30 天
      - expires_at 为 None → 不续期
      - expires_at 格式非法 → 不续期（不崩溃）
    """

    def test_should_extend_when_remaining_3_days(self):
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = (NOW_UTC + timedelta(days=3)).isoformat()

        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

        assert len(conn.executed_sql) >= 1
        sql = conn.executed_sql[-1][0]
        assert "UPDATE auth_tokens" in sql
        assert "expires_at" in sql

    def test_should_not_extend_when_remaining_15_days(self):
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = (NOW_UTC + timedelta(days=15)).isoformat()

        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def test_should_not_extend_when_expires_none(self):
        conn = make_fake_conn()
        _sliding_extend_token(sample_token_hash(), None, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def test_should_not_extend_on_invalid_date_format(self):
        conn = make_fake_conn()
        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), "not-a-date", NOW_UTC)
            _sliding_extend_token(sample_token_hash(), "", NOW_UTC)
            _sliding_extend_token(sample_token_hash(), "2026-13-45", NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def test_should_suppress_get_conn_exception(self):
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        with patch("core.auth._token.get_conn", side_effect=Exception("DB connection failed")):
            try:
                _sliding_extend_token(token_h, expires_at, NOW_UTC)
            except Exception:
                pytest.fail("_sliding_extend_token should not propagate get_conn exceptions")

    def test_extend_should_use_30_day_window(self):
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

        update_sqls = [(s, p) for s, p in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1
        new_expires = update_sqls[0][1][0]
        expected = (NOW_UTC + timedelta(days=30)).isoformat()
        assert new_expires == expected

    def test_boundary_exact_7_days_should_extend(self):
        conn = make_fake_conn()
        exact_threshold = (NOW_UTC + timedelta(days=7)).isoformat()

        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), exact_threshold, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1

    def test_boundary_6_days_59_sec_should_extend(self):
        conn = make_fake_conn()
        just_under = (NOW_UTC + timedelta(days=7, seconds=-1)).isoformat()

        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), just_under, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1


class TestSlidingExtendWithConn:
    """_sliding_extend_token 的 conn 参数测试。"""

    def test_extend_with_external_conn(self):
        """传入 conn 时复用同一连接，不获取新连接。"""
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        with patch("core.auth._token.get_conn") as mock_get_conn:
            _sliding_extend_token(token_h, expires_at, NOW_UTC, conn=conn)

        mock_get_conn.assert_not_called()
        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1

    def test_extend_without_conn_uses_get_conn(self):
        """不传 conn 时独立获取连接（向后兼容）。"""
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1
