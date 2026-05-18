"""聊天消息相关的数据访问层。"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


def get_chat_history(
    conn: ConnType, user_id: int | str, character_id: str,
    limit: int = 50, offset: int = 0,
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
        {"role": row["role"], "content": row["content"], "created_at": row["created_at"]}
        for row in rows
    ]


def count_chat_history(
    conn: ConnType, user_id: int | str, character_id: str,
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


def search_messages(
    conn: ConnType,
    user_id: int | str,
    query: str,
    *,
    character_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """全文搜索聊天消息（tsvector + GIN 索引）。

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        query: 搜索关键词（支持多词空格分隔，自动转为 & 逻辑与）
        character_id: 可选，限定角色
        limit: 返回条数上限
        offset: 分页偏移

    Returns:
        [{"id":..., "role":..., "content":..., "character_id":..., "created_at":...}, ...]
    """
    # 将用户输入转为 tsquery 格式：多个词用 & 连接
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return []
    tsquery = " & ".join(words)

    params: list[Any] = [user_id, tsquery]
    char_filter = ""
    if character_id:
        char_filter = "AND character_id = %s"
        params.append(character_id)
    params.extend([limit, offset])

    rows = conn.execute(
        f"""
        SELECT id, role, content, character_id, created_at,
               ts_rank(search_vector, to_tsquery('simple', %s)) AS rank
        FROM chat_messages
        WHERE user_id = %s
          AND search_vector @@ to_tsquery('simple', %s)
          {char_filter}
        ORDER BY rank DESC, created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "character_id": row["character_id"],
            "created_at": row["created_at"],
            "rank": round(float(row["rank"]), 3),
        }
        for row in rows
    ]


def count_search_results(
    conn: ConnType,
    user_id: int | str,
    query: str,
    *,
    character_id: str | None = None,
) -> int:
    """统计搜索结果总数。"""
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return 0
    tsquery = " & ".join(words)

    params: list[Any] = [user_id, tsquery]
    char_filter = ""
    if character_id:
        char_filter = "AND character_id = %s"
        params.append(character_id)

    row = conn.execute(
        f"""
        SELECT COUNT(*) as total
        FROM chat_messages
        WHERE user_id = %s
          AND search_vector @@ to_tsquery('simple', %s)
          {char_filter}
        """,
        tuple(params),
    ).fetchone()
    return int(row["total"]) if row else 0
