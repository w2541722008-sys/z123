"""
聊天流式服务 - 处理 SSE 流式响应的核心逻辑

核心功能：
    - 流式 AI 补全的消费者和生成器
    - 流式结果持久化（保存用户/助手消息）
    - 重试（regenerate/continue）后处理
    - 依赖注入容器（dataclass）解耦具体实现
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from fastapi.responses import StreamingResponse

from config import AI_CHAT_MAX_OUTPUT_TOKENS
from model_adapter import stream_chat_completion
from services.chat_service import format_sse
from services.memory_service import normalize_reply_text, sanitize_stream_chunk


SSE_STREAM_TIMEOUT = 120


# ── 依赖注入容器（dataclass 替代 TypedDict，提供类型安全） ──────────────

@dataclass
class StreamConsumeDeps:
    stream_ai_completion: Callable
    log_chat_failure: Callable
    estimate_output_tokens: Callable
    parse_stream_reply: Callable
    format_error_event: Callable


@dataclass
class StreamShellDeps:
    build_sse_response: Callable
    stream_with_postprocess: Callable


@dataclass
class RetryPostprocessDeps:
    get_conn: Callable
    save_regenerated_version: Callable
    log_successful_chat_request: Callable
    resolve_public_character_state: Callable
    emit_stream_persist_failure: Callable
    build_stream_done_payload: Callable
    format_done_event: Callable
    format_error_event: Callable
    logger: Any


@dataclass
class PersistStreamDeps:
    get_conn: Callable
    store_user_message: Callable
    save_assistant_message: Callable
    log_successful_chat_request: Callable
    resolve_public_character_state: Callable


@dataclass
class MainPostprocessDeps:
    persist_stream_result: Callable
    emit_stream_persist_failure: Callable
    build_done_payload_from_persisted_result: Callable
    run_memory_summary_background: Callable
    format_done_event: Callable


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
            tail = stream_state["buffer"]
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
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


def _public_character_state(raw_state: dict[str, Any] | None) -> dict[str, Any]:
    if not raw_state:
        return {}
    return {k: v for k, v in raw_state.items() if not k.startswith("_")}


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


def _consume_stream_result(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict,
    user_id: int | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
    deps: StreamConsumeDeps,
) -> Any:
    final_raw, stream_error = yield from deps.stream_ai_completion(stream_messages, ai_config)
    if stream_error:
        deps.log_chat_failure(
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint=endpoint,
            estimate=estimate,
            error_detail=stream_error,
            estimated_output_tokens=deps.estimate_output_tokens(final_raw or ""),
        )
        yield deps.format_error_event(stream_error_message)
        return None
    return deps.parse_stream_reply(final_raw)


def _stream_with_postprocess(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: Any,
    user_id: int | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
    postprocess,
    consume_stream_result,
):
    stream_result = yield from consume_stream_result(
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
    user_id: int | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
    postprocess,
    deps: StreamShellDeps,
    headers: dict[str, str] | None = None,
):
    def event_generator():
        yield from deps.stream_with_postprocess(
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

    return deps.build_sse_response(event_generator, headers=headers)


def _postprocess_regenerate_or_continue_result(
    *,
    user_id: int,
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
    deps: RetryPostprocessDeps,
):
    try:
        save_conn = deps.get_conn()
        try:
            deps.save_regenerated_version(
                save_conn, message_id, final_text, is_append=is_append, commit=False
            )

            deps.log_successful_chat_request(
                save_conn,
                user_id=user_id,
                guest_ip=guest_ip,
                character_id=character_id,
                endpoint=endpoint,
                estimate=estimate,
                reply_text=final_text,
            )

            raw_state = deps.resolve_public_character_state(
                save_conn,
                user_id=user_id,
                character_id=character_id,
                delta=delta,
            )

            save_conn.commit()

        except Exception as exc:
            save_conn.rollback()
            yield deps.emit_stream_persist_failure(
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
        deps.logger.warning(
            f"[{endpoint.split('/')[-1]}] outer error before done: {outer_exc}",
            exc_info=True,
        )
        yield deps.format_error_event("保存失败，请稍后再试")
        return

    yield deps.format_done_event(
        deps.build_stream_done_payload(
            reply=f"{base_reply}{final_text}" if is_append else final_text,
            fallback=False,
            character_state=raw_state,
            message_id=message_id,
            operation=operation,
            appended_text=final_text if is_append else None,
            summary_enabled=True,
        )
    )


def _persist_stream_result(
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    final_reply: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str | None = None,
    deps: PersistStreamDeps,
) -> dict[str, Any]:
    save_conn = deps.get_conn()
    message_id = None
    try:
        if user_message:
            deps.store_user_message(save_conn, user_id, character_id, user_message, commit=False)
        message_id = deps.save_assistant_message(save_conn, user_id, character_id, final_reply, commit=False)
        deps.log_successful_chat_request(
            save_conn,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint="/api/chat/stream",
            estimate=estimate,
            reply_text=final_reply,
        )
        character_state = deps.resolve_public_character_state(
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


def _build_stream_done_payload_from_persisted_result(
    *,
    reply: str,
    persisted_result: dict[str, Any],
    build_stream_done_payload,
) -> dict[str, Any]:
    return build_stream_done_payload(
        reply=reply,
        fallback=False,
        character_state=persisted_result["character_state"],
        message_id=persisted_result["message_id"],
        summary_enabled=True,
    )


def _postprocess_main_stream_result(
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    final_text: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str,
    character: dict[str, Any],
    deps: MainPostprocessDeps,
):
    try:
        persisted_result = deps.persist_stream_result(
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            final_reply=final_text,
            estimate=estimate,
            delta=delta,
            user_message=user_message,
        )
    except Exception as exc:
        yield deps.emit_stream_persist_failure(
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

    deps.run_memory_summary_background(user_id, character_id, character)

    yield deps.format_done_event(
        deps.build_done_payload_from_persisted_result(
            reply=final_text,
            persisted_result=persisted_result,
        )
    )
