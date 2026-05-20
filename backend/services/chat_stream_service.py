"""
聊天流式服务 — 向后兼容 shim，实际实现在 services/chat_stream/ 子包中。

所有公共 API 通过 services.chat_stream 重新导出。
"""

from __future__ import annotations

from services.chat_stream import (
    _bind_stream_postprocess,
    _build_main_stream_postprocess,
    _build_guest_stream_postprocess,
    _build_retry_stream_postprocess,
    _build_main_stream_response,
    _build_guest_stream_response,
    _build_retry_stream_response,
    _stream_regenerate_or_continue_events,
)
from services.chat_stream._sse import (
    _build_sse_response,
    _build_stream_done_payload,
    _build_stream_done_payload_from_persisted_result,
    _default_stream_headers,
    _default_stream_error_message,
)

__all__ = [
    "_bind_stream_postprocess",
    "_build_main_stream_postprocess",
    "_build_guest_stream_postprocess",
    "_build_retry_stream_postprocess",
    "_build_main_stream_response",
    "_build_guest_stream_response",
    "_build_retry_stream_response",
    "_stream_regenerate_or_continue_events",
    "_build_sse_response",
    "_build_stream_done_payload",
    "_build_stream_done_payload_from_persisted_result",
    "_default_stream_headers",
    "_default_stream_error_message",
]
