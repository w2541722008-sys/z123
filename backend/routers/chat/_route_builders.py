"""
路由参数构建模块 - 组装各路由所需的参数 / response

职责：
- 从 DB 获取上下文、构建 Prompt、计算预算
- 从 prepared state 中提取字段，构建 postprocess / response 参数
- 为每个路由提供直接的路由入口
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from core.auth import CurrentUser
from core.schemas import ChatSendPayload, GuestChatPayload
from services.chat_send import (
    _build_guest_stream_messages,
    _build_stream_prepare_result,
    _prepare_ai_budget,
    _prepare_user_chat_request,
)
from services.chat_query import get_character_or_404
from services.chat_retry import _prepare_regenerate_or_continue_request as _retry_prepare_request
from services.plan_service import GUEST_PLAN, get_plan_policy
from services.rate_limit import get_request_client_ip

from services.chat_stream_service import (
    _build_main_stream_postprocess,
    _build_guest_stream_postprocess,
    _build_main_stream_response,
    _build_guest_stream_response,
    _stream_regenerate_or_continue_events,
)


# ============================================================
# 字段提取器 — 从 StreamPrepareResult 中提取路由所需字段
# ============================================================
def _read_main_stream_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
    return {
        "guest_ip": prepared["guest_ip"],
        "ai_config": prepared["ai_config"],
        "character": prepared["character"],
        "clean_text": prepared["clean_text"],
        "stream_messages": prepared["stream_messages"],
        "estimate": prepared["estimate"],
    }


def _read_guest_stream_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
    return {
        "guest_ip": prepared["guest_ip"],
        "ai_config": prepared["ai_config"],
        "stream_messages": prepared["stream_messages"],
        "estimate": prepared["estimate"],
    }


def _read_retry_stream_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
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


# ============================================================
# 请求准备函数
# ============================================================
def _prepare_guest_stream_request(conn, *, payload: GuestChatPayload, request: Request) -> dict[str, Any]:
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


def _read_stream_state_with_conn(conn, prepare_fn, read_fn, **kwargs):
    prepared = prepare_fn(conn, **kwargs)
    return read_fn(prepared)


# ============================================================
# 路由入口
# ============================================================
def _build_main_route_response(
    *,
    conn,
    user: CurrentUser,
    payload: ChatSendPayload,
    request: Request,
) -> StreamingResponse:
    stream_state = _read_stream_state_with_conn(
        conn,
        _prepare_user_chat_request,
        _read_main_stream_prepared,
        user=user,
        payload=payload,
        guest_ip=get_request_client_ip(request),
    )
    postprocess = _build_main_stream_postprocess(
        user_id=user.id,
        guest_ip=stream_state["guest_ip"],
        character_id=payload.character_id,
        estimate=stream_state["estimate"],
        user_message=stream_state["clean_text"],
        character=stream_state["character"],
    )
    return _build_main_stream_response(
        stream_messages=stream_state["stream_messages"],
        ai_config=stream_state["ai_config"],
        user_id=user.id,
        guest_ip=stream_state["guest_ip"],
        character_id=payload.character_id,
        estimate=stream_state["estimate"],
        postprocess=postprocess,
    )


def _build_guest_route_response(
    *,
    conn,
    payload: GuestChatPayload,
    request: Request,
) -> StreamingResponse:
    stream_state = _read_stream_state_with_conn(
        conn,
        _prepare_guest_stream_request,
        _read_guest_stream_prepared,
        payload=payload,
        request=request,
    )
    postprocess = _build_guest_stream_postprocess(
        guest_ip=stream_state["guest_ip"],
        character_id=payload.character_id,
        estimate=stream_state["estimate"],
    )
    return _build_guest_stream_response(
        stream_messages=stream_state["stream_messages"],
        ai_config=stream_state["ai_config"],
        guest_ip=stream_state["guest_ip"],
        character_id=payload.character_id,
        estimate=stream_state["estimate"],
        postprocess=postprocess,
    )


def _build_retry_route_response(
    *,
    conn,
    user: CurrentUser,
    request: Request,
    message_id: str,
    operation: str,
    endpoint: str,
    is_append: bool,
) -> StreamingResponse:
    stream_state = _read_stream_state_with_conn(
        conn,
        _retry_prepare_request,
        _read_retry_stream_prepared,
        user=user,
        message_id=message_id,
        guest_ip=get_request_client_ip(request),
        operation=operation,
    )
    return _stream_regenerate_or_continue_events(
        user_id=user.id,
        guest_ip=stream_state["guest_ip"],
        character_id=stream_state["character_id"],
        message_id=message_id,
        endpoint=endpoint,
        estimate=stream_state["estimate"],
        ai_config=stream_state["ai_config"],
        stream_messages=stream_state["stream_messages"],
        is_append=is_append,
        base_reply=stream_state.get("current_content", ""),
        operation=operation,
    )
