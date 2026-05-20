"""
密码重置服务 — 从 routers/auth.py 提取的业务逻辑。

职责：
    - 请求密码重置（检查用户、防刷、生成验证码、入库）
    - 验证重置验证码（HMAC 比较、尝试次数管理）
    - 执行密码重置（验证码校验、密码哈希、清理旧码）

本模块不依赖 FastAPI，可通过 BadRequestError / RateLimitError 与 HTTP 层解耦。
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.database import ConnType
from core.exceptions import BadRequestError, RateLimitError
from repositories import auth_repository as auth_repo
from repositories import user_repository as user_repo
from core.auth import hash_password_bcrypt
from services.email import generate_reset_code

logger = logging.getLogger(__name__)

_RESET_CODE_MAX_ATTEMPTS = 5
_RESET_CODE_COOLDOWN_SECONDS = 60
_RESET_CODE_EXPIRE_MINUTES = 10


def request_password_reset(
    conn: ConnType,
    normalized_email: str,
    now: datetime | None = None,
) -> tuple[bool, str | None, str | None]:
    """处理忘记密码请求。

    返回 (user_found, user_email, reset_code)。
    - user_found=False 时，调用方仍应返回统一成功提示（防枚举）
    - 不提交事务，由调用方控制 commit/rollback
    """
    if now is None:
        now = datetime.now(timezone.utc)

    user = user_repo.find_user_by_email(conn, normalized_email)
    if not user:
        logger.info("密码重置请求：邮箱不存在或未命中用户 %s", normalized_email)
        return False, None, None

    # 检查冷却期（60 秒内是否已发送过）
    recent_code = auth_repo.check_recent_reset_code(
        conn, normalized_email,
        (now - timedelta(seconds=_RESET_CODE_COOLDOWN_SECONDS)).isoformat(),
    )
    if recent_code:
        raise RateLimitError(detail="请求过于频繁，请 60 秒后再试")

    code = generate_reset_code()
    expires_at = now + timedelta(minutes=_RESET_CODE_EXPIRE_MINUTES)

    auth_repo.insert_reset_code(
        conn,
        email=normalized_email,
        code=code,
        expires_at=expires_at,
    )

    return True, user["email"], code


def get_latest_valid_reset_code(
    conn: ConnType, normalized_email: str, now: datetime
) -> dict[str, Any] | None:
    """获取最新的有效验证码记录。"""
    return auth_repo.get_latest_valid_reset_code(conn, normalized_email, now)


def verify_reset_code(
    conn: ConnType,
    normalized_email: str,
    input_code: str,
    now: datetime | None = None,
) -> None:
    """验证密码重置验证码。失败时抛出 BadRequestError。"""
    if now is None:
        now = datetime.now(timezone.utc)

    reset_code = auth_repo.get_latest_valid_reset_code(conn, normalized_email, now)
    if not reset_code:
        raise BadRequestError(detail="验证码已过期或无效")

    attempts = reset_code.get("attempt_count", 0) or 0
    if attempts >= _RESET_CODE_MAX_ATTEMPTS:
        auth_repo.mark_reset_code_used(conn, reset_code["id"])
        raise BadRequestError(detail="验证码已失效，请重新获取")

    if not hmac.compare_digest(str(reset_code["code"]), str(input_code)):
        auth_repo.increment_reset_code_attempts(conn, reset_code["id"])
        raise BadRequestError(detail="验证码已过期或无效")


def execute_password_reset(
    conn: ConnType,
    normalized_email: str,
    input_code: str,
    new_password: str,
    now: datetime | None = None,
) -> tuple[int | str, str]:
    """执行密码重置全流程。

    验证验证码 → 查找用户 → 哈希密码 → 更新 → 标记使用 → 清理旧码。
    返回 (user_id, user_email)，调用方可用于日志和缓存失效。
    不提交事务，由调用方控制 commit/rollback。
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 验证验证码
    reset_code = auth_repo.get_latest_valid_reset_code(conn, normalized_email, now)
    if not reset_code:
        raise BadRequestError(detail="验证码无效或已过期")

    attempts = reset_code.get("attempt_count", 0) or 0
    if attempts >= _RESET_CODE_MAX_ATTEMPTS:
        auth_repo.mark_reset_code_used(conn, reset_code["id"])
        raise BadRequestError(detail="验证码已失效，请重新获取")

    if not hmac.compare_digest(str(reset_code["code"]), str(input_code)):
        auth_repo.increment_reset_code_attempts(conn, reset_code["id"])
        raise BadRequestError(detail="验证码无效或已过期")

    # 查找用户
    user = user_repo.find_user_by_email(conn, normalized_email)
    if not user:
        raise BadRequestError(detail="用户不存在")

    # 生成新密码哈希并更新
    new_hash = hash_password_bcrypt(new_password)
    user_repo.update_password(conn, user["id"], new_hash)

    # 标记验证码已使用
    auth_repo.mark_reset_code_used(conn, reset_code["id"])

    # 清理该邮箱其他未使用的验证码
    auth_repo.delete_other_reset_codes(conn, normalized_email, reset_code["id"])

    return user["id"], user["email"]
