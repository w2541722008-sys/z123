from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import get_admin_user
from core.database import ConnType, get_db_dep
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
        raise HTTPException(status_code=404, detail="角色不存在")
    return result


@router.get("/admin/character/{character_id}/message-preview")
def admin_message_preview(
    character_id: str,
    affection: int = Query(30, description="好感度 (0-100)"),
    story_phase: str = Query("stranger", description="关系阶段 (stranger/acquaintance/friend/lover)"),
    mood: str = Query("neutral", description="心情 (neutral/happy/sad/angry/flirty)"),
    storyline_id: int | None = Query(None, description="当前剧情线ID"),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    char_row = get_message_preview_data(conn, character_id)
    if not char_row:
        raise HTTPException(status_code=404, detail="角色不存在")

    character_state = {
        "affection": max(0, min(100, affection)),
        "story_phase": story_phase,
        "mood": mood,
        "storyline_id": storyline_id,
        "custom_vars": {},
    }

    preview = build_message_preview(
        character=char_row,
        recent_messages=[],
        memory_summary="",
        user_name="用户",
        character_state=character_state,
    )
    structured = parse_json_object(char_row["structured_asset_json"], fallback={})
    return {
        "character_id": character_id,
        "character_state": character_state,
        "message_count": preview.get("message_count", 0),
        "messages": preview.get("messages", []),
        "runtime_layers": preview.get("runtime_layers") or structured.get("runtime_layers", {}),
        "related_assets": preview.get("related_assets", []),
    }


@router.post("/admin/character/{character_id}/test-keywords")
def test_keywords(
    character_id: str,
    body: KeywordTestPayload,
    conn: ConnType = Depends(get_db_dep),
) -> list[dict[str, Any]]:
    if not check_character_exists(conn, character_id):
        raise HTTPException(status_code=404, detail="角色不存在")
    return test_character_keywords(conn, character_id, body.text)
