"""聊天成本防护与消耗记录工具。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from config import COST_ESTIMATE_CHARS_PER_TOKEN, utc_now_iso

# 常量定义
ERROR_DETAIL_MAX_LENGTH = 500

SUCCESS_STATUSES = ("success", "fallback")


def estimate_tokens_from_chars(chars: int) -> int:
    """按统一比例把字符数估算成 token 数。"""
    if chars <= 0:
        return 0
    return max(1, int(chars / COST_ESTIMATE_CHARS_PER_TOKEN + 0.5))


def estimate_messages_tokens(messages: list[dict[str, str]]) -> dict[str, int]:
    """估算整组 messages 的字符数和 token 数。"""
    total_chars = 0
    for msg in messages:
        total_chars += len(msg.get("role", "")) + len(msg.get("content", "")) + 12
    return {
        "chars": total_chars,
        "tokens": estimate_tokens_from_chars(total_chars),
    }


def estimate_text_tokens(text: str) -> int:
    """估算单段文本的 token 数。"""
    return estimate_tokens_from_chars(len(text or ""))


def _day_range_utc() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start.isoformat(), day_end.isoformat()


def get_daily_usage(
    conn: Any,
    *,
    user_id: int | None = None,
    guest_ip: str | None = None,
) -> dict[str, int]:
    """读取今天已消耗的聊天请求次数和 token 数。"""
    if user_id is None and not guest_ip:
        raise ValueError("user_id 和 guest_ip 至少需要一个")

    start_iso, end_iso = _day_range_utc()
    status_placeholders = ", ".join(["%s"] * len(SUCCESS_STATUSES))

    if user_id is not None:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS request_count,
                   COALESCE(SUM(total_estimated_tokens), 0) AS total_tokens
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
                   COALESCE(SUM(total_estimated_tokens), 0) AS total_tokens
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


def enforce_daily_budget(
    conn: Any,
    *,
    user_id: int | None = None,
    guest_ip: str | None = None,
    planned_tokens: int,
    token_limit: int,
    token_limit_detail: str,
) -> dict[str, int]:
    """检查今日预算，超限时抛出 429。"""
    usage = get_daily_usage(conn, user_id=user_id, guest_ip=guest_ip)
    if token_limit > 0 and usage["total_tokens"] + planned_tokens > token_limit:
        raise HTTPException(status_code=429, detail=token_limit_detail)
    return usage


def log_ai_request(
    conn: Any,
    *,
    user_id: int | None,
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
    commit: bool = True,
) -> None:
    """记录一次聊天请求的估算消耗。"""
    conn.execute(
        """
        INSERT INTO ai_request_logs(
            user_id, guest_ip, character_id, endpoint,
            request_chars, estimated_input_tokens, estimated_output_tokens,
            total_estimated_tokens, used_fallback, status, error_detail, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            utc_now_iso(),
        ),
    )
    if commit:
        conn.commit()