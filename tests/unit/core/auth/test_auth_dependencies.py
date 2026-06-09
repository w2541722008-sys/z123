"""Auth dependency behavior."""

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


class TestIsAdminEmail:
    def test_known_admin_email(self):
        with patch("core.auth._dependencies.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("admin@example.com") is True

    def test_non_admin_email(self):
        with patch("core.auth._dependencies.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("user@example.com") is False

    def test_case_insensitive(self):
        with patch("core.auth._dependencies.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("Admin@Example.COM") is True

    def test_empty_string_returns_false(self):
        assert _is_admin_email("") is False

    def test_none_returns_false(self):
        assert _is_admin_email(None) is False

    def test_whitespace_trimmed(self):
        with patch("core.auth._dependencies.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("  admin@example.com  ") is True


def _make_mock_cache(get=None, set=None, delete=None):
    """构造模拟 cache dict，供依赖注入测试使用。"""
    return {
        "get": get or (lambda k: None),
        "set": set or MagicMock(),
        "delete": delete or MagicMock(),
    }


class _AuthQueryResult:
    def __init__(self, *, one=None):
        self._one = one

    def fetchone(self):
        return self._one


class _AuthConn:
    def __init__(self, row):
        self._row = row
        self.closed = False

    def execute(self, sql, params=None):
        return _AuthQueryResult(one=self._row)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


class TestAuthDependencies:
    def test_get_optional_user_returns_none_without_authorization(self):
        assert get_optional_user(MagicMock(cookies={}), None) is None

    def test_get_optional_user_returns_none_with_non_bearer_header(self):
        assert get_optional_user(MagicMock(cookies={}), "Basic abc") is None

    def test_get_optional_user_returns_none_when_token_not_found(self):
        conn = _AuthConn(None)
        mock_cache = _make_mock_cache()
        with patch("core.auth._dependencies.get_conn", return_value=conn), \
             patch("core.auth._dependencies._cache", mock_cache):
            user = get_optional_user(MagicMock(cookies={}), "Bearer token_x")
        assert user is None
        assert conn.closed is True

    def test_get_optional_user_returns_user_without_sliding_extend(self):
        """用户验证成功时应正确返回用户信息，不再调用滑动续期。"""
        soon_expires = (NOW_UTC + timedelta(days=3)).isoformat()
        row = {
            "id": 1,
            "email": "vip@example.com",
            "nickname": "",
            "plan_type": "vip",
            "plan_expires_at": "2099-01-01T00:00:00+00:00",
            "avatar_url": "/avatar.png",
            "expires_at": soon_expires,
        }
        conn = _AuthConn(row)
        mock_cache = _make_mock_cache()
        with patch("core.auth._dependencies.get_conn", return_value=conn), \
             patch("core.auth._dependencies._cache", mock_cache):
            user = get_optional_user(MagicMock(cookies={}), "Bearer raw_token_123")

        assert user is not None
        assert user.id == 1
        assert user.email == "vip@example.com"
        assert user.nickname == "vip"
        assert conn.closed is True

    def test_get_current_user_raises_401_when_optional_user_missing(self):
        with patch("core.auth._dependencies.get_optional_user", return_value=None):
            with pytest.raises(UnauthorizedError) as exc:
                get_current_user(MagicMock(cookies={}), "Bearer bad")
        assert exc.value.detail == "未登录或登录已过期"

    def test_get_current_user_returns_user_when_optional_user_exists(self):
        expected = CurrentUser(id=99, email="ok@example.com", nickname="ok")
        with patch("core.auth._dependencies.get_optional_user", return_value=expected):
            actual = get_current_user(MagicMock(cookies={}), "Bearer ok")
        assert actual is expected

    def test_get_admin_user_raises_403_when_user_not_admin(self):
        user = CurrentUser(id=3, email="u@example.com", nickname="u", is_admin=False)
        with patch("core.auth._dependencies.get_current_user", return_value=user):
            with pytest.raises(ForbiddenError) as exc:
                get_admin_user("Bearer token")
        assert exc.value.detail == "你没有管理后台权限"

    def test_get_admin_user_returns_current_user_when_admin(self):
        user = CurrentUser(id=4, email="admin@example.com", nickname="admin", is_admin=True)
        with patch("core.auth._dependencies.get_current_user", return_value=user):
            actual = get_admin_user("Bearer token")
        assert actual is user
