"""
聊天路由 - 处理 AI 对话（同步和流式）

端点：
    POST /api/chat/send         - 同步发送消息
    POST /api/chat/stream       - 流式发送消息（SSE）
    POST /api/chat/guest-stream - 游客试聊（无需登录）

流式响应格式（Server-Sent Events）：
    - event: chunk, data: {text: "..."}      # 逐字返回
    - event: done, data: {reply: "...", character_state: {...}}  # 完成

主要流程：
    1. 准备聊天上下文（角色信息、历史消息、记忆摘要）
    2. 构建分层提示词（系统提示 + 记忆 + 历史消息）
    3. 调用 AI 生成回复（同步或流式）
    4. 保存消息到数据库
    5. 更新角色状态（好感度、心情等）
    6. 触发后台记忆摘要（异步）
"""

from __future__ import annotations

# 标准库导入
import logging
import os
from functools import partial
from typing import Any, TypedDict
from typing_extensions import NotRequired

# 第三方库导入
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

# 本地模块导入
from auth import CurrentUser, get_current_user
from config import (
    AI_CHAT_MAX_OUTPUT_TOKENS,
    CHAT_RATE_LIMIT_COUNT,
    CHAT_RATE_LIMIT_WINDOW_SECONDS,
    GUEST_CHAT_RATE_LIMIT_COUNT,
    GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS,
)
from database import get_conn
from model_adapter import get_ai_config
from models import ChatSendPayload, ContinuePayload, GuestChatPayload, RegeneratePayload
from prompt_assembler import build_layered_chat_messages
from services.plan_service import GUEST_PLAN, get_plan_policy
from services.rate_limit import enforce_rate_limit, get_request_client_ip
from services.usage_guard import (
    enforce_daily_budget,
    estimate_messages_tokens,
    estimate_text_tokens,
    log_ai_request,
)
from services.character_state import apply_state_delta, get_character_state
from services.chat_stream_service import (
    StreamConsumeDeps,
    StreamShellDeps,
    RetryPostprocessDeps,
    PersistStreamDeps,
    MainPostprocessDeps,
    _build_sse_response,
    _build_stream_done_payload,
    _build_stream_done_payload_from_persisted_result as _build_stream_done_payload_from_persisted_result_impl,
    _build_streaming_chat_response as _build_streaming_chat_response_impl,
    _consume_stream_result as _consume_stream_result_impl,
    _persist_stream_result as _persist_stream_result_impl,
    _postprocess_main_stream_result as _postprocess_main_stream_result_impl,
    _postprocess_regenerate_or_continue_result as _postprocess_regenerate_or_continue_result_impl,
    _public_character_state,
    _stream_ai_completion,
)
from services.memory_service import parse_state_update_tag, run_memory_summary_background
from services.chat_service import (
    AIChatError,
    _build_chat_send_response,
    _build_guest_quota_payload,
    _build_guest_stream_messages,
    _build_prompt_context_payload,
    _build_stream_prepare_result,
    _build_user_stream_messages_and_budget,
    _log_failed_chat_request,
    _log_successful_chat_request,
    _normalize_non_empty_message,
    _prepare_ai_budget,
    _prepare_user_ai_budget,
    _prepare_user_chat_request,
    _prepare_regenerate_or_continue_request,
    _message_projection,
    _resolve_public_character_state,
    build_reply_with_fallback,
    count_chat_messages,
    format_done_event,
    format_error_event,
    format_sse,
    get_character_or_404,
    save_assistant_message,
    save_regenerated_version,
    store_user_message,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class StreamPrepareResult(TypedDict):
    guest_ip: str
    ai_config: dict[str, Any]
    character: dict[str, Any]
    clean_text: str
    stream_messages: list[dict[str, str]]
    estimate: dict[str, int]
    recent_messages: NotRequired[list[dict[str, Any]]]
    memory_summary: NotRequired[str]
    related_assets: NotRequired[list[Any]]
    character_id: NotRequired[str]
    current_content: NotRequired[str]


def _default_stream_headers() -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}



def _default_stream_error_message() -> str:
    return "网络波动，请稍后再试"



def _bind_stream_postprocess(fn, **kwargs):
    def bound(final_text: str, delta: dict[str, Any] | None = None):
        return fn(final_text=final_text, delta=delta, **kwargs)

    return bound



def _consume_stream_result(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
):
    return (yield from _consume_stream_result_impl(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        stream_error_message=stream_error_message,
        deps=StreamConsumeDeps(
            stream_ai_completion=_stream_ai_completion,
            log_chat_failure=_log_failed_chat_request,
            estimate_output_tokens=estimate_text_tokens,
            parse_stream_reply=parse_state_update_tag,
            format_error_event=format_error_event,
        ),
    ))



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
    consume_stream_result=_consume_stream_result,
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
    headers: dict[str, str] | None = None,
):
    return _build_streaming_chat_response_impl(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        stream_error_message=stream_error_message,
        postprocess=postprocess,
        deps=StreamShellDeps(
            build_sse_response=_build_sse_response,
            stream_with_postprocess=_stream_with_postprocess,
        ),
        headers=headers,
    )



def _build_default_stream_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    postprocess,
    stream_error_message: str | None = None,
    headers: dict[str, str] | None = None,
):
    return _build_streaming_chat_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        stream_error_message=stream_error_message or _default_stream_error_message(),
        postprocess=postprocess,
        headers=headers or _default_stream_headers(),
    )



def _build_persist_stream_deps() -> PersistStreamDeps:
    return PersistStreamDeps(
        get_conn=get_conn,
        store_user_message=store_user_message,
        save_assistant_message=save_assistant_message,
        log_successful_chat_request=_log_successful_chat_request,
        resolve_public_character_state=_resolve_public_character_state,
    )



def _emit_stream_persist_failure(
    *,
    user_id: int,
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



def _build_main_postprocess_deps() -> MainPostprocessDeps:
    return MainPostprocessDeps(
        persist_stream_result=_persist_stream_result,
        emit_stream_persist_failure=_emit_stream_persist_failure,
        build_done_payload_from_persisted_result=lambda *, reply, persisted_result: _build_stream_done_payload_from_persisted_result_impl(
            reply=reply,
            persisted_result=persisted_result,
            build_stream_done_payload=_build_stream_done_payload,
        ),
        run_memory_summary_background=run_memory_summary_background,
        format_done_event=format_done_event,
    )



def _build_retry_postprocess_deps() -> RetryPostprocessDeps:
    return RetryPostprocessDeps(
        get_conn=get_conn,
        save_regenerated_version=save_regenerated_version,
        log_successful_chat_request=_log_successful_chat_request,
        resolve_public_character_state=_resolve_public_character_state,
        emit_stream_persist_failure=_emit_stream_persist_failure,
        build_stream_done_payload=_build_stream_done_payload,
        format_done_event=format_done_event,
        format_error_event=format_error_event,
        logger=logger,
    )



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
        _legacy_postprocess_guest_stream_result_impl(
            final_text,
            guest_ip=guest_ip,
            character_id=character_id,
            estimate=estimate,
        )
    )



def _build_main_stream_postprocess(
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    user_message: str,
    character: dict[str, Any],
):
    return _bind_stream_postprocess(
        _postprocess_main_stream_result_impl,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        estimate=estimate,
        user_message=user_message,
        character=character,
        deps=_build_main_postprocess_deps(),
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
    user_id: int,
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
        _postprocess_regenerate_or_continue_result_impl,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        message_id=message_id,
        endpoint=endpoint,
        estimate=estimate,
        is_append=is_append,
        base_reply=base_reply,
        operation=operation,
        deps=_build_retry_postprocess_deps(),
    )



def _build_main_stream_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    postprocess,
):
    return _build_default_stream_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint="/api/chat/stream",
        estimate=estimate,
        postprocess=postprocess,
    )



def _build_guest_stream_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    postprocess,
):
    return _build_default_stream_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=None,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint="/api/chat/guest-stream",
        estimate=estimate,
        postprocess=postprocess,
    )



def _build_retry_stream_response(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    postprocess,
):
    return _build_default_stream_response(
        stream_messages=stream_messages,
        ai_config=ai_config,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        estimate=estimate,
        postprocess=postprocess,
    )



def _stream_regenerate_or_continue_events(
    *,
    user_id: int,
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



def _stream_chat_events(
    *,
    stream_messages: list[dict[str, str]],
    ai_config: dict[str, Any],
    user_id: int | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    stream_error_message: str,
    postprocess,
):
    try:
        reply_text = ""
        for chunk in build_reply_with_fallback(
            character={"id": character_id},
            recent_messages=stream_messages,
            memory_summary="",
            related_assets=[],
            user_name="游客" if user_id is None else "用户",
            conn=None,
            user_id=user_id,
            ai_config=ai_config,
            commit=False,
            stream=True,
        ):
            if isinstance(chunk, str):
                reply_text += chunk
                yield format_sse("chunk", {"text": chunk})

        done_payload = postprocess(reply_text)
        yield format_done_event(done_payload)
    except Exception as exc:
        logger.exception("stream chat events failed")
        yield format_error_event(stream_error_message)
        raise exc



def _legacy_postprocess_stream_result_impl(
    reply_text: str,
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    user_message: str,
    character: dict[str, Any],
):
    conn = get_conn()
    try:
        save_assistant_message(conn, user_id, character_id, reply_text, commit=False)
        history_count = count_chat_messages(conn, user_id, character_id)
        character_state = _resolve_public_character_state(
            conn,
            user_id=user_id,
            character_id=character_id,
            delta=apply_state_delta(character, user_message, reply_text),
        )
        _log_successful_chat_request(
            conn,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint="/api/chat/stream",
            estimate=estimate,
            reply_text=reply_text,
        )
        conn.commit()
        return {
            "reply": reply_text,
            "history_count": history_count,
            "summary_enabled": True,
            "character_state": character_state,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def _legacy_postprocess_guest_stream_result_impl(
    reply_text: str,
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    log_ai_request(
        user_id=None,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint="/api/chat/guest-stream",
        estimate=estimate,
        success=True,
        error_detail=None,
    )
    return {
        "reply": reply_text,
        "history_count": 0,
        "summary_enabled": False,
        "character_state": None,
    }



def _legacy_postprocess_regenerate_or_continue_result_impl(
    reply_text: str,
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    message_id: str,
    endpoint: str,
    estimate: dict[str, int],
    operation: str,
):
    conn = get_conn()
    try:
        save_regenerated_version(
            conn,
            user_id=user_id,
            character_id=character_id,
            message_id=message_id,
            reply=reply_text,
            is_append=(operation == "continue"),
            commit=False,
        )
        history_count = count_chat_messages(conn, user_id, character_id)
        character_state = _resolve_public_character_state(
            conn,
            user_id=user_id,
            character_id=character_id,
            delta=None,
        )
        _log_successful_chat_request(
            conn,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint=endpoint,
            estimate=estimate,
            reply_text=reply_text,
        )
        conn.commit()
        return {
            "reply": reply_text,
            "history_count": history_count,
            "summary_enabled": True,
            "character_state": character_state,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def _prepare_stream_request_with_conn(prepare_fn, **kwargs):
    conn = get_conn()
    try:
        return prepare_fn(conn, **kwargs)
    finally:
        conn.close()



def _read_stream_state_with_conn(prepare_fn, read_fn, **kwargs):
    prepared = _prepare_stream_request_with_conn(prepare_fn, **kwargs)
    return read_fn(prepared)



def _read_main_stream_prepared(prepared: StreamPrepareResult) -> dict[str, Any]:
    return {
        "guest_ip": prepared["guest_ip"],
        "ai_config": prepared["ai_config"],
        "character": prepared["character"],
        "clean_text": prepared["clean_text"],
        "stream_messages": prepared["stream_messages"],
        "estimate": prepared["estimate"],
    }



def _read_guest_stream_prepared(prepared: StreamPrepareResult) -> dict[str, Any]:
    return {
        "guest_ip": prepared["guest_ip"],
        "ai_config": prepared["ai_config"],
        "stream_messages": prepared["stream_messages"],
        "estimate": prepared["estimate"],
    }



def _read_retry_stream_prepared(prepared: StreamPrepareResult) -> dict[str, Any]:
    result = {
        "guest_ip": prepared["guest_ip"],
        "character_id": prepared["character_id"],
        "stream_messages": prepared["stream_messages"],
        "ai_config": prepared["ai_config"],
        "estimate": prepared["estimate"],
    }
    if "current_content" in prepared:
        result["current_content"] = prepared["current_content"]
    return result



def _read_chat_send_prepared(prepared: StreamPrepareResult) -> dict[str, Any]:
    return {
        "guest_ip": prepared["guest_ip"],
        "ai_config": prepared["ai_config"],
        "character": prepared["character"],
        "clean_text": prepared["clean_text"],
        "recent_messages": prepared["recent_messages"],
        "memory_summary": prepared["memory_summary"],
        "related_assets": prepared["related_assets"],
        "estimate": prepared["estimate"],
    }



def _build_main_route_postprocess_kwargs(
    *,
    stream_state: dict[str, Any],
    user_id: int,
    character_id: str,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        **_build_guest_route_postprocess_kwargs(
            stream_state=stream_state,
            character_id=character_id,
        ),
        "user_message": stream_state["clean_text"],
        "character": stream_state["character"],
    }



def _build_guest_route_postprocess_kwargs(
    *,
    stream_state: dict[str, Any],
    character_id: str,
) -> dict[str, Any]:
    return {
        "guest_ip": stream_state["guest_ip"],
        "character_id": character_id,
        "estimate": stream_state["estimate"],
    }



def _build_main_route_response_kwargs(
    *,
    stream_state: dict[str, Any],
    user_id: int,
    character_id: str,
) -> dict[str, Any]:
    return _build_common_stream_response_kwargs(
        stream_state=stream_state,
        character_id=character_id,
        user_id=user_id,
    )



def _build_guest_route_response_kwargs(
    *,
    stream_state: dict[str, Any],
    character_id: str,
) -> dict[str, Any]:
    return _build_common_stream_response_kwargs(
        stream_state=stream_state,
        character_id=character_id,
    )



def _build_stream_state_builder(target, **fixed_kwargs):
    def builder(stream_state: dict[str, Any]) -> dict[str, Any]:
        return target(
            stream_state=stream_state,
            **fixed_kwargs,
        )

    return builder



def _build_main_route_postprocess_builder(
    *,
    user_id: int,
    character_id: str,
):
    return _build_stream_state_builder(
        _build_main_route_postprocess_kwargs,
        user_id=user_id,
        character_id=character_id,
    )



def _build_main_route_response_builder(
    *,
    user_id: int,
    character_id: str,
):
    return _build_stream_state_builder(
        _build_main_route_response_kwargs,
        user_id=user_id,
        character_id=character_id,
    )



def _build_guest_route_postprocess_builder(*, character_id: str):
    return _build_stream_state_builder(
        _build_guest_route_postprocess_kwargs,
        character_id=character_id,
    )



def _build_guest_route_response_builder(*, character_id: str):
    return _build_stream_state_builder(
        _build_guest_route_response_kwargs,
        character_id=character_id,
    )



def _build_common_stream_response_kwargs(
    *,
    stream_state: dict[str, Any],
    character_id: str,
    user_id: int | None = None,
) -> dict[str, Any]:
    result = {
        "stream_messages": stream_state["stream_messages"],
        "ai_config": stream_state["ai_config"],
        "guest_ip": stream_state["guest_ip"],
        "character_id": character_id,
        "estimate": stream_state["estimate"],
    }
    if user_id is not None:
        result["user_id"] = user_id
    return result



def _build_retry_stream_event_kwargs(
    *,
    stream_state: dict[str, Any],
    user_id: int,
    message_id: str,
    endpoint: str,
    is_append: bool,
    operation: str,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "guest_ip": stream_state["guest_ip"],
        "character_id": stream_state["character_id"],
        "message_id": message_id,
        "endpoint": endpoint,
        "estimate": stream_state["estimate"],
        "ai_config": stream_state["ai_config"],
        "stream_messages": stream_state["stream_messages"],
        "is_append": is_append,
        "base_reply": stream_state.get("current_content", ""),
        "operation": operation,
    }



def _build_retry_route_prepare_kwargs(
    *,
    user: CurrentUser,
    request: Request,
    message_id: str,
    operation: str,
) -> dict[str, Any]:
    return {
        "user": user,
        "message_id": message_id,
        "guest_ip": get_request_client_ip(request),
        "operation": operation,
    }



def _build_retry_route_event_builder(
    *,
    user_id: int,
    message_id: str,
    endpoint: str,
    is_append: bool,
    operation: str,
):
    def builder(stream_state: dict[str, Any]) -> dict[str, Any]:
        return _build_retry_stream_event_kwargs(
            stream_state=stream_state,
            user_id=user_id,
            message_id=message_id,
            endpoint=endpoint,
            is_append=is_append,
            operation=operation,
        )

    return builder



def _build_retry_route_bindings(
    *,
    user_id: int,
    message_id: str,
    endpoint: str,
    is_append: bool,
    operation: str,
) -> dict[str, Any]:
    return {
        "build_response": _stream_regenerate_or_continue_events,
        "response_kwargs_builder": _build_retry_route_event_builder(
            user_id=user_id,
            message_id=message_id,
            endpoint=endpoint,
            is_append=is_append,
            operation=operation,
        ),
    }



def _execute_stream_response(
    *,
    build_response,
    response_kwargs_builder,
    stream_state: dict[str, Any],
):
    return build_response(**response_kwargs_builder(stream_state))



def _build_composed_response_kwargs_builder(
    *,
    build_postprocess,
    postprocess_kwargs_builder,
    build_response,
    response_kwargs_builder,
):
    def builder(stream_state: dict[str, Any]) -> dict[str, Any]:
        return {
            "build_postprocess": build_postprocess,
            "postprocess_kwargs": postprocess_kwargs_builder(stream_state),
            "build_response": build_response,
            "response_kwargs": response_kwargs_builder(stream_state),
        }

    return builder



def _compose_stream_response(
    *,
    build_postprocess,
    postprocess_kwargs: dict[str, Any],
    build_response,
    response_kwargs: dict[str, Any],
):
    postprocess = build_postprocess(**postprocess_kwargs)
    return build_response(
        postprocess=postprocess,
        **response_kwargs,
    )



def _build_stream_route_bindings(
    *,
    character_id: str,
    build_postprocess,
    build_response,
    postprocess_kwargs_builder,
    response_kwargs_builder,
) -> dict[str, Any]:
    return {
        "build_postprocess": build_postprocess,
        "build_response": build_response,
        "postprocess_kwargs_builder": postprocess_kwargs_builder(
            character_id=character_id,
        ),
        "response_kwargs_builder": response_kwargs_builder(
            character_id=character_id,
        ),
    }



def _build_main_route_bindings(*, user_id: int, character_id: str) -> dict[str, Any]:
    return _build_stream_route_bindings(
        character_id=character_id,
        build_postprocess=_build_main_stream_postprocess,
        build_response=_build_main_stream_response,
        postprocess_kwargs_builder=lambda *, character_id: _build_main_route_postprocess_builder(
            user_id=user_id,
            character_id=character_id,
        ),
        response_kwargs_builder=lambda *, character_id: _build_main_route_response_builder(
            user_id=user_id,
            character_id=character_id,
        ),
    )



def _build_guest_route_bindings(*, character_id: str) -> dict[str, Any]:
    return _build_stream_route_bindings(
        character_id=character_id,
        build_postprocess=_build_guest_stream_postprocess,
        build_response=_build_guest_stream_response,
        postprocess_kwargs_builder=_build_guest_route_postprocess_builder,
        response_kwargs_builder=_build_guest_route_response_builder,
    )



def _build_composed_route_response(
    *,
    prepare_fn,
    read_fn,
    prepare_kwargs: dict[str, Any],
    build_postprocess,
    postprocess_kwargs_builder,
    build_response,
    response_kwargs_builder,
) -> StreamingResponse:
    stream_state = _read_stream_state_with_conn(
        prepare_fn,
        read_fn,
        **prepare_kwargs,
    )
    return _execute_stream_response(
        build_response=_compose_stream_response,
        response_kwargs_builder=_build_composed_response_kwargs_builder(
            build_postprocess=build_postprocess,
            postprocess_kwargs_builder=postprocess_kwargs_builder,
            build_response=build_response,
            response_kwargs_builder=response_kwargs_builder,
        ),
        stream_state=stream_state,
    )



def _build_retry_route_response(
    *,
    user: CurrentUser,
    request: Request,
    message_id: str,
    operation: str,
    endpoint: str,
    is_append: bool,
) -> StreamingResponse:
    stream_state = _read_stream_state_with_conn(
        _prepare_regenerate_or_continue_request,
        _read_retry_stream_prepared,
        **_build_retry_route_prepare_kwargs(
            user=user,
            request=request,
            message_id=message_id,
            operation=operation,
        ),
    )
    return _execute_stream_response(
        stream_state=stream_state,
        **_build_retry_route_bindings(
            user_id=user.id,
            message_id=message_id,
            endpoint=endpoint,
            is_append=is_append,
            operation=operation,
        ),
    )



def _build_main_route_response(
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    request: Request,
) -> StreamingResponse:
    return _build_composed_route_response(
        prepare_fn=_prepare_user_chat_request,
        read_fn=_read_main_stream_prepared,
        prepare_kwargs={
            "user": user,
            "payload": payload,
            "guest_ip": get_request_client_ip(request),
        },
        **_build_main_route_bindings(
            user_id=user.id,
            character_id=payload.character_id,
        ),
    )



def _build_guest_route_response(
    *,
    payload: GuestChatPayload,
    request: Request,
) -> StreamingResponse:
    return _build_composed_route_response(
        prepare_fn=_prepare_guest_stream_request,
        read_fn=_read_guest_stream_prepared,
        prepare_kwargs={
            "payload": payload,
            "request": request,
        },
        **_build_guest_route_bindings(character_id=payload.character_id),
    )



def _enforce_user_chat_rate_limit(user_id: int, *, detail: str) -> None:
    enforce_rate_limit(
        "chat_user",
        str(user_id),
        limit=CHAT_RATE_LIMIT_COUNT,
        window_seconds=CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail=detail,
    )



def _build_chat_send_request_context(
    *,
    prepared_state: dict[str, Any],
    character_id: str,
) -> dict[str, Any]:
    return {
        "guest_ip": prepared_state["guest_ip"],
        "character_id": character_id,
        "estimate": prepared_state["estimate"],
    }



def _build_chat_send_success_kwargs(
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    prepared_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "user": user,
        "payload": payload,
        **_build_chat_send_request_context(
            prepared_state=prepared_state,
            character_id=payload.character_id,
        ),
        "character": prepared_state["character"],
        "recent_messages": prepared_state["recent_messages"],
        "memory_summary": prepared_state["memory_summary"],
        "related_assets": prepared_state["related_assets"],
        "ai_config": prepared_state["ai_config"],
    }



def _build_chat_send_reply_kwargs(
    *,
    conn,
    user: CurrentUser,
    character: dict[str, Any],
    recent_messages: list[dict[str, Any]],
    memory_summary: str,
    related_assets: list[Any],
    ai_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "character": character,
        "recent_messages": recent_messages,
        "memory_summary": memory_summary,
        "related_assets": related_assets,
        "user_name": user.nickname,
        "conn": conn,
        "user_id": user.id,
        "ai_config": ai_config,
        "commit": False,
    }



def _persist_stream_result(
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    final_reply: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str | None = None,
):
    return _persist_stream_result_impl(
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        final_reply=final_reply,
        estimate=estimate,
        delta=delta,
        user_message=user_message,
        deps=_build_persist_stream_deps(),
    )



def _finalize_chat_send_success(
    conn,
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    reply: str,
) -> tuple[int, dict[str, Any]]:
    save_assistant_message(conn, user_id, character_id, reply, commit=False)
    history_count = count_chat_messages(conn, user_id, character_id)
    character_state = _resolve_public_character_state(
        conn,
        user_id=user_id,
        character_id=character_id,
        delta=None,
    )
    _log_successful_chat_request(
        conn,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint="/api/chat/send",
        estimate=estimate,
        reply_text=reply,
    )
    conn.commit()
    return history_count, character_state



def _execute_chat_send_success_flow(
    conn,
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    guest_ip: str,
    estimate: dict[str, int],
    character: dict[str, Any],
    recent_messages: list[dict[str, Any]],
    memory_summary: str,
    related_assets: list[Any],
    ai_config: dict[str, Any],
) -> tuple[str, int, dict[str, Any]]:
    reply, _new_state = build_reply_with_fallback(
        **_build_chat_send_reply_kwargs(
            conn=conn,
            user=user,
            character=character,
            recent_messages=recent_messages,
            memory_summary=memory_summary,
            related_assets=related_assets,
            ai_config=ai_config,
        )
    )

    history_count, character_state = _finalize_chat_send_success(
        conn,
        user_id=user.id,
        guest_ip=guest_ip,
        character_id=payload.character_id,
        estimate=estimate,
        reply=reply,
    )
    return reply, history_count, character_state



def _build_chat_send_failure_kwargs(
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    prepared_state: dict[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    return {
        "user_id": user.id,
        **_build_chat_send_request_context(
            prepared_state=prepared_state,
            character_id=payload.character_id,
        ),
        "error_detail": str(exc),
    }



def _process_chat_send_exception(
    conn,
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    prepared_state: dict[str, Any],
    exc: Exception,
) -> None:
    _handle_chat_send_failure(
        conn,
        **_build_chat_send_failure_kwargs(
            user=user,
            payload=payload,
            prepared_state=prepared_state,
            exc=exc,
        ),
    )
    _rethrow_chat_send_exception(exc)



def _handle_chat_send_failure(
    conn,
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
    error_detail: str,
) -> None:
    conn.rollback()
    _log_failed_chat_request(
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint="/api/chat/send",
        estimate=estimate,
        error_detail=error_detail,
    )



def _rethrow_chat_send_exception(exc: Exception) -> None:
    if isinstance(exc, AIChatError):
        raise HTTPException(status_code=503, detail="网络波动，请稍后再试")
    raise exc



def _run_chat_send_transaction(
    conn,
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    prepared: StreamPrepareResult,
) -> dict[str, Any]:
    prepared_state = _read_chat_send_prepared(prepared)

    store_user_message(conn, user.id, payload.character_id, prepared_state["clean_text"], commit=False)
    try:
        reply, history_count, character_state = _execute_chat_send_success_flow(
            conn,
            **_build_chat_send_success_kwargs(
                user=user,
                payload=payload,
                prepared_state=prepared_state,
            )
        )
    except Exception as exc:
        _process_chat_send_exception(
            conn,
            user=user,
            payload=payload,
            prepared_state=prepared_state,
            exc=exc,
        )

    return _build_chat_send_response(
        reply=reply,
        history_count=history_count,
        character_state=character_state,
    )



def _build_chat_send_route_response(
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    request: Request,
) -> dict[str, Any]:
    conn = get_conn()
    try:
        prepared = _prepare_user_chat_request(
            conn,
            user=user,
            payload=payload,
            guest_ip=get_request_client_ip(request),
        )
        return _run_chat_send_transaction(
            conn,
            user=user,
            payload=payload,
            prepared=prepared,
        )
    finally:
        conn.close()



@router.post("/chat/send")
def chat_send(
    payload: ChatSendPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    _enforce_user_chat_rate_limit(user.id, detail="聊天请求过于频繁")
    return _build_chat_send_route_response(user=user, payload=payload, request=request)


@router.post("/chat/stream")
def chat_stream(
    payload: ChatSendPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    return _build_main_route_response(user=user, payload=payload, request=request)


@router.post("/chat/guest-stream")
def chat_guest_stream(
    payload: GuestChatPayload,
    request: Request,
):
    return _build_guest_route_response(payload=payload, request=request)



def _build_retry_route_with_rate_limit(
    *,
    user: CurrentUser,
    request: Request,
    message_id: str,
    operation: str,
    endpoint: str,
    is_append: bool,
) -> StreamingResponse:
    _enforce_user_chat_rate_limit(user.id, detail="操作过于频繁")
    return _build_retry_route_response(
        user=user,
        request=request,
        message_id=message_id,
        operation=operation,
        endpoint=endpoint,
        is_append=is_append,
    )



@router.post("/chat/regenerate")
def chat_regenerate(
    payload: RegeneratePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    return _build_retry_route_with_rate_limit(
        user=user,
        request=request,
        message_id=payload.message_id,
        operation="regenerate",
        endpoint="/api/chat/regenerate",
        is_append=False,
    )



@router.post("/chat/continue")
def chat_continue(
    payload: ContinuePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    return _build_retry_route_with_rate_limit(
        user=user,
        request=request,
        message_id=payload.message_id,
        operation="continue",
        endpoint="/api/chat/continue",
        is_append=True,
    )



def _prepare_guest_stream_request(conn, *, payload: GuestChatPayload, request: Request) -> StreamPrepareResult:
    guest_ip = get_request_client_ip(request)
    character = get_character_or_404(conn, payload.character_id, viewer_plan=GUEST_PLAN)
    clean_text, prompt_messages = _build_guest_stream_messages(character, payload.message, payload.guest_history)
    guest_policy = get_plan_policy(GUEST_PLAN)
    budget = _prepare_ai_budget(
        conn,
        stream_messages=prompt_messages,
        model_profile=guest_policy["model_profile"],
        token_limit=guest_policy["token_limit"],
        token_limit_detail="今日游客体验额度已用完，登录后可继续聊天",
        guest_ip=guest_ip,
    )
    return _build_stream_prepare_result(
        guest_ip=guest_ip,
        stream_payload={
            "stream_messages": prompt_messages,
            "ai_config": budget["ai_config"],
            "estimate": budget["estimate"],
        },
        character=character,
        clean_text=clean_text,
    )



def _prepare_prompt_context_result(
    context_tuple: tuple[dict[str, Any], str, list[dict[str, Any]], str]
) -> dict[str, Any]:
    character, clean_text, recent_messages, memory_summary = context_tuple
    return {
        "character": character,
        "clean_text": clean_text,
        "recent_messages": recent_messages,
        "memory_summary": memory_summary,
    }



def _prepare_regenerate_context_result(
    context_tuple: tuple[dict[str, Any], str, list[dict[str, Any]], str, str]
) -> dict[str, Any]:
    character, character_id, recent_messages, memory_summary, current_content = context_tuple
    return {
        "character": character,
        "character_id": character_id,
        "recent_messages": recent_messages,
        "memory_summary": memory_summary,
        "current_content": current_content,
    }



def _prepare_user_stream_context(
    conn,
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    persist_user_message: bool,
) -> dict[str, Any]:
    return _prepare_prompt_context_result(
        _build_prompt_context_payload(
            conn,
            user.id,
            payload.character_id,
            payload.message,
            persist_user_message=persist_user_message,
            viewer_plan=user.effective_plan,
            commit=False,
        )
    )



def _prepare_retry_stream_context(
    conn,
    *,
    user: CurrentUser,
    message_id: str,
    operation: str,
) -> dict[str, Any]:
    return _prepare_regenerate_context_result(
        _message_projection(
            conn,
            user_id=user.id,
            message_id=message_id,
            operation=operation,
            commit=False,
        )
    )



def _prepare_retry_stream_messages(
    *,
    user: CurrentUser,
    payload_context: dict[str, Any],
) -> dict[str, Any]:
    stream_messages = build_layered_chat_messages(
        character=payload_context["character"],
        recent_messages=payload_context["recent_messages"],
        memory_summary=payload_context["memory_summary"],
        related_assets=[],
        user_name=user.nickname,
    )
    budget = _prepare_user_ai_budget(
        stream_messages=stream_messages,
        plan_name=user.effective_plan,
        user_id=user.id,
        guest_ip=None,
    )
    return {
        "stream_messages": stream_messages,
        "ai_config": budget["ai_config"],
        "estimate": budget["estimate"],
    }



def _prepare_user_stream_payload(
    conn,
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    guest_ip: str,
) -> StreamPrepareResult:
    context_payload = _prepare_user_stream_context(
        conn,
        user=user,
        payload=payload,
        persist_user_message=False,
    )
    related_assets = []
    built = _build_user_stream_messages_and_budget(
        conn,
        user=user,
        character_id=payload.character_id,
        character=context_payload["character"],
        prompt_messages=context_payload["recent_messages"],
        memory_summary=context_payload["memory_summary"],
        related_assets=related_assets,
    )
    return _build_stream_prepare_result(
        guest_ip=guest_ip,
        stream_payload={
            "stream_messages": built["stream_messages"],
            "ai_config": built["ai_config"],
            "estimate": built["estimate"],
        },
        character=context_payload["character"],
        clean_text=context_payload["clean_text"],
        recent_messages=context_payload["recent_messages"],
        memory_summary=context_payload["memory_summary"],
        related_assets=related_assets,
    )



def _prepare_regenerate_or_continue_request(
    conn,
    *,
    user: CurrentUser,
    message_id: str,
    guest_ip: str,
    operation: str,
) -> StreamPrepareResult:
    context_payload = _prepare_retry_stream_context(
        conn,
        user=user,
        message_id=message_id,
        operation=operation,
    )
    built = _prepare_retry_stream_messages(user=user, payload_context=context_payload)
    return _build_stream_prepare_result(
        guest_ip=guest_ip,
        stream_payload={
            "stream_messages": built["stream_messages"],
            "ai_config": built["ai_config"],
            "estimate": built["estimate"],
        },
        character=context_payload["character"],
        clean_text="",
        character_id=context_payload["character_id"],
        current_content=context_payload["current_content"],
    )
