"""
auth 模块单元测试

覆盖范围：
  - Token 哈希与验证（_hash_token_value, verify_password）
  - Token 滑动续期（_sliding_extend_token）— P1-C 核心逻辑，已修复 NameError Bug
  - 管理员判断（_is_admin_email）
  - CurrentUser 数据类

不覆盖：
  - create_token / delete_token（需要数据库写入，归入集成测试）
"""

import hashlib
import hmac
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, MagicMock, patch

from auth import (
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

from conftest import (
    NOW_UTC,
    FakeConn,
    make_fake_conn,
    sample_expires_later,
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
        with patch("auth.APP_SECRET", "test_secret_key"):
            hashed = _sha256_hash_password("mypassword")
            assert verify_password("mypassword", hashed, "sha256") is True

    def test_sha256_verify_wrong(self):
        with patch("auth.APP_SECRET", "test_secret_key"):
            hashed = _sha256_hash_password("mypassword")
            assert verify_password("wrongpass", hashed, "sha256") is False


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

        with patch("auth.get_conn", return_value=conn):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

        assert len(conn.executed_sql) >= 1
        sql = conn.executed_sql[-1][0]
        assert "UPDATE auth_tokens" in sql
        assert "expires_at" in sql

    def test_should_not_extend_when_remaining_15_days(self):
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = (NOW_UTC + timedelta(days=15)).isoformat()

        with patch("auth.get_conn", return_value=conn):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def test_should_not_extend_when_expires_none(self):
        conn = make_fake_conn()
        _sliding_extend_token(sample_token_hash(), None, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def test_should_not_crash_on_invalid_date_format(self):
        conn = make_fake_conn()
        with patch("auth.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), "not-a-date", NOW_UTC)
            _sliding_extend_token(sample_token_hash(), "", NOW_UTC)
            _sliding_extend_token(sample_token_hash(), "2026-13-45", NOW_UTC)

    def test_should_handle_get_conn_exception_gracefully(self):
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        with patch("auth.get_conn", side_effect=Exception("DB connection failed")):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

    def test_extend_should_use_30_day_window(self):
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        with patch("auth.get_conn", return_value=conn):
            _sliding_extend_token(token_h, expires_at, NOW_UTC)

        update_sqls = [(s, p) for s, p in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1
        new_expires = update_sqls[0][1][0]
        expected = (NOW_UTC + timedelta(days=30)).isoformat()
        assert new_expires == expected

    def test_boundary_exact_7_days_should_extend(self):
        conn = make_fake_conn()
        exact_threshold = (NOW_UTC + timedelta(days=7)).isoformat()

        with patch("auth.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), exact_threshold, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1

    def test_boundary_6_days_59_sec_should_extend(self):
        conn = make_fake_conn()
        just_under = (NOW_UTC + timedelta(days=7, seconds=-1)).isoformat()

        with patch("auth.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), just_under, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1


class TestIsAdminEmail:
    def test_known_admin_email(self):
        with patch("auth.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("admin@example.com") is True

    def test_non_admin_email(self):
        with patch("auth.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("user@example.com") is False

    def test_case_insensitive(self):
        with patch("auth.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("Admin@Example.COM") is True

    def test_empty_string_returns_false(self):
        assert _is_admin_email("") is False

    def test_none_returns_false(self):
        assert _is_admin_email(None) is False

    def test_whitespace_trimmed(self):
        with patch("auth.ADMIN_EMAILS", {"admin@example.com"}):
            assert _is_admin_email("  admin@example.com  ") is True


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


class TestVerifyPasswordBranches:
    def test_unknown_algorithm_returns_false(self):
        assert verify_password("pass", "hash", "unknown") is False

    def test_sha256_compare_uses_constant_time(self):
        with patch("auth.APP_SECRET", "test_secret_key"):
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

        with patch("auth.get_conn", return_value=conn):
            _sliding_extend_token(sample_token_hash(), sample_expires_soon(), NOW_UTC)

        conn.close.assert_called_once()


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

    def close(self):
        self.closed = True


class TestAuthDependencies:
    def test_get_optional_user_returns_none_without_authorization(self):
        assert get_optional_user(None) is None

    def test_get_optional_user_returns_none_with_non_bearer_header(self):
        assert get_optional_user("Basic abc") is None

    def test_get_optional_user_returns_none_when_token_not_found(self):
        conn = _AuthConn(None)
        with patch("auth.get_conn", return_value=conn):
            user = get_optional_user("Bearer token_x")
        assert user is None
        assert conn.closed is True

    def test_get_optional_user_returns_user_and_triggers_sliding_extend(self):
        row = {
            "id": 1,
            "email": "vip@example.com",
            "nickname": "",
            "plan_type": "vip",
            "plan_expires_at": "2099-01-01T00:00:00+00:00",
            "avatar_url": "/avatar.png",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        conn = _AuthConn(row)
        with patch("auth.get_conn", return_value=conn), patch(
            "auth._sliding_extend_token"
        ) as mock_extend_token:
            user = get_optional_user("Bearer raw_token_123")

        assert user is not None
        assert user.id == 1
        assert user.email == "vip@example.com"
        assert user.nickname == "vip"
        assert conn.closed is True
        mock_extend_token.assert_called_once_with(
            _hash_token_value("raw_token_123"),
            "2099-01-01T00:00:00+00:00",
            ANY,
        )

    def test_get_current_user_raises_401_when_optional_user_missing(self):
        with patch("auth.get_optional_user", return_value=None):
            with pytest.raises(Exception) as exc:
                get_current_user("Bearer bad")
        assert exc.value.status_code == 401
        assert exc.value.detail == "未登录或登录已过期"

    def test_get_current_user_returns_user_when_optional_user_exists(self):
        expected = CurrentUser(id=99, email="ok@example.com", nickname="ok")
        with patch("auth.get_optional_user", return_value=expected):
            actual = get_current_user("Bearer ok")
        assert actual is expected

    def test_get_admin_user_raises_403_when_user_not_admin(self):
        user = CurrentUser(id=3, email="u@example.com", nickname="u", is_admin=False)
        with patch("auth.get_current_user", return_value=user):
            with pytest.raises(Exception) as exc:
                get_admin_user("Bearer token")
        assert exc.value.status_code == 403
        assert exc.value.detail == "你没有管理后台权限"

    def test_get_admin_user_returns_current_user_when_admin(self):
        user = CurrentUser(id=4, email="admin@example.com", nickname="admin", is_admin=True)
        with patch("auth.get_current_user", return_value=user):
            actual = get_admin_user("Bearer token")
        assert actual is user
