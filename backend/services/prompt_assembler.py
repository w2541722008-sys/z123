from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, cast

from utils.card_text import expand_macros
from utils.json_utils import parse_json_object
from constants.prompt_templates import (
    STATE_UPDATE_INSTRUCTION,
    SCENARIO_STATE_UPDATE_INSTRUCTION,
    SCENARIO_DEFAULT_SYSTEM_PROMPT,
    ROMANCE_SCENARIO_SYSTEM_PROMPT,
)
from core.config import RECENT_MESSAGE_WINDOW
from core.database import ConnType
from core.plan_constants import DEFAULT_CARD_TYPE
from services.world_info_service import resolve_triggered_memories, resolve_post_rules
from services.token_budget import (
    TokenBudget,
    DEFAULT_BUDGET as _DEFAULT_BUDGET,
    LAYER_MAX_CHARS as _LAYER_MAX_CHARS,
    PRIMARY_SYSTEM_MAX_CHARS as _PRIMARY_SYSTEM_MAX_CHARS,
    TOTAL_SYSTEM_MAX_CHARS as _TOTAL_SYSTEM_MAX_CHARS,
    wi_max_triggered as _wi_max_triggered,
    wi_max_chars_per_entry as _wi_max_chars_per_entry,
)
from services.runtime_bundle import (
    build_runtime_bundle,
    expand_bundle_macros as _expand_bundle_macros,
    get_runtime_layers,
    _get_field,
    _merge_text,
    _merge_alternate_greetings,
)
from services.state_snapshot import inject_state_snapshot
from services.prompt_builder import (
    _clip,
    _build_single_system_prompt,
    _related_assets_text,
    _alternate_samples_text,
    _split_last_user_message,
    _world_info_layer_pairs,
    _append_runtime_text_layers,
    _append_world_info_after,
    _mode_sections,
    _append_memory_and_history,
    _append_post_history_then_user,
    _append_runtime_tail,
    _make_mode_builder as _pb_make_mode_builder,
    _select_mode_builder as _pb_select_mode_builder,
)

logger = logging.getLogger(__name__)

ModeBuilder = Callable[..., list[dict[str, str]]]


@dataclass(frozen=True)
class PromptBuildContext:
    """Prompt 装配所需上下文，避免主链路继续传递长参数列表。"""

    character: Any
    recent_messages: list[dict[str, Any]]
    memory_summary: str = ""
    recent_message_window: int = RECENT_MESSAGE_WINDOW
    related_assets: list[Any] | None = None
    user_name: str = ""
    character_state: dict[str, Any] | None = None
    budget: "TokenBudget | None" = None
    conn: ConnType | None = None
    last_chat_time: str | None = None
    user_id: int | str | None = None


# ============================================================
# Prompt 编排层
# 说明：
# - 这里只处理"角色资产 + 关联资产 + 记忆 + 历史消息"如何组装成最终 messages
# - 不负责模型调用，也不负责数据库落库
# - TokenBudget / DEFAULT_BUDGET / WI 预算辅助函数已迁移到 services/token_budget.py
# - build_runtime_bundle / get_runtime_layers / expand_bundle_macros 已迁移到 services/runtime_bundle.py
# - 状态更新指令常量已迁移到 constants/prompt_templates.py
# - _inject_state_snapshot 已迁移到 services/state_snapshot.py
# ============================================================

# 向后兼容别名（实际定义已迁移到 constants/prompt_templates.py）
_STATE_UPDATE_INSTRUCTION: str = STATE_UPDATE_INSTRUCTION
_SCENARIO_STATE_UPDATE_INSTRUCTION: str = SCENARIO_STATE_UPDATE_INSTRUCTION
_SCENARIO_DEFAULT_SYSTEM_PROMPT: str = SCENARIO_DEFAULT_SYSTEM_PROMPT
_ROMANCE_SCENARIO_SYSTEM_PROMPT: str = ROMANCE_SCENARIO_SYSTEM_PROMPT


# ============================================================
# 基础工具（仅保留 prompt_assembler 自身使用的）
# ============================================================


# ── 向后兼容重导出 ──
# 以下名称已迁移到独立模块，此处保留重导出以避免外部调用方中断
__all__ = [
    "TokenBudget",
    "_DEFAULT_BUDGET",
    "DEFAULT_BUDGET",
    "_LAYER_MAX_CHARS",
    "LAYER_MAX_CHARS",
    "_PRIMARY_SYSTEM_MAX_CHARS",
    "PRIMARY_SYSTEM_MAX_CHARS",
    "_TOTAL_SYSTEM_MAX_CHARS",
    "TOTAL_SYSTEM_MAX_CHARS",
    "build_runtime_bundle",
    "get_runtime_layers",
    "_get_field",
    "_merge_text",
    "_merge_alternate_greetings",
    "parse_json_object",
    "expand_macros",
    "expand_bundle_macros",
    "wi_max_triggered",
    "wi_max_chars_per_entry",
    "_clip",
    "_build_single_system_prompt",
    "_related_assets_text",
    "_alternate_samples_text",
    "_split_last_user_message",
    "_world_info_layer_pairs",
    "_append_runtime_text_layers",
    "_append_world_info_after",
    "_mode_sections",
    "_append_memory_and_history",
    "_append_post_history_then_user",
    "_append_runtime_tail",
    "PromptBuildContext",
    "build_layered_chat_messages_from_context",
]

# 重导出已迁移的公共名称
DEFAULT_BUDGET = _DEFAULT_BUDGET
LAYER_MAX_CHARS = _LAYER_MAX_CHARS
PRIMARY_SYSTEM_MAX_CHARS = _PRIMARY_SYSTEM_MAX_CHARS
TOTAL_SYSTEM_MAX_CHARS = _TOTAL_SYSTEM_MAX_CHARS
expand_bundle_macros = _expand_bundle_macros
wi_max_triggered = _wi_max_triggered
wi_max_chars_per_entry = _wi_max_chars_per_entry


# 模式构建器（通过 prompt_builder 创建）
# scenario 模式需要根据 character 动态选择 System Prompt，所以创建一个包装函数
def _make_mode_builder(mode: str) -> ModeBuilder:
    if mode == "scenario":

        def scenario_builder(
            runtime_bundle: dict[str, Any],
            character: Any,
            recent_messages: list[dict[str, str]],
            memory_summary: str,
            recent_message_window: int,
            budget: "TokenBudget | None" = None,
        ) -> list[dict[str, str]]:
            # 根据角色的 scenario_type 动态选择 System Prompt
            scenario_prompt = _get_scenario_system_prompt(character)
            builder = cast(ModeBuilder, _pb_make_mode_builder(mode, scenario_prompt))
            return builder(
                runtime_bundle,
                character,
                recent_messages,
                memory_summary,
                recent_message_window,
                budget,
            )

        return scenario_builder
    else:
        return cast(ModeBuilder, _pb_make_mode_builder(mode, ""))


def _get_scenario_system_prompt(character: Any) -> str:
    """根据角色卡的 scenario_type 返回对应的 System Prompt"""
    # 从 affection_rules_json 中读取 scenario_type
    try:
        rules_json = _get_field(character, "affection_rules_json", {})
        if isinstance(rules_json, str):
            from utils.json_utils import parse_json_object

            rules_json = parse_json_object(rules_json, fallback={})
        scenario_type = str(rules_json.get("scenario_type", "adventure"))

        if scenario_type == "romance":
            return _ROMANCE_SCENARIO_SYSTEM_PROMPT
        else:
            return _SCENARIO_DEFAULT_SYSTEM_PROMPT
    except Exception:
        logger.warning(
            "scenario_type 解析失败，使用默认 adventure prompt", exc_info=True
        )
        return _SCENARIO_DEFAULT_SYSTEM_PROMPT


_build_character_mode_messages = _make_mode_builder("character")
_build_scenario_mode_messages = _make_mode_builder("scenario")
_build_hybrid_mode_messages = _make_mode_builder("hybrid")


def _select_mode_builder(card_type: str, asset_type: str) -> ModeBuilder:
    return cast(
        ModeBuilder,
        _pb_select_mode_builder(
            card_type,
            asset_type,
            character_builder=_build_character_mode_messages,
            scenario_builder=_build_scenario_mode_messages,
            hybrid_builder=_build_hybrid_mode_messages,
        ),
    )


# ============================================================
# World Info 运行时关键词触发
# ============================================================


def resolve_world_info(
    conditional_entries: list[dict],
    context_text: str,
    budget: "TokenBudget | None" = None,
) -> tuple[list[str], list[str]]:
    """按关键词扫描 context_text，返回触发的 before/after 词条文本列表。

    参数：
        conditional_entries  — build_runtime_bundle 里的 conditional_entries 列表
        context_text         — 用于匹配的上下文（一般是用户最新消息 + 最近几条对话）
        budget               — TokenBudget 实例，用于派生词条数量/字符上限；不传则用默认值

    返回：
        (triggered_before, triggered_after)
        triggered_before — position=before_char 的触发词条文本列表
        triggered_after  — position=after_char  的触发词条文本列表

    匹配规则：
    - 词条的 keys 里任意一个关键词出现在 context_text 中就触发
    - 关键词匹配忽略大小写
    - 按 insertion_order 升序排列触发结果，保持 ST 兼容顺序
    - 最多触发 _wi_max_triggered(budget) 条（超出的直接丢弃，避免 prompt 爆炸）
    """
    if not conditional_entries or not context_text:
        return [], []

    max_triggered = _wi_max_triggered(budget)
    max_per_entry = _wi_max_chars_per_entry(budget)

    ctx_lower = context_text.lower()
    triggered: list[dict] = []

    for entry in conditional_entries:
        if not isinstance(entry, dict):
            continue
        keys: list[str] = entry.get("keys") or []
        if not keys:
            continue
        # 任意一个 key 命中即触发
        if any(k.lower() in ctx_lower for k in keys if k):
            triggered.append(entry)

    # 按 insertion_order 升序排序
    triggered.sort(key=lambda e: e.get("insertion_order", 999))
    triggered = triggered[:max_triggered]

    before_list: list[str] = []
    after_list: list[str] = []

    for entry in triggered:
        content = (entry.get("content") or "").strip()
        if not content:
            continue
        if len(content) > max_per_entry:
            content = content[:max_per_entry].rstrip() + "\n…（词条已截断）"
        comment = (entry.get("comment") or "").strip()
        text = f"[{comment}]\n{content}" if comment else content
        position = entry.get("position", "before_char")
        if position == "after_char":
            after_list.append(text)
        else:
            before_list.append(text)

    return before_list, after_list


# ============================================================
# build_layered_chat_messages 阶段函数
# 将原来的 388 行巨函数拆分为 5 个阶段 + 1 个编排函数
# 阶段5 (_inject_state_snapshot) 已迁移到 services/state_snapshot.py
# ============================================================


def _init_runtime_context(
    character: Any,
    related_assets: list[Any] | None,
    user_name: str,
    budget: "TokenBudget | None",
) -> tuple[dict[str, Any], str, str, str, str, "TokenBudget"]:
    """阶段1：初始化运行时 bundle，确定资产类型/产品卡类型，展开宏。"""
    _budget = budget if budget is not None else _DEFAULT_BUDGET
    runtime_bundle = build_runtime_bundle(character, related_assets=related_assets)
    asset_type = runtime_bundle.get("asset_type") or _get_field(
        character, "asset_type", "hybrid"
    )
    card_type = (
        _get_field(character, "card_type", DEFAULT_CARD_TYPE) or DEFAULT_CARD_TYPE
    )
    char_name = _get_field(character, "name", "") or ""
    char_id = _get_field(character, "id", "")
    runtime_bundle = _expand_bundle_macros(
        runtime_bundle, char_name=char_name, user_name=user_name
    )
    return runtime_bundle, asset_type, card_type, char_name, char_id, _budget


def _inject_life_profile(
    runtime_bundle: dict[str, Any],
    character: Any,
    card_type: str,
) -> None:
    """阶段2：注入人生档案（仅对话陪伴类型），存入独立字段供 prompt_builder 作为独立 layer 使用。"""
    if card_type != "intimate":
        return
    life_profile = parse_json_object(
        _get_field(character, "life_profile_json", "{}"), fallback={}
    )
    if not life_profile or not any(life_profile.values()):
        return
    profile_lines: list[str] = []
    if life_profile.get("basic_info"):
        profile_lines.append(life_profile["basic_info"])
    if life_profile.get("childhood"):
        profile_lines.append(f"\n童年经历：\n{life_profile['childhood']}")
    if life_profile.get("family"):
        profile_lines.append(f"\n家庭背景：\n{life_profile['family']}")
    if life_profile.get("work"):
        profile_lines.append(f"\n工作经历：\n{life_profile['work']}")
    if life_profile.get("personality"):
        profile_lines.append(f"\n性格特点：\n{life_profile['personality']}")
    if life_profile.get("habits"):
        profile_lines.append(f"\n生活习惯：\n{life_profile['habits']}")
    if life_profile.get("important_events"):
        profile_lines.append(f"\n重要经历：\n{life_profile['important_events']}")
    if profile_lines:
        runtime_bundle["life_profile"] = "\n".join(profile_lines)


def _resolve_world_info_triggers(
    conn: ConnType | None,
    character: Any,
    runtime_bundle: dict[str, Any],
    recent_messages: list[dict[str, str]],
    character_state: dict | None,
    _budget: "TokenBudget",
) -> None:
    """阶段3：World Info 动态触发——数据库记忆 + 角色卡条件词条合并。"""
    ctx_messages = recent_messages[-(RECENT_MESSAGE_WINDOW):] if recent_messages else []
    ctx_text = " ".join(m.get("content", "") for m in ctx_messages if m.get("content"))

    char_id = _get_field(character, "id", "")
    _custom_vars = (character_state or {}).get("custom_vars") or {}
    _wi_sticky = _custom_vars.get("_wi_sticky") or {}
    _wi_cooldown = _custom_vars.get("_wi_cooldown") or {}

    if conn is not None:
        current_storyline_id = (character_state or {}).get("storyline_id")
        db_before, db_after, new_sticky, new_cooldown = resolve_triggered_memories(
            conn,
            char_id,
            ctx_text,
            max_triggered=_wi_max_triggered(_budget),
            max_per_entry=_wi_max_chars_per_entry(_budget),
            wi_max=_budget.wi_max_chars(),
            sticky_state=_wi_sticky,
            cooldown_state=_wi_cooldown,
            current_storyline_id=current_storyline_id,
        )
    else:
        db_before, db_after = [], []
        new_sticky, new_cooldown = {}, {}

    if character_state is not None:
        cv = dict(character_state.get("custom_vars") or {})
        cv["_wi_sticky"] = new_sticky
        cv["_wi_cooldown"] = new_cooldown
        character_state["custom_vars"] = cv

    conditional_entries = runtime_bundle.get("conditional_entries") or []
    card_before: list[Any] = []
    card_after: list[Any] = []
    if conditional_entries:
        card_before, card_after = resolve_world_info(
            conditional_entries, ctx_text, budget=_budget
        )

    wi_max = _budget.wi_max_chars()

    def _safe_wi_append(
        existing: str, new_items: list[str], remaining_budget: int
    ) -> tuple[str, int]:
        parts = [existing] if existing else []
        used = len(existing) if existing else 0
        for item in new_items:
            item_chars = len(item)
            if used + item_chars > remaining_budget:
                break
            parts.append(item)
            used += item_chars
        return "\n\n".join(parts).strip(), used

    db_reserve_ratio = 0.3
    has_db_entries = bool(db_before or db_after)
    card_wi_budget = int(wi_max * (1 - db_reserve_ratio)) if has_db_entries else wi_max

    if card_before:
        merged_before, card_before_used = _safe_wi_append(
            runtime_bundle.get("world_info_before") or "", card_before, card_wi_budget
        )
        runtime_bundle["world_info_before"] = merged_before
    else:
        card_before_used = 0

    if card_after:
        merged_after, card_after_used = _safe_wi_append(
            runtime_bundle.get("world_info_after") or "", card_after, card_wi_budget
        )
        runtime_bundle["world_info_after"] = merged_after
    else:
        card_after_used = 0

    remaining_before = max(0, wi_max - card_before_used)
    remaining_after = max(0, wi_max - card_after_used)

    if db_before and remaining_before > 0:
        runtime_bundle["world_info_before"] = _safe_wi_append(
            runtime_bundle.get("world_info_before") or "", db_before, remaining_before
        )[0]

    if db_after and remaining_after > 0:
        runtime_bundle["world_info_after"] = _safe_wi_append(
            runtime_bundle.get("world_info_after") or "", db_after, remaining_after
        )[0]


def _inject_post_history_rules(
    conn: ConnType | None,
    char_id: str,
    runtime_bundle: dict[str, Any],
    character_state: dict | None,
    _budget: "TokenBudget",
) -> None:
    """阶段4：从数据库查询后置规则，合并到 runtime_bundle。"""
    if conn is not None:
        db_post_rules = resolve_post_rules(
            conn,
            char_id,
            storyline_id=(
                character_state.get("storyline_id") if character_state else None
            ),
            story_phase=character_state.get("story_phase") if character_state else None,
            max_chars=(
                _budget.reserve_max_chars() if _budget is not None else _LAYER_MAX_CHARS
            ),
        )
    else:
        db_post_rules = []

    if db_post_rules:
        existing_rules = runtime_bundle.get("post_history_rules") or ""
        all_rules = [r for r in ([existing_rules] + db_post_rules) if r and r.strip()]
        merged_rules = "\n\n".join(all_rules).strip()
        runtime_bundle["post_history_rules"] = merged_rules


def _inject_state_snapshot(
    conn: ConnType | None,
    character: Any,
    runtime_bundle: dict[str, Any],
    character_state: dict | None,
    _budget: "TokenBudget",
    card_type: str,
    last_chat_time: str | None,
    user_id: int | str | None,
    char_id: str,
) -> None:
    """阶段5：委托 services/state_snapshot.py 构建状态快照并注入 world_info_after。"""
    inject_state_snapshot(
        conn,
        character,
        runtime_bundle,
        character_state,
        _budget,
        card_type,
        last_chat_time,
        user_id,
        char_id,
    )


def build_layered_chat_messages_from_context(
    context: PromptBuildContext,
) -> list[dict[str, str]]:
    """按资产类型 + 产品卡类型把主资产、关联资产、长期记忆和最近消息装配成最终 messages。

    两层路由：
    ① asset_type（导卡层）: character / hybrid / scenario
    ② card_type（产品层）: intimate(对话陪伴) / scenario(剧情沙盒)
       当 card_type 有明确产品语义时，优先按 card_type 覆盖 builder 选择：
         - card_type=scenario    → 强制走 _build_scenario_mode_messages
         - card_type=intimate    → 按 asset_type 原路由（保持现有行为）
    """
    # 阶段1：初始化运行时上下文
    runtime_bundle, asset_type, card_type, char_name, char_id, _budget = (
        _init_runtime_context(
            context.character,
            context.related_assets,
            context.user_name,
            context.budget,
        )
    )

    # 阶段2：人生档案注入（仅对话陪伴）
    _inject_life_profile(runtime_bundle, context.character, card_type)

    # 阶段3：World Info 动态触发
    _resolve_world_info_triggers(
        context.conn,
        context.character,
        runtime_bundle,
        context.recent_messages,
        context.character_state,
        _budget,
    )

    # 阶段4：后置规则注入
    _inject_post_history_rules(
        context.conn, char_id, runtime_bundle, context.character_state, _budget
    )

    # 阶段5：状态快照与情感锚点注入
    _inject_state_snapshot(
        context.conn,
        context.character,
        runtime_bundle,
        context.character_state,
        _budget,
        card_type,
        context.last_chat_time,
        context.user_id,
        char_id,
    )

    # 阶段6：选择 builder 并构建最终 messages
    builder = _select_mode_builder(card_type, asset_type)
    return builder(
        runtime_bundle,
        context.character,
        context.recent_messages,
        context.memory_summary,
        context.recent_message_window,
        budget=_budget,
    )


def build_layered_chat_messages(
    character: Any,
    recent_messages: list[dict[str, Any]],
    memory_summary: str = "",
    recent_message_window: int = RECENT_MESSAGE_WINDOW,
    related_assets: list[Any] | None = None,
    user_name: str = "",
    character_state: dict[str, Any] | None = None,
    budget: "TokenBudget | None" = None,
    conn: ConnType | None = None,
    last_chat_time: str | None = None,
    user_id: int | str | None = None,
) -> list[dict[str, str]]:
    """兼容旧调用方：把长参数列表转换为 PromptBuildContext。"""
    return build_layered_chat_messages_from_context(
        PromptBuildContext(
            character=character,
            recent_messages=recent_messages,
            memory_summary=memory_summary,
            recent_message_window=recent_message_window,
            related_assets=related_assets,
            user_name=user_name,
            character_state=character_state,
            budget=budget,
            conn=conn,
            last_chat_time=last_chat_time,
            user_id=user_id,
        )
    )


def build_message_preview(
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str = "",
    recent_message_window: int = RECENT_MESSAGE_WINDOW,
    related_assets: list[Any] | None = None,
    user_name: str = "",
    character_state: dict | None = None,
) -> dict[str, Any]:
    """调试用：返回最终 messages、运行时层和关联资产概览。"""
    runtime_bundle = build_runtime_bundle(character, related_assets=related_assets)
    asset_type = runtime_bundle.get("asset_type") or _get_field(
        character, "asset_type", "hybrid"
    )
    messages = build_layered_chat_messages_from_context(
        PromptBuildContext(
            character=character,
            recent_messages=recent_messages,
            memory_summary=memory_summary,
            recent_message_window=recent_message_window,
            related_assets=related_assets,
            user_name=user_name,
            character_state=character_state,
        )
    )
    return {
        "asset_type": asset_type,
        "message_count": len(messages),
        "messages": messages,
        "runtime_layers": runtime_bundle,
        "related_assets": runtime_bundle.get("related_assets") or [],
    }
