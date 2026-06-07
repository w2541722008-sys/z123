from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends

from core.auth import get_admin_user
from core.database import ConnType, get_db_dep
from core.exceptions import BadRequestError, NotFoundError
from core.schemas import PostRulePayload, StoryEventPayload
from repositories import character_admin_story_repository as admin_repo
from repositories import character_repository as char_repo

from ._helpers import (
    _assert_story_event_unlock_refs_owned,
    _assert_storyline_owned,
)

# 认证依赖由父路由 _router.py 统一提供
router = APIRouter(tags=["admin"])


def _require_character(conn: ConnType, character_id: str) -> None:
    if not char_repo.check_character_exists(conn, character_id):
        raise NotFoundError(detail="角色不存在")


@router.get("/admin/character/{character_id}/post-rules")
def list_post_rules(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    _require_character(conn, character_id)
    rows = admin_repo.admin_list_post_rules(conn, character_id)
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
    _require_character(conn, character_id)
    _assert_storyline_owned(conn, character_id, body.storyline_id)

    new_id = admin_repo.admin_create_post_rule(
        conn,
        character_id,
        name=body.name,
        content=body.content,
        storyline_id=body.storyline_id,
        story_phase=body.story_phase if body.story_phase else "",
        priority=body.priority,
        is_active=body.is_active,
    )
    conn.commit()
    return {"ok": True, "id": new_id}


@router.put("/admin/character/{character_id}/post-rules/{rule_id}")
def update_post_rule(
    character_id: str,
    rule_id: str,
    body: PostRulePayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    if not admin_repo.admin_get_post_rule(conn, rule_id, character_id):
        raise NotFoundError(detail="后置规则不存在")
    _assert_storyline_owned(conn, character_id, body.storyline_id)

    admin_repo.admin_update_post_rule(
        conn,
        rule_id,
        name=body.name,
        content=body.content,
        storyline_id=body.storyline_id,
        story_phase=body.story_phase if body.story_phase else "",
        priority=body.priority,
        is_active=body.is_active,
    )
    conn.commit()
    return {"ok": True}


@router.delete("/admin/character/{character_id}/post-rules/{rule_id}")
def delete_post_rule(
    character_id: str,
    rule_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    if not admin_repo.admin_get_post_rule(conn, rule_id, character_id):
        raise NotFoundError(detail="后置规则不存在")

    admin_repo.admin_delete_post_rule(conn, rule_id)
    conn.commit()
    return {"ok": True}


@router.get("/admin/character/{character_id}/story-events")
def list_story_events(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    _require_character(conn, character_id)
    rows = admin_repo.admin_list_story_events(conn, character_id)
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"] or "",
            "trigger_score": row["trigger_score"],
            "trigger_custom_key": row["trigger_custom_key"] or "",
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
    _require_character(conn, character_id)
    _assert_story_event_unlock_refs_owned(
        conn, character_id,
        body.unlocked_memory_ids, body.unlocked_greeting_ids, body.unlocked_storyline_id,
    )

    new_id = admin_repo.admin_create_story_event(
        conn,
        character_id,
        event_id=str(uuid.uuid4()),
        title=body.title,
        description=body.description,
        trigger_score=body.trigger_score,
        trigger_custom_key=body.trigger_custom_key or "",
        unlocked_memory_ids=body.unlocked_memory_ids or "",
        unlocked_greeting_ids=body.unlocked_greeting_ids or "",
        unlocked_storyline_id=body.unlocked_storyline_id if body.unlocked_storyline_id else None,
        event_content=body.event_content or "",
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    conn.commit()
    return {"ok": True, "id": new_id}


@router.put("/admin/character/{character_id}/story-events/{event_id}")
def update_story_event(
    character_id: str,
    event_id: str,
    body: StoryEventPayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    if not admin_repo.admin_get_story_event(conn, event_id, character_id):
        raise NotFoundError(detail="剧情事件不存在")
    _assert_story_event_unlock_refs_owned(
        conn, character_id,
        body.unlocked_memory_ids, body.unlocked_greeting_ids, body.unlocked_storyline_id,
    )

    admin_repo.admin_update_story_event(
        conn,
        event_id,
        title=body.title,
        description=body.description,
        trigger_score=body.trigger_score,
        trigger_custom_key=body.trigger_custom_key or "",
        unlocked_memory_ids=body.unlocked_memory_ids or "",
        unlocked_greeting_ids=body.unlocked_greeting_ids or "",
        unlocked_storyline_id=body.unlocked_storyline_id if body.unlocked_storyline_id else None,
        event_content=body.event_content or "",
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    conn.commit()
    return {"ok": True}


@router.delete("/admin/character/{character_id}/story-events/{event_id}")
def delete_story_event(
    character_id: str,
    event_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    if not admin_repo.admin_get_story_event(conn, event_id, character_id):
        raise NotFoundError(detail="剧情事件不存在")

    admin_repo.admin_delete_story_event(conn, event_id)
    conn.commit()
    return {"ok": True}
