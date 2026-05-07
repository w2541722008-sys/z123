"""
运行时 Bundle 构建 - 把主角色与关联资产合成为一份统一运行时视图

从 prompt_assembler.py 拆分而来，职责：
  - 解析角色卡的运行时层（runtime_cache_json 或字段兜底）
  - 合并主资产与关联资产为统一 bundle
  - 宏展开（{{char}} / {{user}}）
  - 交替开场白合并
"""
from __future__ import annotations

from typing import Any, Optional

from utils.card_text import expand_macros, pick_section_text, split_structured_sections
from utils.json_utils import parse_json_object


# 从 description 中提取 personality 的关键词列表
_PERSONALITY_KEYWORDS = [
    "性格", "personality", "个性", "特质", "特征", "traits",
    "性格特点", "temperament", "品格", "性情",
]


def _get_field(source: Any, key: str, default: Any = "") -> Any:
    """兼容 dict / psycopg2 RealDictRow / 普通对象 三种读取方式。"""
    try:
        value = source[key]
    except Exception:
        value = getattr(source, key, default)
    return default if value is None else value


def get_runtime_layers(character: Any) -> dict[str, Any]:
    """优先读取导卡时缓存好的 runtime layers，没有再走字段兜底。"""
    runtime_layers = parse_json_object(_get_field(character, "runtime_cache_json", ""), fallback={})
    if runtime_layers:
        return runtime_layers
    return {
        "asset_type": _get_field(character, "asset_type", "character"),
        "primary_system_prompt": _get_field(character, "system_prompt", ""),
        "base_profile": _get_field(character, "description", ""),
        "personality": "",
        "scenario": "",
        "world_rules": "",
        "examples": "",
        "post_history_rules": "",
        "alternate_greetings": [],
        "opening_message": _get_field(character, "opening_message", ""),
        "first_message": _get_field(character, "opening_message", ""),
        "extension_hints": {},
    }


def _merge_text(*parts: Any) -> str:
    """合并多段文本，去重并保留顺序。"""
    seen: set[str] = set()
    merged: list[str] = []
    for raw in parts:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return "\n\n".join(merged).strip()


def _merge_alternate_greetings(*groups: Any) -> list[str]:
    """合并多组备选开场白，去重并限制最多 6 条。"""
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged[:6]


def build_runtime_bundle(character: Any, related_assets: list[Any] | None = None) -> dict[str, Any]:
    """把主角色与关联资产合成为一份统一运行时视图。

    当前策略：
    - 主资产决定主模式（character / hybrid / scenario）
    - scenario 资产补充剧情场景、示例和推进约束
    - 额外 character/hybrid 资产只作为补充资料，不反客为主
    """
    related_assets = related_assets or []
    primary_layers = get_runtime_layers(character)
    bundle = {
        "asset_type": primary_layers.get("asset_type") or _get_field(character, "asset_type", "hybrid"),
        "primary_system_prompt": primary_layers.get("primary_system_prompt") or _get_field(character, "system_prompt", ""),
        "base_profile": primary_layers.get("base_profile") or _get_field(character, "description", ""),
        "personality": primary_layers.get("personality") or "",
        "scenario": primary_layers.get("scenario") or "",
        "world_rules": primary_layers.get("world_rules") or "",
        "examples": primary_layers.get("examples") or "",
        "post_history_rules": primary_layers.get("post_history_rules") or "",
        "alternate_greetings": list(primary_layers.get("alternate_greetings") or []),
        "opening_message": primary_layers.get("opening_message") or _get_field(character, "opening_message", ""),
        "first_message": primary_layers.get("first_message") or _get_field(character, "opening_message", ""),
        "extension_hints": dict(primary_layers.get("extension_hints") or {}),
        # depth_prompt 从 extension_hints 里单独提出，方便后续 builder 快速访问
        # 格式：{prompt: str, depth: int, role: str} 或 None
        "depth_prompt": (primary_layers.get("extension_hints") or {}).get("depth_prompt"),
        # ── World Info 层（来自 character_book）────────────────────────────
        "world_info_before": primary_layers.get("world_info_before") or "",
        "world_info_after": primary_layers.get("world_info_after") or "",
        "conditional_entries": list(primary_layers.get("conditional_entries") or []),
        "related_assets": [],
    }

    for asset in related_assets:
        asset_layers = get_runtime_layers(asset)
        asset_type = asset_layers.get("asset_type") or _get_field(asset, "asset_type", "hybrid")
        asset_name = _get_field(asset, "name", "未命名资产")
        bundle["related_assets"].append(
            {
                "id": _get_field(asset, "id", ""),
                "name": asset_name,
                "asset_type": asset_type,
            }
        )

        if asset_type == "scenario":
            bundle["scenario"] = _merge_text(bundle["scenario"], asset_layers.get("base_profile"), asset_layers.get("scenario"))
            bundle["examples"] = _merge_text(bundle["examples"], asset_layers.get("examples"))
            bundle["post_history_rules"] = _merge_text(bundle["post_history_rules"], asset_layers.get("post_history_rules"))
            bundle["alternate_greetings"] = _merge_alternate_greetings(bundle["alternate_greetings"], asset_layers.get("alternate_greetings"))
            continue

        bundle["base_profile"] = _merge_text(bundle["base_profile"], asset_layers.get("base_profile"))
        bundle["personality"] = _merge_text(bundle["personality"], asset_layers.get("personality"))
        bundle["scenario"] = _merge_text(bundle["scenario"], asset_layers.get("scenario"))
        bundle["world_rules"] = _merge_text(bundle["world_rules"], asset_layers.get("world_rules"))
        bundle["examples"] = _merge_text(bundle["examples"], asset_layers.get("examples"))
        bundle["post_history_rules"] = _merge_text(bundle["post_history_rules"], asset_layers.get("post_history_rules"))
        bundle["alternate_greetings"] = _merge_alternate_greetings(bundle["alternate_greetings"], asset_layers.get("alternate_greetings"))

    # P1: 当 personality 仍为空时，尝试从 base_profile (description) 中提取性格相关段落
    # 大量 SillyTavern 卡把性格写在 description 中而非独立 personality 字段
    if not bundle["personality"].strip() and bundle["base_profile"].strip():
        sections = split_structured_sections(bundle["base_profile"])
        extracted = pick_section_text(sections, _PERSONALITY_KEYWORDS)
        if extracted:
            bundle["personality"] = extracted

    return bundle


def expand_bundle_macros(bundle: dict[str, Any], char_name: str, user_name: str) -> dict[str, Any]:
    """对 runtime bundle 里所有文本字段做 {{char}} / {{user}} 宏展开。

    SillyTavern 角色卡大量使用 {{char}} 指代角色名、{{user}} 指代用户名。
    若不替换，这些字面占位符会直接出现在 prompt 里，导致模型输出异常。

    注意：只处理文本字段，不处理 related_assets / alternate_greetings 列表（后者在 builder 里单独处理）。
    """
    text_fields = [
        "primary_system_prompt", "base_profile", "personality",
        "scenario", "world_rules", "examples", "post_history_rules",
        "world_info_before", "world_info_after",
    ]
    expanded = dict(bundle)
    for field in text_fields:
        value = expanded.get(field) or ""
        if value:
            expanded[field] = expand_macros(value, char_name=char_name, user_name=user_name)
    # alternate_greetings 是 list[str]，也要展开
    alt = expanded.get("alternate_greetings") or []
    if alt:
        expanded["alternate_greetings"] = [expand_macros(item, char_name=char_name, user_name=user_name) for item in alt]
    return expanded
