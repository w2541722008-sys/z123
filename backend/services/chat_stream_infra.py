from __future__ import annotations

import time
import logging
from typing import Any, Callable

from starlette.responses import StreamingResponse

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS
from core.model_adapter import stream_chat_completion
from services.chat_send import format_sse, format_done_event, format_error_event, _log_failed_chat_request
from utils.stream_filter import normalize_reply_text, sanitize_stream_chunk, parse_state_update_tag
from services.usage_guard import estimate_text_tokens

logger = logging.getLogger(__name__)
SSE_STREAM_TIMEOUT = 120


def _stream_ai_completion(stream_messages: list, ai_config: dict):
    full_reply = ""
    stream_state = {"buffer": "", "in_think": False, "in_state_update": False}
    stream_start = time.monotonic()
    try:
        for chunk in stream_chat_completion(stream_messages, ai_config, max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS):
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


def _build_sse_response(event_generator, *, headers: dict[str, str] | None = None) -> StreamingResponse:
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


def _default_stream_headers() -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _default_stream_error_message() -> str:
    return "网络波动，请稍后再试"


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
    final_raw, stream_error = yield from _stream_ai_completion(stream_messages, ai_config)
    if stream_error:
        _log_failed_chat_request(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint=endpoint, estimate=estimate, error_detail=stream_error,
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
    _log_failed_chat_request(
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        endpoint=endpoint, estimate=estimate, error_detail=error_detail,
        estimated_output_tokens=estimate_text_tokens(reply_text),
    )
    return format_error_event(client_message)
