"""
SSE 流水线基础设施 — AI 流式补全、事件格式化、错误处理。

职责：
- 调用 AI 流式 API 并生成 SSE chunk 事件
- 构建 SSE StreamingResponse
- 流式结果消费、错误分类、状态增量解析
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from starlette.responses import StreamingResponse

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS
from core.model_adapter import stream_chat_completion
from services.chat_send import (
    format_sse,
    format_done_event,
    format_error_event,
    _log_failed_chat_request,
)
from services.usage_guard import estimate_text_tokens
from utils.stream_filter import normalize_reply_text, sanitize_stream_chunk, parse_state_update_tag

logger = logging.getLogger(__name__)
SSE_STREAM_TIMEOUT = 120


def _stream_ai_completion(stream_messages: list, ai_config: dict):
    """流式调用 AI 并生成 SSE chunk 事件。"""
    chunks: list[str] = []
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
            chunks.append(visible_chunk)
            yield format_sse("chunk", {"text": visible_chunk})
        if stream_state.get("buffer") and not stream_state.get("in_think"):
            tail = str(stream_state["buffer"])
            if tail:
                chunks.append(tail)
                yield format_sse("chunk", {"text": tail})
        full_reply = "".join(chunks)
        final_reply_raw = normalize_reply_text(full_reply)
        if not final_reply_raw:
            raise RuntimeError("模型返回了空内容")
        delta = _parse_accumulated_state_update(stream_state.get("_state_update_parts", []))
        return final_reply_raw, None, delta
    except Exception as exc:
        logger.exception("流式回复最终处理失败: %s", exc)
        return full_reply, str(exc), None
    finally:
        if stream_iter is not None and hasattr(stream_iter, 'close'):
            stream_iter.close()


def _build_sse_response(event_generator, *, headers: dict[str, str] | None = None) -> StreamingResponse:
    """构建 SSE StreamingResponse。"""
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


def _default_stream_headers() -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _default_stream_error_message() -> str:
    return "网络波动，请稍后再试"


def _is_circuit_breaker_error(error_msg: str) -> bool:
    return "circuit" in error_msg.lower() or "熔断" in error_msg or "暂时不可用" in error_msg


def _parse_accumulated_state_update(parts: list[str]) -> dict[str, Any] | None:
    """从流式过滤累积的 STATE_UPDATE 片段中解析状态增量 JSON。"""
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
        if _is_circuit_breaker_error(stream_error):
            yield format_error_event("AI 服务暂时繁忙，请稍后重试")
        else:
            yield format_error_event(stream_error_message)
        return None
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
