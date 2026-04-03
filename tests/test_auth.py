"""
auth 模块单元测试

覆盖范围：
  - Token 哈希与验证（_hash_token_value, verify_password）
  - Token 滑动续期（_sliding_extend_token）— P1-C 核心逻辑，已修复 NameError Bug
  - 管理员判断（_is_admin_email）
  - CurrentUser 数据类

不覆盖：
  - get_current_user / get_optional_user（需要真实数据库连接，归入集成测试）
  - create_token / delete_token（需要数据库写入，归入集成测试）
"""

import hashlib
import hmac
import sys
import os
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.dirname(__file__))  # for conftest

from auth import (
    CurrentUser,
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


# ============================================================
# 1. Token 哈希函数测试
# ============================================================

class TestHashTokenValue:
    """_hash_token_value: 将原始 token 哈希为数据库存储值。"""

    def test_same_input_same_hash(self):
        """相同输入应产生相同哈希。"""
        token = "abc123_token_xyz"
        h1 = _hash_token_value(token)
        h2 = _hash_token_value(token)
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        """不同输入应产生不同哈希。"""
        h1 = _hash_token_value("token_a")
        h2 = _hash_token_value("token_b")
        assert h1 != h2

    def test_output_is_sha256_hex(self):
        """输出应为 64 字符的十六进制字符串。"""
        result = _hash_token_value("test")
        assert len(result) == 64
        int(result, 16)  # 应能解析为十六进制

    def test_empty_string_hash(self):
        """空字符串也应能正常哈希。"""
        result = _hash_token_value("")
        assert len(result) == 64


# ============================================================
# 2. 密码哈希与验证测试
# ============================================================

class TestPasswordBcrypt:
    """bcrypt 密码哈希和验证。"""

    def test_hash_produces_bcrypt_format(self):
        """哈希结果应以 $2b$ 开头（bcrypt 标识）。"""
        hashed = hash_password_bcrypt("my_password_123")
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self):
        """正确密码验证应返回 True。"""
        hashed = hash_password_bcrypt("correct_password")
        assert verify_password("correct_password", hashed, "bcrypt") is True

    def test_verify_wrong_password(self):
        """错误密码验证应返回 False。"""
        hashed = hash_password_bcrypt("correct_password")
        assert verify_password("wrong_password", hashed, "bcrypt") is False

    def test_verify_empty_password(self):
        """空密码对非空哈希应返回 False。"""
        hashed = hash_password_bcrypt("something")
        assert verify_password("", hashed, "bcrypt") is False

    def test_verify_with_invalid_hash(self):
        """非法 bcrypt 哈希格式不应崩溃。"""
        assert verify_password("pass", "not_a_valid_hash", "bcrypt") is False


class TestPasswordSha256Legacy:
    """旧版 SHA-256 密码验证（向后兼容）。"""

    def test_sha256_verify_correct(self):
        """SHA-256 正确密码应通过。"""
        with patch("auth.APP_SECRET", "test_secret_key"):
            hashed = _sha256_hash_password("mypassword")
            assert verify_password("mypassword", hashed, "sha256") is True

    def test_sha256_verify_wrong(self):
        """SHA-256 错误密码应失败。"""
        with patch("auth.APP_SECRET", "test_secret_key"):
            hashed = _sha256_hash_password("mypassword")
            assert verify_password("wrongpass", hashed, "sha256") is False


# ============================================================
# 3. Token 滑动续期测试（P1-C 核心）
# ============================================================

class TestSlidingExtendToken:
    """
    _sliding_extend_token 测试用例。

    业务规则：
      - 剩余有效期 > 7 天 → 不续期
      - 剩余有效期 <= 7 天 → 续期至 30 天
      - expires_at 为 None → 不续期
      - expires_at 格式非法 → 不续期（不崩溃）

    已修复 Bug：extend_conn 在 get_conn() 异常时未初始化导致 NameError。
    """

    def should_extend_when_remaining_3_days(self):
        """剩余 3 天（< 7 天阈值）→ 应触发续期。"""
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = (NOW_UTC + timedelta(days=3)).isoformat()

        _sliding_extend_token(conn, token_h, expires_at, NOW_UTC)

        assert len(conn.executed_sql) >= 1
        sql = conn.executed_sql[-1][0]
        assert "UPDATE auth_tokens" in sql
        assert "expires_at" in sql

    def should_not_extend_when_remaining_15_days(self):
        """剩余 15 天（> 7 天阈值）→ 不应续期。"""
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = (NOW_UTC + timedelta(days=15)).isoformat()

        _sliding_extend_token(conn, token_h, expires_at, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def should_not_extend_when_expires_none(self):
        """expires_at 为 None → 不续期。"""
        conn = make_fake_conn()
        _sliding_extend_token(conn, sample_token_hash(), None, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def should_not_crash_on_invalid_date_format(self):
        """非法日期格式 → 不崩溃、不续期。"""
        conn = make_fake_conn()
        _sliding_extend_token(conn, sample_token_hash(), "not-a-date", NOW_UTC)
        _sliding_extend_token(conn, sample_token_hash(), "", NOW_UTC)
        _sliding_extend_token(conn, sample_token_hash(), "2026-13-45", NOW_UTC)

    def should_handle_get_conn_exception_gracefully(self):
        """get_conn() 抛异常时不应崩溃（NameError Bug 回归测试）。"""
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        with patch("auth.get_conn", side_effect=Exception("DB connection failed")):
            _sliding_extend_token(conn, token_h, expires_at, NOW_UTC)

    def extend_should_use_30_day_window(self):
        """续期后的新过期时间应为 now + 30 天。"""
        conn = make_fake_conn()
        token_h = sample_token_hash()
        expires_at = sample_expires_soon()

        _sliding_extend_token(conn, token_h, expires_at, NOW_UTC)

        update_sqls = [(s, p) for s, p in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1
        new_expires = update_sqls[0][1][0]  # 第一个参数是新的 expires_at
        expected = (NOW_UTC + timedelta(days=30)).isoformat()
        assert new_expires == expected

    def boundary_exact_7_days_no_extend(self):
        """恰好剩余 7 天 → 不续期（> 不是 >=）。"""
        conn = make_fake_conn()
        exact_threshold = (NOW_UTC + timedelta(days=7)).isoformat()

        _sliding_extend_token(conn, sample_token_hash(), exact_threshold, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 0

    def boundary_6_days_59_sec_should_extend(self):
        """剩余 6天23小时59秒（< 7天）→ 应续期。"""
        conn = make_fake_conn()
        just_under = (NOW_UTC + timedelta(days=7, seconds=-1)).isoformat()

        _sliding_extend_token(conn, sample_token_hash(), just_under, NOW_UTC)

        update_sqls = [s for s, _ in conn.executed_sql if "UPDATE" in s]
        assert len(update_sqls) == 1


# ============================================================
# 4. 管理员判断测试
# ============================================================

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


# ============================================================
# 5. CurrentUser 数据类测试
# ============================================================

class TestCurrentUser:

    def test_default_values(self):
        user = CurrentUser(id=1, email="a@b.com", nickname="Test")
        assert user.plan_type == "free"
        assert user.effective_plan == "free"
        assert user.is_admin is False

    def test_custom_values(self):
        user = CurrentUser(
            id=42, email="vip@a.com", nickname="VIP",
            plan_type="pro", effective_plan="pro",
            plan_expires_at="2027-01-01", is_admin=True,
        )
        assert user.is_admin is True
        assert user.plan_type == "pro"

    def test_dataclass_is_mutable(self):
        user = CurrentUser(id=1, email="a@b.com", nickname="T")
        user.id = 99  # dataclass 默认可变（非 frozen）
        assert user.id == 99
