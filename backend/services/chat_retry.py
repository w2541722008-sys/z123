"""
聊天重试服务 - Regenerate / Continue 逻辑

职责：
- 消息投影与截取
- 历史消息定位与加载
- Regenerate/Continue 上下文准备
- 版本保存
"""

from __future__ import annotations

import json
from typing import Any

from core.config import RECENT_MESSAGE_WINDOW, logger, utc_now
from core.database import ConnType
from repositories import chat_repository as chat_repo
from services.memory_service import get_summary_for_prompt
from services.chat_query import (
    ensure_opening_message,
    get_character_or_404,
    get_message_for_regenerate_or_continue,
    get_linked_assets,
    message_projection,
    _message_with_id_projection,
)
from services.chat_send import (
    _build_user_stream_messages_and_budget,
    _build_stream_prepare_result,
    _prepare_prompt_context_result,
)


# ============================================================
# 历史消息截取
# ============================================================
def _fallback_recent_messages(
    fallback_recent: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [fallback_recent[0]] if fallback_recent else []


def _find_target_message_index(
    chronological: list[dict[str, Any]],
    target_message_id: str,
) -> int | None:
    for i, msg in enumerate(chronological):
        if msg["id"] == str(target_message_id):
            return i
    return None


def _messages_before_target(
    chronological: list[dict[str, Any]],
    target_message_id: str,
    fallback_recent: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target_idx = _find_target_message_index(chronological, target_message_id)
    if target_idx is not None:
        # 目标消息在列表中，截取它之前的消息
        return chronological[:target_idx]
    # 目标消息不在列表中（已通过 created_at 过滤排除），
    # 直接使用整个 chronological 列表作为上下文
    return chronological if chronological else fallback_recent


def _trim_recent_messages_tail(
    recent_messages: list[dict[str, Any]],
    fallback_recent: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recent_messages = list(recent_messages)
    while recent_messages and recent_messages[-1].get("role") == "assistant":
        recent_messages.pop()
    if not recent_messages:
        return _fallback_recent_messages(fallback_recent)
    return recent_messages


def _project_message_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _message_with_id_projection(row["id"], row["role"], row["content"])
        for row in rows
    ]


def _resolve_recent_messages_before_target(
    chronological: list[dict[str, Any]],
    *,
    target_message_id: str,
    fallback_recent: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recent_messages = _messages_before_target(
        chronological,
        target_message_id,
        fallback_recent,
    )
    return _trim_recent_messages_tail(recent_messages, fallback_recent)


def _build_recent_messages_before_target(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    target_message_id: str,
    fallback_recent: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # 优化：先获取目标消息的时间戳，再只查询该时间之前的消息
    _MAX_MESSAGES_FOR_CONTEXT = RECENT_MESSAGE_WINDOW * 4  # 48条

    target_ts = chat_repo.get_message_created_at(conn, target_message_id)

    if not target_ts:
        return fallback_recent

    all_rows = chat_repo.get_messages_before_target(
        conn,
        user_id,
        character_id,
        target_ts,
        target_message_id,
        _MAX_MESSAGES_FOR_CONTEXT,
    )
    chronological = _project_message_rows(list(reversed(all_rows)))
    return _resolve_recent_messages_before_target(
        chronological,
        target_message_id=target_message_id,
        fallback_recent=fallback_recent,
    )


# ============================================================
# Regenerate/Continue 上下文准备
# ============================================================
def _prepare_character_prompt_context(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    viewer_plan: str | None = None,
) -> tuple[Any, str, list[Any]]:
    character = get_character_or_404(conn, character_id, viewer_plan=viewer_plan)
    memory_summary = get_summary_for_prompt(conn, user_id, character_id)
    related_assets = get_linked_assets(conn, character_id)
    return character, memory_summary, related_assets


def _build_continue_prompt_messages(
    recent_messages: list[dict[str, str]],
    current_content: str,
) -> list[dict[str, str]]:
    continue_messages = list(recent_messages)
    continue_messages.append(
        {
            "role": "assistant",
            "content": current_content,
        }
    )
    continue_messages.append(
        {
            "role": "user",
            "content": "【请继续】请接着上面的话继续说下去，保持角色设定和语气，不要重复已说过的内容。直接继续输出即可。",
        }
    )
    return continue_messages


def prepare_regenerate_context(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    recent_messages: list[dict[str, str]],
    viewer_plan: str | None = None,
) -> tuple[Any, str, list[dict[str, str]], list[Any]]:
    """
    为 regenerate 准备完整的聊天上下文。

    返回：
        (character, memory_summary, recent_messages_with_memory, related_assets)
    """
    character, memory_summary, related_assets = _prepare_character_prompt_context(
        conn,
        user_id=user_id,
        character_id=character_id,
        viewer_plan=viewer_plan,
    )
    return character, memory_summary, recent_messages, related_assets


def prepare_continue_context(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    message_id: str,
    current_content: str,
    recent_messages: list[dict[str, str]],
    viewer_plan: str | None = None,
) -> tuple[Any, str, list[dict[str, str]], list[Any]]:
    """
    为 continue 准备上下文：在历史消息中追加一条"继续"指令。
    """
    _ = message_id
    character, memory_summary, related_assets = _prepare_character_prompt_context(
        conn,
        user_id=user_id,
        character_id=character_id,
        viewer_plan=viewer_plan,
    )
    continue_messages = _build_continue_prompt_messages(
        recent_messages, current_content
    )
    return character, memory_summary, continue_messages, related_assets


# ============================================================
# Retry Prompt 上下文构建
# ============================================================
def _prepare_regenerate_prompt_context(
    conn: ConnType,
    *,
    user: Any,
    character_id: str,
    recent_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    context_tuple = prepare_regenerate_context(
        conn,
        user.id,
        character_id,
        recent_messages,
        viewer_plan=user.effective_plan,
    )
    return _prepare_prompt_context_result(
        current_content="",
        context_tuple=context_tuple,
        fallback_prompt_messages=recent_messages,
    )


def _prepare_continue_prompt_context(
    conn: ConnType,
    *,
    user: Any,
    character_id: str,
    message_id: str,
    current_content: str,
    recent_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    context_tuple = prepare_continue_context(
        conn,
        user.id,
        character_id,
        message_id,
        current_content,
        recent_messages,
        viewer_plan=user.effective_plan,
    )
    return _prepare_prompt_context_result(
        current_content=current_content,
        context_tuple=context_tuple,
    )


def _prepare_retry_prompt_context(
    conn: ConnType,
    *,
    user: Any,
    operation: str,
    prompt_args: dict[str, Any],
) -> dict[str, Any]:
    if operation == "continue":
        return _prepare_continue_prompt_context(
            conn,
            user=user,
            character_id=prompt_args["character_id"],
            message_id=prompt_args["message_id"],
            current_content=prompt_args["current_content"],
            recent_messages=prompt_args["recent_messages"],
        )
    return _prepare_regenerate_prompt_context(
        conn,
        user=user,
        character_id=prompt_args["character_id"],
        recent_messages=prompt_args["recent_messages"],
    )


# ============================================================
# Retry 流程组装
# ============================================================
def _build_retry_fallback_recent(
    message_row: dict[str, Any],
) -> list[dict[str, Any]]:
    return [message_projection("assistant", message_row.get("content"))]


def _load_retry_target_message(
    conn: ConnType,
    *,
    user_id: int | str,
    message_id: str,
    operation: str,
) -> tuple[dict[str, Any], str]:
    return get_message_for_regenerate_or_continue(
        conn,
        user_id,
        message_id,
        operation=operation,
    )


def _prepare_retry_message_context(
    conn: ConnType,
    *,
    user: Any,
    message_id: str,
    guest_ip: str,
    operation: str,
) -> dict[str, Any]:
    message_row, character_id = _load_retry_target_message(
        conn,
        user_id=user.id,
        message_id=message_id,
        operation=operation,
    )
    recent_messages = _build_recent_messages_before_target(
        conn,
        user.id,
        character_id,
        message_id,
        _build_retry_fallback_recent(message_row),
    )
    return {
        "guest_ip": guest_ip,
        "message_row": message_row,
        "character_id": character_id,
        "recent_messages": recent_messages,
    }


def _build_retry_prompt_args(
    message_context: dict[str, Any],
    *,
    message_id: str,
) -> dict[str, Any]:
    return {
        "character_id": message_context["character_id"],
        "message_id": message_id,
        "current_content": message_context["message_row"].get("content") or "",
        "recent_messages": message_context["recent_messages"],
    }


def _build_retry_stream_payload(
    conn: ConnType,
    *,
    user: Any,
    prompt_args: dict[str, Any],
    prompt_context: dict[str, Any],
) -> dict[str, Any]:
    return _build_user_stream_messages_and_budget(
        conn,
        user=user,
        character_id=prompt_args["character_id"],
        character=prompt_context["character"],
        prompt_messages=prompt_context["prompt_messages"],
        memory_summary=prompt_context["memory_summary"],
        related_assets=prompt_context["related_assets"],
    )


def _build_retry_stream_prepare_result(
    conn: ConnType,
    *,
    user: Any,
    message_context: dict[str, Any],
    message_id: str,
    operation: str,
) -> dict[str, Any]:
    prompt_args = _build_retry_prompt_args(message_context, message_id=message_id)
    prompt_context = _prepare_retry_prompt_context(
        conn,
        user=user,
        operation=operation,
        prompt_args=prompt_args,
    )
    stream_payload = _build_retry_stream_payload(
        conn,
        user=user,
        prompt_args=prompt_args,
        prompt_context=prompt_context,
    )
    return _build_stream_prepare_result(
        guest_ip=message_context["guest_ip"],
        stream_payload=stream_payload,
        character_id=prompt_args["character_id"],
        current_content=prompt_context["current_content"],
    )


def _prepare_regenerate_or_continue_request(
    conn: ConnType,
    *,
    user: Any,
    message_id: str,
    guest_ip: str,
    operation: str,
) -> dict[str, Any]:
    message_context = _prepare_retry_message_context(
        conn,
        user=user,
        message_id=message_id,
        guest_ip=guest_ip,
        operation=operation,
    )
    ensure_opening_message(conn, user.id, message_context["character_id"], commit=False)
    return _build_retry_stream_prepare_result(
        conn,
        user=user,
        message_context=message_context,
        message_id=message_id,
        operation=operation,
    )


# ============================================================
# 版本保存
# ============================================================
def save_regenerated_version(
    conn: ConnType,
    message_id: str,
    new_content: str,
    *,
    is_append: bool = False,
    commit: bool = True,
) -> None:
    """
    保存新生成的内容，仅保留最终版本到数据库。

    策略：不累积历史版本。每次 regenerate/continue 只保存最终结果。

    参数：
        conn: 数据库连接
        message_id: 目标消息 ID (UUID)
        new_content: 新生成的内容（regenerate=完整替换, continue=追加部分）
        is_append: True 表示 continue（追加），False 表示 regenerate（替换）
        commit: 是否立即提交事务
    """
    try:
        current_content = chat_repo.get_message_content(conn, message_id)

        if current_content is None:
            raise ValueError(f"消息 {message_id} 不存在")

        now = utc_now()

        if is_append:
            final_content = (current_content or "") + new_content
        else:
            final_content = new_content

        versions = [
            {
                "content": final_content,
                "created_at": now.isoformat(),
                "operation": "continue" if is_append else "regenerate",
            }
        ]

        chat_repo.update_message_with_versions(
            conn,
            message_id,
            final_content,
            json.dumps(versions, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning("版本保存失败，降级为仅更新内容: %s", e, exc_info=True)

        if is_append:
            existing = chat_repo.get_message_content(conn, message_id)
            final_content = (existing or "") + new_content if existing else new_content
        else:
            final_content = new_content

        chat_repo.update_message_content(conn, message_id, final_content)

    if commit:
        conn.commit()
