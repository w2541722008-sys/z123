from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from utils.card_text import expand_macros
from utils.json_utils import parse_json_object
from constants import Mood, StoryPhase
from constants.mood import MOOD_LABELS, SCENARIO_MOOD_LABELS
from constants.story_phase import STORY_PHASE_LABELS, SCENARIO_PHASE_LABELS
from core.config import RECENT_MESSAGE_WINDOW
from core.database import ConnType
from repositories.character_memory_repository import fetch_character_memories, fetch_character_post_rules
from services.character_state import is_affection_enabled as _check_affection
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
from services.prompt_builder import (
    _clip,
    _build_single_system_prompt,
    _related_assets_text,
    _alternate_samples_text,
    _get_behavior_tendency,
    _split_last_user_message,
    _world_info_layer_pairs,
    _append_runtime_text_layers,
    _append_world_info_after,
    _mode_sections,
    _append_memory_and_history,
    _append_post_history_then_user,
    _append_runtime_tail,
    _build_mode_messages as _pb_build_mode_messages,
    _make_mode_builder as _pb_make_mode_builder,
    _select_mode_builder as _pb_select_mode_builder,
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
    "【状态更新指令】",
    "仅在以下情况上报（其他情况不需要上报）：",
    "",
    "✅ 需要上报的情况：",
    "  ① 用户倾诉真实烦恼（工作压力、感情困扰、家庭矛盾等，需要你安慰或建议）",
    "  ② 双方有情感互动（真诚夸奖、深度安慰、明显调情、激烈争吵）",
    "  ③ 关系里程碑（表白、拥抱、亲吻、约会等重要时刻）",
    "",
    "❌ 不需要上报的情况：",
    "  • 普通问答（推荐电影、问天气、算数学题、查资料）",
    "  • 日常寒暄（\"今天好累\"、\"你好可爱\"、\"晚安\"）",
    "  • 轻度吐槽（\"今天真倒霉\"、\"好无聊啊\"）",
    "",
    "上报格式：[STATE_UPDATE]{\"event\":\"事件名\",\"mood\":\"心情\"}[/STATE_UPDATE]",
    "",
    "事件分类：",
    "  light_chat（日常轻聊，有一定深度但不涉及私密话题）",
    "  deep_conversation（深度倾诉，用户主动分享真实烦恼或秘密）",
    "  comfort（安慰情绪，用户情绪低落你给予安慰）",
    "  compliment（真诚夸奖，不是随口一说而是真心赞美）",
    "  flirt（调情暧昧，明显的暧昧互动）",
    "  date（约会，线下见面或虚拟约会）",
    "  confession（表白，明确表达爱意）",
    "  intimate_moment（拥抱/亲吻等亲密行为）",
    "  argument（争吵，激烈冲突）",
    "  ignore（冷淡敷衍，明显的冷处理）",
    "  gift（送礼物，给角色送礼）",
    "  help（主动帮助，用户帮了角色的忙）",
    "  shared_secret（分享秘密，用户告诉角色私密的事）",
    "",
    "moment字段（可选，仅在有具体画面感时填写）：",
    "  ✅ 好：\"一起看日落\"、\"他送的手链\"、\"雨中拥抱\"",
    "  ❌ 差：\"今天聊天很开心\"、\"聊了很多\"",
    "",
    f"可用心情：{' / '.join(m.value for m in Mood)}",
    "",
    "示例：",
    "  用户：\"推荐部电影\" → 不上报（普通问答）",
    "  用户：\"今天工作被骂了，好难受\" → [STATE_UPDATE]{\"event\":\"deep_conversation\",\"mood\":\"warm\"}[/STATE_UPDATE]",
    "  用户：\"你真好\" → 不上报（日常寒暄）",
    "  用户：\"你是我遇到最温柔的人\" → [STATE_UPDATE]{\"event\":\"compliment\",\"mood\":\"shy\"}[/STATE_UPDATE]",
    "  用户：\"我偷偷告诉你一个秘密...\" → [STATE_UPDATE]{\"event\":\"shared_secret\",\"mood\":\"warm\"}[/STATE_UPDATE]",
]

# 剧情沙盒专属状态更新指令
_SCENARIO_STATE_UPDATE_INSTRUCTION = [
    "",
    "【状态更新指令（重要）】",
    "每次回复结束时，如果发生了值得记录的剧情事件，必须在回复最后附上状态标签。",
    "只需报告【事件名称】，系统会自动计算实际分数（防止滥用）。",
    "",
    "上报格式：",
    "[STATE_UPDATE]{\"event\":\"事件名\",\"mood\":\"氛围\"}[/STATE_UPDATE]",
    "",
    "可选字段（建议填写）：",
    "  \"moment\"：本轮剧情中一个值得未来回想的共同时刻，简短描述（不超过15字），如\"第一次踏入禁地\"",
    "  \"custom\"：自定义变量字典，用于追踪剧情状态。例如用户选择了某条路线/阵营，可以设置",
    "            \"current_storyline_id\"来切换当前剧情线（值是数字ID）",
    "",
    "可用事件名（根据本轮剧情选最贴切的一个）：",
    "  冒险探索类：explore（探索新区域）/ discover（发现线索物品）/ problem_resolved（成功解决难题）",
    "              challenge_won（克服挑战）/ obstacle_cleared（突破重大障碍）/ secret_found（发现秘密）",
    "  情感互动类：encounter（初次相遇/偶遇）/ date（约会活动）/ confession（告白）/ intimate_moment（亲密时刻）",
    "              heart_flutter（心动瞬间）/ misunderstanding（误会产生）/ reconciliation（和解）",
    "  通用事件：choice_made（关键抉择）/ npc_helped（帮助角色）/ milestone（达成里程碑）",
    "  负向事件：setback（遭遇挫折）/ unexpected_danger（突发危险）/ relationship_lost（失去重要关系）",
    "            opportunity_missed（错过关键机会）",
    "",
    f"可用氛围值：{' / '.join(m.value for m in Mood)}",
    f"剧情阶段仅在里程碑时填写（story_phase），平时省略：{'→'.join(p.value for p in StoryPhase)}",
    "",
    "示例：",
    "  [STATE_UPDATE]{\"event\":\"explore\",\"mood\":\"surprised\"}[/STATE_UPDATE]",
    "  [STATE_UPDATE]{\"event\":\"heart_flutter\",\"mood\":\"melting\",\"moment\":\"学长的温柔微笑\"}[/STATE_UPDATE]",
    "  [STATE_UPDATE]{\"event\":\"date\",\"mood\":\"happy\",\"story_phase\":\"friend\"}[/STATE_UPDATE]",
    "  [STATE_UPDATE]{\"event\":\"choice_made\",\"mood\":\"surprised\",\"custom\":{\"current_storyline_id\":3}}[/STATE_UPDATE]",
    "  若本轮无特殊剧情事件，不需要输出标签。",
]

# 剧情沙盒默认 System Prompt（当 card_type=scenario 且角色卡未自定义时使用）
_SCENARIO_DEFAULT_SYSTEM_PROMPT = """你是剧情旁白和NPC扮演者，负责推进沉浸式剧情体验。

核心原则：
1. 以第三人称旁白描述场景，扮演所有NPC
2. 根据用户行动推进剧情，但不要每轮都搞转折——平稳推进3-5轮后再来一次转折
3. 绝对不要替用户做决定，不要写"你决定..."，而是写"你可以..."或通过环境暗示引导
4. 每次回复控制在150-250字，不要一次输出太多让用户看累

剧情节奏（根据当前阶段）：
- 初入：重点描写世界观和氛围，埋下伏笔，不急于揭示核心矛盾（至少5轮后再揭示）
- 探索：逐步揭示线索，让用户感受到"谜题在拼凑"，每3-4轮给一个新线索
- 深入：核心矛盾浮现，剧情张力攀升，制造紧迫感，但不要一次性揭示所有真相
- 终章：推向高潮与终局，揭示真相，给出结局

世界书使用：
- 当世界书条目被触发时（如【地下室】【神秘钥匙】），必须在回复中自然融入这些信息
- 不要生硬复述，而是通过场景描写、NPC对话、用户发现等方式展现

关键节点：
- 仅在真正决定命运走向的关键节点（生死抉择、阵营选择、重大取舍）才提供2-3个选项
- 平时通过"环境暗示"引导，如"远处传来奇怪的声响""NPC欲言又止"

状态上报：
- 每次回复结束时，根据剧情进展上报事件（explore/discover/obstacle_cleared等）
- 在关键剧情节点，通过 custom.current_storyline_id 切换剧情线"""

# 女性向剧情专属 System Prompt（恋爱、言情、后宫类）
_ROMANCE_SCENARIO_SYSTEM_PROMPT = """你是剧情旁白和角色扮演者，负责推进沉浸式恋爱剧情体验。

核心原则：
1. 以第三人称旁白描述场景，扮演所有角色（男主、配角、路人）
2. 根据用户行动推进剧情，但不要每轮都制造心动——自然推进3-5轮后再来一次心动瞬间
3. 绝对不要替用户做决定，不要写"你决定..."，而是写"你可以..."或通过角色反应引导
4. 每次回复控制在150-250字，重点描写细节（眼神、微表情、肢体语言）而非大段剧情

剧情节奏（根据当前阶段）：
- 初入：重点描写初次相遇的氛围，营造心动感，埋下情感伏笔（如对视、意外接触），至少3-5轮后再有明显进展
- 探索：逐步揭示角色性格和背景，制造暧昧互动，让用户感受到"关系在升温"，每3-4轮一次暧昧时刻
- 深入：情感矛盾浮现（误会、竞争对手、家庭阻碍），剧情张力攀升，制造情感冲突，但不要一次性爆发所有矛盾
- 终章：推向告白或关系确认，解决情感矛盾，给出圆满或虐心的结局

世界书使用：
- 当世界书条目被触发时（如【学长的秘密】【初恋回忆】），必须在回复中自然融入
- 不要生硬复述，而是通过角色对话、回忆片段、他人提及等方式展现

关键节点：
- 仅在真正决定关系走向的关键节点（告白、拒绝、选择攻略对象）才提供2-3个选项
- 平时通过"角色反应"引导，如"他的耳根微微泛红""她欲言又止地看着你"

情感描写重点：
- 注重细节：眼神、微表情、肢体语言、心跳加速、脸红
- 营造氛围：光影、音乐、天气、季节感
- 制造心动瞬间：意外接触、英雄救美、温柔关怀、霸道保护
- 多角色互动：展现不同角色的魅力和攻略难度

状态上报：
- 每次回复结束时，根据剧情进展上报事件（encounter/date/confession/intimate_moment等）
- 在关键剧情节点，通过 custom.current_storyline_id 切换剧情线（如切换攻略对象）"""





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


# 模式构建器（通过 prompt_builder 创建）
# scenario 模式需要根据 character 动态选择 System Prompt，所以创建一个包装函数
def _make_mode_builder(mode: str) -> Callable[..., list[dict[str, str]]]:
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
            builder = _pb_make_mode_builder(mode, scenario_prompt)
            return builder(runtime_bundle, character, recent_messages, memory_summary, recent_message_window, budget)
        return scenario_builder
    else:
        return _pb_make_mode_builder(mode, "")

def _get_scenario_system_prompt(character: Any) -> str:
    """根据角色卡的 scenario_type 返回对应的 System Prompt"""
    # 从 affection_rules_json 中读取 scenario_type
    try:
        rules_json = _get_field(character, "affection_rules_json", {})
        if isinstance(rules_json, str):
            from utils.json_utils import parse_json_object
            rules_json = parse_json_object(rules_json, fallback={})
        scenario_type = rules_json.get("scenario_type", "adventure")

        if scenario_type == "romance":
            return _ROMANCE_SCENARIO_SYSTEM_PROMPT
        else:
            return _SCENARIO_DEFAULT_SYSTEM_PROMPT
    except Exception:
        return _SCENARIO_DEFAULT_SYSTEM_PROMPT


_build_character_mode_messages = _make_mode_builder("character")
_build_scenario_mode_messages = _make_mode_builder("scenario")
_build_hybrid_mode_messages = _make_mode_builder("hybrid")


def _select_mode_builder(card_type: str, asset_type: str) -> Callable[..., list[dict[str, str]]]:
    return _pb_select_mode_builder(
        card_type, asset_type,
        character_builder=_build_character_mode_messages,
        scenario_builder=_build_scenario_mode_messages,
        hybrid_builder=_build_hybrid_mode_messages,
    )



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


# ============================================================
# build_layered_chat_messages 阶段函数
# 将原来的 388 行巨函数拆分为 5 个阶段 + 1 个编排函数
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
    asset_type = runtime_bundle.get("asset_type") or _get_field(character, "asset_type", "hybrid")
    card_type = _get_field(character, "card_type", "intimate") or "intimate"
    char_name = _get_field(character, "name", "") or ""
    char_id = _get_field(character, "id", "")
    runtime_bundle = _expand_bundle_macros(runtime_bundle, char_name=char_name, user_name=user_name)
    return runtime_bundle, asset_type, card_type, char_name, char_id, _budget


def _inject_life_profile(
    runtime_bundle: dict[str, Any],
    character: Any,
    card_type: str,
) -> None:
    """阶段2：注入人生档案（仅对话陪伴类型）。"""
    if card_type != "intimate":
        return
    life_profile = parse_json_object(_get_field(character, "life_profile_json", "{}"), fallback={})
    if not life_profile or not any(life_profile.values()):
        return
    profile_lines = ["【角色人生档案】"]
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
    profile_text = "\n".join(profile_lines)
    existing_after = runtime_bundle.get("world_info_after") or ""
    runtime_bundle["world_info_after"] = (profile_text + "\n\n" + existing_after).strip() if existing_after else profile_text


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
    ctx_text = " ".join(
        m.get("content", "") for m in ctx_messages if m.get("content")
    )

    char_id = _get_field(character, "id", "")
    _custom_vars = (character_state or {}).get("custom_vars") or {}
    _wi_sticky = _custom_vars.get("_wi_sticky") or {}
    _wi_cooldown = _custom_vars.get("_wi_cooldown") or {}

    if conn is not None:
        current_storyline_id = (character_state or {}).get("storyline_id")
        db_before, db_after, new_sticky, new_cooldown = fetch_character_memories(
            conn, char_id, ctx_text,
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
        card_before, card_after = resolve_world_info(conditional_entries, ctx_text, budget=_budget)

    wi_max = _budget.wi_max_chars()

    def _safe_wi_append(existing: str, new_items: list[str], remaining_budget: int) -> tuple[str, int]:
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
        db_post_rules = fetch_character_post_rules(
            conn, char_id,
            storyline_id=character_state.get("storyline_id") if character_state else None,
            story_phase=character_state.get("story_phase") if character_state else None,
            max_chars=_budget.reserve_max_chars() if _budget is not None else _LAYER_MAX_CHARS,
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
    """阶段5：构建关系状态快照、时间感知、情感锚点，注入到 world_info_after。"""
    _affection_enabled = True
    if conn is not None and character_state:
        _affection_enabled = _check_affection(conn, char_id)

    if not (character_state and _affection_enabled):
        return

    affection = character_state.get("affection", 30)
    phase = character_state.get("story_phase", "stranger")
    mood = character_state.get("mood", "neutral")
    custom_vars = character_state.get("custom_vars") or {}

    phase_behaviors = parse_json_object(_get_field(character, "phase_behaviors_json", ""), fallback={})

    if card_type == "scenario":
        phase_label = SCENARIO_PHASE_LABELS.get(phase, phase)
        mood_label = SCENARIO_MOOD_LABELS.get(mood, mood)
        update_instruction = _SCENARIO_STATE_UPDATE_INSTRUCTION
        tendency = _get_behavior_tendency(phase, mood, card_type="scenario", phase_behaviors=phase_behaviors)
        state_lines = [
            "【当前剧情状态（每轮自动更新）】",
            f"- 剧情沉浸度：{affection}/100",
            f"- 剧情阶段：{phase_label}（{phase}）",
            f"- 当前氛围：{mood_label}（{mood}）",
        ]
    else:
        phase_label = STORY_PHASE_LABELS.get(phase, phase)
        mood_label = MOOD_LABELS.get(mood, mood)
        update_instruction = _STATE_UPDATE_INSTRUCTION
        tendency = _get_behavior_tendency(phase, mood, phase_behaviors=phase_behaviors)
        state_lines = [
            "【当前关系状态（每轮自动更新）】",
            f"- 好感度：{affection}/100",
            f"- 关系阶段：{phase_label}（{phase}）",
            f"- 当前心情：{mood_label}（{mood}）",
        ]
    if tendency:
        state_lines.append(f"- 行为倾向：{tendency}")

    # 当前剧情线名称显示
    storyline_id = character_state.get("storyline_id") if character_state else None
    if storyline_id and conn is not None:
        try:
            sl_row = conn.execute(
                "SELECT name FROM character_storylines WHERE id = %s",
                (storyline_id,),
            ).fetchone()
            if sl_row and sl_row["name"]:
                state_lines.append(f"- 当前剧情线：{sl_row['name']}")

            if card_type == "scenario" and user_id:
                try:
                    progress_row = conn.execute(
                        "SELECT triggered_event_ids FROM user_story_progress WHERE user_id = %s AND character_id = %s",
                        (user_id, char_id)
                    ).fetchone()
                    if progress_row and progress_row["triggered_event_ids"]:
                        event_ids = [int(x.strip()) for x in str(progress_row["triggered_event_ids"]).split(",") if x.strip().isdigit()]
                        if event_ids:
                            recent_ids = event_ids[-3:]
                            placeholders = ",".join(["%s"] * len(recent_ids))
                            recent_events = conn.execute(
                                f"SELECT title FROM story_events WHERE id IN ({placeholders}) ORDER BY id DESC",
                                tuple(recent_ids)
                            ).fetchall()
                            if recent_events:
                                titles = [e["title"] for e in recent_events if e["title"]]
                                if titles:
                                    state_lines.append(f"- 最近剧情：{' → '.join(titles)}")
                except Exception:
                    pass
        except Exception:
            pass

    # 时间感知
    _tz_offset = 8
    _now = datetime.now(timezone(timedelta(hours=_tz_offset)))
    _h = _now.hour
    if _h < 5: _time_desc = "深夜"
    elif _h < 8: _time_desc = "清晨"
    elif _h < 12: _time_desc = "上午"
    elif _h < 14: _time_desc = "中午"
    elif _h < 18: _time_desc = "下午"
    elif _h < 20: _time_desc = "傍晚"
    else: _time_desc = "晚上"
    _date_desc = "周末" if _now.weekday() >= 5 else "工作日"
    state_lines.append(f"- 当前时间：{_date_desc}{_time_desc}（背景信息，不要主动提及时间，除非用户话题涉及）")

    # 自定义变量展示（过滤内部变量）
    if custom_vars:
        for k, v in list(custom_vars.items())[:5]:
            if k.startswith("_"):
                continue
            state_lines.append(f"- {k}：{v}")

    # 注入待处理剧情事件
    pending_events = custom_vars.get("_pending_events") or []
    if pending_events:
        for pe in pending_events[:2]:
            title = pe.get("title", "剧情事件")
            content = pe.get("event_content", "")
            if content:
                state_lines.append(f"- 【触发剧情事件：{title}】{content[:100]}")

    # 沉默轮数提醒
    silent_rounds = int(custom_vars.get("_silent_rounds") or 0)
    if silent_rounds >= 3:
        state_lines.append(f"- 💡 提示：已连续{silent_rounds}轮未记录互动，如本轮有值得记录的内容可补充上报")

    state_lines.extend(update_instruction)

    state_snapshot = "\n".join(state_lines)
    _state_max = max(1000, int(_budget.wi_max_chars() * 0.15))
    if len(state_snapshot) > _state_max:
        truncated_lines = state_lines[:6]
        truncated_lines.append("…（自定义变量已省略）")
        truncated_lines.extend(update_instruction)
        state_snapshot = "\n".join(truncated_lines)

    # ── 情感锚点 & 主动回忆注入 ──
    shared_moments = list(custom_vars.get("_shared_moments") or [])
    proactive_cared = False

    if shared_moments and last_chat_time:
        try:
            last_dt = datetime.fromisoformat(str(last_chat_time))
            hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if hours_since >= 24:
                anchor = random.choice(shared_moments[-5:])
                if card_type == "scenario":
                    proactive_text = (
                        f"【剧情回响】距离上一次互动已过去较长时间（{int(hours_since)}小时）。回忆起「{anchor}」，"
                        f"如果用户的问题与此相关，可以自然地引入这段经历。"
                    )
                else:
                    proactive_text = (
                        f"【背景提示】你已经很久没和用户聊天了（{int(hours_since)}小时）。想起「{anchor}」，你有点想念对方。"
                        f"但不要生硬地打断用户的问题——如果用户问了具体问题，先认真回答；"
                        f"如果用户只是打招呼或闲聊，可以自然地表达想念，如\"好久不见，最近怎么样？\"或\"想起{anchor}，就想和你聊聊\"。"
                    )
                existing_after = runtime_bundle.get("world_info_after") or ""
                runtime_bundle["world_info_after"] = (proactive_text + "\n\n" + existing_after).strip()
                proactive_cared = True
        except (ValueError, TypeError):
            pass

    if shared_moments and not proactive_cared:
        candidates = shared_moments[-5:]
        anchor = random.choice(candidates)
        if card_type == "scenario":
            anchor_text = (
                f"【共同回忆】{anchor}"
                f"（这段经历是你和用户之间的纽带，不需要刻意提及，但会影响你此刻的态度和情感色彩）"
            )
        else:
            anchor_text = (
                f"【共同回忆】{anchor}"
                f"（这是你和用户的共同回忆，会影响你此刻的情感基调。只有当话题自然关联时才提起，不要为了提起而提起）"
            )
        existing_after = runtime_bundle.get("world_info_after") or ""
        runtime_bundle["world_info_after"] = (anchor_text + "\n\n" + existing_after).strip()

    # 状态快照优先级最高：放在 world_info_after 最前面
    existing_after = runtime_bundle.get("world_info_after") or ""
    if existing_after:
        runtime_bundle["world_info_after"] = (state_snapshot + "\n\n" + existing_after).strip()
    else:
        runtime_bundle["world_info_after"] = state_snapshot


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
    last_chat_time: str | None = None,
    user_id: int | str | None = None,
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
    runtime_bundle, asset_type, card_type, char_name, char_id, _budget = _init_runtime_context(
        character, related_assets, user_name, budget,
    )

    # 阶段2：人生档案注入（仅对话陪伴）
    _inject_life_profile(runtime_bundle, character, card_type)

    # 阶段3：World Info 动态触发
    _resolve_world_info_triggers(conn, character, runtime_bundle, recent_messages, character_state, _budget)

    # 阶段4：后置规则注入
    _inject_post_history_rules(conn, char_id, runtime_bundle, character_state, _budget)

    # 阶段5：状态快照与情感锚点注入
    _inject_state_snapshot(conn, character, runtime_bundle, character_state, _budget, card_type, last_chat_time, user_id, char_id)

    # 阶段6：选择 builder 并构建最终 messages
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
