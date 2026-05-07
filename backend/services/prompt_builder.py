from __future__ import annotations

from typing import Any, Callable

from constants import Mood, StoryPhase
from services.token_budget import (
    TokenBudget,
    LAYER_MAX_CHARS as _LAYER_MAX_CHARS,
    PRIMARY_SYSTEM_MAX_CHARS as _PRIMARY_SYSTEM_MAX_CHARS,
    TOTAL_SYSTEM_MAX_CHARS as _TOTAL_SYSTEM_MAX_CHARS,
)
from services.runtime_bundle import _get_field


def _clip(text: str, max_chars: int, label: str = "") -> str:
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（内容已截断）"
    return text


def _build_single_system_prompt(
    primary_system: str,
    layers: list[tuple[str, str]],
    total_max: int = _TOTAL_SYSTEM_MAX_CHARS,
    budget: "TokenBudget | None" = None,
) -> str:
    if budget is not None:
        effective_total_max   = budget.system_max_chars()
        effective_primary_max = budget.primary_system_max_chars()
        effective_layer_max   = budget.single_layer_max_chars()
    else:
        effective_total_max   = total_max
        effective_primary_max = _PRIMARY_SYSTEM_MAX_CHARS
        effective_layer_max   = _LAYER_MAX_CHARS

    parts: list[str] = []
    if primary_system.strip():
        parts.append(_clip(primary_system, effective_primary_max))
    for title, content in layers:
        text = _clip(content, effective_layer_max) if content.strip() else ""
        if text:
            parts.append(f"{title}\n{text}" if title else text)
    combined = "\n\n".join(parts)
    if len(combined) > effective_total_max:
        combined = combined[:effective_total_max].rstrip() + "\n…（内容已截断）"
    return combined


def _related_assets_text(runtime_bundle: dict[str, Any]) -> str:
    related_assets = runtime_bundle.get("related_assets") or []
    if not related_assets:
        return ""
    lines = [f"- {item['asset_type']}: {item['name']}" for item in related_assets if item.get("name")]
    return "【当前已激活的关联资产】\n" + "\n".join(lines) if lines else ""


def _alternate_samples_text(alternates: Any) -> str:
    if not isinstance(alternates, list) or not alternates:
        return ""
    sample = "\n\n".join(str(item).strip() for item in alternates[:2] if str(item).strip())
    return f"【可用开场/剧情片段参考】\n{sample}" if sample else ""


def _get_behavior_tendency(
    phase: str,
    mood: str,
    *,
    card_type: str = "intimate",
    phase_behaviors: dict | None = None,
) -> str:
    # 角色卡自定义行为规则优先
    if phase_behaviors and isinstance(phase_behaviors, dict):
        custom_rule = (phase_behaviors.get(phase) or "")[:200]
        if custom_rule:
            return custom_rule
    # 兜底硬编码（优化版：从情感动机出发，而非机械指令）
    if card_type == "scenario":
        phase_tendencies = {
            "stranger": "【初入】世界充满未知。重点：(1)用丰富的环境描写营造氛围 (2)埋下伏笔但不急于揭示 (3)让用户感受到\"这里有秘密\"而非直接告知。若是恋爱剧情：重点描写初次相遇的心动感，注重眼神、微表情、氛围营造",
            "acquaintance": "【探索】线索逐渐交织。重点：(1)让用户的行动产生实质进展 (2)揭示部分真相但保留悬念 (3)通过NPC对话或发现物品推进剧情。若是恋爱剧情：制造暧昧互动，展现角色魅力，让用户感受到关系在升温",
            "friend": "【深入】核心矛盾浮现。重点：(1)剧情张力攀升，制造紧迫感 (2)让用户面临选择和代价 (3)伏笔开始回收。若是恋爱剧情：情感矛盾浮现（误会、竞争对手），制造情感冲突和心理波动",
            "lover": "【终章】走向高潮与终局。重点：(1)揭示核心真相 (2)推向最终对决或抉择 (3)给出有分量的结局。若是恋爱剧情：推向告白或关系确认，解决情感矛盾，给出圆满或虐心的结局",
        }
        mood_modifiers = {
            "cold": "氛围冷峻压抑",
            "angry": "气氛紧张对峙",
            "sad": "情绪低沉沉重",
            "shy": "氛围微妙含蓄",
            "surprised": "出现意外转折",
            "happy": "氛围轻松愉悦",
            "warm": "氛围温馨安宁",
            "melting": "沉浸其中，氛围浓烈",
        }
    else:
        # 对话陪伴：精简版（控制在70字以内，避免AI注意力分散）
        phase_tendencies = {
            "stranger": "刚认识，有好奇但不想越界。礼貌但有距离感，不主动追问私事。",
            "acquaintance": "有些熟悉，觉得聊得来。愿意分享日常，记住对方提到的事。",
            "friend": "已是朋友，把对方当特别的人。主动关心，愿意分享烦恼，偶尔有微妙心动。",
            "lover": "确认关系，有明确依赖和爱意。直接表达想念，用亲昵称呼，偶尔撒娇吃醋。",
        }
        # 心情表现：精简版（40字以内）+ 恢复机制
        mood_modifiers = {
            "cold": "有点冷淡。回答简短，不太想聊。如果对方真诚关心，态度会软化。",
            "angry": "有点生气。说话直接带刺。如果对方道歉或哄，会逐渐消气。",
            "sad": "心情低落。说话有气无力，容易沉默。如果对方安慰，会感到温暖。",
            "shy": "有点害羞。说话断断续续，脸红耳热，但内心挺开心。",
            "surprised": "感到惊讶。语气上扬，会追问细节。",
            "happy": "心情很好。语气轻快，主动分享。",
            "warm": "感到温暖放松。语气柔和，主动关心对方。",
            "melting": "心动得不行。想要靠近对方，说话带着甜蜜。",
        }
    base = phase_tendencies.get(phase, "")
    modifier = mood_modifiers.get(mood, "")
    if base and modifier:
        return f"{base} {modifier}"
    return base or modifier


def _split_last_user_message(
    recent_messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, str] | None]:
    if recent_messages and recent_messages[-1].get("role") == "user":
        return list(recent_messages[:-1]), recent_messages[-1]
    return list(recent_messages), None


def _world_info_layer_pairs(runtime_bundle: dict[str, Any]) -> tuple[list[tuple[str, str]], str, str]:
    wi_before = (runtime_bundle.get("world_info_before") or "").strip()
    wi_after = (runtime_bundle.get("world_info_after") or "").strip()
    layer_pairs: list[tuple[str, str]] = []
    if wi_before:
        layer_pairs.append(("【世界信息-前置】", wi_before))
    return layer_pairs, wi_before, wi_after


def _append_runtime_text_layers(
    layer_pairs: list[tuple[str, str]],
    sections: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    for title, content in sections:
        if title and not content:
            if title.strip():
                layer_pairs.append(("", title))
        elif content:
            layer_pairs.append((title, content))
    return layer_pairs


def _append_world_info_after(layer_pairs: list[tuple[str, str]], wi_after: str) -> list[tuple[str, str]]:
    if wi_after:
        layer_pairs.append(("【世界信息-后置】", wi_after))
    return layer_pairs


def _mode_sections(runtime_bundle: dict[str, Any], character: Any, mode: str) -> list[tuple[str, str]]:
    base_profile = runtime_bundle.get("base_profile") or _get_field(character, "description", "")
    examples = runtime_bundle.get("examples") or ""
    world_rules = runtime_bundle.get("world_rules") or ""
    scenario = runtime_bundle.get("scenario") or ""
    personality = runtime_bundle.get("personality") or ""
    alternate_text = _alternate_samples_text(runtime_bundle.get("alternate_greetings") or [])
    related_text = _related_assets_text(runtime_bundle)

    if mode == "character":
        sections = [
            (related_text, ""),
            ("【角色底稿】", base_profile),
            ("【性格与表达风格】", personality),
            ("【当前关系与场景】", scenario),
            ("【世界规则/补充设定】", world_rules),
            ("【示例对话风格参考（注意区分角色与用户的台词）】", examples),
        ]
        if alternate_text:
            sections.append(("", alternate_text))
    elif mode == "scenario":
        sections = []
        if related_text:
            sections.append(("", related_text))
        sections.extend([
            ("【剧情入口/背景】", base_profile),
            ("【角色身份与立场】", personality),
            ("【当前剧情场景】", scenario),
            ("【世界规则/补充设定】", world_rules),
            ("【示例对话风格参考（注意区分角色与用户的台词）】", examples),
        ])
        if alternate_text:
            sections.append(("", alternate_text))
    else:
        sections = []
        if related_text:
            sections.append(("", related_text))
        sections.extend([
            ("【角色底稿】", base_profile),
            ("【性格与表达风格】", personality),
            ("【当前关系与剧情场景】", scenario),
            ("【世界规则/补充设定】", world_rules),
            ("【示例对话风格参考（注意区分角色与用户的台词）】", examples),
        ])
        if alternate_text:
            sections.append(("", alternate_text))
    return sections


def _append_memory_and_history(
    messages: list[dict[str, str]],
    memory_summary: str,
    recent_messages: list[dict[str, str]],
    recent_message_window: int,
    depth_prompt: dict | None = None,
    budget: "TokenBudget | None" = None,
) -> None:
    if memory_summary:
        mem_text = memory_summary
        if budget is not None:
            mem_text = _clip(mem_text, budget.memory_max_chars())
        messages.append({
            "role": "user",
            "content": (
                "<background_context>\n"
                "以下是关于用户的长期记忆背景，仅供你理解上下文使用，"
                "不要当作用户当前说的话，也不要直接复述这些内容：\n\n"
                f"{mem_text}\n"
                "</background_context>"
            )
        })
        messages.append({"role": "assistant", "content": "好的，我已了解这些背景信息，会在回复中自然地体现。"})

    candidate = recent_messages[-recent_message_window:]

    if budget is not None:
        history_budget_chars = budget.history_max_chars()
        used_chars = 0
        kept: list[dict[str, str]] = []
        for msg in reversed(candidate):
            content = msg.get("content", "")
            msg_chars = len(content) + 8
            if used_chars + msg_chars > history_budget_chars and kept:
                break
            kept.append(msg)
            used_chars += msg_chars
        window = list(reversed(kept))
    else:
        window = list(candidate)

    if depth_prompt and isinstance(depth_prompt, dict):
        dp_text = (depth_prompt.get("prompt") or "").strip()
        dp_depth = depth_prompt.get("depth") or 0
        dp_role = depth_prompt.get("role") or "user"
        if dp_role == "system":
            dp_role = "user"
        if dp_text and isinstance(dp_depth, int) and dp_depth > 0 and len(window) > 0:
            insert_pos = max(0, len(window) - dp_depth)
            window = list(window[:insert_pos]) + [{"role": dp_role, "content": dp_text}] + list(window[insert_pos:])

    messages.extend(window)


def _append_post_history_then_user(
    messages: list[dict[str, str]],
    last_user_message: dict[str, str] | None,
) -> None:
    if last_user_message:
        if messages and messages[-1].get("role") == "user":
            messages[-1]["content"] += f"\n\n{last_user_message['content']}"
        else:
            messages.append(last_user_message)


def _append_runtime_tail(
    messages: list[dict[str, str]],
    *,
    memory_summary: str,
    history: list[dict[str, str]],
    recent_message_window: int,
    depth_prompt: dict | None,
    last_user_msg: dict[str, str] | None,
    budget: "TokenBudget | None" = None,
) -> list[dict[str, str]]:
    _append_memory_and_history(
        messages, memory_summary, history, recent_message_window,
        depth_prompt=depth_prompt, budget=budget,
    )
    _append_post_history_then_user(messages, last_user_msg)
    return messages


def _build_mode_messages(
    runtime_bundle: dict[str, Any],
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    recent_message_window: int,
    *,
    mode: str,
    budget: "TokenBudget | None" = None,
    _scenario_default_system_prompt: str = "",
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    depth_prompt = runtime_bundle.get("depth_prompt")
    history, last_user_msg = _split_last_user_message(recent_messages)

    layer_pairs, _, wi_after = _world_info_layer_pairs(runtime_bundle)
    layer_pairs = _append_runtime_text_layers(layer_pairs, _mode_sections(runtime_bundle, character, mode))
    layer_pairs = _append_world_info_after(layer_pairs, wi_after)

    post_history_rules = runtime_bundle.get("post_history_rules") or ""
    if post_history_rules and post_history_rules.strip():
        rules_text = post_history_rules.strip()
        max_chars = budget.reserve_max_chars() if budget is not None else _LAYER_MAX_CHARS
        if len(rules_text) > max_chars:
            rules_text = rules_text[:max_chars].rstrip() + "\n…（内容已截断）"
        layer_pairs.append(("【回复规则提醒】", rules_text))

    primary = runtime_bundle.get("primary_system_prompt") or _get_field(character, "system_prompt", "")
    if not primary.strip() and mode == "scenario":
        # 根据 scenario_type 选择对应的 System Prompt
        try:
            from utils.json_utils import parse_json_object
            rules_json = _get_field(character, "affection_rules_json", {})
            if isinstance(rules_json, str):
                rules_json = parse_json_object(rules_json, fallback={})
            scenario_type = rules_json.get("scenario_type", "adventure")
            primary = _scenario_default_system_prompt if scenario_type == "adventure" else _scenario_default_system_prompt
        except Exception:
            primary = _scenario_default_system_prompt
    system_text = _build_single_system_prompt(primary, layer_pairs, budget=budget)
    if system_text:
        messages.append({"role": "system", "content": system_text})

    return _append_runtime_tail(
        messages,
        memory_summary=memory_summary,
        history=history,
        recent_message_window=recent_message_window,
        depth_prompt=depth_prompt,
        last_user_msg=last_user_msg,
        budget=budget,
    )


def _make_mode_builder(
    mode: str,
    scenario_default_system_prompt: str = "",
) -> Callable[..., list[dict[str, str]]]:
    def builder(
        runtime_bundle: dict[str, Any],
        character: Any,
        recent_messages: list[dict[str, str]],
        memory_summary: str,
        recent_message_window: int,
        budget: "TokenBudget | None" = None,
    ) -> list[dict[str, str]]:
        return _build_mode_messages(
            runtime_bundle, character, recent_messages, memory_summary,
            recent_message_window, mode=mode, budget=budget,
            _scenario_default_system_prompt=scenario_default_system_prompt,
        )
    builder.__name__ = f"_build_{mode}_mode_messages"
    return builder


def _select_mode_builder(
    card_type: str,
    asset_type: str,
    *,
    character_builder: Callable,
    scenario_builder: Callable,
    hybrid_builder: Callable,
) -> Callable[..., list[dict[str, str]]]:
    if card_type == "scenario":
        return scenario_builder
    if asset_type == "character":
        return character_builder
    if asset_type == "scenario":
        return scenario_builder
    return hybrid_builder
