"""
角色会话服务 - 管理聊天会话的重置和清理

核心功能：
    - 重置角色聊天状态（清除消息、摘要、状态）
    - 清除聊天历史并设置指定开场白
"""

from __future__ import annotations

import json
from typing import Any

from config import utc_now_iso
from services.character_state import get_character_state
from services.chat_service import ensure_opening_message


def _normalize_greeting_index(raw_index: Any) -> tuple[Any, int, bool]:
    if isinstance(raw_index, int):
        index = raw_index
    elif isinstance(raw_index, str) and raw_index.lstrip('-').isdigit():
        index = int(raw_index)
    else:
        index = -1
    is_non_default = (index > 0) if index >= 0 else (isinstance(raw_index, str) and raw_index not in ("", "0", "-1"))
    return raw_index, index, is_non_default


def _resolve_chat_clear_greeting(conn: Any, character_id: str, greeting_index: Any) -> str:
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

    structured = json.loads(char_row["structured_asset_json"] or "{}") if char_row["structured_asset_json"] else {}
    alts = structured.get("alternate_greetings", [])
    if not is_non_default:
        return char_row["opening_message"] or (alts[0] if alts else greeting)
    if greeting == "你好，很高兴认识你。" and isinstance(alts, list) and 1 <= index <= len(alts):
        return alts[index - 1]
    return greeting


def _clear_chat_data(conn: Any, user_id: int, character_id: str) -> None:
    """清除指定用户和角色的聊天消息和摘要数据。

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID
    """
    conn.execute(
        "DELETE FROM chat_messages WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    )
    conn.execute(
        "DELETE FROM chat_summaries WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    )


def reset_character_chat_state(
    conn: Any,
    *,
    user_id: int,
    character_id: str,
    clear_state: bool,
    commit: bool = True,
) -> dict[str, Any]:
    _clear_chat_data(conn, user_id, character_id)
    if clear_state:
        conn.execute(
            "DELETE FROM character_states WHERE user_id = %s AND character_id = %s",
            (user_id, character_id),
        )

    ensure_opening_message(conn, user_id, character_id, commit=False)
    state = get_character_state(conn, user_id, character_id) if clear_state else None

    if commit:
        conn.commit()

    result: dict[str, Any] = {"ok": True}
    if state is not None:
        result["state"] = {k: v for k, v in state.items() if not k.startswith("_")}
    return result


def clear_chat_history_with_greeting(
    conn: Any,
    *,
    user_id: int,
    character_id: str,
    greeting_index: Any,
    commit: bool = True,
) -> str:
    _clear_chat_data(conn, user_id, character_id)
    greeting = _resolve_chat_clear_greeting(conn, character_id, greeting_index)
    conn.execute(
        """
        INSERT INTO chat_messages(user_id, character_id, role, content, created_at, is_summarized)
        VALUES (%s, %s, 'assistant', %s, %s, 1)
        """,
        (user_id, character_id, greeting, utc_now_iso()),
    )
    if commit:
        conn.commit()
    return greeting
