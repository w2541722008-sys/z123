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
from datetime import datetime, timezone
from typing import Any

from core.config import AI_CHAT_MAX_OUTPUT_TOKENS, logger
from core.database import ConnType, get_conn
from core.model_adapter import get_ai_config, request_chat_completion
from services.prompt_assembler import build_layered_chat_messages
from utils.json_utils import parse_json_object, to_json_string
from core.plan_constants import GUEST_PLAN, plan_display_name
from services.plan_service import get_plan_policy
from services.character_state import apply_state_delta, get_character_state
from services.usage_guard import (
    enforce_daily_budget,
    estimate_messages_tokens,
    estimate_text_tokens,
    get_daily_usage,
    log_ai_request,
)
from utils.stream_filter import normalize_reply_text, parse_state_update_tag
from services.chat_query import (
    get_character_or_404,
    ensure_opening_message,
    _normalize_non_empty_message,
    _load_recent_messages_and_summary,
    get_linked_assets,
    count_chat_messages,
    get_last_chat_time,
)


# ============================================================
# 自定义异常
# ============================================================
class AIChatError(Exception):
    """AI 调用失败时抛出，由路由层决定如何向用户展示错误。"""


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

    messages = build_layered_chat_messages(
        character, recent_messages, memory_summary,
        related_assets=related_assets, user_name=user_name,
        character_state=character_state,
        conn=conn,
        last_chat_time=last_chat_time,
        user_id=user_id,
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

    # 应用增量到 DB
    new_state: dict[str, Any] | None = None
    if delta and conn is not None and user_id is not None:
        try:
            new_state = apply_state_delta(conn, user_id, character["id"], delta, commit=commit)
        except Exception as exc:
            logger.warning(
                "角色状态更新失败 user_id=%s character_id=%s delta=%s error=%s",
                user_id,
                character["id"],
                delta,
                exc,
            )

    return cleaned_reply, new_state


def build_mock_reply(character: Any, user_message: str) -> str:
    """
    生成 fallback mock 回复。
    
    当真实 AI 调用失败时使用，根据 mock_reply_style 轮换回复风格。
    """
    # jsonb 列：psycopg2 自动解析为 Python list，兼容旧 text 格式
    raw_styles = character.get("mock_reply_style", "[]")
    styles: list[str] = raw_styles if isinstance(raw_styles, list) else json.loads(raw_styles or "[]")
    if not styles:
        return "我在，你继续说。"
    fingerprint = sum(ord(ch) for ch in user_message) % len(styles)
    base: str = styles[fingerprint]

    # 通用情感关键词额外拼接
    if any(keyword in user_message for keyword in ["累", "困", "难受", "烦", "崩溃", "委屈", "哭"]):
        return "%s先别想别的，先说说你现在的感受。" % base

    if any(keyword in user_message for keyword in ["想你", "喜欢你", "爱你", "爱上了"]):
        return "%s……我听到了，继续说。" % base

    return base


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
        prompt_messages=prompt_messages if prompt_messages is not None else (fallback_prompt_messages or []),
        related_assets=related_assets,
    )


# ============================================================
# 游客流式构建
# ============================================================
def _build_guest_fallback_messages(character: dict[str, Any], user_message: str) -> list[dict[str, str]]:
    """最简降级 prompt — 仅在 build_layered_chat_messages 异常时使用。"""
    name = character.get("name", "AI角色")
    subtitle = character.get("subtitle", "")
    identity = "你是" + name
    if subtitle:
        identity += "，" + subtitle
    description = character.get("description", "")
    if description:
        identity += "\n" + description

    return [
        {"role": "system", "content": identity + "\n\n请用第一人称自然回复，保持角色设定。"},
        {"role": "user", "content": user_message},
    ]


def _build_guest_stream_messages(
    character: dict[str, Any],
    message_text: str,
    guest_history: list[Any],
) -> tuple[str, list[dict[str, str]]]:
    from services.chat_retry import message_projection
    clean_text = _normalize_non_empty_message(message_text)
    fake_history = [
        message_projection(item.role, item.content)
        for item in guest_history
    ]
    # 将用户消息加入历史末尾，由 build_layered_chat_messages 统一走预算控制
    fake_history.append({"role": "user", "content": clean_text})
    try:
        messages = build_layered_chat_messages(
            character=character,
            recent_messages=fake_history,
            memory_summary="",
            related_assets=[],
            user_name="访客",
            character_state=None,
        )
    except Exception as exc:
        logger.warning("游客 prompt 构建失败，使用降级 prompt: %s", exc)
        messages = _build_guest_fallback_messages(character, clean_text)
    return clean_text, messages


def _build_guest_quota_payload(conn: ConnType, guest_ip: str) -> dict[str, Any]:
    plan_policy = get_plan_policy(GUEST_PLAN)
    token_limit = max(0, int(plan_policy["token_limit"] or 0))
    usage = get_daily_usage(conn, guest_ip=guest_ip)
    used_tokens = max(0, int(usage["total_tokens"] or 0))
    remaining_tokens = max(0, token_limit - used_tokens)
    remaining_percent = int(remaining_tokens * 100 / token_limit) if token_limit > 0 else 100

    if remaining_tokens <= 0:
        status_text = "额度已用完"
    elif remaining_percent <= 35:
        status_text = "额度不多"
    else:
        status_text = "额度充足"

    return {
        "guest": True,
        "status_text": status_text,
        "remaining_percent": max(0, min(100, remaining_percent)),
        "used_tokens": used_tokens,
        "remaining_tokens": remaining_tokens,
        "token_limit": token_limit,
    }


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
) -> dict[str, Any]:
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
        pass
    finally:
        log_conn.close()


def _persist_wi_state(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    character_state: dict[str, Any],
) -> None:
    """将 WI sticky/cooldown 状态持久化到 character_states.custom_vars。"""
    custom_vars = character_state.get("custom_vars") or {}
    wi_sticky = custom_vars.get("_wi_sticky")
    wi_cooldown = custom_vars.get("_wi_cooldown")
    # _pending_events 不在此处持久化，由 apply_state_delta 统一管理
    # 避免在 AI 调用前就清空，导致失败重试时事件丢失
    if wi_sticky is None and wi_cooldown is None:
        return
    # 读取当前 DB 中的 custom_vars，合并状态后写回
    row = conn.execute(
        "SELECT custom_vars FROM character_states WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    ).fetchone()
    if not row:
        return
    db_custom_vars = parse_json_object(row["custom_vars"])
    if wi_sticky is not None:
        db_custom_vars["_wi_sticky"] = wi_sticky
    if wi_cooldown is not None:
        db_custom_vars["_wi_cooldown"] = wi_cooldown
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
    if delta:
        raw_state = apply_state_delta(conn, user_id, character_id, delta, commit=False)
    else:
        raw_state = get_character_state(conn, user_id, character_id)
    if not raw_state:
        return {}
    result = {
        k: v
        for k, v in raw_state.items()
        if not str(k).startswith("_")
    }
    # 暴露剧情事件给前端（Optimization B：去掉下划线前缀使前端可见）
    if "_triggered_events" in raw_state:
        result["triggered_events"] = raw_state["_triggered_events"]
    # 从角色卡配置中提取 show_bar 偏好，供前端控制状态栏显隐
    try:
        rules_row = conn.execute(
            "SELECT affection_rules_json FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if rules_row and rules_row["affection_rules_json"]:
            rules = parse_json_object(rules_row["affection_rules_json"], fallback={})
            if "show_bar" in rules:
                result["show_bar"] = bool(rules["show_bar"])
    except Exception:
        pass
    # 追加剧情线名称（前端状态栏展示用）
    storyline_id = raw_state.get("storyline_id")
    if storyline_id and conn is not None:
        try:
            sl_row = conn.execute(
                "SELECT name FROM character_storylines WHERE id = %s",
                (storyline_id,),
            ).fetchone()
            if sl_row and sl_row["name"]:
                result["storyline_name"] = sl_row["name"]
        except Exception:
            pass
    return result


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
    stream_messages = build_layered_chat_messages(
        character,
        prompt_messages,
        memory_summary,
        related_assets=related_assets,
        user_name=user.nickname,
        character_state=character_state,
        conn=conn,
        last_chat_time=last_chat_time,
    )
    # WI sticky/cooldown 状态已被 build_layered_chat_messages 写入 character_state.custom_vars
    # 立即持久化到 DB，确保流式响应完成后状态不丢失
    _persist_wi_state(conn, user.id, character_id, character_state)
    budget = _prepare_user_ai_budget(conn, user=user, stream_messages=stream_messages)
    return {
        "stream_messages": stream_messages,
        "ai_config": budget["ai_config"],
        "estimate": budget["estimate"],
    }
