"""
流式结果后处理 — 消息持久化、状态更新、后台任务。

职责：
- 流式结果持久化（用户消息 + AI 回复 + 状态更新）
- 主聊天 / 重试 / 游客三类场景的后处理逻辑
- 游客会话级状态追踪（内存缓存，不写 DB）
"""

from __future__ import annotations

import logging
import time
from typing import Any

from constants import Mood
from core.database import get_conn
from services.character_affection import (
    calculate_affection_change,
    get_affection_rules,
    get_daily_cap,
    is_affection_enabled,
    update_anti_abuse_counters,
)
from services.character_state import (
    _reset_daily_fields_if_needed,
    _sanitize_state_delta,
    tick_passive_character_state,
)
from services.chat_send import (
    format_done_event,
    format_error_event,
    save_assistant_message,
    store_user_message,
    _log_failed_chat_request,
    _log_successful_chat_request,
    _persist_wi_state,
    _resolve_public_character_state,
)
from services.chat_query import ensure_opening_message
from services.chat_retry import save_regenerated_version
from services.memory_service import run_memory_summary_background
from services.usage_guard import estimate_text_tokens, log_ai_request
from services.chat_stream._sse import (
    _build_stream_done_payload,
    _build_stream_done_payload_from_persisted_result,
    _emit_stream_persist_failure,
)

logger = logging.getLogger(__name__)


# ============================================================
# 持久化层 - 消息存储与状态更新
# ============================================================

def _persist_stream_result(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    final_reply: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str | None = None,
    wi_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """持久化流式结果（用户消息 + AI 回复 + 状态更新）。"""
    save_conn = get_conn()
    message_id = None
    try:
        if user_message:
            ensure_opening_message(save_conn, user_id, character_id, commit=False)
        if user_message:
            store_user_message(save_conn, user_id, character_id, user_message, commit=False)
        message_id = save_assistant_message(save_conn, user_id, character_id, final_reply, commit=False)
        _log_successful_chat_request(
            save_conn, user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint="/api/chat/stream", estimate=estimate, reply_text=final_reply,
        )
        if delta:
            character_state = _resolve_public_character_state(
                save_conn, user_id=user_id, character_id=character_id, delta=delta,
            )
        else:
            character_state = tick_passive_character_state(
                save_conn, user_id=user_id, character_id=character_id, commit=False,
            )
        if wi_state:
            _persist_wi_state(save_conn, user_id, character_id, wi_state)
        save_conn.commit()
        return {"character_state": character_state, "message_id": message_id}
    except Exception:
        save_conn.rollback()
        raise
    finally:
        save_conn.close()


def _postprocess_main_stream_result(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    final_text: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str,
    character: dict[str, Any],
    wi_state: dict[str, Any] | None = None,
):
    """主聊天流式后处理（持久化 + 后台摘要）。"""
    try:
        persisted_result = _persist_stream_result(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            final_reply=final_text, estimate=estimate, delta=delta,
            user_message=user_message, wi_state=wi_state,
        )
    except Exception as exc:
        yield _emit_stream_persist_failure(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint="/api/chat/stream", estimate=estimate,
            error_detail=f"persist_failed: {exc}", reply_text=final_text,
            client_message="消息保存失败，请稍后再试",
        )
        return
    run_memory_summary_background(user_id, character_id, character)
    yield format_done_event(
        _build_stream_done_payload_from_persisted_result(reply=final_text, persisted_result=persisted_result)
    )


def _postprocess_regenerate_or_continue_result(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    message_id: str,
    endpoint: str,
    estimate: dict[str, int],
    is_append: bool,
    base_reply: str,
    operation: str,
    final_text: str,
    delta: dict[str, Any] | None,
):
    """重试流式后处理（regenerate / continue）。"""
    try:
        save_conn = get_conn()
        try:
            save_regenerated_version(save_conn, message_id, final_text, is_append=is_append, commit=False)
            _log_successful_chat_request(
                save_conn, user_id=user_id, guest_ip=guest_ip, character_id=character_id,
                endpoint=endpoint, estimate=estimate, reply_text=final_text,
            )
            # 重新生成/续写只改已有助手消息。原始发送已更新过关系状态，
            # 这里不能再次应用 STATE_UPDATE，否则反复重试会刷动好感度。
            raw_state = _resolve_public_character_state(
                save_conn, user_id=user_id, character_id=character_id, delta=None,
            )
            save_conn.commit()
        except Exception as exc:
            save_conn.rollback()
            yield _emit_stream_persist_failure(
                user_id=user_id, guest_ip=guest_ip, character_id=character_id,
                endpoint=endpoint, estimate=estimate,
                error_detail=f"persist_failed: {exc}", reply_text=final_text,
                client_message="保存失败，请稍后再试",
            )
            return
        finally:
            save_conn.close()
    except Exception as outer_exc:
        logger.warning(f"[{endpoint.split('/')[-1]}] outer error before done: {outer_exc}", exc_info=True)
        yield format_error_event("保存失败，请稍后再试")
        return

    # 触发后台记忆摘要刷新（与主聊天流保持一致）
    run_memory_summary_background(user_id, character_id)

    yield format_done_event(
        _build_stream_done_payload(
            reply=f"{base_reply}{final_text}" if is_append else final_text,
            fallback=False, character_state=raw_state, message_id=message_id,
            operation=operation, appended_text=final_text if is_append else None,
            summary_enabled=True,
        )
    )


# ============================================================
# 游客状态追踪（会话级内存缓存，不持久化）
# ============================================================

_guest_state_cache: dict[str, dict[str, Any]] = {}
_GUEST_STATE_CACHE_TTL = 3600
_GUEST_STATE_CACHE_MAX = 10000


def _evict_expired_guest_states(now: float) -> None:
    """清理过期的游客状态条目，防止内存无限增长。"""
    expired = [k for k, v in _guest_state_cache.items()
               if now - v.get("_cached_at", 0) >= _GUEST_STATE_CACHE_TTL]
    for k in expired:
        _guest_state_cache.pop(k, None)


def _get_guest_state(guest_ip: str, character_id: str) -> dict[str, Any]:
    """读取或创建游客状态（带 TTL 自动过期 + 上限淘汰）。"""
    key = f"{guest_ip}:{character_id}"
    now = time.time()
    if key in _guest_state_cache:
        entry = _guest_state_cache[key]
        if now - entry.get("_cached_at", 0) < _GUEST_STATE_CACHE_TTL:
            return entry
    # 惰性清理过期条目
    _evict_expired_guest_states(now)
    # 超上限时淘汰最旧的条目
    if len(_guest_state_cache) >= _GUEST_STATE_CACHE_MAX:
        oldest = min(_guest_state_cache, key=lambda k: _guest_state_cache[k].get("_cached_at", 0))
        _guest_state_cache.pop(oldest, None)
    state = {
        "affection": 0,
        "story_phase": "stranger",
        "mood": "neutral",
        "custom_vars": {},
        "_daily_event_counts": {},
        "_daily_affection_gained": 0,
        "_last_event_timestamps": {},
        "_daily_reset_date": "",
        "_cached_at": now,
    }
    _guest_state_cache[key] = state
    return state


def get_guest_character_state_for_prompt(
    guest_ip: str,
    character_id: str,
) -> dict[str, Any]:
    """读取游客 prompt 使用的状态快照，返回副本避免构建 prompt 时污染缓存。"""
    state = _get_guest_state(guest_ip, character_id)
    public_state = {k: v for k, v in state.items() if not k.startswith("_")}
    public_state["custom_vars"] = dict(public_state.get("custom_vars") or {})
    return public_state


def _compute_guest_character_state(
    conn,
    guest_ip: str,
    character_id: str,
    delta: dict[str, Any] | None,
) -> dict[str, Any]:
    """为游客计算角色状态（使用与登录用户相同的计算逻辑，但不写 DB）。"""
    if delta is None:
        state = _get_guest_state(guest_ip, character_id)
        return {k: v for k, v in state.items() if not k.startswith("_")}

    delta = _sanitize_state_delta(delta)
    state = _get_guest_state(guest_ip, character_id)
    state = _reset_daily_fields_if_needed(state)

    affection = state["affection"]
    mood = state["mood"]

    if is_affection_enabled(conn, character_id):
        if "event" in delta:
            event_name = str(delta["event"]).strip().lower()
            rules = get_affection_rules(conn, character_id)
            daily_cap = get_daily_cap(conn, character_id)
            affection_change, _ = calculate_affection_change(
                event_name, rules, state, daily_cap=daily_cap,
            )
            state = update_anti_abuse_counters(state, event_name, affection_change)
            affection = max(0, min(100, affection + affection_change))
        elif "affection" in delta:
            raw = str(delta["affection"]).strip()
            try:
                if raw.startswith("+"):
                    affection = max(0, min(100, affection + int(raw[1:])))
                elif raw.startswith("-"):
                    affection = max(0, min(100, affection - int(raw[1:])))
                else:
                    affection = max(0, min(100, int(raw)))
            except ValueError:
                pass

    if "mood" in delta:
        val = str(delta["mood"]).strip().lower()
        if val in [m.value for m in Mood]:
            mood = val

    state["affection"] = affection
    state["mood"] = mood
    state["_cached_at"] = time.time()
    _guest_state_cache[f"{guest_ip}:{character_id}"] = state

    return {k: v for k, v in state.items() if not k.startswith("_")}


def _postprocess_guest_stream_result_impl(
    reply_text: str,
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None = None,
):
    """游客流式后处理实现（记录日志 + 计算会话级角色状态）。"""
    log_conn = get_conn()
    try:
        output_tokens = estimate_text_tokens(reply_text)
        log_ai_request(
            log_conn, user_id=None, guest_ip=guest_ip, character_id=character_id,
            endpoint="/api/chat/guest-stream",
            request_chars=estimate["chars"],
            estimated_input_tokens=estimate["tokens"],
            estimated_output_tokens=output_tokens,
            total_estimated_tokens=estimate["tokens"] + output_tokens,
            used_fallback=False, status="success", error_detail="",
        )
        log_conn.commit()
    except Exception:
        log_conn.rollback()
        logger.warning("AI 请求日志写入失败", exc_info=True)
    finally:
        log_conn.close()

    character_state = None
    state_conn = get_conn()
    try:
        character_state = _compute_guest_character_state(
            state_conn, guest_ip, character_id, delta,
        )
    except Exception:
        logger.warning("游客状态计算失败 guest_ip=%s char=%s", guest_ip, character_id, exc_info=True)
    finally:
        state_conn.close()
    return {
        "reply": reply_text,
        "history_count": 0,
        "summary_enabled": False,
        "character_state": character_state,
    }


def _postprocess_guest_stream_result(
    final_text: str,
    delta: dict[str, Any] | None = None,
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    """游客流式后处理（SSE 事件格式）。"""
    yield format_done_event(
        _postprocess_guest_stream_result_impl(
            final_text, guest_ip=guest_ip, character_id=character_id, estimate=estimate,
            delta=delta,
        )
    )
