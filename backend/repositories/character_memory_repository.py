"""
角色记忆与后置规则的数据查询层（纯 SQL，不含业务逻辑）。

关键词匹配、粘性/冷却状态机、预算控制等业务逻辑已迁移至
services/world_info_service.py。
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


def fetch_active_memory_rows(
    conn: ConnType, character_id: str
) -> list[dict[str, Any]]:
    """获取角色所有活跃记忆条目（纯 SQL，不做关键词匹配）。"""
    return conn.execute(
        """
        SELECT id, keywords, trigger_logic, content, position, priority,
               selective, constant, sticky, cooldown
        FROM character_memories
        WHERE character_id = %s AND is_active = 1
        ORDER BY priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()


def fetch_active_post_rule_rows(
    conn: ConnType,
    character_id: str,
    *,
    storyline_id: int | None = None,
    story_phase: str | None = None,
) -> list[dict[str, Any]]:
    """获取角色活跃后置规则（纯 SQL，条件过滤在 service 层处理）。"""
    conditions = ["character_id = %s", "is_active = 1"]
    params: list[Any] = [character_id]

    if storyline_id is not None:
        conditions.append("(storyline_id IS NULL OR storyline_id = %s)")
        params.append(storyline_id)

    if story_phase:
        conditions.append(
            "(story_phase IS NULL OR story_phase = '' OR story_phase = %s)"
        )
        params.append(story_phase)

    where_clause = " AND ".join(conditions)

    return conn.execute(
        f"""
        SELECT content, priority
        FROM character_post_rules
        WHERE {where_clause}
        ORDER BY priority ASC, id ASC
        """,
        tuple(params),
    ).fetchall()


def get_active_keyword_memories(
    conn: ConnType, character_id: str
) -> list[dict[str, Any]]:
    """获取角色所有活跃的关键词记忆（用于管理后台关键词测试）。"""
    return conn.execute(
        """
        SELECT id, keywords, trigger_logic, content
        FROM character_memories
        WHERE character_id = %s AND is_active = 1
        ORDER BY priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()
