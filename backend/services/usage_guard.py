"""聊天成本防护与消耗记录工具。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.exceptions import BudgetExceededError
from core.config import COST_ESTIMATE_CHARS_PER_TOKEN
from core.database import ConnType
from repositories import usage_repository as usage_repo

# Token 估算系数：CJK 字符约 1.6 chars/token，Latin 约 4 chars/token
_CJK_CHARS_PER_TOKEN = 1.6
_LATIN_CHARS_PER_TOKEN = 4.0


def _cjk_ratio(text: str) -> float:
    """检测文本中 CJK 字符的占比，用于自适应 token 估算。"""
    if not text:
        return 0.0
    cjk = 0
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or  # CJK Unified
            0x3400 <= cp <= 0x4DBF or  # CJK Extension A
            0x3000 <= cp <= 0x303F or  # CJK Symbols
            0xFF00 <= cp <= 0xFFEF or  # Halfwidth/Fullwidth
            0x3040 <= cp <= 0x309F or  # Hiragana
            0x30A0 <= cp <= 0x30FF or  # Katakana
            0xAC00 <= cp <= 0xD7AF):    # Hangul
            cjk += 1
    return cjk / len(text)


def estimate_tokens_from_chars(chars: int, *, cjk_ratio: float | None = None) -> int:
    """按统一比例把字符数估算成 token 数。

    cjk_ratio 为 None 时使用全局默认系数（向后兼容）；
    传入 0~1 值时按 CJK/Latin 比例自适应计算。
    """
    if chars <= 0:
        return 0
    if cjk_ratio is None:
        chars_per_token = COST_ESTIMATE_CHARS_PER_TOKEN
    else:
        # 加权平均：CJK 权重 + Latin 权重
        chars_per_token = cjk_ratio * _CJK_CHARS_PER_TOKEN + (1 - cjk_ratio) * _LATIN_CHARS_PER_TOKEN
    return max(1, int(chars / chars_per_token + 0.5))


def estimate_messages_tokens(messages: list[dict[str, str]]) -> dict[str, int]:
    """估算整组 messages 的字符数和 token 数。自适应检测中英文比例。"""
    total_chars = 0
    combined_text_parts = []
    for msg in messages:
        total_chars += len(msg.get("role", "")) + len(msg.get("content", "")) + 12
        combined_text_parts.append(msg.get("content", ""))
    ratio = _cjk_ratio("".join(combined_text_parts))
    return {
        "chars": total_chars,
        "tokens": estimate_tokens_from_chars(total_chars, cjk_ratio=ratio),
    }


def estimate_text_tokens(text: str) -> int:
    """估算单段文本的 token 数，自适应检测中英文比例。"""
    text_str = text or ""
    ratio = _cjk_ratio(text_str)
    return estimate_tokens_from_chars(len(text_str), cjk_ratio=ratio)


def _day_range_utc() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start.isoformat(), day_end.isoformat()


def get_daily_usage(
    conn: ConnType,
    *,
    user_id: int | str | None = None,
    guest_ip: str | None = None,
) -> dict[str, int]:
    """读取今天已消耗的聊天请求次数和 token 数。"""
    if user_id is None and not guest_ip:
        raise ValueError("user_id 和 guest_ip 至少需要一个")

    start_iso, end_iso = _day_range_utc()
    usage = usage_repo.get_daily_usage(
        conn,
        user_id=user_id,
        guest_ip=guest_ip,
        start_iso=start_iso,
        end_iso=end_iso,
    )
    return {
        "request_count": int(usage.get("request_count") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def _budget_lock_key(identifier: str) -> int:
    """生成确定性 bigint 用于 pg_advisory_xact_lock，防止同一用户并发超额。

    使用 djb2 哈希算法确保所有 Python 进程对同一标识符产生相同锁键。
    PostgreSQL advisory lock 在事务提交/回滚时自动释放，
    因此 enforce_daily_budget 获取锁后，直到 log_ai_request 提交才释放。
    """
    h = 5381
    for c in identifier:
        h = ((h << 5) + h + ord(c)) & 0xFFFFFFFFFFFFFFFF
    if h >= 0x8000000000000000:
        h -= 0x10000000000000000
    return h


def enforce_daily_budget(
    conn: ConnType,
    *,
    user_id: int | str | None = None,
    guest_ip: str | None = None,
    planned_tokens: int,
    token_limit: int,
    token_limit_detail: str,
) -> dict[str, int]:
    """检查今日预算，超限时抛出 429。

    通过 pg_advisory_xact_lock 对同一用户串行化 check-then-insert，
    消除 SELECT 和 INSERT 之间的竞态窗口。锁在 log_ai_request 的 commit 时自动释放。
    """
    lock_key_str = f"budget:{user_id or guest_ip}"
    lock_key = _budget_lock_key(lock_key_str)
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

    usage = get_daily_usage(conn, user_id=user_id, guest_ip=guest_ip)
    if token_limit > 0 and usage["total_tokens"] + planned_tokens > token_limit:
        raise BudgetExceededError(detail=token_limit_detail)
    return usage


def log_ai_request(
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
    commit: bool = True,
) -> None:
    """记录一次聊天请求的估算消耗。"""
    usage_repo.insert_request_log(
        conn,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        request_chars=request_chars,
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        total_estimated_tokens=total_estimated_tokens,
        used_fallback=used_fallback,
        status=status,
        error_detail=error_detail,
    )
    if commit:
        conn.commit()
