from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from core.auth import get_admin_user
from core.database import ConnType, get_db_dep
from core.exceptions import BadRequestError, NotFoundError
from core.schemas import KeywordTestPayload
from services.character_insights_service import (
    get_character_config_summary,
    get_message_preview_data,
    test_character_keywords,
)
from repositories.character_repository import check_character_exists
from services.prompt_assembler import build_message_preview
from utils.json_utils import parse_json_object

# 认证依赖由父路由 _router.py 统一提供
router = APIRouter(tags=["admin"])


@router.get("/admin/character/{character_id}/config-summary")
def admin_character_config_summary(character_id: str, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    result = get_character_config_summary(conn, character_id)
    if not result:
        raise NotFoundError(detail="角色不存在")
    return result


@router.get("/admin/character/{character_id}/message-preview")
def admin_message_preview(
    character_id: str,
    affection: int = Query(30, description="好感度 (0-100)"),
    story_phase: str = Query("stranger", description="关系/剧情阶段 (stranger/acquaintance/friend/lover)"),
    mood: str = Query("neutral", description="心情/氛围"),
    storyline_id: int | None = Query(None, description="当前剧情线ID"),
    sample_user_message: str | None = Query(None, max_length=2000, description="模拟用户消息，用于触发世界书预览"),
    custom_vars_json: str | None = Query(None, max_length=4000, description="模拟 custom_vars JSON 对象"),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    custom_vars = parse_json_object(custom_vars_json, fallback={}) if custom_vars_json else {}
    if custom_vars_json and not custom_vars:
        stripped = custom_vars_json.strip()
        if stripped and stripped != "{}":
            raise BadRequestError(detail="custom_vars_json 必须是 JSON 对象")

    char_row = get_message_preview_data(conn, character_id)
    if not char_row:
        raise NotFoundError(detail="角色不存在")

    character_state = {
        "affection": max(0, min(100, affection)),
        "story_phase": story_phase,
        "mood": mood,
        "storyline_id": storyline_id,
        "custom_vars": custom_vars,
    }

    sample_text = (sample_user_message or "").strip()
    recent_messages = [{"role": "user", "content": sample_text}] if sample_text else []

    preview = build_message_preview(
        character=char_row,
        recent_messages=recent_messages,
        memory_summary="",
        user_name="用户",
        character_state=character_state,
        conn=conn,
    )
    structured = parse_json_object(char_row["structured_asset_json"], fallback={})
    messages = preview.get("messages", [])
    system_text = "\n\n".join(
        m.get("content", "")
        for m in messages
        if str(m.get("role", "")).lower() == "system"
    )
    preview_summary = {
        "has_sample_user_message": bool(sample_text),
        "has_world_info": "【世界信息-" in system_text,
        "has_post_rules": "【回复规则提醒】" in system_text,
        "has_state_snapshot": "【当前关系状态" in system_text or "【当前剧情状态" in system_text,
    }
    return {
        "character_id": character_id,
        "character_state": character_state,
        "message_count": preview.get("message_count", 0),
        "messages": messages,
        "runtime_layers": preview.get("runtime_layers") or structured.get("runtime_layers", {}),
        "related_assets": preview.get("related_assets", []),
        "preview_summary": preview_summary,
    }


@router.post("/admin/character/{character_id}/test-keywords")
def test_keywords(
    character_id: str,
    body: KeywordTestPayload,
    conn: ConnType = Depends(get_db_dep),
) -> list[dict[str, Any]]:
    if not check_character_exists(conn, character_id):
        raise NotFoundError(detail="角色不存在")
    return test_character_keywords(conn, character_id, body.text)
