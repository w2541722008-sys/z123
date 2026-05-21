"""
角色洞察服务 — 管理后台角色配置摘要和健康检查。

职责：
- 汇总角色配置完整度评分
- 生成配置警告列表
- 关键词测试
- 消息预览数据准备
"""

from __future__ import annotations

import json
from typing import Any

from core.plan_constants import VALID_CARD_TYPES

from core.database import ConnType
from repositories.character_repository import (
    check_character_exists,
    get_active_greeting_count,
    get_asset_max_updated_at,
    get_character_asset_stats,
    get_character_config_fields,
    get_character_full,
    get_default_storyline_id,
    get_greeting_phase_coverage,
    get_story_events_for_validation,
    get_valid_asset_ids,
)
from repositories.character_memory_repository import get_active_keyword_memories
from utils.json_utils import parse_json_object


def _split_csv_ids(value: str | None) -> list[str]:
    """拆分逗号分隔的 ID 列表。"""
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _affection_rules_use_default(raw: Any) -> bool:
    """判断好感度规则是否使用默认值（空规则）。"""
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


def compute_config_warnings(character: dict[str, Any], runtime_layers: dict[str, Any]) -> list[str]:
    """计算角色基础配置警告。"""
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


def compute_advanced_warnings(
    conn: ConnType,
    character: dict[str, Any],
    stats: dict[str, Any],
    greeting_phase_coverage: int,
    default_storyline_id: int | None,
    active_greetings: int,
) -> list[str]:
    """计算角色高级配置警告（需数据库查询）。"""
    warnings: list[str] = []
    if stats["memory_count"] > 0 and stats["memory_active"] == 0:
        warnings.append("存在记忆条目，但全部处于禁用状态")
    elif 0 < stats["memory_active"] < 3:
        warnings.append("启用中的记忆条目较少，建议至少准备 3 条高频记忆")
    if stats["storyline_count"] > 0 and not default_storyline_id:
        warnings.append("存在剧情线，但未设置默认剧情线")
    if stats["greeting_count"] > 0 and active_greetings == 0:
        warnings.append("存在开场白，但全部处于禁用状态")
    elif stats["greeting_count"] > 0 and greeting_phase_coverage < 2:
        warnings.append("开场白阶段覆盖偏少，建议至少覆盖 2 个关系阶段")
    if stats["post_rule_count"] > 0 and stats["post_rule_active"] == 0:
        warnings.append("存在后置规则，但全部处于禁用状态")
    if character.get("card_type") in VALID_CARD_TYPES and stats["greeting_count"] == 0:
        warnings.append("当前角色还没有多阶段开场白，首次体验会偏单一")

    empty_unlock_event_count = 0
    empty_event_content_count = 0
    if stats["story_event_count"] > 0:
        events = get_story_events_for_validation(conn, character["id"])
        valid_ids = get_valid_asset_ids(conn, character["id"])
        for event in events:
            bad_m = [x for x in _split_csv_ids(event["unlocked_memory_ids"]) if x not in valid_ids["memories"]]
            bad_g = [x for x in _split_csv_ids(event["unlocked_greeting_ids"]) if x not in valid_ids["greetings"]]
            bad_s = event["unlocked_storyline_id"] and event["unlocked_storyline_id"] not in valid_ids["storylines"]
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
    return warnings


def compute_completeness_score(
    row: dict[str, Any],
    runtime_layers: dict[str, Any],
    stats: dict[str, Any],
    active_greetings: int,
    greeting_phase_coverage: int,
    default_storyline_id: int | None,
    empty_unlock_event_count: int,
) -> int:
    """计算配置完整度百分比分数。"""
    checks = [
        bool((row["name"] or "").strip()),
        bool((row["system_prompt"] or "").strip()),
        bool((row["opening_message"] or "").strip()),
        bool(str(runtime_layers.get("base_profile") or "").strip()),
        bool(str(runtime_layers.get("examples") or "").strip()),
        stats["memory_active"] > 0,
        active_greetings > 0,
        greeting_phase_coverage >= 2,
        (not row["affection_enabled"]) or _affection_rules_use_default(row["affection_rules_json"]) or bool(parse_json_object(row["affection_rules_json"], fallback={})),
        stats["storyline_count"] == 0 or bool(default_storyline_id),
        stats["story_event_count"] == 0 or empty_unlock_event_count == 0,
    ]
    return round(sum(1 for x in checks if x) / len(checks) * 100)


def get_character_config_summary(conn: ConnType, character_id: str) -> dict[str, Any]:
    """获取角色配置摘要（完整度评分 + 警告列表 + 统计信息）。"""
    row = get_character_config_fields(conn, character_id)
    if not row:
        return None

    structured = parse_json_object(row["structured_asset_json"], fallback={})
    runtime_layers = structured.get("runtime_layers", {}) or {}

    stats = get_character_asset_stats(conn, character_id)
    greeting_phase_coverage = get_greeting_phase_coverage(conn, character_id)
    default_storyline_id = get_default_storyline_id(conn, character_id)
    active_greetings = get_active_greeting_count(conn, character_id)

    warnings = compute_config_warnings(dict(row), runtime_layers)
    warnings += compute_advanced_warnings(
        conn, dict(row), stats, greeting_phase_coverage, default_storyline_id, active_greetings,
    )

    empty_unlock_count = sum(
        1 for w in warnings if "还没有配置任何解锁内容" in w
    )
    completion_score = compute_completeness_score(
        dict(row), runtime_layers, stats, active_greetings,
        greeting_phase_coverage, default_storyline_id, empty_unlock_count,
    )

    last_updated = get_asset_max_updated_at(conn, character_id)

    return {
        "character_id": row["id"],
        "name": row["name"],
        "subtitle": row["subtitle"] or "",
        "runtime_layer_count": len(runtime_layers),
        "default_storyline_id": default_storyline_id,
        "last_updated": last_updated or "",
        "completeness": completion_score,
        "warnings": warnings,
        "stats": {
            "memories": stats["memory_count"],
            "active_memories": stats["memory_active"],
            "categories": stats.get("category_count", 0),
            "greetings": stats["greeting_count"],
            "active_greetings": active_greetings,
            "greeting_phase_coverage": greeting_phase_coverage,
            "storylines": stats["storyline_count"],
            "active_storylines": stats["storyline_active"],
            "post_rules": stats["post_rule_count"],
            "active_post_rules": stats["post_rule_active"],
            "events": stats["story_event_count"],
            "active_events": stats["story_event_active"],
        },
    }


def get_message_preview_data(conn: ConnType, character_id: str) -> dict[str, Any]:
    """获取消息预览所需的角色数据。"""
    return get_character_full(conn, character_id)


def test_character_keywords(conn: ConnType, character_id: str, text: str) -> list[dict[str, Any]]:
    """测试输入文本与角色关键词记忆的匹配。"""
    rows = get_active_keyword_memories(conn, character_id)

    results = []
    text_lower = text.lower()

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
