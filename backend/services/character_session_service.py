"""
角色会话服务 - 管理聊天会话的重置和清理

核心功能：
    - 重置角色聊天状态（清除消息、摘要、状态）
    - 清除聊天历史并设置指定开场白
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType
from repositories import chat_repository as chat_repo
from services.character_state import get_character_state
from services.chat_query import ensure_opening_message
from utils.json_utils import parse_json_object


def _normalize_greeting_index(raw_index: Any) -> tuple[Any, int, bool]:
    if isinstance(raw_index, int):
        index = raw_index
    elif isinstance(raw_index, str) and raw_index.lstrip('-').isdigit():
        index = int(raw_index)
    else:
        index = -1
    is_non_default = (index > 0) if index >= 0 else (isinstance(raw_index, str) and raw_index not in ("", "0", "-1"))
    return raw_index, index, is_non_default


def _resolve_chat_clear_greeting(conn: ConnType, character_id: str, greeting_index: Any) -> str:
    char_row = conn.execute(
        "SELECT opening_message, structured_asset_json FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    greeting = "你好，很高兴认识你。"
    if not char_row:
        return greeting

    raw_index, index, is_non_default = _normalize_greeting_index(greeting_index)
    if is_non_default:
        greeting_row = conn.execute(
            """
            SELECT content FROM character_greetings
            WHERE id = %s AND character_id = %s AND is_active = 1
            LIMIT 1
            """,
            (raw_index, character_id),
        ).fetchone()
        if greeting_row and (greeting_row["content"] or "").strip():
            greeting = greeting_row["content"].strip()

    structured = parse_json_object(char_row["structured_asset_json"], fallback={})
    alts = structured.get("alternate_greetings", [])
    if not is_non_default:
        return str(char_row["opening_message"] or "") or (alts[0] if alts else greeting)
    if greeting == "你好，很高兴认识你。" and isinstance(alts, list) and 1 <= index <= len(alts):
        return str(alts[index - 1])
    return greeting


def _clear_chat_data(conn: ConnType, user_id: int | str, character_id: str) -> None:
    """清除指定用户和角色的所有对话数据。

    包括：聊天消息、摘要、关系状态、剧情进度。
    清空后一切从零开始，避免出现"关系还在但记忆全无"的逻辑矛盾。
    """
    chat_repo.delete_user_messages(conn, user_id, character_id)
    chat_repo.delete_user_summaries(conn, user_id, character_id)
    # 同步重置关系状态，防止"失忆但关系还在"的违和感
    conn.execute(
        "DELETE FROM character_states WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    )
    # 同步清除剧情线进度
    conn.execute(
        "DELETE FROM user_story_progress WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    )


def reset_character_chat_state(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    clear_state: bool,
    commit: bool = True,
) -> dict[str, Any]:
    _clear_chat_data(conn, user_id, character_id)
    # _clear_chat_data 已包含 character_states 和 user_story_progress 的删除，
    # clear_state 参数保留兼容，但实际已无额外操作

    ensure_opening_message(conn, user_id, character_id, commit=False)
    state = get_character_state(conn, user_id, character_id) if clear_state else None

    if commit:
        conn.commit()

    result: dict[str, Any] = {"ok": True}
    if state is not None:
        result["state"] = {k: v for k, v in state.items() if not k.startswith("_")}
    return result


def clear_chat_history_with_greeting(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    greeting_index: Any,
    commit: bool = True,
) -> str:
    _clear_chat_data(conn, user_id, character_id)
    greeting = _resolve_chat_clear_greeting(conn, character_id, greeting_index)
    chat_repo.insert_message(conn, user_id=user_id, character_id=character_id, role="assistant", content=greeting, is_summarized=1)
    if commit:
        conn.commit()
    return greeting
