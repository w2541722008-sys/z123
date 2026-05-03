from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import get_admin_user
from core.database import ConnType, get_db_dep
from core.schemas import KeywordTestPayload
from services.prompt_assembler import build_message_preview
from utils.json_utils import parse_json_object

from .characters_common import _split_csv_ids

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])


def _affection_rules_use_default(raw: Any) -> bool:
    """判断好感度规则是否使用默认值（空规则）。

    兼容 JSONB（psycopg2 返回 dict）和旧 text 格式。
    """
    # JSONB 列：psycopg2 直接返回 dict
    if isinstance(raw, dict):
        return len(raw) == 0
    text = str(raw or "").strip()
    if not text:
        return True
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and len(parsed) == 0


def _basic_config_warnings(character: dict[str, Any], runtime_layers: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not (character.get("name") or "").strip():
        warnings.append("角色名为空")
    if not (character.get("system_prompt") or "").strip():
        warnings.append("主指令 system_prompt 为空")
    if not (character.get("opening_message") or "").strip():
        warnings.append("默认开场白为空")
    if not str(runtime_layers.get("base_profile") or "").strip():
        warnings.append("runtime_layers.base_profile 为空")
    if not str(runtime_layers.get("examples") or "").strip():
        warnings.append("示例对话 examples 为空")
    if character.get("is_visible") and not (character.get("subtitle") or "").strip():
        warnings.append("角色已设为可见，但副标题为空")
    if character.get("affection_enabled"):
        raw_rules = character.get("affection_rules_json")
        if not _affection_rules_use_default(raw_rules):
            rules = parse_json_object(raw_rules, fallback={})
            if not rules:
                warnings.append("已启用好感度系统，但好感度规则 JSON 无法解析，请检查格式")
    return warnings


@router.get("/admin/character/{character_id}/config-summary")
def admin_character_config_summary(character_id: str, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, name, subtitle, opening_message, system_prompt, is_visible,
               card_type,
               affection_enabled, affection_rules_json, structured_asset_json
        FROM characters
        WHERE id = %s
        """,
        (character_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")

    structured = parse_json_object(row["structured_asset_json"], fallback={})
    runtime_layers = structured.get("runtime_layers", {}) or {}

    counts = {
        "memory_count": conn.execute("SELECT COUNT(*) FROM character_memories WHERE character_id = %s", (character_id,)).fetchone()["count"],
        "memory_category_count": conn.execute("SELECT COUNT(*) FROM memory_categories WHERE character_id = %s", (character_id,)).fetchone()["count"],
        "greeting_count": conn.execute("SELECT COUNT(*) FROM character_greetings WHERE character_id = %s", (character_id,)).fetchone()["count"],
        "storyline_count": conn.execute("SELECT COUNT(*) FROM character_storylines WHERE character_id = %s", (character_id,)).fetchone()["count"],
        "post_rule_count": conn.execute("SELECT COUNT(*) FROM character_post_rules WHERE character_id = %s", (character_id,)).fetchone()["count"],
        "story_event_count": conn.execute("SELECT COUNT(*) FROM story_events WHERE character_id = %s", (character_id,)).fetchone()["count"],
    }
    active_counts = {
        "memory_count": conn.execute("SELECT COUNT(*) FROM character_memories WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
        "greeting_count": conn.execute("SELECT COUNT(*) FROM character_greetings WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
        "storyline_count": conn.execute("SELECT COUNT(*) FROM character_storylines WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
        "post_rule_count": conn.execute("SELECT COUNT(*) FROM character_post_rules WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
        "story_event_count": conn.execute("SELECT COUNT(*) FROM story_events WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
    }
    greeting_phase_coverage = len(conn.execute(
        "SELECT DISTINCT story_phase FROM character_greetings WHERE character_id = %s AND is_active = 1",
        (character_id,),
    ).fetchall())

    default_storyline_id_row = conn.execute(
        "SELECT id FROM character_storylines WHERE character_id = %s AND is_default = 1 ORDER BY id ASC LIMIT 1",
        (character_id,),
    ).fetchone()
    active_greetings = conn.execute(
        "SELECT COUNT(*) FROM character_greetings WHERE character_id = %s AND is_active = 1",
        (character_id,),
    ).fetchone()["count"]

    warnings = _basic_config_warnings(dict(row), runtime_layers)
    if counts["memory_count"] > 0 and active_counts["memory_count"] == 0:
        warnings.append("存在记忆条目，但全部处于禁用状态")
    elif 0 < active_counts["memory_count"] < 3:
        warnings.append("启用中的记忆条目较少，建议至少准备 3 条高频记忆")
    if counts["storyline_count"] > 0 and not default_storyline_id_row:
        warnings.append("存在剧情线，但未设置默认剧情线")
    if counts["greeting_count"] > 0 and active_greetings == 0:
        warnings.append("存在开场白，但全部处于禁用状态")
    elif counts["greeting_count"] > 0 and greeting_phase_coverage < 2:
        warnings.append("开场白阶段覆盖偏少，建议至少覆盖 2 个关系阶段")
    if counts["post_rule_count"] > 0 and active_counts["post_rule_count"] == 0:
        warnings.append("存在后置规则，但全部处于禁用状态")
    if row["card_type"] in {"intimate", "scenario"} and counts["greeting_count"] == 0:
        warnings.append("当前角色还没有多阶段开场白，首次体验会偏单一")

    empty_unlock_event_count = 0
    empty_event_content_count = 0
    if counts["story_event_count"] > 0:
        events = conn.execute(
            "SELECT id, unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id, event_content FROM story_events WHERE character_id = %s",
            (character_id,),
        ).fetchall()
        valid_memory_ids = {r["id"] for r in conn.execute("SELECT id FROM character_memories WHERE character_id = %s", (character_id,)).fetchall()}
        valid_greeting_ids = {r["id"] for r in conn.execute("SELECT id FROM character_greetings WHERE character_id = %s", (character_id,)).fetchall()}
        valid_storyline_ids = {r["id"] for r in conn.execute("SELECT id FROM character_storylines WHERE character_id = %s", (character_id,)).fetchall()}
        for event in events:
            bad_m = [x for x in _split_csv_ids(event["unlocked_memory_ids"]) if x not in valid_memory_ids]
            bad_g = [x for x in _split_csv_ids(event["unlocked_greeting_ids"]) if x not in valid_greeting_ids]
            bad_s = event["unlocked_storyline_id"] and event["unlocked_storyline_id"] not in valid_storyline_ids
            has_unlocks = bool(_split_csv_ids(event["unlocked_memory_ids"]) or _split_csv_ids(event["unlocked_greeting_ids"]) or event["unlocked_storyline_id"])
            has_event_content = bool((event["event_content"] or "").strip())
            if not has_unlocks:
                empty_unlock_event_count += 1
            if not has_event_content:
                empty_event_content_count += 1
            if bad_m or bad_g or bad_s:
                warnings.append(f"剧情事件 #{event['id']} 存在失效的解锁对象引用")
                break
    if empty_unlock_event_count:
        warnings.append(f"有 {empty_unlock_event_count} 个剧情事件还没有配置任何解锁内容。")
    if empty_event_content_count:
        warnings.append(f"有 {empty_event_content_count} 个剧情事件没有触发文案，剧情衔接可能偏生硬")

    checks = [
        bool((row["name"] or "").strip()),
        bool((row["system_prompt"] or "").strip()),
        bool((row["opening_message"] or "").strip()),
        bool(str(runtime_layers.get("base_profile") or "").strip()),
        bool(str(runtime_layers.get("examples") or "").strip()),
        active_counts["memory_count"] > 0,
        active_counts["greeting_count"] > 0,
        (row["card_type"] == "world") or greeting_phase_coverage >= 2,
        (not row["affection_enabled"]) or _affection_rules_use_default(row["affection_rules_json"]) or bool(parse_json_object(row["affection_rules_json"], fallback={})),
        counts["storyline_count"] == 0 or bool(default_storyline_id_row),
        counts["story_event_count"] == 0 or empty_unlock_event_count == 0,
    ]
    completion_score = round(sum(1 for x in checks if x) / len(checks) * 100)

    last_updated_candidates = []
    for table in ["character_memories", "memory_categories", "character_greetings", "character_storylines", "character_post_rules", "story_events"]:
        r = conn.execute(f"SELECT MAX(updated_at) as max FROM {table} WHERE character_id = %s", (character_id,)).fetchone()
        if r and r["max"]:
            last_updated_candidates.append(str(r["max"]))

    return {
        "character_id": row["id"],
        "name": row["name"],
        "subtitle": row["subtitle"] or "",
        "runtime_layer_count": len(runtime_layers),
        "default_storyline_id": default_storyline_id_row["id"] if default_storyline_id_row else None,
        "last_updated": max(last_updated_candidates) if last_updated_candidates else "",
        "completeness": completion_score,
        "warnings": warnings,
        "stats": {
            "memories": counts["memory_count"],
            "active_memories": active_counts["memory_count"],
            "categories": counts["memory_category_count"],
            "greetings": counts["greeting_count"],
            "active_greetings": active_counts["greeting_count"],
            "greeting_phase_coverage": greeting_phase_coverage,
            "storylines": counts["storyline_count"],
            "active_storylines": active_counts["storyline_count"],
            "post_rules": counts["post_rule_count"],
            "active_post_rules": active_counts["post_rule_count"],
            "events": counts["story_event_count"],
            "active_events": active_counts["story_event_count"],
            "empty_unlock_events": empty_unlock_event_count,
            "empty_event_content_events": empty_event_content_count,
        },
    }


@router.get("/admin/character/{character_id}/message-preview")
def admin_message_preview(
    character_id: str,
    affection: int = Query(30, description="好感度 (0-100)"),
    story_phase: str = Query("stranger", description="关系阶段 (stranger/acquaintance/friend/lover)"),
    mood: str = Query("neutral", description="心情 (neutral/happy/sad/angry/flirty)"),
    storyline_id: int | None = Query(None, description="当前剧情线ID"),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    char_row = conn.execute("SELECT * FROM characters WHERE id = %s", (character_id,)).fetchone()
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
    char = conn.execute(
        "SELECT id FROM characters WHERE id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(status_code=404, detail="角色不存在")

    rows = conn.execute(
        """
        SELECT id, keywords, trigger_logic, content
        FROM character_memories
        WHERE character_id = %s AND is_active = 1
        ORDER BY priority ASC
        """,
        (character_id,),
    ).fetchall()

    results = []
    text_lower = body.text.lower()

    for row in rows:
        keywords = [k.strip().lower() for k in row["keywords"].split(",") if k.strip()]
        if not keywords:
            continue

        trigger_logic = row["trigger_logic"] or "any"
        matched = []

        if trigger_logic == "all":
            if all(kw in text_lower for kw in keywords):
                matched = keywords
        else:
            matched = [kw for kw in keywords if kw in text_lower]

        if matched:
            results.append({
                "id": row["id"],
                "keywords": row["keywords"],
                "content": row["content"],
                "matched_keywords": matched,
                "trigger_logic": trigger_logic,
            })

    return results
