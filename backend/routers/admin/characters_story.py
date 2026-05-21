from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user
from core.database import ConnType, get_db_dep
from core.schemas import GreetingPayload, StorylinePayload
from repositories import character_admin_story_repository as admin_repo
from repositories import character_repository as char_repo
from utils.json_utils import to_json_string

from ._helpers import _write_audit_log, _assert_storyline_owned

# 认证依赖由父路由 _router.py 统一提供
router = APIRouter(tags=["admin"])


def _require_character(conn: ConnType, character_id: str) -> None:
    if not char_repo.check_character_exists(conn, character_id):
        raise HTTPException(status_code=404, detail="角色不存在")


@router.get("/admin/character/{character_id}/greetings")
def list_greetings(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    _require_character(conn, character_id)
    rows = admin_repo.admin_list_greetings(conn, character_id)
    return [
        {
            "id": row["id"],
            "story_phase": row["story_phase"],
            "mood": row["mood"],
            "content": row["content"],
            "storyline_id": row["storyline_id"],
            "priority": row["priority"],
            "is_active": bool(row["is_active"]),
            "use_count": row["use_count"],
            "comment": row["comment"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@router.post("/admin/character/{character_id}/greetings")
def create_greeting(
    character_id: str,
    body: GreetingPayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    _require_character(conn, character_id)
    _assert_storyline_owned(conn, character_id, body.storyline_id)

    new_id = admin_repo.admin_create_greeting(
        conn,
        character_id,
        story_phase=body.story_phase,
        mood=body.mood,
        content=body.content,
        storyline_id=body.storyline_id,
        priority=body.priority,
        is_active=body.is_active,
        comment=body.comment,
    )
    conn.commit()
    return {"id": new_id, "ok": True}


@router.put("/admin/character/{character_id}/greetings/{greeting_id}")
def update_greeting(
    character_id: str,
    greeting_id: str,
    body: GreetingPayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    if not admin_repo.admin_get_greeting(conn, greeting_id, character_id):
        raise HTTPException(status_code=404, detail="开场白不存在")
    _assert_storyline_owned(conn, character_id, body.storyline_id)

    admin_repo.admin_update_greeting(
        conn,
        greeting_id,
        story_phase=body.story_phase,
        mood=body.mood,
        content=body.content,
        storyline_id=body.storyline_id,
        priority=body.priority,
        is_active=body.is_active,
        comment=body.comment,
    )
    conn.commit()
    return {"ok": True}


@router.delete("/admin/character/{character_id}/greetings/{greeting_id}")
def delete_greeting(
    character_id: str,
    greeting_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    if not admin_repo.admin_get_greeting(conn, greeting_id, character_id):
        raise HTTPException(status_code=404, detail="开场白不存在")

    admin_repo.admin_delete_greeting(conn, greeting_id)
    conn.commit()
    return {"ok": True}


@router.get("/admin/character/{character_id}/storylines")
def list_storylines(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    _require_character(conn, character_id)
    rows = admin_repo.admin_list_storylines(conn, character_id)
    return [
        {
            "id": row["id"],
            "storyline_id": row["storyline_id"] or "",
            "title": row["title"] or "",
            "name": row["name"] or "",
            "description": row["description"] or "",
            "unlock_score": row["unlock_score"],
            "unlock_condition": row["unlock_condition"] or "",
            "stages": row["stages"] if isinstance(row.get("stages"), list) else [],
            "is_default": bool(row["is_default"]),
            "is_active": bool(row["is_active"]),
            "sort_order": row["sort_order"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@router.post("/admin/character/{character_id}/storylines")
def create_storyline(
    character_id: str,
    body: StorylinePayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    _require_character(conn, character_id)

    if body.is_default:
        admin_repo.admin_clear_default_storyline(conn, character_id)

    new_id = admin_repo.admin_create_storyline(
        conn,
        character_id,
        storyline_id=body.storyline_id,
        title=body.title,
        name=body.name,
        description=body.description,
        unlock_score=body.unlock_score,
        unlock_condition=body.unlock_condition,
        stages_json=to_json_string(body.stages),
        is_default=body.is_default,
        is_active=body.is_active,
        sort_order=body.sort_order,
    )
    conn.commit()
    return {"id": new_id, "ok": True}


@router.put("/admin/character/{character_id}/storylines/{storyline_id}")
def update_storyline(
    character_id: str,
    storyline_id: str,
    body: StorylinePayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    if not admin_repo.admin_get_storyline(conn, storyline_id, character_id):
        raise HTTPException(status_code=404, detail="剧情线不存在")

    if body.is_default:
        admin_repo.admin_clear_default_storyline(conn, character_id, exclude_id=storyline_id)

    admin_repo.admin_update_storyline(
        conn,
        storyline_id,
        storyline_id_field=body.storyline_id,
        title=body.title,
        name=body.name,
        description=body.description,
        unlock_score=body.unlock_score,
        unlock_condition=body.unlock_condition,
        stages_json=to_json_string(body.stages),
        is_default=body.is_default,
        is_active=body.is_active,
        sort_order=body.sort_order,
    )
    conn.commit()
    return {"ok": True}


@router.delete("/admin/character/{character_id}/storylines/{storyline_id}")
def delete_storyline(
    character_id: str,
    storyline_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    sl = admin_repo.admin_get_storyline(conn, storyline_id, character_id)
    if not sl:
        raise HTTPException(status_code=404, detail="剧情线不存在")

    admin_repo.admin_detach_storyline_refs(conn, storyline_id)
    admin_repo.admin_delete_storyline(conn, storyline_id)

    _write_audit_log(
        conn,
        operator_id=current_user.id,
        operator_email=current_user.email,
        action="delete_storyline",
        target_type="storyline",
        target_id=storyline_id,
        detail={
            "character_id": character_id,
            "storyline_name": sl["name"],
        },
    )
    conn.commit()
    return {"ok": True}


@router.get("/admin/character/{character_id}/storylines/{storyline_id}/delete-impact")
def storyline_delete_impact(
    character_id: str,
    storyline_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    storyline = admin_repo.admin_get_storyline_for_impact(conn, storyline_id, character_id)
    if not storyline:
        raise HTTPException(status_code=404, detail="剧情线不存在")

    greetings = admin_repo.admin_list_greetings_for_storyline(conn, character_id, storyline_id)
    post_rules = admin_repo.admin_list_post_rules_for_storyline(conn, character_id, storyline_id)
    unlock_events = admin_repo.admin_list_story_events_for_storyline(conn, character_id, storyline_id)

    return {
        "character_id": character_id,
        "storyline": {
            "id": storyline["id"],
            "name": storyline["name"],
            "is_default": bool(storyline["is_default"]),
        },
        "impact": {
            "greetings": [
                {
                    "id": row["id"],
                    "label": f"{row['story_phase']} / {(row['content'] or '')[:24]}",
                }
                for row in greetings
            ],
            "post_rules": [
                {
                    "id": row["id"],
                    "label": row["name"] or f"规则#{row['id']}",
                }
                for row in post_rules
            ],
            "unlock_events": [
                {
                    "id": row["id"],
                    "label": row["title"] or f"事件#{row['id']}",
                }
                for row in unlock_events
            ],
        },
        "summary": {
            "greeting_count": len(greetings),
            "post_rule_count": len(post_rules),
            "unlock_event_count": len(unlock_events),
        },
    }
