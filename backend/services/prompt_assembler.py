from __future__ import annotations

from typing import Any, Callable

from utils.card_text import expand_macros
from utils.json_utils import parse_json_object
from constants import Mood, StoryPhase
from constants.mood import MOOD_LABELS
from constants.story_phase import STORY_PHASE_LABELS
from core.config import RECENT_MESSAGE_WINDOW
from core.database import ConnType
from services.character_memory_repository import fetch_character_memories, fetch_character_post_rules
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


# ============================================================
# Prompt 编排层
# 说明：
# - 这里只处理"角色资产 + 关联资产 + 记忆 + 历史消息"如何组装成最终 messages
# - 不负责模型调用，也不负责数据库落库
# - 参考 SillyTavern 的思路：导卡格式可以多样，但运行时应收敛为少数清晰层位
# - TokenBudget / DEFAULT_BUDGET / WI 预算辅助函数已迁移到 services/token_budget.py
# - build_runtime_bundle / get_runtime_layers / expand_bundle_macros 已迁移到 services/runtime_bundle.py
# ============================================================

# 状态更新指令（用于 prompt 中注入，指导 AI 输出状态更新标签）
_STATE_UPDATE_INSTRUCTION = [
    "",
    "【状态更新指令（重要）】",
    "每次回复结束时，如果发生了值得记录的互动，必须在回复最后附上状态标签。",
    "只需报告【事件名称】，系统会自动计算实际分数（防止滥用）。",
    "",
    "上报格式：",
    "[STATE_UPDATE]{\"event\":\"事件名\",\"mood\":\"心情\"}[/STATE_UPDATE]",
    "",
    "可用事件名（根据本轮对话内容选最贴切的一个）：",
    "  正向事件：deep_conversation（深聊）/ light_chat（日常闲聊）/ compliment（夸奖）",
    "             gift（送礼）/ help（帮助解决问题）/ shared_secret（分享秘密）",
    "             comfort（安慰情绪）/ flirt（调情撒娇）/ date（约会活动）",
    "             first_hug（第一次拥抱）/ kiss（亲吻）/ confession（表白）",
    "  负向事件：argument（争吵）/ rude（无礼言行）/ ignore（漠视敷衍）",
    "             lie（说谎）/ betray（背叛）/ insult（侮辱）",
    "",
    f"可用心情值：{' / '.join(m.value for m in Mood)}",
    f"关系阶段仅在里程碑时填写（story_phase），平时省略：{'→'.join(p.value for p in StoryPhase)}",
    "",
    "示例：",
    "  [STATE_UPDATE]{\"event\":\"deep_conversation\",\"mood\":\"warm\"}[/STATE_UPDATE]",
    "  [STATE_UPDATE]{\"event\":\"argument\",\"mood\":\"cold\",\"story_phase\":\"stranger\"}[/STATE_UPDATE]",
    "  若本轮无特殊互动，不需要输出标签。",
]



# ============================================================
# 基础工具
# ============================================================

# ============================================================
# 基础工具（仅保留 prompt_assembler 自身使用的）
# ============================================================


# ── 向后兼容重导出 ──
# 以下名称已迁移到独立模块，此处保留重导出以避免外部调用方中断
__all__ = [
    "TokenBudget", "_DEFAULT_BUDGET", "DEFAULT_BUDGET",
    "_LAYER_MAX_CHARS", "LAYER_MAX_CHARS",
    "_PRIMARY_SYSTEM_MAX_CHARS", "PRIMARY_SYSTEM_MAX_CHARS",
    "_TOTAL_SYSTEM_MAX_CHARS", "TOTAL_SYSTEM_MAX_CHARS",
    "build_runtime_bundle", "get_runtime_layers", "_get_field",
    "parse_json_object", "expand_bundle_macros",
    "wi_max_triggered", "wi_max_chars_per_entry",
]

# 重导出已迁移的公共名称
DEFAULT_BUDGET = _DEFAULT_BUDGET
LAYER_MAX_CHARS = _LAYER_MAX_CHARS
PRIMARY_SYSTEM_MAX_CHARS = _PRIMARY_SYSTEM_MAX_CHARS
TOTAL_SYSTEM_MAX_CHARS = _TOTAL_SYSTEM_MAX_CHARS
expand_bundle_macros = _expand_bundle_macros


def _clip(text: str, max_chars: int, label: str = "") -> str:
    """截断超长文本并加提示。"""
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
    """把主系统提示 + 各分层内容合并成一条 system message。

    说明：
    - MiniMax API（以及部分其他 API）只允许 messages 里有一条 role=system 的条目。
    - 我们原来按层各自 append system，会产生多条 system，导致 400 bad request。
    - 这里统一做合并：主 prompt 在前，各层用标题+内容追加，最后整体截断。

    参数：
        budget — TokenBudget 实例（可选）。传入时，total_max / 单层上限均从 budget 派生，
                 忽略 total_max 参数默认值。不传则行为与原先完全一致（向下兼容）。
    """
    if budget is not None:
        # 从 budget 派生各上限，忽略调用方传入的 total_max 默认值
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
    """把关联资产列表格式化为可嵌入 system 的文本，不存在则返回空串。"""
    related_assets = runtime_bundle.get("related_assets") or []
    if not related_assets:
        return ""
    lines = [f"- {item['asset_type']}: {item['name']}" for item in related_assets if item.get("name")]
    return "【当前已激活的关联资产】\n" + "\n".join(lines) if lines else ""


def _alternate_samples_text(alternates: Any) -> str:
    """把备用开场列表格式化为可嵌入 system 的文本。"""
    if not isinstance(alternates, list) or not alternates:
        return ""
    sample = "\n\n".join(str(item).strip() for item in alternates[:2] if str(item).strip())
    return f"【可用开场/剧情片段参考】\n{sample}" if sample else ""


def _split_last_user_message(
    recent_messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], dict[str, str] | None]:
    """把最近消息里的最后一条用户消息剥出来，单独返回。

    目的：让 post_history_instructions 可以插在「历史末尾、当前用户消息之前」，
    与 SillyTavern 的注入行为保持一致。
    如果最后一条不是 user 消息（理论上不应该发生，但做兜底），则不拆分。
    """
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



def _append_runtime_tail(
    messages: list[dict[str, str]],
    *,
    memory_summary: str,
    history: list[dict[str, str]],
    recent_message_window: int,
    depth_prompt: dict | None,
    post_history_rules: str,
    last_user_msg: dict[str, str] | None,
    budget: "TokenBudget | None" = None,
) -> list[dict[str, str]]:
    _append_memory_and_history(
        messages,
        memory_summary,
        history,
        recent_message_window,
        depth_prompt=depth_prompt,
        budget=budget,
    )
    _append_post_history_then_user(messages, post_history_rules, last_user_msg, budget=budget)
    return messages



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
            ("【示例对话风格参考】", examples),
            ("【备用开场参考】", alternate_text),
        ]
    elif mode == "system":
        sections = []
        if related_text:
            sections.append(("", related_text))
        sections.extend([
            ("【核心系统设定】", base_profile),
            ("【世界规则/补充设定】", world_rules),
            ("【当前剧情场景】", scenario),
            ("【示例对话风格参考】", examples),
        ])
        if alternate_text:
            sections.append(("", alternate_text))
    elif mode == "scenario":
        sections = []
        if related_text:
            sections.append(("", related_text))
        sections.extend([
            ("【剧情入口/背景】", base_profile),
            ("【当前剧情场景】", scenario),
            ("【世界规则/补充设定】", world_rules),
            ("【示例对话风格参考】", examples),
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
            ("【示例对话风格参考】", examples),
        ])
        if alternate_text:
            sections.append(("", alternate_text))
    return sections



def _build_mode_messages(
    runtime_bundle: dict[str, Any],
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    recent_message_window: int,
    *,
    mode: str,
    budget: "TokenBudget | None" = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    depth_prompt = runtime_bundle.get("depth_prompt")
    history, last_user_msg = _split_last_user_message(recent_messages)

    layer_pairs, _, wi_after = _world_info_layer_pairs(runtime_bundle)
    layer_pairs = _append_runtime_text_layers(
        layer_pairs,
        _mode_sections(runtime_bundle, character, mode),
    )
    layer_pairs = _append_world_info_after(layer_pairs, wi_after)

    primary = runtime_bundle.get("primary_system_prompt") or _get_field(character, "system_prompt", "")
    system_text = _build_single_system_prompt(primary, layer_pairs, budget=budget)
    if system_text:
        messages.append({"role": "system", "content": system_text})

    return _append_runtime_tail(
        messages,
        memory_summary=memory_summary,
        history=history,
        recent_message_window=recent_message_window,
        depth_prompt=depth_prompt,
        post_history_rules=runtime_bundle.get("post_history_rules") or "",
        last_user_msg=last_user_msg,
        budget=budget,
    )



def _append_memory_and_history(
    messages: list[dict[str, str]],
    memory_summary: str,
    recent_messages: list[dict[str, str]],
    recent_message_window: int,
    depth_prompt: dict | None = None,
    budget: "TokenBudget | None" = None,
) -> None:
    """把长期记忆摘要 + 最近历史消息追加到 messages。

    升级策略（Token 预算贪心）：
    - 若传入 budget，则用 token 预算（而非固定条数）决定保留多少历史。
      从最新消息往前贪心填充，预算耗尽即停，保留"最近且有价值"的对话。
    - 不传 budget 时行为与原先完全一致（向下兼容）。

    注意：memory_summary 用 user role 包装（而不是 assistant），
    避免模型将记忆内容误认为是"自己之前说过的话"。
    明确标注这是"关于用户的信息"，让模型正确理解上下文。
    """
    # ── 1. 长期记忆摘要 ─────────────────────────────────────────
    if memory_summary:
        mem_text = memory_summary
        if budget is not None:
            mem_text = _clip(mem_text, budget.memory_max_chars())
        # 使用 user role 包装记忆摘要，避免模型混淆主语
        # 明确标注这是"关于用户的信息"，让模型正确理解上下文
        messages.append({
            "role": "user",
            "content": f"【系统提示：以下是关于用户的长期记忆，请结合这些背景信息进行回复】\n\n{mem_text}"
        })

    # ── 2. 历史消息：决定保留窗口 ──────────────────────────────
    # 先按 recent_message_window 取候选集（兜底，保证不超过窗口设置）
    candidate = recent_messages[-recent_message_window:]

    if budget is not None:
        # Token 预算贪心：从新到旧逆序遍历，用完预算截止
        history_budget_chars = budget.history_max_chars()
        used_chars = 0
        kept: list[dict[str, str]] = []
        for msg in reversed(candidate):
            content = msg.get("content", "")
            msg_chars = len(content) + 8   # +8 模拟 role 标签开销
            if used_chars + msg_chars > history_budget_chars and kept:
                # 预算用完，且至少已保留 1 条（保证不空手）
                break
            kept.append(msg)
            used_chars += msg_chars
        window = list(reversed(kept))  # 恢复时间顺序
    else:
        window = list(candidate)

    # ── 3. 处理 depth_prompt 深度插入 ─────────────────────────
    if depth_prompt and isinstance(depth_prompt, dict):
        dp_text = (depth_prompt.get("prompt") or "").strip()
        dp_depth = depth_prompt.get("depth") or 0
        # depth_prompt 的 role 如果是 system 改为 user，避免多条 system
        dp_role = depth_prompt.get("role") or "user"
        if dp_role == "system":
            dp_role = "user"

        if dp_text and isinstance(dp_depth, int) and dp_depth > 0 and len(window) > 0:
            insert_pos = max(0, len(window) - dp_depth)
            window = list(window[:insert_pos]) + [{"role": dp_role, "content": dp_text}] + list(window[insert_pos:])

    messages.extend(window)


def _append_post_history_then_user(
    messages: list[dict[str, str]],
    post_history_rules: str,
    last_user_message: dict[str, str] | None,
    budget: "TokenBudget | None" = None,
) -> None:
    """先追加 post_history_rules（以 user 角色注入），再追加当前用户消息（如果有）。

    使用 user role 而非 system role，以兼容只允许单条 system 的 API（如 MiniMax）。

    升级：传入 budget 时，post_history_rules 的截断上限来自 budget.reserve_max_chars()，
    而非硬编码的 _LAYER_MAX_CHARS，确保关键指令不被过度压缩。
    """
    if post_history_rules:
        text = post_history_rules.strip()
        if text:
            max_chars = budget.reserve_max_chars() if budget is not None else _LAYER_MAX_CHARS
            if len(text) > max_chars:
                text = text[:max_chars].rstrip() + "\n…（内容已截断）"
            messages.append({"role": "user", "content": f"【回复规则提醒】{text}"})
    if last_user_message:
        messages.append(last_user_message)


def _make_mode_builder(mode: str) -> Callable[..., list[dict[str, str]]]:
    """工厂：为指定 mode 创建构建函数，消除 4 个仅 mode 参数不同的重复函数。"""
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
        )
    builder.__name__ = f"_build_{mode}_mode_messages"
    return builder


# 模式构建器：每种 mode 仅调用 _build_mode_messages 时传入不同 mode 参数
_build_character_mode_messages = _make_mode_builder("character")
_build_system_mode_messages = _make_mode_builder("system")
_build_scenario_mode_messages = _make_mode_builder("scenario")
_build_hybrid_mode_messages = _make_mode_builder("hybrid")



def _select_mode_builder(card_type: str, asset_type: str) -> Callable[..., list[dict[str, str]]]:
    if card_type == "scenario":
        return _build_scenario_mode_messages
    if card_type == "world":
        return _build_system_mode_messages
    if asset_type == "character":
        return _build_character_mode_messages
    if asset_type == "scenario":
        return _build_scenario_mode_messages
    if asset_type in {"world", "system"}:
        return _build_system_mode_messages
    return _build_hybrid_mode_messages



# ============================================================
# World Info 运行时关键词触发
# ============================================================
# _wi_max_triggered 和 _wi_max_chars_per_entry 已迁移到 services/token_budget.py


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


def build_layered_chat_messages(
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str = "",
    recent_message_window: int = RECENT_MESSAGE_WINDOW,
    related_assets: list[Any] | None = None,
    user_name: str = "",
    character_state: dict | None = None,
    budget: "TokenBudget | None" = None,
    conn: ConnType | None = None,
) -> list[dict[str, str]]:
    """按资产类型 + 产品卡类型把主资产、关联资产、长期记忆和最近消息装配成最终 messages。

    两层路由：
    ① asset_type（导卡层）: character / hybrid / scenario / world / system
    ② card_type（产品层）: intimate(对话陪伴) / scenario(剧情沙盒) / world(世界探索) / divination(占卜形象)
       当 card_type 有明确产品语义时，优先按 card_type 覆盖 builder 选择：
         - card_type=scenario    → 强制走 _build_scenario_mode_messages（旁白/NPC/分支剧情）
         - card_type=world       → 强制走 _build_system_mode_messages（纯知识库注入，无角色）
         - card_type=divination  → 同 intimate，走 asset_type 原路由
         - card_type=intimate    → 按 asset_type 原路由（保持现有行为）

    user_name：当前用户的显示名（用于替换 {{user}} 宏），可选。
    character_state：当前关系状态快照，格式 {"affection":int,"story_phase":str,"mood":str,"custom_vars":dict}，可选。
    budget：TokenBudget 实例（可选），控制各区块的 token 分配。
            不传时自动使用 _DEFAULT_BUDGET（64K context，2048 output reserve）。
    """
    # 使用传入的 budget 或默认实例
    _budget = budget if budget is not None else _DEFAULT_BUDGET

    runtime_bundle = build_runtime_bundle(character, related_assets=related_assets)
    asset_type = runtime_bundle.get("asset_type") or _get_field(character, "asset_type", "hybrid")
    # 读取产品层 card_type（数据库字段，用 _get_field 兼容多种返回格式）
    card_type = _get_field(character, "card_type", "intimate") or "intimate"
    char_name = _get_field(character, "name", "") or ""
    # 对 bundle 内所有文本做一次宏展开（{{char}} → 角色名，{{user}} → 用户名）
    runtime_bundle = _expand_bundle_macros(runtime_bundle, char_name=char_name, user_name=user_name)

    # ── World Info 动态触发 ──────────────────────────────────────────────
    # 用最新用户消息 + 最近几条对话作为匹配上下文
    # 触发到的词条追加到 world_info_before / world_info_after
    
    # 构建用于关键词匹配的上下文文本（最近消息末尾几条）
    ctx_messages = recent_messages[-(RECENT_MESSAGE_WINDOW):] if recent_messages else []
    ctx_text = " ".join(
        m.get("content", "") for m in ctx_messages if m.get("content")
    )
    
    # 1. 从数据库查询记忆条目（新的角色配置系统）
    char_id = _get_field(character, "id", "")
    _b = _budget or _DEFAULT_BUDGET
    if conn is not None:
        db_before, db_after = fetch_character_memories(
            conn, char_id, ctx_text,
            max_triggered=_wi_max_triggered(_budget),
            max_per_entry=_wi_max_chars_per_entry(_budget),
            wi_max=_b.wi_max_chars(),
        )
    else:
        db_before, db_after = [], []
    
    # 2. 从角色卡解析的 conditional_entries（兼容旧的角色卡导入）
    conditional_entries = runtime_bundle.get("conditional_entries") or []
    card_before: list[Any] = []
    card_after: list[Any] = []
    if conditional_entries:
        card_before, card_after = resolve_world_info(conditional_entries, ctx_text, budget=_budget)
    
    # 3. 合并数据库和角色卡的触发结果（角色卡优先，数据库补充）
    # 角色卡包含核心设定，应优先保证；数据库的记忆条目作为动态补充
    wi_max = _budget.wi_max_chars()

    def _calc_wi_used(items: list[str]) -> int:
        """计算已使用的 World Info 字符数。"""
        return sum(len(item) for item in items)

    def _safe_wi_append(existing: str, new_items: list[str], remaining_budget: int) -> tuple[str, int]:
        """把 new_items 追加到 existing，总量不超过 remaining_budget。
        返回 (合并后的文本, 实际使用的字符数)
        """
        parts = [existing] if existing else []
        used = 0
        for item in new_items:
            item_chars = len(item)
            if used + item_chars > remaining_budget:
                break
            parts.append(item)
            used += item_chars
        return "\n\n".join(parts).strip(), used

    # 先处理角色卡的 World Info（优先）
    # 注意：必须按顺序追加并获取实际使用量，而不是预先计算
    
    # 处理 card_before
    if card_before:
        merged_before, card_before_used = _safe_wi_append(
            runtime_bundle.get("world_info_before") or "", card_before, wi_max
        )
        runtime_bundle["world_info_before"] = merged_before
    else:
        card_before_used = 0
    
    # 处理 card_after
    if card_after:
        merged_after, card_after_used = _safe_wi_append(
            runtime_bundle.get("world_info_after") or "", card_after, wi_max
        )
        runtime_bundle["world_info_after"] = merged_after
    else:
        card_after_used = 0
    
    # 再处理数据库的记忆条目（使用实际剩余预算）
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

    # ── 后置规则动态注入 ──────────────────────────────────────────────────
    # 从数据库查询后置规则，合并到 runtime_bundle 的 post_history_rules 中
    # 后置规则放在历史记录后，用于控制输出格式、过滤内容等
    if conn is not None:
        db_post_rules = fetch_character_post_rules(
            conn, char_id,
            storyline_id=character_state.get("storyline_id") if character_state else None,
            story_phase=character_state.get("story_phase") if character_state else None,
            max_chars=_budget.reserve_max_chars() if _budget is not None else _LAYER_MAX_CHARS,
        )
    else:
        db_post_rules = []
    
    if db_post_rules:
        # 合并数据库后置规则和角色卡原有的 post_history_rules
        # 合并顺序：角色卡规则在前，数据库规则在后
        # 这样数据库的动态规则会覆盖角色卡的静态规则（后出现的指令优先）
        existing_rules = runtime_bundle.get("post_history_rules") or ""
        # 过滤掉空字符串，避免产生多余的换行
        all_rules = [r for r in ([existing_rules] + db_post_rules) if r and r.strip()]
        merged_rules = "\n\n".join(all_rules).strip()
        runtime_bundle["post_history_rules"] = merged_rules

    # ── 关系状态快照注入 ──────────────────────────────────────────────────
    # 将当前好感度/阶段/心情以紧凑文本注入到 world_info_after（放在设定末尾，
    # 让 AI 每轮都能看到"当前关系快照"，并据此决定是否输出 [STATE_UPDATE]）。
    if character_state:
        affection = character_state.get("affection", 30)
        phase = character_state.get("story_phase", "stranger")
        mood = character_state.get("mood", "neutral")
        phase_label = STORY_PHASE_LABELS.get(phase, phase)
        mood_label = MOOD_LABELS.get(mood, mood)
        custom_vars = character_state.get("custom_vars") or {}

        state_lines = [
            "【当前关系状态（每轮自动更新）】",
            f"- 好感度：{affection}/100",
            f"- 关系阶段：{phase_label}（{phase}）",
            f"- 当前心情：{mood_label}（{mood}）",
        ]
        if custom_vars:
            for k, v in list(custom_vars.items())[:5]:  # 最多显示5个自定义变量
                state_lines.append(f"- {k}：{v}")

        state_lines.extend(_STATE_UPDATE_INSTRUCTION)

        state_snapshot = "\n".join(state_lines)
        # 状态快照字数保护：上限为 WI 预算的 15%，但保证至少 1000 字符
        # 状态快照对角色行为影响重大，需要保证完整性
        _state_max = max(1000, int(_budget.wi_max_chars() * 0.15))
        if len(state_snapshot) > _state_max:
            # 优先截断自定义变量部分，保留核心状态信息
            truncated_lines = state_lines[:6]  # 保留标题和核心状态（好感度、阶段、心情）
            truncated_lines.append("…（自定义变量已省略）")
            truncated_lines.extend(_STATE_UPDATE_INSTRUCTION)  # 保留指令部分
            state_snapshot = "\n".join(truncated_lines)
        
        # 状态快照优先级最高：放在 world_info_after 的最前面
        # 这样即使 world_info_after 被截断，状态快照也能保留
        existing_after = runtime_bundle.get("world_info_after") or ""
        if existing_after:
            runtime_bundle["world_info_after"] = (state_snapshot + "\n\n" + existing_after).strip()
        else:
            runtime_bundle["world_info_after"] = state_snapshot

    builder = _select_mode_builder(card_type, asset_type)
    return builder(
        runtime_bundle,
        character,
        recent_messages,
        memory_summary,
        recent_message_window,
        budget=_budget,
    )


def build_memory_summary_messages(
    character: Any,
    existing_summary: str,
    unsummarized_messages: list[Any],
    related_assets: list[Any] | None = None,
) -> list[dict[str, str]]:
    """让长期记忆摘要链路也复用同一套运行时上下文，而不是走旧的单角色 prompt。"""
    runtime_bundle = build_runtime_bundle(character, related_assets=related_assets)
    message_lines = []
    for row in unsummarized_messages:
        role = _get_field(row, "role", "")
        content = _get_field(row, "content", "")
        if role and content:
            message_lines.append(f"{role}: {content}")
    conversation_text = "\n".join(message_lines)
    related_assets_text = "\n".join(
        f"- {item['asset_type']}: {item['name']}" for item in runtime_bundle.get("related_assets") or [] if item.get("name")
    ) or "- 无"

    runtime_context_blocks = [
        ("【当前主资产类型】", runtime_bundle.get("asset_type") or "hybrid"),
        ("【角色底稿】", runtime_bundle.get("base_profile") or _get_field(character, "description", "")),
        ("【性格与表达风格】", runtime_bundle.get("personality") or ""),
        ("【当前剧情场景】", runtime_bundle.get("scenario") or ""),
        ("【世界规则/补充设定】", runtime_bundle.get("world_rules") or ""),
        ("【回复约束】", runtime_bundle.get("post_history_rules") or ""),
    ]
    runtime_context = "\n\n".join(f"{title}\n{content}" for title, content in runtime_context_blocks if str(content).strip())

    system_prompt = """你是角色扮演对话的长期记忆整理器。请把聊天内容整理成结构化长期记忆，供后续继续聊天时使用。

输出规则：
1. 必须按以下五个标题输出：
[用户画像]
[用户偏好]
[近期事件]
[关系状态]
[待跟进事项]
2. 每个标题下使用简洁中文要点列表，每行一个要点，统一以"- "开头。
3. 没有信息的分区也要保留标题，但下面可以写"- 暂无稳定信息"。
4. 只保留未来会影响互动的长期信息，不写流水账。
5. “待跟进事项”只记录后续值得主动提起、兑现承诺或继续推进的话题，不要把普通寒暄塞进去。
6. 你在整理时必须参考当前运行时设定，尤其要区分角色关系、剧情状态、世界规则，不要把不稳定的临时台词误写成长期事实。
7. 不编造，不解释过程，不输出多余文字。"""

    user_prompt = f"""当前角色：{_get_field(character, 'name', '未命名角色')}
当前已有长期记忆：
{existing_summary or '（暂无）'}

当前已激活关联资产：
{related_assets_text}

当前运行时上下文：
{runtime_context or '（暂无额外上下文）'}

这次需要整理进长期记忆的新对话：
{conversation_text}

请输出更新后的结构化长期记忆。"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


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
    asset_type = runtime_bundle.get("asset_type") or _get_field(character, "asset_type", "hybrid")
    messages = build_layered_chat_messages(
        character,
        recent_messages,
        memory_summary,
        recent_message_window,
        related_assets=related_assets,
        user_name=user_name,
        character_state=character_state,
    )
    return {
        "asset_type": asset_type,
        "message_count": len(messages),
        "messages": messages,
        "runtime_layers": runtime_bundle,
        "related_assets": runtime_bundle.get("related_assets") or [],
    }
