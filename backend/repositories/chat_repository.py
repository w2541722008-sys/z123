"""聊天消息相关的数据访问层。"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


def get_chat_history(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """获取用户与角色的聊天历史（分页）。"""
    rows = conn.execute(
        """
        SELECT role, content, created_at
        FROM chat_messages
        WHERE user_id = %s AND character_id = %s
        ORDER BY created_at ASC
        LIMIT %s OFFSET %s
        """,
        (user_id, character_id, limit, offset),
    ).fetchall()
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def insert_message(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    role: str,
    content: str,
    is_summarized: int = 0,
) -> None:
    """插入一条聊天消息。"""
    conn.execute(
        """
        INSERT INTO chat_messages(user_id, character_id, role, content, is_summarized)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (user_id, character_id, role, content, is_summarized),
    )


def message_with_content_exists(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    role: str,
    content: str,
) -> bool:
    """按用户、角色、角色类型和内容检查消息是否已存在。"""
    row = conn.execute(
        """
        SELECT id FROM chat_messages
        WHERE user_id = %s AND character_id = %s AND role = %s AND content = %s
        LIMIT 1
        """,
        (user_id, character_id, role, content),
    ).fetchone()
    return row is not None


def delete_user_messages(conn: ConnType, user_id: int | str, character_id: str) -> None:
    """删除用户与角色的所有聊天消息。"""
    conn.execute(
        "DELETE FROM chat_messages WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    )


def delete_user_summaries(
    conn: ConnType, user_id: int | str, character_id: str
) -> None:
    """删除用户与角色的所有聊天摘要。"""
    conn.execute(
        "DELETE FROM chat_summaries WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    )


def count_chat_history(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> int:
    """获取聊天消息总数。"""
    row = conn.execute(
        """
        SELECT COUNT(*) as total
        FROM chat_messages
        WHERE user_id = %s AND character_id = %s
        """,
        (user_id, character_id),
    ).fetchone()
    return row["total"] if row else 0


def get_last_assistant_message_time(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> str | None:
    """获取用户与角色最近一条 assistant 消息的 created_at。"""
    row = conn.execute(
        """SELECT created_at FROM chat_messages
           WHERE user_id = %s AND character_id = %s AND role = 'assistant'
           ORDER BY id DESC LIMIT 1""",
        (user_id, character_id),
    ).fetchone()
    return row["created_at"] if row else None


def get_assistant_message_by_id(
    conn: ConnType,
    message_id: str,
    user_id: int | str,
) -> dict[str, Any] | None:
    """按 ID 和用户获取一条 assistant 消息。"""
    return conn.execute(
        """SELECT * FROM chat_messages
           WHERE id = %s AND user_id = %s AND role = 'assistant'""",
        (message_id, user_id),
    ).fetchone()


def message_exists(conn: ConnType, user_id: int | str, character_id: str) -> bool:
    """检查用户与角色之间是否已有聊天记录。"""
    row = conn.execute(
        "SELECT 1 FROM chat_messages WHERE user_id = %s AND character_id = %s LIMIT 1",
        (user_id, character_id),
    ).fetchone()
    return row is not None


def mark_messages_summarized(conn: ConnType, message_ids: list[int]) -> None:
    """批量标记消息为已摘要。"""
    if not message_ids:
        return
    placeholders = ",".join("%s" for _ in message_ids)
    conn.execute(
        f"UPDATE chat_messages SET is_summarized = 1 WHERE id IN ({placeholders})",
        message_ids,
    )


def count_unsummarized_messages(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> int:
    """统计未摘要消息数。"""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM chat_messages WHERE user_id = %s AND character_id = %s AND is_summarized = 0",
        (user_id, character_id),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def get_unsummarized_messages(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> list[dict[str, Any]]:
    """获取所有未摘要的消息。"""
    return conn.execute(
        """
        SELECT id, role, content, created_at
        FROM chat_messages
        WHERE user_id = %s AND character_id = %s AND is_summarized = 0
        ORDER BY id ASC
        """,
        (user_id, character_id),
    ).fetchall()


def get_summary_record(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> dict[str, Any] | None:
    """获取聊天摘要记录。"""
    return conn.execute(
        "SELECT * FROM chat_summaries WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    ).fetchone()


def get_message_created_at(conn: ConnType, message_id: str) -> str | None:
    """获取消息的 created_at 时间戳。"""
    row = conn.execute(
        "SELECT created_at FROM chat_messages WHERE id = %s",
        (message_id,),
    ).fetchone()
    return row["created_at"] if row else None


def get_message_content(conn: ConnType, message_id: str) -> str | None:
    """获取消息内容。"""
    row = conn.execute(
        "SELECT content FROM chat_messages WHERE id = %s",
        (message_id,),
    ).fetchone()
    return row["content"] if row else None


def get_messages_before_target(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    target_created_at: str,
    target_message_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """获取目标消息之前的聊天记录（按时间降序）。"""
    return conn.execute(
        """SELECT id, role, content, created_at FROM chat_messages
           WHERE user_id = %s AND character_id = %s
             AND (created_at < %s OR (created_at = %s AND id::text < %s))
           ORDER BY created_at DESC, id DESC
           LIMIT %s""",
        (
            user_id,
            character_id,
            target_created_at,
            target_created_at,
            str(target_message_id),
            limit,
        ),
    ).fetchall()


def update_message_with_versions(
    conn: ConnType,
    message_id: str,
    content: str,
    versions_json: str,
) -> None:
    """更新消息内容和版本历史。"""
    conn.execute(
        """UPDATE chat_messages
           SET content = %s,
               versions = %s::jsonb,
               current_version_index = 0,
               updated_at = now()
           WHERE id = %s""",
        (content, versions_json, message_id),
    )


def update_message_content(
    conn: ConnType,
    message_id: str,
    content: str,
) -> None:
    """简单更新消息内容。"""
    conn.execute(
        """UPDATE chat_messages
           SET content = %s, updated_at = now()
           WHERE id = %s""",
        (content, message_id),
    )
