"""剧情事件与故事进度 — 纯 SQL 层。

将 story_event_service.py 中的裸 SQL 下沉至此，
覆盖 story_events / user_story_progress / character_memories / character_greetings / character_storylines。
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


def fetch_active_story_events(
    conn: ConnType, character_id: str
) -> list[dict[str, Any]]:
    """获取角色所有启用的剧情事件，按触发分数升序。"""
    return conn.execute(
        """
        SELECT id, title, description, trigger_score, trigger_custom_key,
               unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
               event_content, is_active
        FROM story_events
        WHERE character_id = %s AND is_active = 1
        ORDER BY trigger_score ASC
        """,
        (character_id,),
    ).fetchall()


def get_triggered_event_ids(
    conn: ConnType, user_id: int | str, character_id: str
) -> set[int]:
    """读取用户已触发的剧情事件 ID 集合。"""
    progress_row = conn.execute(
        """
        SELECT triggered_event_ids FROM user_story_progress
        WHERE user_id = %s AND character_id = %s
        """,
        (user_id, character_id),
    ).fetchone()

    if not progress_row or not progress_row["triggered_event_ids"]:
        return set()

    return set(
        int(x.strip())
        for x in str(progress_row["triggered_event_ids"]).split(",")
        if x.strip().isdigit()
    )


def unlock_memories(
    conn: ConnType, character_id: str, memory_ids: list[int]
) -> None:
    """批量激活角色记忆条目。"""
    if not memory_ids:
        return
    placeholders = ",".join(["%s"] * len(memory_ids))
    conn.execute(
        f"""
        UPDATE character_memories
        SET is_active = 1
        WHERE character_id = %s AND id IN ({placeholders})
        """,
        (character_id,) + tuple(memory_ids),
    )


def unlock_greetings(
    conn: ConnType, character_id: str, greeting_ids: list[int]
) -> None:
    """批量激活角色开场白。"""
    if not greeting_ids:
        return
    placeholders = ",".join(["%s"] * len(greeting_ids))
    conn.execute(
        f"""
        UPDATE character_greetings
        SET is_active = 1
        WHERE character_id = %s AND id IN ({placeholders})
        """,
        (character_id,) + tuple(greeting_ids),
    )


def unlock_storyline(
    conn: ConnType, character_id: str, storyline_id: int
) -> None:
    """激活角色剧情线。"""
    conn.execute(
        """
        UPDATE character_storylines
        SET is_active = 1
        WHERE character_id = %s AND id = %s
        """,
        (character_id, storyline_id),
    )


def get_storyline_name(conn: ConnType, storyline_id: int) -> str | None:
    """获取剧情线名称。"""
    row = conn.execute(
        "SELECT name FROM character_storylines WHERE id = %s",
        (storyline_id,),
    ).fetchone()
    return row["name"] if row and row["name"] else None


def get_recent_event_titles(conn: ConnType, event_ids: list[int]) -> list[str]:
    """按 ID 列表获取最近剧情事件的标题（降序）。"""
    if not event_ids:
        return []
    placeholders = ",".join(["%s"] * len(event_ids))
    rows = conn.execute(
        f"SELECT title FROM story_events WHERE id IN ({placeholders}) ORDER BY id DESC",
        tuple(event_ids),
    ).fetchall()
    return [r["title"] for r in rows if r["title"]]


def get_current_storyline_id(
    conn: ConnType, user_id: int | str, character_id: str,
) -> int | None:
    """读取用户当前剧情线 ID。"""
    row = conn.execute(
        "SELECT current_storyline_id FROM user_story_progress WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    ).fetchone()
    if not row or row["current_storyline_id"] is None:
        return None
    try:
        return int(row["current_storyline_id"])
    except (ValueError, TypeError):
        return None


def is_storyline_valid(
    conn: ConnType, storyline_id: int, character_id: str,
) -> bool:
    """检查剧情线是否属于该角色且处于激活状态。"""
    row = conn.execute(
        "SELECT 1 FROM character_storylines WHERE id = %s AND character_id = %s AND is_active = TRUE",
        (storyline_id, character_id),
    ).fetchone()
    return row is not None


def set_current_storyline_id(
    conn: ConnType, user_id: int | str, character_id: str, storyline_id: int,
) -> None:
    """设置用户当前剧情线（不修改 triggered_event_ids）。"""
    conn.execute(
        """
        INSERT INTO user_story_progress (user_id, character_id, triggered_event_ids, current_storyline_id)
        VALUES (%s, %s, '', %s)
        ON CONFLICT(user_id, character_id) DO UPDATE SET
            current_storyline_id = excluded.current_storyline_id,
            last_updated = now()
        """,
        (user_id, character_id, storyline_id),
    )


def upsert_story_progress(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    triggered_ids_str: str,
    storyline_id: int | None = None,
) -> None:
    """写入/更新用户剧情进度（INSERT ON CONFLICT DO UPDATE）。"""
    conn.execute(
        """
        INSERT INTO user_story_progress
        (user_id, character_id, triggered_event_ids, current_storyline_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT(user_id, character_id) DO UPDATE SET
            triggered_event_ids = excluded.triggered_event_ids,
            last_updated = now()
        """,
        (user_id, character_id, triggered_ids_str, storyline_id),
    )
