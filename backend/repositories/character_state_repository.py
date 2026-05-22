"""角色关系状态 — 纯 SQL 层。

将 character_state.py 中 character_states 表的裸 SQL 下沉至此。
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


def get_character_state(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    """读取用户对某角色的关系状态行，可选 FOR UPDATE 行锁。"""
    lock_clause = "\nFOR UPDATE" if for_update else ""
    return conn.execute(
        f"""
        SELECT affection, story_phase, mood, custom_vars,
               daily_event_counts, daily_affection_gained, last_event_timestamps, daily_reset_date
        FROM character_states
        WHERE user_id = %s AND character_id = %s{lock_clause}
        """,
        (user_id, character_id),
    ).fetchone()


def upsert_character_state(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    affection: int,
    story_phase: str,
    mood: str,
    custom_vars_json: str,
    daily_event_counts_json: str,
    daily_affection_gained: int,
    last_event_timestamps_json: str,
    daily_reset_date: str,
) -> None:
    """写入/更新角色关系状态（INSERT ON CONFLICT DO UPDATE）。

    所有 JSON 字段由调用方预序列化，本方法不自行 commit。
    """
    conn.execute(
        """
        INSERT INTO character_states(
            user_id, character_id, affection, story_phase, mood, custom_vars,
            daily_event_counts, daily_affection_gained, last_event_timestamps,
            daily_reset_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(user_id, character_id) DO UPDATE SET
            affection = excluded.affection,
            story_phase = excluded.story_phase,
            mood = excluded.mood,
            custom_vars = excluded.custom_vars,
            daily_event_counts = excluded.daily_event_counts,
            daily_affection_gained = excluded.daily_affection_gained,
            last_event_timestamps = excluded.last_event_timestamps,
            daily_reset_date = excluded.daily_reset_date,
            updated_at = now()
        """,
        (
            user_id, character_id, affection, story_phase, mood, custom_vars_json,
            daily_event_counts_json, daily_affection_gained, last_event_timestamps_json,
            daily_reset_date,
        ),
    )
