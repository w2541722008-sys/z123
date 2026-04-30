from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import utc_now_iso
from database import get_conn
from models import MemoryCategoryPayload, MemoryEntryPayload

from .characters_common import _assert_memory_category_owned

router = APIRouter(tags=["admin"])


@router.get("/admin/character/{character_id}/memories")
def list_memories(character_id: str) -> list[dict[str, object]]:
    conn = get_conn()
    try:
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, keywords, trigger_logic, content, category_id, position,
                   priority, is_active, comment, created_at, updated_at
            FROM character_memories
            WHERE character_id = %s
            ORDER BY priority ASC, id ASC
            """,
            (character_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "keywords": row["keywords"],
                "trigger_logic": row["trigger_logic"],
                "content": row["content"],
                "category_id": row["category_id"],
                "position": row["position"],
                "priority": row["priority"],
                "is_active": bool(row["is_active"]),
                "comment": row["comment"] or "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/memories")
def create_memory(
    character_id: str,
    body: MemoryEntryPayload,
) -> dict[str, object]:
    conn = get_conn()
    try:
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        _assert_memory_category_owned(conn, character_id, body.category_id)

        now = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO character_memories
            (character_id, keywords, trigger_logic, content, category_id, position,
             priority, is_active, comment, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                body.keywords,
                body.trigger_logic,
                body.content,
                body.category_id,
                body.position,
                body.priority,
                body.is_active,
                body.comment,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"id": new_id, "ok": True}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/memories/{memory_id}")
def update_memory(
    character_id: str,
    memory_id: str,
    body: MemoryEntryPayload,
) -> dict[str, object]:
    conn = get_conn()
    try:
        mem = conn.execute(
            "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
            (memory_id, character_id),
        ).fetchone()
        if not mem:
            raise HTTPException(status_code=404, detail="记忆条目不存在")

        _assert_memory_category_owned(conn, character_id, body.category_id)

        now = utc_now_iso()
        conn.execute(
            """
            UPDATE character_memories SET
                keywords = %s,
                trigger_logic = %s,
                content = %s,
                category_id = %s,
                position = %s,
                priority = %s,
                is_active = %s,
                comment = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.keywords,
                body.trigger_logic,
                body.content,
                body.category_id,
                body.position,
                body.priority,
                body.is_active,
                body.comment,
                now,
                memory_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/memories/{memory_id}")
def delete_memory(
    character_id: str,
    memory_id: str,
) -> dict[str, object]:
    conn = get_conn()
    try:
        mem = conn.execute(
            "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
            (memory_id, character_id),
        ).fetchone()
        if not mem:
            raise HTTPException(status_code=404, detail="记忆条目不存在")

        conn.execute(
            "DELETE FROM character_memories WHERE id = %s",
            (memory_id,),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.get("/admin/character/{character_id}/memory-categories")
def list_memory_categories(character_id: str) -> list[dict[str, object]]:
    conn = get_conn()
    try:
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, name, description, color, sort_order, created_at, updated_at
            FROM memory_categories
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
                "color": row["color"] or "#1890FF",
                "sort_order": row["sort_order"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/memory-categories")
def create_memory_category(
    character_id: str,
    body: MemoryCategoryPayload,
) -> dict[str, object]:
    conn = get_conn()
    try:
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        now = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO memory_categories
            (character_id, name, description, color, sort_order, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                body.name,
                body.description,
                body.color,
                body.sort_order,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"ok": True, "id": new_id}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/memory-categories/{category_id}")
def update_memory_category(
    character_id: str,
    category_id: str,
    body: MemoryCategoryPayload,
) -> dict[str, object]:
    conn = get_conn()
    try:
        cat = conn.execute(
            "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
            (category_id, character_id),
        ).fetchone()
        if not cat:
            raise HTTPException(status_code=404, detail="记忆分类不存在")

        now = utc_now_iso()
        conn.execute(
            """
            UPDATE memory_categories SET
                name = %s,
                description = %s,
                color = %s,
                sort_order = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.name,
                body.description,
                body.color,
                body.sort_order,
                now,
                category_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/memory-categories/{category_id}")
def delete_memory_category(
    character_id: str,
    category_id: str,
) -> dict[str, object]:
    conn = get_conn()
    try:
        cat = conn.execute(
            "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
            (category_id, character_id),
        ).fetchone()
        if not cat:
            raise HTTPException(status_code=404, detail="记忆分类不存在")

        mem_count = conn.execute(
            "SELECT COUNT(*) FROM character_memories WHERE category_id = %s",
            (category_id,),
        ).fetchone()["count"]

        if mem_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"该分类下还有 {mem_count} 个记忆条目，请先移除或修改这些条目",
            )

        conn.execute(
            "DELETE FROM memory_categories WHERE id = %s",
            (category_id,),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.get("/admin/character/{character_id}/memory-categories/{category_id}/delete-impact")
def memory_category_delete_impact(
    character_id: str,
    category_id: str,
) -> dict[str, object]:
    conn = get_conn()
    try:
        category = conn.execute(
            """
            SELECT id, name
            FROM memory_categories
            WHERE id = %s AND character_id = %s
            """,
            (category_id, character_id),
        ).fetchone()
        if not category:
            raise HTTPException(status_code=404, detail="记忆分类不存在")

        memories = conn.execute(
            """
            SELECT id, keywords, comment
            FROM character_memories
            WHERE character_id = %s AND category_id = %s
            ORDER BY priority ASC, id ASC
            """,
            (character_id, category_id),
        ).fetchall()

        return {
            "character_id": character_id,
            "category": {
                "id": category["id"],
                "name": category["name"],
            },
            "impact": {
                "memories": [
                    {
                        "id": row["id"],
                        "label": row["keywords"] or row["comment"] or f"记忆#{row['id']}",
                    }
                    for row in memories
                ]
            },
            "summary": {
                "memory_count": len(memories),
            },
        }
    finally:
        conn.close()
