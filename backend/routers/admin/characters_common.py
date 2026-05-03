from __future__ import annotations

from typing import Any

from core.database import ConnType
from fastapi import HTTPException


def _split_csv_ids(raw: str | None) -> list[str]:
    out: list[str] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(part)
    return out


def _assert_memory_category_owned(
    conn: ConnType,
    character_id: str,
    category_id: str | None,
) -> None:
    if category_id is None:
        return
    row = conn.execute(
        "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
        (category_id, character_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="分类不存在或不属于该角色")


def _assert_storyline_owned(
    conn: ConnType,
    character_id: str,
    storyline_id: str | None,
) -> None:
    if storyline_id is None:
        return
    row = conn.execute(
        "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
        (storyline_id, character_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="剧情线不存在或不属于该角色")


def _assert_story_event_unlock_refs_owned(
    conn: ConnType,
    character_id: str,
    unlocked_memory_ids: str | None,
    unlocked_greeting_ids: str | None,
    unlocked_storyline_id: str | None,
) -> None:
    memory_ids = _split_csv_ids(unlocked_memory_ids)
    greeting_ids = _split_csv_ids(unlocked_greeting_ids)

    if memory_ids:
        valid_memory_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM character_memories WHERE character_id = %s AND is_active = 1",
                (character_id,),
            ).fetchall()
        }
        bad_ids = [x for x in memory_ids if x not in valid_memory_ids]
        if bad_ids:
            raise HTTPException(status_code=400, detail=f"存在无效或已禁用的记忆解锁对象：{bad_ids}")

    if greeting_ids:
        valid_greeting_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM character_greetings WHERE character_id = %s AND is_active = 1",
                (character_id,),
            ).fetchall()
        }
        bad_ids = [x for x in greeting_ids if x not in valid_greeting_ids]
        if bad_ids:
            raise HTTPException(status_code=400, detail=f"存在无效或已禁用的开场白解锁对象：{bad_ids}")

    if unlocked_storyline_id:
        row = conn.execute(
            "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s AND is_active = 1",
            (unlocked_storyline_id, character_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="解锁的剧情线不存在、不属于该角色或已被禁用")
