"""
管理后台角色记忆资产 CRUD — 纯 SQL 层。

覆盖表：character_memories, memory_categories

设计原则：
    - 只做 SQL，不管理事务（commit/rollback 由调用方控制）
    - 返回原始行（RealDictRow），表示层格式由路由负责
    - 函数以 admin_ 前缀命名，区分于用户端查询
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


# ============================================================
# 记忆条目 (character_memories)
# ============================================================

def admin_list_memories(conn: ConnType, character_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, keywords, trigger_logic, content, category_id, position,
               priority, is_active, comment, selective, constant, sticky, cooldown,
               created_at, updated_at
        FROM character_memories
        WHERE character_id = %s
        ORDER BY priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()


def admin_create_memory(
    conn: ConnType,
    character_id: str,
    *,
    keywords: str,
    trigger_logic: str,
    content: str,
    category_id: str | None,
    position: str,
    priority: int,
    is_active: bool,
    comment: str | None,
    selective: bool,
    constant: bool,
    sticky: int,
    cooldown: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO character_memories
        (character_id, keywords, trigger_logic, content, category_id, position,
         priority, is_active, comment, selective, constant, sticky, cooldown)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id, keywords, trigger_logic, content, category_id,
            position, priority, 1 if is_active else 0, comment,
            1 if selective else 0, 1 if constant else 0,
            sticky, cooldown,
        ),
    )
    return cur.fetchone()["id"]


def admin_get_memory(conn: ConnType, memory_id: str, character_id: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
        (memory_id, character_id),
    ).fetchone()


def admin_update_memory(
    conn: ConnType,
    memory_id: str,
    *,
    keywords: str,
    trigger_logic: str,
    content: str,
    category_id: str | None,
    position: str,
    priority: int,
    is_active: bool,
    comment: str | None,
    selective: bool,
    constant: bool,
    sticky: int,
    cooldown: int,
) -> None:
    conn.execute(
        """
        UPDATE character_memories SET
            keywords = %s, trigger_logic = %s, content = %s, category_id = %s,
            position = %s, priority = %s, is_active = %s, comment = %s,
            selective = %s, constant = %s, sticky = %s, cooldown = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            keywords, trigger_logic, content, category_id, position, priority,
            1 if is_active else 0, comment,
            1 if selective else 0, 1 if constant else 0,
            sticky, cooldown, memory_id,
        ),
    )


def admin_delete_memory(conn: ConnType, memory_id: str) -> None:
    conn.execute("DELETE FROM character_memories WHERE id = %s", (memory_id,))


# ============================================================
# 记忆分类 (memory_categories)
# ============================================================

def admin_list_memory_categories(conn: ConnType, character_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, name, description, color, sort_order, created_at, updated_at
        FROM memory_categories
        WHERE character_id = %s
        ORDER BY sort_order ASC, id ASC
        """,
        (character_id,),
    ).fetchall()


def admin_create_memory_category(
    conn: ConnType,
    character_id: str,
    *,
    name: str,
    description: str | None,
    color: str | None,
    sort_order: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO memory_categories
        (character_id, name, description, color, sort_order)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (character_id, name, description, color, sort_order),
    )
    return cur.fetchone()["id"]


def admin_get_memory_category(
    conn: ConnType, category_id: str, character_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
        (category_id, character_id),
    ).fetchone()


def admin_update_memory_category(
    conn: ConnType,
    category_id: str,
    *,
    name: str,
    description: str | None,
    color: str | None,
    sort_order: int,
) -> None:
    conn.execute(
        """
        UPDATE memory_categories SET
            name = %s, description = %s, color = %s, sort_order = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (name, description, color, sort_order, category_id),
    )


def admin_delete_memory_category(conn: ConnType, category_id: str) -> None:
    conn.execute("DELETE FROM memory_categories WHERE id = %s", (category_id,))


def admin_count_memories_in_category(conn: ConnType, category_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM character_memories WHERE category_id = %s",
        (category_id,),
    ).fetchone()
    return row["count"] if row else 0


def admin_get_memory_category_for_impact(
    conn: ConnType, category_id: str, character_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, name
        FROM memory_categories
        WHERE id = %s AND character_id = %s
        """,
        (category_id, character_id),
    ).fetchone()


def admin_list_memories_in_category(
    conn: ConnType, character_id: str, category_id: str
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, keywords, comment
        FROM character_memories
        WHERE character_id = %s AND category_id = %s
        ORDER BY priority ASC, id ASC
        """,
        (character_id, category_id),
    ).fetchall()
