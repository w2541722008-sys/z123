"""
聊天路由 - 处理 AI 对话（同步和流式）

端点：
    POST /api/chat/send         - 同步发送消息
    POST /api/chat/stream       - 流式发送消息（SSE）
    POST /api/chat/guest-stream - 游客试聊（无需登录）
    POST /api/chat/regenerate   - 重新生成回复
    POST /api/chat/continue     - 续写回复
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import CurrentUser, get_current_user
from core.config import (
    CHAT_RATE_LIMIT_COUNT,
    CHAT_RATE_LIMIT_WINDOW_SECONDS,
    GUEST_CHAT_RATE_LIMIT_COUNT,
    GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS,
)
from core.database import ConnType, get_db_dep
from core.schemas import (
    ChatSendPayload,
    ContinuePayload,
    GuestChatPayload,
    RegeneratePayload,
)
from services.chat_send import (
    AIChatError,
    _build_chat_send_response,
    _log_failed_chat_request,
    _log_successful_chat_request,
    _prepare_user_chat_request,
    _resolve_public_character_state,
    build_reply_with_fallback,
    save_assistant_message,
    store_user_message,
)
from services.chat_query import count_chat_messages
from services.rate_limit import enforce_rate_limit, get_request_client_ip

from ._route_builders import (
    _build_main_route_response,
    _build_guest_route_response,
    _build_retry_route_response,
)

router = APIRouter(tags=["chat"])


# ============================================================
# 限流
# ============================================================
def _enforce_user_chat_rate_limit(user_id: int | str, *, detail: str) -> None:
    enforce_rate_limit(
        "chat_user",
        str(user_id),
        limit=CHAT_RATE_LIMIT_COUNT,
        window_seconds=CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail=detail,
    )


# ============================================================
# 同步聊天发送流程
# ============================================================
def _run_chat_send_transaction(
    conn,
    *,
    user: CurrentUser,
    payload: ChatSendPayload,
    prepared: dict[str, Any],
) -> dict[str, Any]:
    clean_text = prepared["clean_text"]
    character = prepared["character"]
    ai_config = prepared["ai_config"]
    recent_messages = prepared["recent_messages"]
    memory_summary = prepared["memory_summary"]
    related_assets = prepared["related_assets"]
    estimate = prepared["estimate"]
    guest_ip = prepared["guest_ip"]

    store_user_message(conn, user.id, payload.character_id, clean_text, commit=False)
    try:
        reply, _new_state = build_reply_with_fallback(
            character=character,
            recent_messages=recent_messages,
            memory_summary=memory_summary,
            related_assets=related_assets,
            user_name=user.nickname,
            conn=conn,
            user_id=user.id,
            ai_config=ai_config,
            commit=False,
        )

        save_assistant_message(conn, user.id, payload.character_id, reply, commit=False)
        history_count = count_chat_messages(conn, user.id, payload.character_id)
        character_state = _resolve_public_character_state(
            conn,
            user_id=user.id,
            character_id=payload.character_id,
            delta=None,
        )
        _log_successful_chat_request(
            conn,
            user_id=user.id,
            guest_ip=guest_ip,
            character_id=payload.character_id,
            endpoint="/api/chat/send",
            estimate=estimate,
            reply_text=reply,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        _log_failed_chat_request(
            user_id=user.id,
            guest_ip=guest_ip,
            character_id=payload.character_id,
            endpoint="/api/chat/send",
            estimate=estimate,
            error_detail=str(exc),
        )
        if isinstance(exc, AIChatError):
            raise HTTPException(status_code=503, detail="网络波动，请稍后再试")
        raise

    return _build_chat_send_response(
        reply=reply,
        history_count=history_count,
        character_state=character_state,
    )


def _build_chat_send_route_response(
    *,
    conn,
    user: CurrentUser,
    payload: ChatSendPayload,
    request: Request,
) -> dict[str, Any]:
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


# ============================================================
# 路由端点
# ============================================================
@router.post("/chat/send")
def chat_send(
    payload: ChatSendPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
):
    _enforce_user_chat_rate_limit(user.id, detail="聊天请求过于频繁")
    return _build_chat_send_route_response(
        conn=conn, user=user, payload=payload, request=request
    )


@router.post("/chat/stream")
def chat_stream(
    payload: ChatSendPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
):
    _enforce_user_chat_rate_limit(user.id, detail="聊天请求过于频繁")
    return _build_main_route_response(
        conn=conn, user=user, payload=payload, request=request
    )


@router.post("/chat/guest-stream")
def chat_guest_stream(
    payload: GuestChatPayload,
    request: Request,
    conn: ConnType = Depends(get_db_dep),
):
    guest_ip = get_request_client_ip(request)
    enforce_rate_limit(
        "chat_guest",
        guest_ip,
        limit=GUEST_CHAT_RATE_LIMIT_COUNT,
        window_seconds=GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail="游客请求过于频繁，请稍后再试或登录继续",
    )
    return _build_guest_route_response(conn=conn, payload=payload, request=request)


@router.post("/chat/regenerate")
def chat_regenerate(
    payload: RegeneratePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
):
    return _build_retry_route_with_rate_limit(
        conn=conn,
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
    conn: ConnType = Depends(get_db_dep),
):
    return _build_retry_route_with_rate_limit(
        conn=conn,
        user=user,
        request=request,
        message_id=payload.message_id,
        operation="continue",
        endpoint="/api/chat/continue",
        is_append=True,
    )




# ============================================================
# 内部辅助
# ============================================================
def _build_retry_route_with_rate_limit(
    *,
    conn: ConnType,
    user: CurrentUser,
    request: Request,
    message_id: str,
    operation: str,
    endpoint: str,
    is_append: bool,
):
    _enforce_user_chat_rate_limit(user.id, detail="操作过于频繁")
    return _build_retry_route_response(
        conn=conn,
        user=user,
        request=request,
        message_id=message_id,
        operation=operation,
        endpoint=endpoint,
        is_append=is_append,
    )
