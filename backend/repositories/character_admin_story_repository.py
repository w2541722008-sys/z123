"""
管理后台角色故事资产 CRUD — 纯 SQL 层。

覆盖表：character_greetings, character_storylines, character_post_rules, story_events

设计原则：
    - 只做 SQL，不管理事务（commit/rollback 由调用方控制）
    - 返回原始行（RealDictRow），表示层格式由路由负责
    - 函数以 admin_ 前缀命名，区分于用户端查询
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


# ============================================================
# 开场白 (character_greetings)
# ============================================================

def admin_list_greetings(conn: ConnType, character_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, story_phase, mood, content, storyline_id,
               priority, is_active, use_count, comment, created_at, updated_at
        FROM character_greetings
        WHERE character_id = %s
        ORDER BY story_phase, priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()


def admin_create_greeting(
    conn: ConnType,
    character_id: str,
    *,
    story_phase: str,
    mood: str,
    content: str,
    storyline_id: str | None,
    priority: int,
    is_active: bool,
    comment: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO character_greetings
        (character_id, story_phase, mood, content, storyline_id,
         priority, is_active, comment)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id, story_phase, mood, content, storyline_id,
            priority, is_active, comment,
        ),
    )
    return cur.fetchone()["id"]


def admin_get_greeting(
    conn: ConnType, greeting_id: str, character_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
        (greeting_id, character_id),
    ).fetchone()


def admin_update_greeting(
    conn: ConnType,
    greeting_id: str,
    *,
    story_phase: str,
    mood: str,
    content: str,
    storyline_id: str | None,
    priority: int,
    is_active: bool,
    comment: str | None,
) -> None:
    conn.execute(
        """
        UPDATE character_greetings SET
            story_phase = %s, mood = %s, content = %s, storyline_id = %s,
            priority = %s, is_active = %s, comment = %s, updated_at = now()
        WHERE id = %s
        """,
        (
            story_phase, mood, content, storyline_id,
            priority, is_active, comment, greeting_id,
        ),
    )


def admin_delete_greeting(conn: ConnType, greeting_id: str) -> None:
    conn.execute("DELETE FROM character_greetings WHERE id = %s", (greeting_id,))


# ============================================================
# 剧情线 (character_storylines)
# ============================================================

def admin_list_storylines(conn: ConnType, character_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, storyline_id, title, name, description, unlock_score,
               unlock_condition, stages, is_default,
               is_active, sort_order, created_at, updated_at
        FROM character_storylines
        WHERE character_id = %s
        ORDER BY sort_order ASC, id ASC
        """,
        (character_id,),
    ).fetchall()


def admin_clear_default_storyline(
    conn: ConnType, character_id: str, *, exclude_id: str | None = None
) -> None:
    if exclude_id:
        conn.execute(
            "UPDATE character_storylines SET is_default = 0 WHERE character_id = %s AND id != %s",
            (character_id, exclude_id),
        )
    else:
        conn.execute(
            "UPDATE character_storylines SET is_default = 0 WHERE character_id = %s",
            (character_id,),
        )


def admin_create_storyline(
    conn: ConnType,
    character_id: str,
    *,
    storyline_id: str | None,
    title: str,
    name: str,
    description: str | None,
    unlock_score: int,
    unlock_condition: str | None,
    stages_json: str,
    is_default: bool,
    is_active: bool,
    sort_order: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO character_storylines
        (character_id, storyline_id, title, name, description,
         unlock_score, unlock_condition, stages,
         is_default, is_active, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id, storyline_id, title, name, description,
            unlock_score, unlock_condition, stages_json,
            is_default, is_active, sort_order,
        ),
    )
    return cur.fetchone()["id"]


def admin_get_storyline(
    conn: ConnType, storyline_id: str, character_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id, name FROM character_storylines WHERE id = %s AND character_id = %s",
        (storyline_id, character_id),
    ).fetchone()


def admin_update_storyline(
    conn: ConnType,
    storyline_id: str,
    *,
    storyline_id_field: str | None,
    title: str,
    name: str,
    description: str | None,
    unlock_score: int,
    unlock_condition: str | None,
    stages_json: str,
    is_default: bool,
    is_active: bool,
    sort_order: int,
) -> None:
    conn.execute(
        """
        UPDATE character_storylines SET
            storyline_id = %s, title = %s, name = %s, description = %s,
            unlock_score = %s, unlock_condition = %s, stages = %s,
            is_default = %s, is_active = %s, sort_order = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            storyline_id_field, title, name, description,
            unlock_score, unlock_condition, stages_json,
            is_default, is_active, sort_order, storyline_id,
        ),
    )


def admin_detach_storyline_refs(conn: ConnType, storyline_id: str) -> None:
    """删除剧情线前，将关联的开场白/后置规则/剧情事件的引用置空。"""
    conn.execute(
        "UPDATE character_greetings SET storyline_id = NULL WHERE storyline_id = %s",
        (storyline_id,),
    )
    conn.execute(
        "UPDATE character_post_rules SET storyline_id = NULL WHERE storyline_id = %s",
        (storyline_id,),
    )
    conn.execute(
        "UPDATE story_events SET unlocked_storyline_id = NULL WHERE unlocked_storyline_id = %s",
        (storyline_id,),
    )


def admin_delete_storyline(conn: ConnType, storyline_id: str) -> None:
    conn.execute("DELETE FROM character_storylines WHERE id = %s", (storyline_id,))


def admin_get_storyline_for_impact(
    conn: ConnType, storyline_id: str, character_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, name, is_default
        FROM character_storylines
        WHERE id = %s AND character_id = %s
        """,
        (storyline_id, character_id),
    ).fetchone()


def admin_list_greetings_for_storyline(
    conn: ConnType, character_id: str, storyline_id: str
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, story_phase, content
        FROM character_greetings
        WHERE character_id = %s AND storyline_id = %s
        ORDER BY id ASC
        """,
        (character_id, storyline_id),
    ).fetchall()


def admin_list_post_rules_for_storyline(
    conn: ConnType, character_id: str, storyline_id: str
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, name
        FROM character_post_rules
        WHERE character_id = %s AND storyline_id = %s
        ORDER BY id ASC
        """,
        (character_id, storyline_id),
    ).fetchall()


def admin_list_story_events_for_storyline(
    conn: ConnType, character_id: str, storyline_id: str
) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, title
        FROM story_events
        WHERE character_id = %s AND unlocked_storyline_id = %s
        ORDER BY id ASC
        """,
        (character_id, storyline_id),
    ).fetchall()


# ============================================================
# 后置规则 (character_post_rules)
# ============================================================

def admin_list_post_rules(conn: ConnType, character_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, name, content, storyline_id, story_phase,
               priority, is_active, created_at, updated_at
        FROM character_post_rules
        WHERE character_id = %s
        ORDER BY priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()


def admin_create_post_rule(
    conn: ConnType,
    character_id: str,
    *,
    name: str,
    content: str,
    storyline_id: str | None,
    story_phase: str,
    priority: int,
    is_active: bool,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO character_post_rules
        (character_id, name, content, storyline_id, story_phase,
         priority, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id, name, content, storyline_id, story_phase,
            priority, is_active,
        ),
    )
    return cur.fetchone()["id"]


def admin_get_post_rule(
    conn: ConnType, rule_id: str, character_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
        (rule_id, character_id),
    ).fetchone()


def admin_update_post_rule(
    conn: ConnType,
    rule_id: str,
    *,
    name: str,
    content: str,
    storyline_id: str | None,
    story_phase: str,
    priority: int,
    is_active: bool,
) -> None:
    conn.execute(
        """
        UPDATE character_post_rules SET
            name = %s, content = %s, storyline_id = %s, story_phase = %s,
            priority = %s, is_active = %s, updated_at = now()
        WHERE id = %s
        """,
        (
            name, content, storyline_id, story_phase,
            priority, is_active, rule_id,
        ),
    )


def admin_delete_post_rule(conn: ConnType, rule_id: str) -> None:
    conn.execute("DELETE FROM character_post_rules WHERE id = %s", (rule_id,))


# ============================================================
# 剧情事件 (story_events)
# ============================================================

def admin_list_story_events(conn: ConnType, character_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT id, title, description, trigger_score, trigger_custom_key,
               unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
               event_content, sort_order, is_active, created_at, updated_at
        FROM story_events
        WHERE character_id = %s
        ORDER BY trigger_score ASC, sort_order ASC, id ASC
        """,
        (character_id,),
    ).fetchall()


def admin_create_story_event(
    conn: ConnType,
    character_id: str,
    *,
    event_id: str,
    title: str,
    description: str | None,
    trigger_score: int,
    trigger_custom_key: str,
    unlocked_memory_ids: str,
    unlocked_greeting_ids: str,
    unlocked_storyline_id: str | None,
    event_content: str,
    sort_order: int,
    is_active: bool,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO story_events
        (character_id, event_id, title, description, trigger_score, trigger_custom_key,
         unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
         event_content, sort_order, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id, event_id, title, description, trigger_score,
            trigger_custom_key, unlocked_memory_ids, unlocked_greeting_ids,
            unlocked_storyline_id, event_content, sort_order, is_active,
        ),
    )
    return cur.fetchone()["id"]


def admin_get_story_event(
    conn: ConnType, event_id: str, character_id: str
) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
        (event_id, character_id),
    ).fetchone()


def admin_update_story_event(
    conn: ConnType,
    event_id: str,
    *,
    title: str,
    description: str | None,
    trigger_score: int,
    trigger_custom_key: str,
    unlocked_memory_ids: str,
    unlocked_greeting_ids: str,
    unlocked_storyline_id: str | None,
    event_content: str,
    sort_order: int,
    is_active: bool,
) -> None:
    conn.execute(
        """
        UPDATE story_events SET
            title = %s, description = %s, trigger_score = %s,
            trigger_custom_key = %s, unlocked_memory_ids = %s,
            unlocked_greeting_ids = %s, unlocked_storyline_id = %s,
            event_content = %s, sort_order = %s, is_active = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            title, description, trigger_score, trigger_custom_key,
            unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
            event_content, sort_order, is_active, event_id,
        ),
    )


def admin_delete_story_event(conn: ConnType, event_id: str) -> None:
    conn.execute("DELETE FROM story_events WHERE id = %s", (event_id,))
