from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import CurrentUser, get_admin_user
from core.database import ConnType, get_db_dep
from core.exceptions import BadRequestError, NotFoundError
from core.schemas import MemoryCategoryPayload, MemoryEntryPayload
from repositories import character_admin_memory_repository as admin_repo
from repositories import character_repository as char_repo

from ._helpers import _assert_memory_category_owned, _insert_admin_audit

# 认证依赖由父路由 _router.py 统一提供
router = APIRouter(tags=["admin"])


def _require_character(conn: ConnType, character_id: str) -> None:
    if not char_repo.check_character_exists(conn, character_id):
        raise NotFoundError(detail="角色不存在")


@router.get("/admin/character/{character_id}/memories")
def list_memories(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, object]]:
    _require_character(conn, character_id)
    rows = admin_repo.admin_list_memories(conn, character_id)
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
            "selective": bool(row["selective"]),
            "constant": bool(row["constant"]),
            "sticky": row["sticky"],
            "cooldown": row["cooldown"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


@router.post("/admin/character/{character_id}/memories")
def create_memory(
    character_id: str,
    body: MemoryEntryPayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, object]:
    _require_character(conn, character_id)
    _assert_memory_category_owned(conn, character_id, body.category_id)

    new_id = admin_repo.admin_create_memory(
        conn,
        character_id,
        keywords=body.keywords,
        trigger_logic=body.trigger_logic,
        content=body.content,
        category_id=body.category_id,
        position=body.position,
        priority=body.priority,
        is_active=body.is_active,
        comment=body.comment,
        selective=body.selective,
        constant=body.constant,
        sticky=body.sticky,
        cooldown=body.cooldown,
    )
    _insert_admin_audit(
        conn,
        current_user,
        action="create_memory",
        target_type="memory",
        target_id=str(new_id),
        detail={"character_id": character_id, "keywords": body.keywords},
    )
    conn.commit()
    return {"id": new_id, "ok": True}


@router.put("/admin/character/{character_id}/memories/{memory_id}")
def update_memory(
    character_id: str,
    memory_id: str,
    body: MemoryEntryPayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, object]:
    if not admin_repo.admin_get_memory(conn, memory_id, character_id):
        raise NotFoundError(detail="记忆条目不存在")
    _assert_memory_category_owned(conn, character_id, body.category_id)

    admin_repo.admin_update_memory(
        conn,
        memory_id,
        keywords=body.keywords,
        trigger_logic=body.trigger_logic,
        content=body.content,
        category_id=body.category_id,
        position=body.position,
        priority=body.priority,
        is_active=body.is_active,
        comment=body.comment,
        selective=body.selective,
        constant=body.constant,
        sticky=body.sticky,
        cooldown=body.cooldown,
    )
    _insert_admin_audit(
        conn,
        current_user,
        action="update_memory",
        target_type="memory",
        target_id=str(memory_id),
        detail={"character_id": character_id, "keywords": body.keywords},
    )
    conn.commit()
    return {"ok": True}


@router.delete("/admin/character/{character_id}/memories/{memory_id}")
def delete_memory(
    character_id: str,
    memory_id: str,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, object]:
    if not admin_repo.admin_get_memory(conn, memory_id, character_id):
        raise NotFoundError(detail="记忆条目不存在")

    admin_repo.admin_delete_memory(conn, memory_id)
    _insert_admin_audit(
        conn,
        current_user,
        action="delete_memory",
        target_type="memory",
        target_id=str(memory_id),
        detail={"character_id": character_id},
    )
    conn.commit()
    return {"ok": True}


@router.get("/admin/character/{character_id}/memory-categories")
def list_memory_categories(character_id: str, conn: ConnType = Depends(get_db_dep)) -> list[dict[str, object]]:
    _require_character(conn, character_id)
    rows = admin_repo.admin_list_memory_categories(conn, character_id)
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


@router.post("/admin/character/{character_id}/memory-categories")
def create_memory_category(
    character_id: str,
    body: MemoryCategoryPayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, object]:
    _require_character(conn, character_id)

    new_id = admin_repo.admin_create_memory_category(
        conn,
        character_id,
        name=body.name,
        description=body.description,
        color=body.color,
        sort_order=body.sort_order,
    )
    _insert_admin_audit(
        conn,
        current_user,
        action="create_memory_category",
        target_type="memory_category",
        target_id=str(new_id),
        detail={"character_id": character_id, "name": body.name},
    )
    conn.commit()
    return {"ok": True, "id": new_id}


@router.put("/admin/character/{character_id}/memory-categories/{category_id}")
def update_memory_category(
    character_id: str,
    category_id: str,
    body: MemoryCategoryPayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, object]:
    if not admin_repo.admin_get_memory_category(conn, category_id, character_id):
        raise NotFoundError(detail="记忆分类不存在")

    admin_repo.admin_update_memory_category(
        conn,
        category_id,
        name=body.name,
        description=body.description,
        color=body.color,
        sort_order=body.sort_order,
    )
    _insert_admin_audit(
        conn,
        current_user,
        action="update_memory_category",
        target_type="memory_category",
        target_id=str(category_id),
        detail={"character_id": character_id, "name": body.name},
    )
    conn.commit()
    return {"ok": True}


@router.delete("/admin/character/{character_id}/memory-categories/{category_id}")
def delete_memory_category(
    character_id: str,
    category_id: str,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, object]:
    if not admin_repo.admin_get_memory_category(conn, category_id, character_id):
        raise NotFoundError(detail="记忆分类不存在")

    mem_count = admin_repo.admin_count_memories_in_category(conn, category_id)
    if mem_count > 0:
        raise BadRequestError(
            detail=f"该分类下还有 {mem_count} 个记忆条目，请先移除或修改这些条目",
        )

    admin_repo.admin_delete_memory_category(conn, category_id)
    _insert_admin_audit(
        conn,
        current_user,
        action="delete_memory_category",
        target_type="memory_category",
        target_id=str(category_id),
        detail={"character_id": character_id},
    )
    conn.commit()
    return {"ok": True}


@router.get("/admin/character/{character_id}/memory-categories/{category_id}/delete-impact")
def memory_category_delete_impact(
    character_id: str,
    category_id: str,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, object]:
    category = admin_repo.admin_get_memory_category_for_impact(conn, category_id, character_id)
    if not category:
        raise NotFoundError(detail="记忆分类不存在")

    memories = admin_repo.admin_list_memories_in_category(conn, character_id, category_id)

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
