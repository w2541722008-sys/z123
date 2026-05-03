"""认证相关的数据访问层（密码重置验证码等）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.database import ConnType


def get_latest_valid_reset_code(
    conn: ConnType, normalized_email: str, now: datetime
) -> dict[str, Any] | None:
    """获取最新有效的密码重置验证码。"""
    return conn.execute(
        """
        SELECT id, code, expires_at, used, attempt_count
        FROM password_reset_codes
        WHERE email = %s AND used = FALSE AND expires_at > %s
        ORDER BY created_at DESC LIMIT 1
        """,
        (normalized_email, now),
    ).fetchone()


def mark_reset_code_used(conn: ConnType, code_id: int | str) -> None:
    """标记验证码为已使用。"""
    conn.execute(
        "UPDATE password_reset_codes SET used = TRUE WHERE id = %s",
        (code_id,),
    )


def increment_reset_code_attempts(conn: ConnType, code_id: int | str) -> None:
    """递增验证码尝试次数。"""
    conn.execute(
        "UPDATE password_reset_codes SET attempt_count = attempt_count + 1 WHERE id = %s",
        (code_id,),
    )


def check_recent_reset_code(conn: ConnType, normalized_email: str, cutoff: datetime) -> dict[str, Any] | None:
    """检查最近一段时间内是否已发送过验证码。"""
    return conn.execute(
        """
        SELECT created_at FROM password_reset_codes
        WHERE email = %s AND used = FALSE AND created_at > %s
        ORDER BY created_at DESC LIMIT 1
        """,
        (normalized_email, cutoff),
    ).fetchone()


def insert_reset_code(
    conn: ConnType,
    *,
    email: str,
    code: str,
    expires_at: datetime,
) -> None:
    """插入密码重置验证码。created_at 由 DB DEFAULT now() 填充。"""
    conn.execute(
        """
        INSERT INTO password_reset_codes (email, code, expires_at, used)
        VALUES (%s, %s, %s, FALSE)
        """,
        (email, code, expires_at),
    )


def delete_other_reset_codes(conn: ConnType, email: str, keep_code_id: int | str) -> None:
    """清理该邮箱其他未使用的验证码。"""
    conn.execute(
        "DELETE FROM password_reset_codes WHERE email = %s AND id != %s",
        (email, keep_code_id),
    )
