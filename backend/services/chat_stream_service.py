"""
聊天流式服务 - SSE 流式响应、持久化、后处理

职责：
- AI 流式补全与 SSE 事件生成
- 流式结果持久化（消息存储、状态更新）
- 各类流式端点的后处理逻辑
- 响应构建器（主聊天、游客、重试）
"""

from __future__ import annotations

import json
import time
import logging
from typing import Any, Callable

from starlette.responses import StreamingResponse

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS
from core.database import ConnType, get_conn
from core.model_adapter import stream_chat_completion
from services.chat_send import (
    format_sse,
    format_done_event,
    format_error_event,
    save_assistant_message,
    store_user_message,
    _log_failed_chat_request,
    _log_successful_chat_request,
    _resolve_public_character_state,
)
from services.chat_retry import save_regenerated_version
from services.memory_service import run_memory_summary_background
from services.usage_guard import estimate_text_tokens, log_ai_request
from utils.stream_filter import normalize_reply_text, sanitize_stream_chunk, parse_state_update_tag

logger = logging.getLogger(__name__)
SSE_STREAM_TIMEOUT = 120


# ============================================================
# 基础设施层 - AI 流式补全与 SSE 响应
# ============================================================

def _stream_ai_completion(stream_messages: list, ai_config: dict):
    """流式调用 AI 并生成 SSE chunk 事件。

    返回值：
        (cleaned_reply, None, delta_or_none) — 成功时
        (partial_reply, error_string, None) — 失败时
    """
    full_reply = ""
    stream_state = {"buffer": "", "in_think": False, "in_state_update": False, "_state_update_parts": []}
    stream_start = time.monotonic()
    stream_iter = None
    try:
        stream_iter = stream_chat_completion(stream_messages, ai_config, max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS)
        for chunk in stream_iter:
            if time.monotonic() - stream_start > SSE_STREAM_TIMEOUT:
                raise TimeoutError(f"SSE 流式响应超时（{SSE_STREAM_TIMEOUT}秒）")
            visible_chunk = sanitize_stream_chunk(chunk, stream_state)
            if not visible_chunk:
                continue
            full_reply += visible_chunk
            yield format_sse("chunk", {"text": visible_chunk})
        if stream_state.get("buffer") and not stream_state.get("in_think"):
            tail = str(stream_state["buffer"])
            if tail:
                full_reply += tail
                yield format_sse("chunk", {"text": tail})
        final_reply_raw = normalize_reply_text(full_reply)
        if not final_reply_raw:
            raise RuntimeError("模型返回了空内容")
        # 从流式过滤过程中累积的 STATE_UPDATE 标签内容解析状态增量
        delta = _parse_accumulated_state_update(stream_state.get("_state_update_parts", []))
        return final_reply_raw, None, delta
    except Exception as exc:
        return full_reply, str(exc), None
    finally:
        if stream_iter is not None and hasattr(stream_iter, 'close'):
            stream_iter.close()


def _build_sse_response(event_generator, *, headers: dict[str, str] | None = None) -> StreamingResponse:
    """构建 SSE StreamingResponse。"""
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


def _default_stream_headers() -> dict[str, str]:
    """默认流式响应头。"""
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _default_stream_error_message() -> str:
    """默认流式错误提示。"""
    return "网络波动，请稍后再试"


def _is_circuit_breaker_error(error_msg: str) -> bool:
    """判断是否为熔断器错误（用于区分用户提示文案）。"""
    return "circuit" in error_msg.lower() or "熔断" in error_msg or "暂时不可用" in error_msg


def _parse_accumulated_state_update(parts: list[str]) -> dict[str, Any] | None:
    """从流式过滤累积的 STATE_UPDATE 片段中解析状态增量 JSON。

    仅使用首个 STATE_UPDATE 块（与同步路径 parse_state_update_tag 行为一致）。
    """
    if not parts:
        return None
    raw_json = parts[0].strip()
    if not raw_json:
        return None
    try:
        delta = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    return delta if isinstance(delta, dict) else None


def _build_stream_done_payload(
    *,
    reply: str,
    fallback: bool,
    character_state: dict[str, Any] | None = None,
    message_id: str | None = None,
    operation: str | None = None,
    appended_text: str | None = None,
    guest: bool = False,
    summary_enabled: bool | None = None,
) -> dict[str, Any]:
    """构建流式完成事件的 payload。"""
    payload: dict[str, Any] = {"reply": reply, "fallback": fallback}
    if character_state is not None:
        payload["character_state"] = character_state
    if message_id is not None:
        payload["message_id"] = message_id
    if operation is not None:
        payload["operation"] = operation
    if appended_text is not None:
        payload["appended_text"] = appended_text
    if guest:
        payload["guest"] = True
    if summary_enabled is not None:
        payload["summary_enabled"] = summary_enabled
    return payload


def _build_stream_done_payload_from_persisted_result(
    *, reply: str, persisted_result: dict[str, Any],
) -> dict[str, Any]:
    """从持久化结果构建 done payload。"""
    return _build_stream_done_payload(
        reply=reply, fallback=False,
        character_state=persisted_result["character_state"],
        message_id=persisted_result["message_id"],
        summary_enabled=True,
    )


def _consume_stream_result(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int | str | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
):
    """消费流式结果并处理错误。"""
    final_raw, stream_error, delta = yield from _stream_ai_completion(stream_messages, ai_config)
    if stream_error:
        _log_failed_chat_request(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint=endpoint, estimate=estimate, error_detail=stream_error,
            estimated_output_tokens=estimate_text_tokens(final_raw or ""),
        )
        # 区分熔断器和一般错误，给用户准确的反馈
        if _is_circuit_breaker_error(stream_error):
            yield format_error_event("AI 服务暂时繁忙，请稍后重试")
        else:
            yield format_error_event(stream_error_message)
        return None
    # 优先使用流式过滤过程中提取的 delta（避免被 sanitize_stream_chunk 剥离）
    if delta is not None:
        return final_raw, delta
    return parse_state_update_tag(final_raw)


def _stream_with_postprocess(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: Any,
    user_id: int | str | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
    postprocess,
):
    """流式生成 + 后处理。"""
    stream_result = yield from _consume_stream_result(
        stream_messages=stream_messages, ai_config=ai_config,
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        endpoint=endpoint, estimate=estimate, stream_error_message=stream_error_message,
    )
    if stream_result is None:
        return
    final_text, delta = stream_result
    yield from postprocess(final_text, delta)


def _build_streaming_chat_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: Any,
    user_id: int | str | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
    postprocess: Callable[..., dict[str, Any]],
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """构建完整的流式聊天响应。"""
    def event_generator():
        yield from _stream_with_postprocess(
            stream_messages=stream_messages, ai_config=ai_config,
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint=endpoint, estimate=estimate,
            stream_error_message=stream_error_message, postprocess=postprocess,
        )
    return _build_sse_response(event_generator, headers=headers)


def _emit_stream_persist_failure(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    error_detail: str,
    reply_text: str,
    client_message: str,
):
    """发送持久化失败事件。"""
    _log_failed_chat_request(
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        endpoint=endpoint, estimate=estimate, error_detail=error_detail,
        estimated_output_tokens=estimate_text_tokens(reply_text),
    )
    return format_error_event(client_message)


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
) -> dict[str, Any]:
    """持久化流式结果（用户消息 + AI 回复 + 状态更新）。"""
    save_conn = get_conn()
    message_id = None
    try:
        if user_message:
            store_user_message(save_conn, user_id, character_id, user_message, commit=False)
        message_id = save_assistant_message(save_conn, user_id, character_id, final_reply, commit=False)
        _log_successful_chat_request(
            save_conn, user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint="/api/chat/stream", estimate=estimate, reply_text=final_reply,
        )
        character_state = _resolve_public_character_state(
            save_conn, user_id=user_id, character_id=character_id, delta=delta,
        )
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
):
    """主聊天流式后处理（持久化 + 后台摘要）。"""
    try:
        persisted_result = _persist_stream_result(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            final_reply=final_text, estimate=estimate, delta=delta, user_message=user_message,
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
            raw_state = _resolve_public_character_state(
                save_conn, user_id=user_id, character_id=character_id, delta=delta,
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
_GUEST_STATE_CACHE_TTL = 3600  # 1 小时


def _get_guest_state(guest_ip: str, character_id: str) -> dict[str, Any]:
    """读取或创建游客状态（带 TTL 自动过期）。"""
    key = f"{guest_ip}:{character_id}"
    now = time.time()
    if key in _guest_state_cache:
        entry = _guest_state_cache[key]
        if now - entry.get("_cached_at", 0) < _GUEST_STATE_CACHE_TTL:
            return entry
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


def _compute_guest_character_state(
    conn: ConnType,
    guest_ip: str,
    character_id: str,
    delta: dict[str, Any] | None,
) -> dict[str, Any]:
    """为游客计算角色状态（使用与登录用户相同的计算逻辑，但不写 DB）。"""
    if delta is None:
        state = _get_guest_state(guest_ip, character_id)
        return {k: v for k, v in state.items() if not k.startswith("_")}

    from services.character_affection import (
        _get_affection_rules,
        _get_daily_cap,
        _calculate_affection_change,
        _update_anti_abuse_counters,
        is_affection_enabled,
    )
    from services.character_state import (
        _sanitize_state_delta,
        _reset_daily_fields_if_needed,
    )
    from constants import Mood

    delta = _sanitize_state_delta(delta)
    state = _get_guest_state(guest_ip, character_id)
    state = _reset_daily_fields_if_needed(state)

    affection = state["affection"]
    mood = state["mood"]

    if is_affection_enabled(conn, character_id):
        if "event" in delta:
            event_name = str(delta["event"]).strip().lower()
            rules = _get_affection_rules(conn, character_id)
            daily_cap = _get_daily_cap(conn, character_id)
            affection_change, _ = _calculate_affection_change(
                event_name, rules, state, daily_cap=daily_cap,
            )
            state = _update_anti_abuse_counters(state, event_name, affection_change)
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
    """游客流式后处理。"""
    yield format_done_event(
        _postprocess_guest_stream_result_impl(
            final_text, guest_ip=guest_ip, character_id=character_id, estimate=estimate,
            delta=delta,
        )
    )


# ============================================================
# 响应构建器 - 各类流式端点
# ============================================================

def _bind_stream_postprocess(fn, **kwargs):
    """绑定后处理函数的参数。"""
    def bound(final_text: str, delta: dict[str, Any] | None = None):
        return fn(final_text=final_text, delta=delta, **kwargs)
    return bound


def _build_main_stream_postprocess(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    user_message: str,
    character: dict[str, Any],
):
    """构建主聊天后处理函数。"""
    return _bind_stream_postprocess(
        _postprocess_main_stream_result,
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        estimate=estimate, user_message=user_message, character=character,
    )


def _build_guest_stream_postprocess(
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    """构建游客后处理函数。"""
    return _bind_stream_postprocess(
        _postprocess_guest_stream_result,
        guest_ip=guest_ip, character_id=character_id, estimate=estimate,
    )


def _build_retry_stream_postprocess(
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
):
    """构建重试后处理函数。"""
    return _bind_stream_postprocess(
        _postprocess_regenerate_or_continue_result,
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        message_id=message_id, endpoint=endpoint, estimate=estimate,
        is_append=is_append, base_reply=base_reply, operation=operation,
    )


def _build_main_stream_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    postprocess: Callable[..., dict[str, Any]],
) -> StreamingResponse:
    """构建主聊天流式响应。"""
    return _build_streaming_chat_response(
        stream_messages=stream_messages, ai_config=ai_config,
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        endpoint="/api/chat/stream", estimate=estimate,
        stream_error_message=_default_stream_error_message(),
        postprocess=postprocess, headers=_default_stream_headers(),
    )


def _build_guest_stream_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    postprocess: Callable[..., dict[str, Any]],
) -> StreamingResponse:
    """构建游客流式响应。"""
    return _build_streaming_chat_response(
        stream_messages=stream_messages, ai_config=ai_config,
        user_id=None, guest_ip=guest_ip, character_id=character_id,
        endpoint="/api/chat/guest-stream", estimate=estimate,
        stream_error_message=_default_stream_error_message(),
        postprocess=postprocess, headers=_default_stream_headers(),
    )


def _build_retry_stream_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    postprocess: Callable[..., dict[str, Any]],
) -> StreamingResponse:
    """构建重试流式响应。"""
    return _build_streaming_chat_response(
        stream_messages=stream_messages, ai_config=ai_config,
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        endpoint=endpoint, estimate=estimate,
        stream_error_message=_default_stream_error_message(),
        postprocess=postprocess, headers=_default_stream_headers(),
    )


def _stream_regenerate_or_continue_events(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    message_id: str,
    endpoint: str,
    estimate: dict[str, int],
    ai_config: dict[str, Any],
    stream_messages: list[dict[str, str]],
    is_append: bool,
    base_reply: str = "",
    operation: str,
) -> StreamingResponse:
    """构建 regenerate/continue 流式响应。"""
    return _build_retry_stream_response(
        stream_messages=stream_messages, ai_config=ai_config,
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        endpoint=endpoint, estimate=estimate,
        postprocess=_build_retry_stream_postprocess(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            message_id=message_id, endpoint=endpoint, estimate=estimate,
            is_append=is_append, base_reply=base_reply, operation=operation,
        ),
    )
