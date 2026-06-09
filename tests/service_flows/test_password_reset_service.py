"""password_reset_service 单元测试 — 密码重置全流程。
使用 unittest.mock.patch 在 repository 边界隔离，测试服务层编排逻辑。
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.exceptions import BadRequestError, RateLimitError

_NOW = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)


# ── request_password_reset ──────────────────────────────

class TestRequestPasswordReset:
    def test_user_not_found_returns_false_and_masks_email_log(self, caplog):
        """不存在的用户返回 (False, None, None)，防枚举。"""
        from services.password_reset_service import request_password_reset

        caplog.set_level("INFO", logger="services.password_reset_service")
        with patch(
            "services.password_reset_service.user_repo.find_user_by_email",
            return_value=None,
        ):
            found, email, code = request_password_reset(
                MagicMock(), "no@test.com", now=_NOW,
            )
        assert found is False
        assert email is None
        assert code is None
        assert "n***@test.com" in caplog.text
        assert "no@test.com" not in caplog.text

    def test_user_found_generates_6_digit_code(self):
        """存在的用户生成 6 位数字验证码。"""
        from services.password_reset_service import request_password_reset

        with (
            patch(
                "services.password_reset_service.user_repo.find_user_by_email",
                return_value={"id": 1, "email": "a@test.com"},
            ),
            patch(
                "services.password_reset_service.auth_repo.check_recent_reset_code",
                return_value=None,
            ),
            patch(
                "services.password_reset_service.auth_repo.insert_reset_code",
            ),
        ):
            found, email, code = request_password_reset(
                MagicMock(), "a@test.com", now=_NOW,
            )
        assert found is True
        assert email == "a@test.com"
        assert code is not None
        assert len(code) == 6
        assert code.isdigit()

    def test_cooldown_raises_rate_limit_error(self):
        """冷却期内重复请求抛出 RateLimitError。"""
        from services.password_reset_service import request_password_reset

        with (
            patch(
                "services.password_reset_service.user_repo.find_user_by_email",
                return_value={"id": 1, "email": "a@test.com"},
            ),
            patch(
                "services.password_reset_service.auth_repo.check_recent_reset_code",
                return_value={"id": 99},
            ),
        ):
            with pytest.raises(RateLimitError, match="60 秒"):
                request_password_reset(MagicMock(), "a@test.com", now=_NOW)


# ── verify_reset_code ───────────────────────────────────

class TestVerifyResetCode:
    def test_valid_code_passes_silently(self):
        """正确验证码不抛异常。"""
        from services.password_reset_service import verify_reset_code

        with patch(
            "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
            return_value={"id": 1, "code": "ABC123", "attempt_count": 0},
        ):
            verify_reset_code(MagicMock(), "a@test.com", "ABC123", now=_NOW)

    def test_no_valid_code_raises(self):
        """无有效验证码抛出 BadRequestError。"""
        from services.password_reset_service import verify_reset_code

        with patch(
            "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
            return_value=None,
        ):
            with pytest.raises(BadRequestError, match="已过期或无效"):
                verify_reset_code(MagicMock(), "a@test.com", "ANY", now=_NOW)

    def test_max_attempts_marks_used_and_raises(self):
        """尝试次数达上限后标记已使用并抛出。"""
        from services.password_reset_service import verify_reset_code

        with (
            patch(
                "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
                return_value={"id": 1, "code": "ABC123", "attempt_count": 5},
            ),
            patch(
                "services.password_reset_service.auth_repo.mark_reset_code_used",
            ) as mock_mark,
        ):
            with pytest.raises(BadRequestError, match="已失效"):
                verify_reset_code(MagicMock(), "a@test.com", "ABC123", now=_NOW)
            mock_mark.assert_called_once()
            assert mock_mark.call_args[0][1] == 1  # reset_code id

    def test_wrong_code_increments_and_raises(self):
        """错误验证码增加尝试计数并抛出。"""
        from services.password_reset_service import verify_reset_code

        with (
            patch(
                "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
                return_value={"id": 1, "code": "RIGHT", "attempt_count": 0},
            ),
            patch(
                "services.password_reset_service.auth_repo.increment_reset_code_attempts",
            ) as mock_incr,
        ):
            with pytest.raises(BadRequestError, match="已过期或无效"):
                verify_reset_code(MagicMock(), "a@test.com", "WRONG", now=_NOW)
            mock_incr.assert_called_once()
            assert mock_incr.call_args[0][1] == 1  # reset_code id

    def test_attempt_count_none_treated_as_zero(self):
        """attempt_count 为 None 时当作 0 处理（防御性）。"""
        from services.password_reset_service import verify_reset_code

        with patch(
            "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
            return_value={"id": 1, "code": "ABC123", "attempt_count": None},
        ):
            verify_reset_code(MagicMock(), "a@test.com", "ABC123", now=_NOW)


# ── execute_password_reset ──────────────────────────────

class TestExecutePasswordReset:
    def test_full_flow_success(self):
        """完整流程：验证码校验 → 用户查找 → 密码哈希 → 更新 → 标记 → 清理。"""
        from services.password_reset_service import execute_password_reset

        with (
            patch(
                "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
                return_value={"id": 1, "code": "ABC123", "attempt_count": 0},
            ),
            patch(
                "services.password_reset_service.user_repo.find_user_by_email",
                return_value={"id": 42, "email": "a@test.com"},
            ),
            patch(
                "services.password_reset_service.user_repo.update_password",
            ) as mock_update,
            patch(
                "services.password_reset_service.auth_repo.mark_reset_code_used",
            ) as mock_mark,
            patch(
                "services.password_reset_service.auth_repo.delete_other_reset_codes",
            ) as mock_delete,
            patch(
                "services.password_reset_service.hash_password_bcrypt",
                return_value="hashed_xxx",
            ),
        ):
            user_id, email = execute_password_reset(
                MagicMock(), "a@test.com", "ABC123", "newpass123", now=_NOW,
            )

        assert user_id == 42
        assert email == "a@test.com"
        mock_update.assert_called_once()
        mock_mark.assert_called_once()
        assert mock_mark.call_args[0][1] == 1  # reset_code id
        mock_delete.assert_called_once()
        assert mock_delete.call_args[0][1:] == ("a@test.com", 1)

    def test_no_valid_code_raises(self):
        """无有效验证码阻止重置。"""
        from services.password_reset_service import execute_password_reset

        with patch(
            "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
            return_value=None,
        ):
            with pytest.raises(BadRequestError, match="无效或已过期"):
                execute_password_reset(MagicMock(), "a@test.com", "BAD", "pw", now=_NOW)

    def test_max_attempts_raises_and_marks_used(self):
        """尝试超限阻止重置并标记已使用。"""
        from services.password_reset_service import execute_password_reset

        with (
            patch(
                "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
                return_value={"id": 1, "code": "ABC123", "attempt_count": 5},
            ),
            patch(
                "services.password_reset_service.auth_repo.mark_reset_code_used",
            ) as mock_mark,
        ):
            with pytest.raises(BadRequestError, match="已失效"):
                execute_password_reset(MagicMock(), "a@test.com", "ABC123", "pw", now=_NOW)
            mock_mark.assert_called_once()

    def test_wrong_code_raises(self):
        """错误验证码增加尝试计数后抛出。"""
        from services.password_reset_service import execute_password_reset

        with (
            patch(
                "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
                return_value={"id": 1, "code": "RIGHT", "attempt_count": 0},
            ),
            patch(
                "services.password_reset_service.auth_repo.increment_reset_code_attempts",
            ) as mock_incr,
        ):
            with pytest.raises(BadRequestError, match="无效或已过期"):
                execute_password_reset(MagicMock(), "a@test.com", "WRONG", "pw", now=_NOW)
            mock_incr.assert_called_once()

    def test_user_not_found_after_valid_code_raises(self):
        """验证码有效但用户已被删除时抛出。"""
        from services.password_reset_service import execute_password_reset

        with (
            patch(
                "services.password_reset_service.auth_repo.get_latest_valid_reset_code",
                return_value={"id": 1, "code": "ABC123", "attempt_count": 0},
            ),
            patch(
                "services.password_reset_service.user_repo.find_user_by_email",
                return_value=None,
            ),
        ):
            with pytest.raises(BadRequestError, match="用户不存在"):
                execute_password_reset(MagicMock(), "a@test.com", "ABC123", "pw", now=_NOW)
