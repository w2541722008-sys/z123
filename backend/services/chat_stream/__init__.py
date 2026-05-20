"""
聊天流式服务 - SSE 流式响应、持久化、后处理

子模块：
    _sse.py           — SSE 流水线基础设施（AI 调用、事件格式化、错误处理）
    _postprocess.py   — 流式结果后处理（持久化、游客状态、后台摘要）

此模块导出高层响应构建器，供路由层直接调用。
"""

from __future__ import annotations

from typing import Any, Callable

from starlette.responses import StreamingResponse

from services.chat_stream._sse import (
    _build_streaming_chat_response,
    _default_stream_headers,
    _default_stream_error_message,
)
from services.chat_stream._postprocess import (
    _postprocess_main_stream_result,
    _postprocess_regenerate_or_continue_result,
    _postprocess_guest_stream_result,
)


# ============================================================
# 后处理参数绑定
# ============================================================

def _bind_stream_postprocess(fn, **kwargs):
    """绑定后处理函数的参数。"""
    def bound(final_text: str, delta: dict[str, Any] | None = None):
        return fn(final_text=final_text, delta=delta, **kwargs)
    return bound


# ============================================================
# 后处理构建器
# ============================================================

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
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        estimate=estimate, user_message=user_message, character=character,
    )


def _build_guest_stream_postprocess(
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
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
    return _bind_stream_postprocess(
        _postprocess_regenerate_or_continue_result,
        user_id=user_id, guest_ip=guest_ip, character_id=character_id,
        message_id=message_id, endpoint=endpoint, estimate=estimate,
        is_append=is_append, base_reply=base_reply, operation=operation,
    )


# ============================================================
# 端点响应构建器
# ============================================================

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
