"""
聊天流式服务 - 处理 SSE 流式响应的核心逻辑

核心功能：
    - 流式 AI 补全的消费者和生成器
    - 流式结果持久化（保存用户/助手消息）
    - 重试（regenerate/continue）后处理
    - 游客流式后处理
    - 流式响应构建
"""

from __future__ import annotations

import time
import logging
from typing import Any, Callable

from starlette.responses import StreamingResponse

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS
from core.database import get_conn
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
from services.stream_filter import normalize_reply_text, sanitize_stream_chunk, parse_state_update_tag
from services.memory_service import run_memory_summary_background
from services.usage_guard import estimate_text_tokens, log_ai_request


logger = logging.getLogger(__name__)

SSE_STREAM_TIMEOUT = 120


# ============================================================
# 流式 AI 补全
# ============================================================
def _stream_ai_completion(stream_messages: list, ai_config: dict):
    full_reply = ""
    stream_state = {"buffer": "", "in_think": False, "in_state_update": False}
    stream_start = time.monotonic()

    try:
        for chunk in stream_chat_completion(
            stream_messages,
            ai_config,
            max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS,
        ):
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

        return final_reply_raw, None

    except Exception as exc:
        return full_reply, str(exc)


# ============================================================
# SSE 响应构建
# ============================================================
def _build_sse_response(event_generator, *, headers: dict[str, str] | None = None) -> StreamingResponse:
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


def _default_stream_headers() -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _default_stream_error_message() -> str:
    return "网络波动，请稍后再试"


# ============================================================
# Done payload 构建
# ============================================================
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
    payload: dict[str, Any] = {
        "reply": reply,
        "fallback": fallback,
    }
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
    *,
    reply: str,
    persisted_result: dict[str, Any],
) -> dict[str, Any]:
    return _build_stream_done_payload(
        reply=reply,
        fallback=False,
        character_state=persisted_result["character_state"],
        message_id=persisted_result["message_id"],
        summary_enabled=True,
    )


# ============================================================
# 流式消费与后处理管道
# ============================================================
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
    final_raw, stream_error = yield from _stream_ai_completion(stream_messages, ai_config)
    if stream_error:
        _log_failed_chat_request(
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint=endpoint,
            estimate=estimate,
            error_detail=stream_error,
            estimated_output_tokens=estimate_text_tokens(final_raw or ""),
        )
        yield format_error_event(stream_error_message)
        return None
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
    stream_result = yield from _consume_stream_result(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        stream_error_message=stream_error_message,
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
    def event_generator():
        yield from _stream_with_postprocess(
            stream_messages=stream_messages,
            ai_config=ai_config,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint=endpoint,
            estimate=estimate,
            stream_error_message=stream_error_message,
            postprocess=postprocess,
        )

    return _build_sse_response(event_generator, headers=headers)


# ============================================================
# 持久化
# ============================================================
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
    _log_failed_chat_request(
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        error_detail=error_detail,
        estimated_output_tokens=estimate_text_tokens(reply_text),
    )
    return format_error_event(client_message)


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
    save_conn = get_conn()
    message_id = None
    try:
        if user_message:
            store_user_message(save_conn, user_id, character_id, user_message, commit=False)
        message_id = save_assistant_message(save_conn, user_id, character_id, final_reply, commit=False)
        _log_successful_chat_request(
            save_conn,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint="/api/chat/stream",
            estimate=estimate,
            reply_text=final_reply,
        )
        character_state = _resolve_public_character_state(
            save_conn,
            user_id=user_id,
            character_id=character_id,
            delta=delta,
        )
        save_conn.commit()
        return {
            "character_state": character_state,
            "message_id": message_id,
        }
    except Exception:
        save_conn.rollback()
        raise
    finally:
        save_conn.close()


# ============================================================
# 后处理：主流程（stream）
# ============================================================
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
    try:
        persisted_result = _persist_stream_result(
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            final_reply=final_text,
            estimate=estimate,
            delta=delta,
            user_message=user_message,
        )
    except Exception as exc:
        yield _emit_stream_persist_failure(
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint="/api/chat/stream",
            estimate=estimate,
            error_detail=f"persist_failed: {exc}",
            reply_text=final_text,
            client_message="消息保存失败，请稍后再试",
        )
        return

    run_memory_summary_background(user_id, character_id, character)

    yield format_done_event(
        _build_stream_done_payload_from_persisted_result(
            reply=final_text,
            persisted_result=persisted_result,
        )
    )


# ============================================================
# 后处理：重试（regenerate/continue）
# ============================================================
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
    try:
        save_conn = get_conn()
        try:
            save_regenerated_version(
                save_conn, message_id, final_text, is_append=is_append, commit=False
            )

            _log_successful_chat_request(
                save_conn,
                user_id=user_id,
                guest_ip=guest_ip,
                character_id=character_id,
                endpoint=endpoint,
                estimate=estimate,
                reply_text=final_text,
            )

            raw_state = _resolve_public_character_state(
                save_conn,
                user_id=user_id,
                character_id=character_id,
                delta=delta,
            )

            save_conn.commit()

        except Exception as exc:
            save_conn.rollback()
            yield _emit_stream_persist_failure(
                user_id=user_id,
                guest_ip=guest_ip,
                character_id=character_id,
                endpoint=endpoint,
                estimate=estimate,
                error_detail=f"persist_failed: {exc}",
                reply_text=final_text,
                client_message="保存失败，请稍后再试",
            )
            return
        finally:
            save_conn.close()
    except Exception as outer_exc:
        logger.warning(
            f"[{endpoint.split('/')[-1]}] outer error before done: {outer_exc}",
            exc_info=True,
        )
        yield format_error_event("保存失败，请稍后再试")
        return

    yield format_done_event(
        _build_stream_done_payload(
            reply=f"{base_reply}{final_text}" if is_append else final_text,
            fallback=False,
            character_state=raw_state,
            message_id=message_id,
            operation=operation,
            appended_text=final_text if is_append else None,
            summary_enabled=True,
        )
    )


# ============================================================
# 后处理：游客流式
# ============================================================
def _postprocess_guest_stream_result_impl(
    reply_text: str,
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    log_conn = get_conn()
    try:
        output_tokens = estimate_text_tokens(reply_text)
        log_ai_request(
            log_conn,
            user_id=None,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint="/api/chat/guest-stream",
            request_chars=estimate["chars"],
            estimated_input_tokens=estimate["tokens"],
            estimated_output_tokens=output_tokens,
            total_estimated_tokens=estimate["tokens"] + output_tokens,
            used_fallback=False,
            status="success",
            error_detail="",
        )
        log_conn.commit()
    except Exception:
        log_conn.rollback()
    finally:
        log_conn.close()
    return {
        "reply": reply_text,
        "history_count": 0,
        "summary_enabled": False,
        "character_state": None,
    }


def _postprocess_guest_stream_result(
    final_text: str,
    delta: dict[str, Any] | None = None,
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    _ = delta
    yield format_done_event(
        _postprocess_guest_stream_result_impl(
            final_text,
            guest_ip=guest_ip,
            character_id=character_id,
            estimate=estimate,
        )
    )


# ============================================================
# 后处理绑定与流式响应构建
# ============================================================
def _bind_stream_postprocess(fn, **kwargs):
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
    return _bind_stream_postprocess(
        _postprocess_main_stream_result,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        estimate=estimate,
        user_message=user_message,
        character=character,
    )


def _build_guest_stream_postprocess(
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    return _bind_stream_postprocess(
        _postprocess_guest_stream_result,
        guest_ip=guest_ip,
        character_id=character_id,
        estimate=estimate,
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
    return _bind_stream_postprocess(
        _postprocess_regenerate_or_continue_result,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        message_id=message_id,
        endpoint=endpoint,
        estimate=estimate,
        is_append=is_append,
        base_reply=base_reply,
        operation=operation,
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
    return _build_streaming_chat_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint="/api/chat/stream",
        estimate=estimate,
        stream_error_message=_default_stream_error_message(),
        postprocess=postprocess,
        headers=_default_stream_headers(),
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
    return _build_streaming_chat_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=None,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint="/api/chat/guest-stream",
        estimate=estimate,
        stream_error_message=_default_stream_error_message(),
        postprocess=postprocess,
        headers=_default_stream_headers(),
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
    return _build_streaming_chat_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        stream_error_message=_default_stream_error_message(),
        postprocess=postprocess,
        headers=_default_stream_headers(),
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
    return _build_retry_stream_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        postprocess=_build_retry_stream_postprocess(
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            message_id=message_id,
            endpoint=endpoint,
            estimate=estimate,
            is_append=is_append,
            base_reply=base_reply,
            operation=operation,
        ),
    )
