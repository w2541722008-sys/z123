"""聊天消息相关的数据访问层。"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


def get_chat_history(
    conn: ConnType, user_id: int | str, character_id: str
) -> list[dict[str, Any]]:
    """获取用户与角色的全部聊天历史。"""
    rows = conn.execute(
        """
        SELECT role, content, created_at
        FROM chat_messages
        WHERE user_id = %s AND character_id = %s
        ORDER BY created_at ASC
        """,
        (user_id, character_id),
    ).fetchall()
    return [
        {"role": row["role"], "content": row["content"], "created_at": row["created_at"]}
        for row in rows
    ]
