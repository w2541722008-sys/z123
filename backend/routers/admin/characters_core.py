from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user
from core.database import ConnType, get_db_dep
from core.schemas import AdminUpdatePayload
from repositories import character_repository as char_repo
from services.cache_service import cache_delete, invalidate_character, invalidate_character_affection_rules, invalidate_character_list_all
from utils.json_utils import parse_json_list, parse_json_object, to_json_string

from ._helpers import _ADMIN_EDITABLE_FIELDS, _transaction, _write_audit_log

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])


@router.get("/admin/characters")
def admin_list_characters(conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    rows = char_repo.admin_list_all_characters(conn)

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


@router.post("/admin/characters")
def admin_create_character(
    body: dict[str, Any],
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
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

    def _do_create():
        if char_repo.check_character_exists(conn, char_id):
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

        valid_card_types = ["intimate", "scenario"]
        valid_plans = ["guest", "free", "vip", "svip"]
        if card_type not in valid_card_types:
            raise HTTPException(status_code=400, detail=f"card_type必须是以下之一: {', '.join(valid_card_types)}")
        if required_plan not in valid_plans:
            raise HTTPException(status_code=400, detail=f"required_plan必须是以下之一: {', '.join(valid_plans)}")

        if not (0 <= home_priority <= 9999):
            raise HTTPException(status_code=400, detail="home_priority必须在0-9999之间")

        char_repo.insert_character(
            conn,
            (
                char_id, name, abbr, subtitle, avatar_url, cover_url, description,
                system_prompt, opening_message, tags,
                card_type, required_plan, home_priority, is_visible, home_priority,  # sort_order=home_priority
                "[]", "character", "manual", "",
                "json", None, "{}",
                "[]", 0, 0, "{}"
            ),
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
    return dict(result)  # type: ignore[arg-type]


@router.get("/admin/character/{character_id}")
def admin_get_character(character_id: str, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    row = char_repo.get_character_full(conn, character_id)

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
        "affection_rules_json": to_json_string(row["affection_rules_json"], default_on_error='{}'),
        "import_locked": bool(row["import_locked"]),
        "source_kind": row["source_kind"],
        "source_path": row["source_path"],
        "asset_type": row["asset_type"] or "character",
        "embedded_format": row["embedded_format"] or "json",
        "mock_reply_style": to_json_string(row["mock_reply_style"], default_on_error='[]'),
        "import_diagnostics": to_json_string(row["import_diagnostics"], default_on_error='[]'),
        "runtime_layers": runtime_layers_str,
        "phase_behaviors_json": to_json_string(row.get("phase_behaviors_json"), default_on_error='{}'),
    }


@router.delete("/admin/character/{character_id}")
def admin_delete_character(
    character_id: str,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    row = char_repo.delete_character_cascade(conn, character_id)
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")

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
    invalidate_character_affection_rules(character_id)
    cache_delete("character_list_all")

    return {"ok": True, "id": character_id, "name": row["name"]}


@router.post("/admin/character/{character_id}")
def admin_update_character(
    character_id: str,
    body: AdminUpdatePayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    safe_direct = {k: v for k, v in body.updates.items() if k in _ADMIN_EDITABLE_FIELDS}
    rl_updates = {k[4:]: v for k, v in body.updates.items() if k.startswith("rl__")}

    if not safe_direct and not rl_updates:
        raise HTTPException(status_code=400, detail="没有合法的可更新字段")

    row = char_repo.get_character_structured_json(conn, character_id)
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")

    if safe_direct:
        # 白名单校验：确保 f-string 拼接的列名来自 _ADMIN_EDITABLE_FIELDS 白名单
        # 注意：不使用 assert，因为 python -O 会跳过 assert 导致安全防护失效
        invalid_fields = set(safe_direct.keys()) - _ADMIN_EDITABLE_FIELDS
        if invalid_fields:
            raise HTTPException(status_code=400, detail=f"非法更新字段: {invalid_fields}")

        # 校验 affection_rules_json 格式（必须是扁平键值对，禁止嵌套格式）
        if "affection_rules_json" in safe_direct:
            rules_raw = safe_direct["affection_rules_json"]
            if rules_raw and str(rules_raw).strip():
                try:
                    rules = json.loads(str(rules_raw)) if isinstance(rules_raw, str) else rules_raw
                    if not isinstance(rules, dict):
                        raise HTTPException(status_code=400, detail="affection_rules_json 必须是 JSON 对象")
                    for k, v in rules.items():
                        if k in ("enabled", "daily_cap", "allow_regression", "show_bar", "scenario_type"):
                            continue  # 元数据键允许非 int 值
                        if isinstance(v, (list, dict)):
                            raise HTTPException(
                                status_code=400,
                                detail=f"affection_rules_json 格式错误：'{k}' 的值不能是数组或对象。"
                                       f"正确格式为扁平键值对，如 {{\"deep_conversation\": 4, \"light_chat\": 1}}，"
                                       f"不要使用嵌套的 events/milestones 格式。"
                            )
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="affection_rules_json 不是合法的 JSON")

        set_clause = ", ".join(f"{k} = %s" for k in safe_direct)
        char_repo.update_character_fields(conn, character_id, safe_direct)

    if rl_updates:
        try:
            sj = parse_json_object(row.get("structured_asset_json"), fallback={})
            if not sj:
                rc = parse_json_object(row.get("runtime_cache_json"), fallback={})
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

            char_repo.update_character_json_fields(conn, character_id, new_structured_json, new_runtime_json)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"更新 runtime_layers 失败: {e}")

    conn.commit()

    invalidate_character(character_id)
    invalidate_character_affection_rules(character_id)
    invalidate_character_list_all()

    return {"ok": True, "updated": list(safe_direct.keys()) + [f"rl__{k}" for k in rl_updates]}
