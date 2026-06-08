"""
聊天发送服务 - AI 回复生成、消息持久化、SSE 格式化

职责：
- 聊天上下文准备与消息存储
- AI 回复生成（含 fallback）
- SSE 事件格式化
- 预算检查与请求日志
- 流式请求构建
"""

from __future__ import annotations

import json
import os
from typing import Any

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS, logger
from core.database import ConnType, get_conn
from core.model_adapter import get_ai_config, request_chat_completion
from services.prompt_assembler import (
    PromptBuildContext,
    build_layered_chat_messages_from_context,
)
from utils.json_utils import parse_json_object, to_json_string
from services.plan_service import get_plan_policy
from services.character_state import (
    apply_state_delta,
    get_character_state,
    get_public_character_state,
)
from services.usage_guard import (
    enforce_daily_budget,
    estimate_messages_tokens,
    estimate_text_tokens,
    log_ai_request,
)
from utils.stream_filter import normalize_reply_text, parse_state_update_tag
from services.chat_query import (
    get_character_or_404,
    ensure_opening_message,
    _normalize_non_empty_message,
    _load_recent_messages_and_summary,
    get_linked_assets,
    get_last_chat_time,
)


# ============================================================
# 自定义异常
# ============================================================
class AIChatError(Exception):
    """AI 调用失败时抛出，由路由层决定如何向用户展示错误。"""


_PROMPT_RUNTIME_CUSTOM_KEYS = ("_wi_sticky", "_wi_cooldown", "_last_anchor_index")


# ============================================================
# 聊天上下文准备
# ============================================================
def prepare_chat_context(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    user_message: str,
    persist_user_message: bool = True,
    viewer_plan: str | None = None,
    *,
    commit: bool = True,
) -> tuple[Any, str, list[dict[str, str]], str]:
    """
    准备聊天所需的上下文数据。

    返回：
        (character, clean_text, recent_messages, memory_summary)
    """
    character = get_character_or_404(conn, character_id, viewer_plan=viewer_plan)
    clean_text = _normalize_non_empty_message(user_message)
    ensure_opening_message(conn, user_id, character_id, commit=False)

    if persist_user_message:
        store_user_message(conn, user_id, character_id, clean_text, commit=False)

    recent_messages, memory_summary = _load_recent_messages_and_summary(
        conn,
        user_id=user_id,
        character_id=character_id,
        clean_text=clean_text,
        persist_user_message=persist_user_message,
    )

    if commit:
        conn.commit()

    return character, clean_text, recent_messages, memory_summary


# ============================================================
# 消息保存
# ============================================================
def save_assistant_message(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    reply: str,
    *,
    commit: bool = True,
) -> str:
    """保存 AI 助手的回复到数据库。返回新消息的 ID。"""
    row = conn.execute(
        "INSERT INTO chat_messages(user_id, character_id, role, content) VALUES (%s, %s, 'assistant', %s) RETURNING id",
        (user_id, character_id, reply),
    ).fetchone()
    if commit:
        conn.commit()
    return str(row["id"]) if row else ""


def store_user_message(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    content: str,
    *,
    commit: bool = True,
) -> None:
    """保存用户消息到数据库。"""
    conn.execute(
        "INSERT INTO chat_messages(user_id, character_id, role, content) VALUES (%s, %s, 'user', %s)",
        (user_id, character_id, content),
    )
    if commit:
        conn.commit()


# ============================================================
# AI 回复生成
# ============================================================
def build_reply_with_fallback(
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    related_assets: list[Any] | None = None,
    user_name: str = "",
    conn: ConnType | None = None,
    user_id: int | str | None = None,
    ai_config: dict[str, str] | None = None,
    *,
    commit: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    """
    组装 Prompt → 调用 AI → 解析状态增量 → 返回 (cleaned_reply, new_state)。

    AI 调用失败时抛出 AIChatError，由调用方决定如何向用户展示错误。
    """
    # 读取当前关系状态
    character_state: dict[str, Any] | None = None
    last_chat_time: str | None = None
    if conn is not None and user_id is not None:
        character_state = get_character_state(conn, user_id, character["id"])
        last_chat_time = get_last_chat_time(conn, user_id, character["id"])

    messages = build_layered_chat_messages_from_context(
        PromptBuildContext(
            character=character,
            recent_messages=recent_messages,
            memory_summary=memory_summary,
            related_assets=related_assets,
            user_name=user_name,
            character_state=character_state,
            conn=conn,
            last_chat_time=last_chat_time,
            user_id=user_id,
        )
    )

    if conn is not None and user_id is not None and character_state is not None:
        _persist_wi_state(conn, user_id, character["id"], character_state)

    try:
        raw_reply = request_chat_completion(
            messages,
            ai_config or get_ai_config(os.environ),
            normalize_reply_text,
            max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS,
        )
    except Exception as e:
        raise AIChatError("AI 调用失败: %s" % e) from e

    # 解析状态增量
    cleaned_reply, delta = parse_state_update_tag(raw_reply)

    # 应用增量到 DB（失败时不阻断回复交付，但需记录完整堆栈便于排查）
    new_state: dict[str, Any] | None = None
    if delta and conn is not None and user_id is not None:
        try:
            new_state = apply_state_delta(
                conn, user_id, character["id"], delta, commit=commit
            )
        except Exception:
            logger.exception(
                "角色状态更新失败 user_id=%s character_id=%s delta=%s",
                user_id,
                character["id"],
                delta,
            )

    return cleaned_reply, new_state


# ============================================================
# SSE 格式化
# ============================================================
def format_sse(event: str, data: dict[str, Any]) -> str:
    """格式化 Server-Sent Events (SSE) 消息。"""
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))


def format_done_event(payload: dict[str, Any]) -> str:
    return format_sse("done", payload)


def format_error_event(message: str) -> str:
    return format_sse("error", {"message": message})


# ============================================================
# 预算与请求日志
# ============================================================
def _prepare_ai_budget(
    conn: ConnType,
    *,
    stream_messages: list[dict[str, str]],
    model_profile: str,
    token_limit: int,
    token_limit_detail: str,
    user_id: int | str | None = None,
    guest_ip: str = "",
) -> dict[str, Any]:
    ai_config = get_ai_config(os.environ, profile=model_profile)
    estimate = estimate_messages_tokens(stream_messages)
    planned_tokens = estimate["tokens"] + AI_CHAT_MAX_OUTPUT_TOKENS
    enforce_daily_budget(
        conn,
        user_id=user_id,
        guest_ip=guest_ip,
        planned_tokens=planned_tokens,
        token_limit=token_limit,
        token_limit_detail=token_limit_detail,
    )
    return {"ai_config": ai_config, "estimate": estimate}


def _build_prompt_context_payload(
    *,
    current_content: str,
    character: dict[str, Any],
    memory_summary: str,
    prompt_messages: list[dict[str, Any]],
    related_assets: list[Any],
) -> dict[str, Any]:
    return {
        "current_content": current_content,
        "character": character,
        "memory_summary": memory_summary,
        "prompt_messages": prompt_messages,
        "related_assets": related_assets,
    }


def _prepare_prompt_context_result(
    *,
    current_content: str,
    context_tuple: tuple[Any, str, list[dict[str, str]] | None, list[Any]],
    fallback_prompt_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    character, memory_summary, prompt_messages, related_assets = context_tuple
    return _build_prompt_context_payload(
        current_content=current_content,
        character=character,
        memory_summary=memory_summary,
        prompt_messages=(
            prompt_messages
            if prompt_messages is not None
            else (fallback_prompt_messages or [])
        ),
        related_assets=related_assets,
    )


# 游客流式函数已移入 services.chat_stream._guest，请直接从该模块导入


# ============================================================
# 用户流式构建
# ============================================================
def _build_stream_prepare_result(
    *,
    guest_ip: str,
    stream_payload: dict[str, Any],
    character: dict[str, Any] | None = None,
    clean_text: str | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
    memory_summary: str | None = None,
    related_assets: list[Any] | None = None,
    character_id: str | None = None,
    current_content: str | None = None,
    wi_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_wi_state = wi_state if wi_state is not None else stream_payload.get("wi_state")
    result = {
        "guest_ip": guest_ip,
        "stream_messages": stream_payload["stream_messages"],
        "ai_config": stream_payload["ai_config"],
        "estimate": stream_payload["estimate"],
    }
    if character is not None:
        result["character"] = character
    if clean_text is not None:
        result["clean_text"] = clean_text
    if recent_messages is not None:
        result["recent_messages"] = recent_messages
    if memory_summary is not None:
        result["memory_summary"] = memory_summary
    if related_assets is not None:
        result["related_assets"] = related_assets
    if character_id is not None:
        result["character_id"] = character_id
    if current_content is not None:
        result["current_content"] = current_content
    if effective_wi_state is not None:
        result["wi_state"] = effective_wi_state
    return result


def _prepare_user_chat_request(
    conn: ConnType,
    *,
    user: Any,
    payload: Any,
    guest_ip: str,
) -> dict[str, Any]:
    character, clean_text, recent_messages, memory_summary = prepare_chat_context(
        conn,
        user.id,
        payload.character_id,
        payload.message,
        persist_user_message=False,
        viewer_plan=user.effective_plan,
        commit=False,
    )
    related_assets = get_linked_assets(conn, payload.character_id)
    stream_payload = _build_user_stream_messages_and_budget(
        conn,
        user=user,
        character_id=payload.character_id,
        character=character,
        prompt_messages=recent_messages,
        memory_summary=memory_summary,
        related_assets=related_assets,
    )
    return _build_stream_prepare_result(
        guest_ip=guest_ip,
        stream_payload=stream_payload,
        character=character,
        clean_text=clean_text,
        recent_messages=recent_messages,
        memory_summary=memory_summary,
        related_assets=related_assets,
    )


def _build_chat_send_response(
    *,
    reply: str,
    history_count: int,
    character_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "reply": reply,
        "history_count": history_count,
        "summary_enabled": True,
        "character_state": character_state,
    }


def _log_successful_chat_request(
    conn: ConnType,
    *,
    user_id: int | str | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    reply_text: str,
) -> None:
    actual_output_tokens = estimate_text_tokens(reply_text)
    log_ai_request(
        conn,
        user_id=user_id,
        guest_ip=guest_ip,
        character_id=character_id,
        endpoint=endpoint,
        request_chars=estimate["chars"],
        estimated_input_tokens=estimate["tokens"],
        estimated_output_tokens=actual_output_tokens,
        total_estimated_tokens=estimate["tokens"] + actual_output_tokens,
        used_fallback=False,
        status="success",
        commit=False,
    )


def _log_failed_chat_request(
    *,
    user_id: int | str | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    error_detail: str,
    estimated_output_tokens: int = 0,
) -> None:
    log_conn = get_conn()
    try:
        safe_output_tokens = max(0, estimated_output_tokens)
        log_ai_request(
            log_conn,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint=endpoint,
            request_chars=estimate["chars"],
            estimated_input_tokens=estimate["tokens"],
            estimated_output_tokens=safe_output_tokens,
            total_estimated_tokens=estimate["tokens"] + safe_output_tokens,
            used_fallback=False,
            status="error",
            error_detail=error_detail,
        )
    except Exception:
        logger.warning(
            "AI 请求日志记录失败 user_id=%s character_id=%s",
            user_id,
            character_id,
            exc_info=True,
        )
    finally:
        log_conn.close()


def _persist_wi_state(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    character_state: dict[str, Any],
) -> None:
    """将 prompt 运行时状态持久化到 character_states.custom_vars。"""
    custom_vars = character_state.get("custom_vars") or {}
    runtime_vars = {
        key: custom_vars[key]
        for key in _PROMPT_RUNTIME_CUSTOM_KEYS
        if key in custom_vars
    }
    # _pending_events 不在此处持久化，由 apply_state_delta 统一管理
    # 避免在 AI 调用前就清空，导致失败重试时事件丢失
    if not runtime_vars:
        return
    # 读取当前 DB 中的 custom_vars，合并状态后写回
    # FOR UPDATE 防止并发请求之间的 read-modify-write 竞态
    row = conn.execute(
        "SELECT custom_vars FROM character_states WHERE user_id = %s AND character_id = %s FOR UPDATE",
        (user_id, character_id),
    ).fetchone()
    if not row:
        return
    db_custom_vars = parse_json_object(row["custom_vars"])
    db_custom_vars.update(runtime_vars)
    conn.execute(
        "UPDATE character_states SET custom_vars = %s WHERE user_id = %s AND character_id = %s",
        (to_json_string(db_custom_vars), user_id, character_id),
    )


def _resolve_public_character_state(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    delta: dict[str, Any] | None,
) -> dict[str, Any]:
    return get_public_character_state(
        conn,
        user_id=user_id,
        character_id=character_id,
        delta=delta,
    )


def _prepare_user_ai_budget(
    conn: ConnType,
    *,
    user: Any,
    stream_messages: list[dict[str, str]],
) -> dict[str, Any]:
    plan_policy = get_plan_policy(user.effective_plan)
    return _prepare_ai_budget(
        conn,
        stream_messages=stream_messages,
        model_profile=plan_policy["model_profile"],
        token_limit=plan_policy["token_limit"],
        token_limit_detail="你今天的 AI 使用额度已达上限，请明天再来",
        user_id=user.id,
    )


def _build_user_stream_messages_and_budget(
    conn: ConnType,
    *,
    user: Any,
    character_id: str,
    character: dict[str, Any],
    prompt_messages: list[dict[str, Any]],
    memory_summary: str,
    related_assets: list[Any],
) -> dict[str, Any]:
    character_state = get_character_state(conn, user.id, character_id)
    last_chat_time = get_last_chat_time(conn, user.id, character_id)
    stream_messages = build_layered_chat_messages_from_context(
        PromptBuildContext(
            character=character,
            recent_messages=prompt_messages,
            memory_summary=memory_summary,
            related_assets=related_assets,
            user_name=user.nickname,
            character_state=character_state,
            conn=conn,
            last_chat_time=last_chat_time,
            user_id=user.id,
        )
    )
    custom_vars = character_state.get("custom_vars") or {}
    wi_state = {
        "custom_vars": {
            key: custom_vars[key]
            for key in _PROMPT_RUNTIME_CUSTOM_KEYS
            if key in custom_vars
        }
    }
    budget = _prepare_user_ai_budget(conn, user=user, stream_messages=stream_messages)
    result = {
        "stream_messages": stream_messages,
        "ai_config": budget["ai_config"],
        "estimate": budget["estimate"],
    }
    if wi_state["custom_vars"]:
        result["wi_state"] = wi_state
    return result
