"""AI 请求用量日志 — 纯 SQL 层。

将 usage_guard.py 中的 ai_request_logs 表操作下沉至此。
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType

ERROR_DETAIL_MAX_LENGTH = 500
SUCCESS_STATUSES = ("success", "fallback")


def get_daily_usage(
    conn: ConnType,
    *,
    user_id: int | str | None = None,
    guest_ip: str | None = None,
    start_iso: str,
    end_iso: str,
) -> dict[str, int]:
    """读取今天已消耗的聊天请求次数和 token 数。"""
    if user_id is None and not guest_ip:
        raise ValueError("user_id 和 guest_ip 至少需要一个")

    status_placeholders = ", ".join(["%s"] * len(SUCCESS_STATUSES))

    if user_id is not None:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS request_count,
                   COALESCE(SUM(CAST(total_estimated_tokens AS bigint)), 0) AS total_tokens
            FROM ai_request_logs
            WHERE user_id = %s
              AND status IN ({status_placeholders})
              AND created_at >= %s
              AND created_at < %s
            """,
            (user_id, *SUCCESS_STATUSES, start_iso, end_iso),
        ).fetchone()
    else:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS request_count,
                   COALESCE(SUM(CAST(total_estimated_tokens AS bigint)), 0) AS total_tokens
            FROM ai_request_logs
            WHERE guest_ip = %s
              AND status IN ({status_placeholders})
              AND created_at >= %s
              AND created_at < %s
            """,
            (guest_ip or "", *SUCCESS_STATUSES, start_iso, end_iso),
        ).fetchone()

    return {
        "request_count": int(row["request_count"] or 0) if row else 0,
        "total_tokens": int(row["total_tokens"] or 0) if row else 0,
    }


def insert_request_log(
    conn: ConnType,
    *,
    user_id: int | str | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    request_chars: int,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    total_estimated_tokens: int,
    used_fallback: bool,
    status: str,
    error_detail: str = "",
) -> None:
    """记录一次聊天请求的估算消耗。"""
    conn.execute(
        """
        INSERT INTO ai_request_logs(
            user_id, guest_ip, character_id, endpoint,
            request_chars, estimated_input_tokens, estimated_output_tokens,
            total_estimated_tokens, used_fallback, status, error_detail
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            user_id,
            guest_ip or "",
            character_id,
            endpoint,
            request_chars,
            estimated_input_tokens,
            estimated_output_tokens,
            total_estimated_tokens,
            1 if used_fallback else 0,
            status,
            (error_detail or "")[:ERROR_DETAIL_MAX_LENGTH],
        ),
    )
