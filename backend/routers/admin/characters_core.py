from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import CurrentUser, get_current_user
from database import get_conn
from models import AdminUpdatePayload
from services.cache_service import cache_delete, invalidate_character
from utils.json_utils import parse_json_list, parse_json_object

from ._shared import _ADMIN_EDITABLE_FIELDS, _transaction, _write_audit_log

router = APIRouter(tags=["admin"])


@router.get("/admin/characters")
def admin_list_characters() -> list[dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, name, abbr, subtitle, avatar_url, description, tags,
                   card_type, required_plan, is_visible, home_priority, sort_order
            FROM characters
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "abbr": row["abbr"],
                "subtitle": row["subtitle"] or "",
                "avatar_url": row["avatar_url"] or "",
                "description": (row["description"] or "")[:100] + "..." if row["description"] else "",
                "tags": parse_json_list(row["tags"]),
                "card_type": row["card_type"] or "intimate",
                "required_plan": row["required_plan"] or "guest",
                "is_visible": bool(row["is_visible"]),
                "home_priority": row["home_priority"],
                "sort_order": row["sort_order"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/characters")
def admin_create_character(
    body: dict[str, Any],
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    char_id = body.get("id", "").strip()
    name = body.get("name", "").strip()
    system_prompt = body.get("system_prompt", "").strip()

    if not char_id:
        raise HTTPException(status_code=400, detail="角色ID不能为空")
    if not name:
        raise HTTPException(status_code=400, detail="角色名不能为空")
    if not system_prompt:
        raise HTTPException(status_code=400, detail="主指令（System Prompt）不能为空")

    if not char_id.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="角色ID只能包含英文、数字和下划线")

    conn = get_conn()
    try:
        def _do_create():
            existing = conn.execute(
                "SELECT id FROM characters WHERE id = %s",
                (char_id,)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail=f"角色ID '{char_id}' 已存在")

            abbr = body.get("abbr", name).strip() or name
            subtitle = body.get("subtitle", "").strip()
            description = body.get("description", "").strip()
            opening_message = body.get("opening_message", "").strip()
            tags = body.get("tags", "[]")
            card_type = body.get("card_type", "intimate")
            required_plan = body.get("required_plan", "guest")
            avatar_url = body.get("avatar_url", "").strip()
            cover_url = body.get("cover_url", "").strip()
            home_priority = int(body.get("home_priority", 10))
            is_visible = 1 if body.get("is_visible", True) else 0

            try:
                tags_list = json.loads(tags) if tags else []
                if not isinstance(tags_list, list):
                    raise HTTPException(status_code=400, detail="tags必须是JSON数组格式")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="tags格式错误，必须是有效的JSON")

            valid_card_types = ["intimate", "friend", "mentor", "entertainment"]
            valid_plans = ["guest", "free", "vip", "svip"]
            if card_type not in valid_card_types:
                raise HTTPException(status_code=400, detail=f"card_type必须是以下之一: {', '.join(valid_card_types)}")
            if required_plan not in valid_plans:
                raise HTTPException(status_code=400, detail=f"required_plan必须是以下之一: {', '.join(valid_plans)}")

            if not (0 <= home_priority <= 9999):
                raise HTTPException(status_code=400, detail="home_priority必须在0-9999之间")

            conn.execute(
                """
                INSERT INTO characters (
                    id, name, abbr, subtitle, avatar_url, cover_url, description,
                    system_prompt, opening_message, tags,
                    card_type, required_plan, home_priority, is_visible, sort_order,
                    mock_reply_style, asset_type, source_kind, source_path,
                    embedded_format, raw_card_json, structured_asset_json,
                    import_diagnostics, import_locked, affection_enabled, affection_rules_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    char_id, name, abbr, subtitle, avatar_url, cover_url, description,
                    system_prompt, opening_message, tags,
                    card_type, required_plan, home_priority, is_visible, home_priority,
                    "温柔、体贴、会关心人", "character", "manual", "",
                    "json", "", "{}",
                    "[]", 0, 1, "{}"
                )
            )

            _write_audit_log(
                conn,
                operator_id=current_user.id,
                operator_email=current_user.email,
                action="create_character",
                target_type="character",
                target_id=char_id,
                detail={"name": name, "card_type": card_type, "required_plan": required_plan},
            )

            return {"ok": True, "id": char_id, "message": f"角色 '{name}' 创建成功"}

        result = _transaction(conn, _do_create)
        cache_delete("character_list_all")
        return result
    finally:
        conn.close()


@router.get("/admin/character/{character_id}")
def admin_get_character(character_id: str) -> dict[str, Any]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        runtime_layers = parse_json_object(row.get("runtime_cache_json"), fallback={})
        if not runtime_layers:
            structured = parse_json_object(row.get("structured_asset_json"), fallback={})
            runtime_layers = structured.get("runtime_layers", {})

        runtime_layers_str: dict[str, str] = {}
        for k, v in runtime_layers.items():
            if isinstance(v, list):
                runtime_layers_str[k] = "\n---\n".join(str(x) for x in v)
            else:
                runtime_layers_str[k] = str(v)

        return {
            "id": row["id"],
            "name": row["name"],
            "abbr": row["abbr"],
            "subtitle": row["subtitle"] or "",
            "avatar_url": row["avatar_url"] or "",
            "cover_url": row["cover_url"] or "",
            "description": row["description"] or "",
            "tags": parse_json_list(row["tags"]),
            "opening_message": row["opening_message"] or "",
            "system_prompt": row["system_prompt"] or "",
            "sort_order": row["sort_order"],
            "is_visible": bool(row["is_visible"]),
            "home_priority": row["home_priority"],
            "card_type": row["card_type"] or "intimate",
            "required_plan": row["required_plan"] or "guest",
            "affection_enabled": bool(row["affection_enabled"]),
            "affection_rules_json": row["affection_rules_json"] or "{}",
            "import_locked": bool(row["import_locked"]),
            "source_kind": row["source_kind"],
            "source_path": row["source_path"],
            "asset_type": row["asset_type"] or "character",
            "embedded_format": row["embedded_format"] or "json",
            "mock_reply_style": row["mock_reply_style"] or "",
            "import_diagnostics": row["import_diagnostics"] or "[]",
            "runtime_layers": runtime_layers_str,
        }
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}")
def admin_delete_character(
    character_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, name FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        conn.execute("DELETE FROM user_character_profiles WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM character_states WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM character_greetings WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM character_memories WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM memory_categories WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM character_post_rules WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM story_events WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM character_storylines WHERE character_id = %s", (character_id,))
        conn.execute("DELETE FROM characters WHERE id = %s", (character_id,))

        _write_audit_log(
            conn,
            operator_id=current_user.id,
            operator_email=current_user.email,
            action="delete_character",
            target_type="character",
            target_id=character_id,
            detail={"name": row["name"]},
        )

        conn.commit()

        invalidate_character(character_id)
        cache_delete("character_list_all")

        return {"ok": True, "id": character_id, "name": row["name"]}
    finally:
        conn.close()


@router.post("/admin/character/{character_id}")
def admin_update_character(
    character_id: str,
    body: AdminUpdatePayload,
) -> dict[str, Any]:
    safe_direct = {k: v for k, v in body.updates.items() if k in _ADMIN_EDITABLE_FIELDS}
    rl_updates = {k[4:]: v for k, v in body.updates.items() if k.startswith("rl__")}

    if not safe_direct and not rl_updates:
        raise HTTPException(status_code=400, detail="没有合法的可更新字段")

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, structured_asset_json FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        if safe_direct:
            set_clause = ", ".join(f"{k} = %s" for k in safe_direct)
            conn.execute(
                f"UPDATE characters SET {set_clause} WHERE id = %s",
                list(safe_direct.values()) + [character_id],
            )

        if rl_updates:
            try:
                sj_raw = row.get("structured_asset_json") or "{}"
                sj = json.loads(sj_raw) if sj_raw else {}

                if not sj:
                    rc_raw = row.get("runtime_cache_json") or "{}"
                    rc = json.loads(rc_raw) if rc_raw else {}
                    sj = {"runtime_layers": rc}

                rl = sj.setdefault("runtime_layers", {})
                for k, v in rl_updates.items():
                    orig = rl.get(k)
                    if isinstance(orig, list) and isinstance(v, str):
                        rl[k] = [x.strip() for x in v.split("\n---\n") if x.strip()]
                    else:
                        rl[k] = v

                new_structured_json = json.dumps(sj, ensure_ascii=False)
                new_runtime_json = json.dumps(rl, ensure_ascii=False)

                conn.execute(
                    "UPDATE characters SET structured_asset_json = %s, runtime_cache_json = %s WHERE id = %s",
                    (new_structured_json, new_runtime_json, character_id),
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"更新 runtime_layers 失败: {e}")

        conn.commit()

        invalidate_character(character_id)
        cache_delete("character_list_all")

        return {"ok": True, "updated": list(safe_direct.keys()) + [f"rl__{k}" for k in rl_updates]}
    finally:
        conn.close()
