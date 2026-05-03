from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.auth import CurrentUser, get_current_user
from core.database import ConnType, get_db_dep
from core.schemas import GreetingPayload, StorylinePayload

from ._shared import _write_audit_log
from .characters_common import _assert_storyline_owned

router = APIRouter(tags=["admin"])


@router.get("/admin/character/{character_id}/greetings")
def list_greetings(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    rows = conn.execute(
        """
        SELECT id, story_phase, mood, content, storyline_id,
               priority, is_active, use_count, comment, created_at, updated_at
        FROM character_greetings
        WHERE character_id = %s
        ORDER BY story_phase, priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()

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
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    _assert_storyline_owned(conn, character_id, body.storyline_id)

    cur = conn.execute(
        """
        INSERT INTO character_greetings
        (character_id, story_phase, mood, content, storyline_id,
         priority, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id,
            body.story_phase,
            body.mood,
            body.content,
            body.storyline_id,
            body.priority,
            body.is_active,
        ),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    return {"id": new_id, "ok": True}


@router.put("/admin/character/{character_id}/greetings/{greeting_id}")
def update_greeting(
    character_id: str,
    greeting_id: str,
    body: GreetingPayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    g = conn.execute(
        "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
        (greeting_id, character_id),
    ).fetchone()
    if not g:
        raise HTTPException(status_code=404, detail="开场白不存在")

    _assert_storyline_owned(conn, character_id, body.storyline_id)

    conn.execute(
        """
        UPDATE character_greetings SET
            story_phase = %s,
            mood = %s,
            content = %s,
            storyline_id = %s,
            priority = %s,
            is_active = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            body.story_phase,
            body.mood,
            body.content,
            body.storyline_id,
            body.priority,
            body.is_active,
            greeting_id,
        ),
    )
    conn.commit()

    return {"ok": True}


@router.delete("/admin/character/{character_id}/greetings/{greeting_id}")
def delete_greeting(
    character_id: str,
    greeting_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    g = conn.execute(
        "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
        (greeting_id, character_id),
    ).fetchone()
    if not g:
        raise HTTPException(status_code=404, detail="开场白不存在")

    conn.execute(
        "DELETE FROM character_greetings WHERE id = %s",
        (greeting_id,),
    )
    conn.commit()

    return {"ok": True}


@router.get("/admin/character/{character_id}/storylines")
def list_storylines(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    rows = conn.execute(
        """
        SELECT id, name, description, unlock_score, is_default,
               is_active, sort_order, created_at, updated_at
        FROM character_storylines
        WHERE character_id = %s
        ORDER BY sort_order ASC, id ASC
        """,
        (character_id,),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
            "unlock_score": row["unlock_score"],
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
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    if body.is_default:
        conn.execute(
            "UPDATE character_storylines SET is_default = FALSE WHERE character_id = %s",
            (character_id,),
        )

    cur = conn.execute(
        """
        INSERT INTO character_storylines
        (character_id, name, description,
         unlock_score, is_default, is_active, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            character_id,
            body.name,
            body.description,
            body.unlock_score,
            body.is_default,
            body.is_active,
            body.sort_order,
        ),
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    return {"id": new_id, "ok": True}


@router.put("/admin/character/{character_id}/storylines/{storyline_id}")
def update_storyline(
    character_id: str,
    storyline_id: str,
    body: StorylinePayload,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    sl = conn.execute(
        "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
        (storyline_id, character_id),
    ).fetchone()
    if not sl:
        raise HTTPException(status_code=404, detail="剧情线不存在")

    if body.is_default:
        conn.execute(
            """UPDATE character_storylines SET is_default = FALSE
               WHERE character_id = %s AND id != %s""",
            (character_id, storyline_id),
        )

    conn.execute(
        """
        UPDATE character_storylines SET
            name = %s,
            description = %s,
            unlock_score = %s,
            is_default = %s,
            is_active = %s,
            sort_order = %s,
            updated_at = now()
        WHERE id = %s
        """,
        (
            body.name,
            body.description,
            body.unlock_score,
            body.is_default,
            body.is_active,
            body.sort_order,
            storyline_id,
        ),
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
    sl = conn.execute(
        "SELECT id, name FROM character_storylines WHERE id = %s AND character_id = %s",
        (storyline_id, character_id),
    ).fetchone()
    if not sl:
        raise HTTPException(status_code=404, detail="剧情线不存在")

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

    conn.execute(
        "DELETE FROM character_storylines WHERE id = %s",
        (storyline_id,),
    )

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
    storyline = conn.execute(
        """
        SELECT id, name, is_default
        FROM character_storylines
        WHERE id = %s AND character_id = %s
        """,
        (storyline_id, character_id),
    ).fetchone()
    if not storyline:
        raise HTTPException(status_code=404, detail="剧情线不存在")

    greetings = conn.execute(
        """
        SELECT id, story_phase, content
        FROM character_greetings
        WHERE character_id = %s AND storyline_id = %s
        ORDER BY id ASC
        """,
        (character_id, storyline_id),
    ).fetchall()
    post_rules = conn.execute(
        """
        SELECT id, name
        FROM character_post_rules
        WHERE character_id = %s AND storyline_id = %s
        ORDER BY id ASC
        """,
        (character_id, storyline_id),
    ).fetchall()
    unlock_events = conn.execute(
        """
        SELECT id, title
        FROM story_events
        WHERE character_id = %s AND unlocked_storyline_id = %s
        ORDER BY id ASC
        """,
        (character_id, storyline_id),
    ).fetchall()

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
