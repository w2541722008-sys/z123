"""CurrentUser serialization and auth cache behavior."""

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


class TestCurrentUser:
    def test_current_user_fields(self):
        user = CurrentUser(
            id=1,
            email="u@example.com",
            nickname="U",
            plan_type="free",
            effective_plan="vip",
            is_admin=True,
        )
        assert user.id == 1
        assert user.email == "u@example.com"
        assert user.nickname == "U"
        assert user.plan_type == "free"
        assert user.effective_plan == "vip"
        assert user.is_admin is True

    def test_current_user_defaults(self):
        user = CurrentUser(id=2, email="x@example.com", nickname="")
        assert user.nickname == ""
        assert user.plan_type == "free"
        assert user.effective_plan == "free"
        assert user.is_admin is False


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


class TestCurrentUserSerialization:
    """CurrentUser to_dict / from_dict 序列化（用于缓存）。"""

    def test_to_dict_roundtrip(self):
        user = CurrentUser(
            id=1, email="u@example.com", nickname="U",
            plan_type="vip", effective_plan="svip",
            plan_expires_at="2099-01-01", is_admin=True, avatar_url="/a.png",
        )
        d = user.to_dict()
        restored = CurrentUser.from_dict(d)
        assert restored == user

    def test_to_dict_contains_all_fields(self):
        user = CurrentUser(id=2, email="x@y.com", nickname="X")
        d = user.to_dict()
        assert set(d.keys()) == {
            "id", "email", "nickname", "plan_type", "effective_plan",
            "plan_expires_at", "is_admin", "avatar_url",
        }

    def test_from_dict_handles_defaults(self):
        d = {"id": 3, "email": "a@b.com", "nickname": "A"}
        user = CurrentUser.from_dict(d)
        assert user.plan_type == "free"
        assert user.is_admin is False


class TestAuthCacheIntegration:
    """认证缓存集成测试。"""

    def test_verify_token_uses_cache_on_hit(self):
        """缓存命中时跳过 DB 查询。"""
        cached_data = CurrentUser(
            id=1, email="cached@example.com", nickname="Cached",
        ).to_dict()
        mock_cache = _make_mock_cache(get=lambda k: cached_data)
        with patch("core.auth._dependencies._cache", mock_cache):
            user = get_optional_user(MagicMock(cookies={}), "Bearer some_token")
        assert user is not None
        assert user.email == "cached@example.com"

    def test_verify_token_caches_on_db_hit(self):
        """DB 查询成功后写入缓存。"""
        row = {
            "id": 1, "email": "db@example.com", "nickname": "",
            "plan_type": "free", "plan_expires_at": "", "avatar_url": "",
            "expires_at": (NOW_UTC + timedelta(days=15)).isoformat(),
        }
        conn = _AuthConn(row)
        mock_cache = _make_mock_cache(set=MagicMock())
        with patch("core.auth._dependencies.get_conn", return_value=conn), \
             patch("core.auth._dependencies._cache", mock_cache):
            user = get_optional_user(MagicMock(cookies={}), "Bearer token_y")

        assert user is not None
        mock_cache["set"].assert_called_once()
        cache_key = mock_cache["set"].call_args[0][0]
        assert cache_key.startswith("auth_token:")

    def test_verify_token_clears_cache_on_corrupt_data(self):
        """缓存数据损坏时清除后走 DB。"""
        row = {
            "id": 1, "email": "db@example.com", "nickname": "",
            "plan_type": "free", "plan_expires_at": "", "avatar_url": "",
            "expires_at": (NOW_UTC + timedelta(days=15)).isoformat(),
        }
        conn = _AuthConn(row)
        corrupt_cache = {"id": 1}  # 缺少必要字段
        mock_cache = _make_mock_cache(get=lambda k: corrupt_cache)
        with patch("core.auth._dependencies.get_conn", return_value=conn), \
             patch("core.auth._dependencies._cache", mock_cache):
            user = get_optional_user(MagicMock(cookies={}), "Bearer token_z")

        assert user is not None
        mock_cache["delete"].assert_called_once()
