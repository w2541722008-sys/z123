from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_admin_user
from core.database import ConnType, get_db_dep
from core.schemas import PostRulePayload, StoryEventPayload

from .characters_common import (
    _assert_story_event_unlock_refs_owned,
    _assert_storyline_owned,
)

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])


@router.get("/admin/character/{character_id}/post-rules")
def list_post_rules(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    rows = conn.execute(
        """
        SELECT id, name, content, storyline_id, story_phase,
               priority, is_active, created_at, updated_at
        FROM character_post_rules
        WHERE character_id = %s
        ORDER BY priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "content": row["content"],
            "storyline_id": row["storyline_id"],
            "story_phase": row["story_phase"],
            "priority": row["priority"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@router.post("/admin/character/{character_id}/post-rules")
def create_post_rule(
    character_id: str,
    body: PostRulePayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    _assert_storyline_owned(conn, character_id, body.storyline_id)

    story_phase_val = body.story_phase if body.story_phase else ""
    cur = conn.execute(
        """
        INSERT INTO character_post_rules
        (character_id, name, content, storyline_id, story_phase,
         priority, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id,
            body.name,
            body.content,
            body.storyline_id,
            story_phase_val,
            body.priority,
            body.is_active,
        ),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    return {"ok": True, "id": new_id}


@router.put("/admin/character/{character_id}/post-rules/{rule_id}")
def update_post_rule(
    character_id: str,
    rule_id: str,
    body: PostRulePayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    rule = conn.execute(
        "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
        (rule_id, character_id),
    ).fetchone()
    if not rule:
        raise HTTPException(status_code=404, detail="后置规则不存在")

    _assert_storyline_owned(conn, character_id, body.storyline_id)

    story_phase_val = body.story_phase if body.story_phase else ""
    conn.execute(
        """
        UPDATE character_post_rules SET
            name = %s,
            content = %s,
            storyline_id = %s,
            story_phase = %s,
            priority = %s,
            is_active = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            body.name,
            body.content,
            body.storyline_id,
            story_phase_val,
            body.priority,
            body.is_active,
            rule_id,
        ),
    )
    conn.commit()

    return {"ok": True}


@router.delete("/admin/character/{character_id}/post-rules/{rule_id}")
def delete_post_rule(
    character_id: str,
    rule_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    rule = conn.execute(
        "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
        (rule_id, character_id),
    ).fetchone()
    if not rule:
        raise HTTPException(status_code=404, detail="后置规则不存在")

    conn.execute(
        "DELETE FROM character_post_rules WHERE id = %s",
        (rule_id,),
    )
    conn.commit()

    return {"ok": True}


@router.get("/admin/character/{character_id}/story-events")
def list_story_events(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    rows = conn.execute(
        """
        SELECT id, title, description, trigger_score,
               unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
               event_content, sort_order, is_active, created_at, updated_at
        FROM story_events
        WHERE character_id = %s
        ORDER BY trigger_score ASC, sort_order ASC, id ASC
        """,
        (character_id,),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"] or "",
            "trigger_score": row["trigger_score"],
            "unlocked_memory_ids": row["unlocked_memory_ids"] or "",
            "unlocked_greeting_ids": row["unlocked_greeting_ids"] or "",
            "unlocked_storyline_id": row["unlocked_storyline_id"],
            "event_content": row["event_content"] or "",
            "sort_order": row["sort_order"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@router.post("/admin/character/{character_id}/story-events")
def create_story_event(
    character_id: str,
    body: StoryEventPayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    _assert_story_event_unlock_refs_owned(
        conn,
        character_id,
        body.unlocked_memory_ids,
        body.unlocked_greeting_ids,
        body.unlocked_storyline_id,
    )

    unlocked_sl_id = body.unlocked_storyline_id if body.unlocked_storyline_id else None
    cur = conn.execute(
        """
        INSERT INTO story_events
        (character_id, event_id, title, description, trigger_score,
         unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
         event_content, sort_order, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id,
            str(uuid.uuid4()),
            body.title,
            body.description,
            body.trigger_score,
            body.unlocked_memory_ids or "",
            body.unlocked_greeting_ids or "",
            unlocked_sl_id,
            body.event_content or "",
            body.sort_order,
            body.is_active,
        ),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    return {"ok": True, "id": new_id}


@router.put("/admin/character/{character_id}/story-events/{event_id}")
def update_story_event(
    character_id: str,
    event_id: str,
    body: StoryEventPayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    event = conn.execute(
        "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
        (event_id, character_id),
    ).fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="剧情事件不存在")

    _assert_story_event_unlock_refs_owned(
        conn,
        character_id,
        body.unlocked_memory_ids,
        body.unlocked_greeting_ids,
        body.unlocked_storyline_id,
    )

    unlocked_sl_id = body.unlocked_storyline_id if body.unlocked_storyline_id else None
    conn.execute(
        """
        UPDATE story_events SET
            title = %s,
            description = %s,
            trigger_score = %s,
            unlocked_memory_ids = %s,
            unlocked_greeting_ids = %s,
            unlocked_storyline_id = %s,
            event_content = %s,
            sort_order = %s,
            is_active = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            body.title,
            body.description,
            body.trigger_score,
            body.unlocked_memory_ids or "",
            body.unlocked_greeting_ids or "",
            unlocked_sl_id,
            body.event_content or "",
            body.sort_order,
            body.is_active,
            event_id,
        ),
    )
    conn.commit()

    return {"ok": True}


@router.delete("/admin/character/{character_id}/story-events/{event_id}")
def delete_story_event(
    character_id: str,
    event_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    event = conn.execute(
        "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
        (event_id, character_id),
    ).fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="剧情事件不存在")

    conn.execute(
        "DELETE FROM story_events WHERE id = %s",
        (event_id,),
    )
    conn.commit()

    return {"ok": True}
