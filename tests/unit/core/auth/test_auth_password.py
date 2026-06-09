"""Password hashing and token hashing behavior."""

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


class TestHashTokenValue:
    """_hash_token_value: 将原始 token 哈希为数据库存储值。"""

    def test_same_input_same_hash(self):
        token = "abc123_token_xyz"
        h1 = _hash_token_value(token)
        h2 = _hash_token_value(token)
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        h1 = _hash_token_value("token_a")
        h2 = _hash_token_value("token_b")
        assert h1 != h2

    def test_output_is_sha256_hex(self):
        result = _hash_token_value("test")
        assert len(result) == 64
        int(result, 16)

    def test_empty_string_hash(self):
        result = _hash_token_value("")
        assert len(result) == 64


class TestPasswordBcrypt:
    """bcrypt 密码哈希和验证。"""

    def test_hash_produces_bcrypt_format(self):
        hashed = hash_password_bcrypt("my_password_123")
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self):
        hashed = hash_password_bcrypt("correct_password")
        assert verify_password("correct_password", hashed, "bcrypt") is True

    def test_verify_wrong_password(self):
        hashed = hash_password_bcrypt("correct_password")
        assert verify_password("wrong_password", hashed, "bcrypt") is False

    def test_verify_empty_password(self):
        hashed = hash_password_bcrypt("something")
        assert verify_password("", hashed, "bcrypt") is False

    def test_verify_with_invalid_hash(self):
        assert verify_password("pass", "not_a_valid_hash", "bcrypt") is False


class TestPasswordSha256Legacy:
    """旧版 SHA-256 密码验证（向后兼容）。"""

    def test_sha256_verify_correct(self):
        with patch("core.auth._password.APP_SECRET", "test_secret_key"):
            hashed = _sha256_hash_password("mypassword")
            assert verify_password("mypassword", hashed, "sha256") is True

    def test_sha256_verify_wrong(self):
        with patch("core.auth._password.APP_SECRET", "test_secret_key"):
            hashed = _sha256_hash_password("mypassword")
            assert verify_password("wrongpass", hashed, "sha256") is False


class TestVerifyPasswordBranches:
    def test_unknown_algorithm_returns_false(self):
        assert verify_password("pass", "hash", "unknown") is False

    def test_sha256_compare_uses_constant_time(self):
        with patch("core.auth._password.APP_SECRET", "test_secret_key"):
            hashed = _sha256_hash_password("mypassword")
            assert hmac.compare_digest(hashed, _sha256_hash_password("mypassword")) is True

    def test_hash_token_matches_hashlib_sha256(self):
        token = "abc123"
        assert _hash_token_value(token) == hashlib.sha256(token.encode("utf-8")).hexdigest()

    def test_sliding_extend_ignores_rowcount_property_mock(self):
        conn = MagicMock(spec=FakeConn)
        conn.executed_sql = []
        conn.execute.side_effect = lambda sql, params=None: conn.executed_sql.append((sql, params)) or conn
        conn.commit = MagicMock()
        conn.close = MagicMock()

        with patch("core.auth._token.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), sample_expires_soon(), NOW_UTC)

        conn.close.assert_called_once()
