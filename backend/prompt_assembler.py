from __future__ import annotations

import json
from typing import Any

from card_text_utils import expand_macros


# ============================================================
# Prompt 编排层
# 说明：
# - 这里只处理"角色资产 + 关联资产 + 记忆 + 历史消息"如何组装成最终 messages
# - 不负责模型调用，也不负责数据库落库
# - 参考 SillyTavern 的思路：导卡格式可以多样，但运行时应收敛为少数清晰层位
# ============================================================
RECENT_MESSAGE_WINDOW = 12


# ============================================================
# Token 预算分配器
#
# 设计原则：
#   1. 完全 API 无关——只用字符数估算，不调用任何厂商 token 计数接口
#   2. 估算比例：1600 中文字符 ≈ 1000 tokens（= 0.625 token/字符）
#   3. 优先级分层（从高到低）：
#      [预留] post_history 提醒 + 最新用户消息（必须发送，先扣预算）
#      [高]   system prompt 各层（角色设定，硬上限保护）
#      [中]   长期记忆摘要（相对稳定，按需裁剪）
#      [低]   历史消息（从新到旧贪心填充，预算耗尽截止）
#      [可选] World Info 词条（全局预算 25%）
#
# 接入方式：
#   - 替换原来的 _LAYER_MAX_CHARS / _TOTAL_SYSTEM_MAX_CHARS 字数检查
#   - 各 builder 把 TokenBudget 实例传入，调用完整一致
# ============================================================

class TokenBudget:
    """基于字符数估算的 Token 预算分配器。

    参数：
        context_tokens  — 模型总上下文窗口（token 数），默认 64000（MiniMax-M2.5）
        output_reserve  — 预留给模型输出的 token，默认 2048
        chars_per_token — 字符/token 换算比，默认 1.6（即 1600 字 ≈ 1000 tokens）
    """

    # 各内容区块的预算占比（占「可用 token」的百分比）
    # 设计时留有余量，不追求 100% 填满，以免截断关键内容
    _SYSTEM_RATIO   = 0.55   # system prompt（含所有设定层）最多占 55%
    _MEMORY_RATIO   = 0.08   # 长期记忆摘要最多占 8%
    _HISTORY_RATIO  = 0.30   # 历史消息最多占 30%
    _RESERVE_RATIO  = 0.07   # 预留给 post_history 提醒 + 用户消息（至少 7%）

    def __init__(
        self,
        context_tokens: int = 64000,
        output_reserve: int = 2048,
        chars_per_token: float = 1.6,
    ) -> None:
        self.context_tokens = context_tokens
        self.output_reserve = output_reserve
        self.chars_per_token = chars_per_token
        # 实际可分配给 prompt 的 token 数
        self._available_tokens = max(context_tokens - output_reserve, 4000)

    # ── 单位换算 ──────────────────────────────────────────────
    def chars_to_tokens(self, chars: int) -> int:
        """字符数 → 估算 token 数（向上取整）。"""
        return max(1, int(chars / self.chars_per_token + 0.5))

    def tokens_to_chars(self, tokens: int) -> int:
        """token 数 → 估算字符数（向下取整，保守）。"""
        return max(1, int(tokens * self.chars_per_token))

    # ── 预算查询 ──────────────────────────────────────────────
    def system_max_chars(self) -> int:
        """system prompt 区块的最大字符数（55% 预算）。"""
        return self.tokens_to_chars(int(self._available_tokens * self._SYSTEM_RATIO))

    def memory_max_chars(self) -> int:
        """长期记忆摘要区块的最大字符数（8% 预算）。"""
        return self.tokens_to_chars(int(self._available_tokens * self._MEMORY_RATIO))

    def history_max_chars(self) -> int:
        """历史消息区块的最大字符数（30% 预算）。"""
        return self.tokens_to_chars(int(self._available_tokens * self._HISTORY_RATIO))

    def reserve_max_chars(self) -> int:
        """post_history + 用户消息的保留字符数（7% 预算，最小 800 字）。"""
        return max(800, self.tokens_to_chars(int(self._available_tokens * self._RESERVE_RATIO)))

    def single_layer_max_chars(self) -> int:
        """单个设定层的最大字符数（system 预算的 30%，防止一层把 system 撑爆）。"""
        return int(self.system_max_chars() * 0.30)

    def primary_system_max_chars(self) -> int:
        """primary_system_prompt 单独最大字符数（system 预算的 15%）。"""
        return int(self.system_max_chars() * 0.15)

    def wi_max_chars(self) -> int:
        """World Info 词条总注入量上限（全局可用 token 的 25%）。"""
        return self.tokens_to_chars(int(self._available_tokens * 0.25))

    def summary(self) -> dict:
        """返回各区块预算摘要（调试/日志用）。"""
        return {
            "context_tokens":       self.context_tokens,
            "available_tokens":     self._available_tokens,
            "system_max_chars":     self.system_max_chars(),
            "memory_max_chars":     self.memory_max_chars(),
            "history_max_chars":    self.history_max_chars(),
            "reserve_max_chars":    self.reserve_max_chars(),
            "single_layer_max":     self.single_layer_max_chars(),
            "primary_system_max":   self.primary_system_max_chars(),
            "wi_max_chars":         self.wi_max_chars(),
        }


# 默认预算实例（可在构造 messages 时传入自定义实例覆盖）
_DEFAULT_BUDGET = TokenBudget(context_tokens=64000, output_reserve=2048, chars_per_token=1.6)

# ── 向下兼容：保留旧的字符常量（部分代码可能直接引用），但值改为从默认预算派生 ──
# 这样即使还有地方用旧常量，数值也与新预算系统一致，不会出现两套标准打架
_LAYER_MAX_CHARS        = _DEFAULT_BUDGET.single_layer_max_chars()
_PRIMARY_SYSTEM_MAX_CHARS = _DEFAULT_BUDGET.primary_system_max_chars()
_TOTAL_SYSTEM_MAX_CHARS = _DEFAULT_BUDGET.system_max_chars()


# ============================================================
# 基础工具
# ============================================================
def parse_json_object(text: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    raw = (text or "").strip()
    if not raw:
        return dict(fallback)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return dict(fallback)
    return value if isinstance(value, dict) else dict(fallback)


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


# ============================================================
# 运行时装配
# ============================================================
def build_runtime_bundle(character: Any, related_assets: list[Any] | None = None) -> dict[str, Any]:
    """把主角色与关联资产合成为一份统一运行时视图。

    当前策略：
    - 主资产决定主模式（character / hybrid / world / scenario ...）
    - world/system 资产补充世界规则与系统约束
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
        # world_info_before：常驻，注入在角色设定之前（世界观/背景，优先级最高）
        # world_info_after：常驻，注入在角色设定之后（补充规则/随机事件）
        # conditional_entries：条件触发词条列表，运行时按关键词动态注入
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

        if asset_type in {"world", "system"}:
            bundle["world_rules"] = _merge_text(bundle["world_rules"], asset_layers.get("base_profile"), asset_layers.get("world_rules"))
            bundle["scenario"] = _merge_text(bundle["scenario"], asset_layers.get("scenario"))
            bundle["post_history_rules"] = _merge_text(bundle["post_history_rules"], asset_layers.get("post_history_rules"))
            bundle["examples"] = _merge_text(bundle["examples"], asset_layers.get("examples"))
            bundle["alternate_greetings"] = _merge_alternate_greetings(bundle["alternate_greetings"], asset_layers.get("alternate_greetings"))
            continue

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

    return bundle


# ⚠️ 注意：以下常量仅保留名称用于向下兼容，值已统一从 _DEFAULT_BUDGET 派生（见文件顶部）。
# 不要在这里硬编码数字！修改预算请去 TokenBudget 类或 _DEFAULT_BUDGET 实例。
# _LAYER_MAX_CHARS        → _DEFAULT_BUDGET.single_layer_max_chars()    ≈ 16354 字
# _PRIMARY_SYSTEM_MAX_CHARS → _DEFAULT_BUDGET.primary_system_max_chars() ≈ 8177 字
# _TOTAL_SYSTEM_MAX_CHARS  → _DEFAULT_BUDGET.system_max_chars()          ≈ 54517 字


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


def _build_character_mode_messages(
    runtime_bundle: dict[str, Any],
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    recent_message_window: int,
    budget: "TokenBudget | None" = None,
) -> list[dict[str, str]]:
    """character 模式：把所有设定层合并成单条 system，再追加历史消息。

    World Info 注入顺序（对应 SillyTavern 规范）：
      world_info_before → 主 prompt + 角色设定层 → world_info_after
    """
    messages: list[dict[str, str]] = []
    depth_prompt = runtime_bundle.get("depth_prompt")
    history, last_user_msg = _split_last_user_message(recent_messages)

    # World Info: before_char（世界观/背景，最高优先级，放在最前）
    wi_before = (runtime_bundle.get("world_info_before") or "").strip()
    # World Info: after_char（补充规则/随机事件，放在设定层最后）
    wi_after = (runtime_bundle.get("world_info_after") or "").strip()

    # 合并所有设定层为单条 system（兼容 MiniMax 等只允许一条 system 的 API）
    layers = [
        (_related_assets_text(runtime_bundle), ""),           # 关联资产（已是完整标题文本）
        ("【角色底稿】", runtime_bundle.get("base_profile") or _get_field(character, "description", "")),
        ("【性格与表达风格】", runtime_bundle.get("personality") or ""),
        ("【当前关系与场景】", runtime_bundle.get("scenario") or ""),
        ("【世界规则/补充设定】", runtime_bundle.get("world_rules") or ""),
        ("【示例对话风格参考】", runtime_bundle.get("examples") or ""),
        ("【备用开场参考】", _alternate_samples_text(runtime_bundle.get("alternate_greetings") or [])),
    ]
    # 构建 (title, content) 列表传给 _build_single_system_prompt
    layer_pairs: list[tuple[str, str]] = []
    # world_info_before 插最前
    if wi_before:
        layer_pairs.append(("【世界信息-前置】", wi_before))
    for title, content in layers:
        if title and not content:
            # _related_assets_text 等已经是完整文本，直接当 content，title 为空
            if title.strip():
                layer_pairs.append(("", title))  # title 实际上就是完整内容
        elif content:
            layer_pairs.append((title, content))
    # world_info_after 插最后
    if wi_after:
        layer_pairs.append(("【世界信息-后置】", wi_after))

    primary = runtime_bundle.get("primary_system_prompt") or _get_field(character, "system_prompt", "")
    system_text = _build_single_system_prompt(primary, layer_pairs, budget=budget)
    if system_text:
        messages.append({"role": "system", "content": system_text})

    _append_memory_and_history(messages, memory_summary, history, recent_message_window, depth_prompt=depth_prompt, budget=budget)
    _append_post_history_then_user(messages, runtime_bundle.get("post_history_rules") or "", last_user_msg, budget=budget)
    return messages


def _build_system_mode_messages(
    runtime_bundle: dict[str, Any],
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    recent_message_window: int,
    budget: "TokenBudget | None" = None,
) -> list[dict[str, str]]:
    """system/world 模式：把设定层合并为单条 system。

    World Info 注入：world_info_before 最前，world_info_after 最后。
    """
    messages: list[dict[str, str]] = []
    depth_prompt = runtime_bundle.get("depth_prompt")
    history, last_user_msg = _split_last_user_message(recent_messages)

    wi_before = (runtime_bundle.get("world_info_before") or "").strip()
    wi_after = (runtime_bundle.get("world_info_after") or "").strip()

    related_text = _related_assets_text(runtime_bundle)
    layer_pairs: list[tuple[str, str]] = []
    if wi_before:
        layer_pairs.append(("【世界信息-前置】", wi_before))
    if related_text:
        layer_pairs.append(("", related_text))
    for title, content in [
        ("【核心系统设定】", runtime_bundle.get("base_profile") or _get_field(character, "description", "")),
        ("【世界规则/补充设定】", runtime_bundle.get("world_rules") or ""),
        ("【当前剧情场景】", runtime_bundle.get("scenario") or ""),
        ("【示例对话风格参考】", runtime_bundle.get("examples") or ""),
    ]:
        if content:
            layer_pairs.append((title, content))
    alt_text = _alternate_samples_text(runtime_bundle.get("alternate_greetings") or [])
    if alt_text:
        layer_pairs.append(("", alt_text))
    if wi_after:
        layer_pairs.append(("【世界信息-后置】", wi_after))

    primary = runtime_bundle.get("primary_system_prompt") or _get_field(character, "system_prompt", "")
    system_text = _build_single_system_prompt(primary, layer_pairs, budget=budget)
    if system_text:
        messages.append({"role": "system", "content": system_text})

    _append_memory_and_history(messages, memory_summary, history, recent_message_window, depth_prompt=depth_prompt, budget=budget)
    _append_post_history_then_user(messages, runtime_bundle.get("post_history_rules") or "", last_user_msg, budget=budget)
    return messages


def _build_scenario_mode_messages(
    runtime_bundle: dict[str, Any],
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    recent_message_window: int,
    budget: "TokenBudget | None" = None,
) -> list[dict[str, str]]:
    """scenario 模式：把设定层合并为单条 system。

    World Info 注入：world_info_before 最前，world_info_after 最后。
    """
    messages: list[dict[str, str]] = []
    depth_prompt = runtime_bundle.get("depth_prompt")
    history, last_user_msg = _split_last_user_message(recent_messages)

    wi_before = (runtime_bundle.get("world_info_before") or "").strip()
    wi_after = (runtime_bundle.get("world_info_after") or "").strip()

    related_text = _related_assets_text(runtime_bundle)
    layer_pairs: list[tuple[str, str]] = []
    if wi_before:
        layer_pairs.append(("【世界信息-前置】", wi_before))
    if related_text:
        layer_pairs.append(("", related_text))
    for title, content in [
        ("【剧情入口/背景】", runtime_bundle.get("base_profile") or _get_field(character, "description", "")),
        ("【当前剧情场景】", runtime_bundle.get("scenario") or ""),
        ("【世界规则/补充设定】", runtime_bundle.get("world_rules") or ""),
        ("【示例对话风格参考】", runtime_bundle.get("examples") or ""),
    ]:
        if content:
            layer_pairs.append((title, content))
    alt_text = _alternate_samples_text(runtime_bundle.get("alternate_greetings") or [])
    if alt_text:
        layer_pairs.append(("", alt_text))
    if wi_after:
        layer_pairs.append(("【世界信息-后置】", wi_after))

    primary = runtime_bundle.get("primary_system_prompt") or _get_field(character, "system_prompt", "")
    system_text = _build_single_system_prompt(primary, layer_pairs, budget=budget)
    if system_text:
        messages.append({"role": "system", "content": system_text})

    _append_memory_and_history(messages, memory_summary, history, recent_message_window, depth_prompt=depth_prompt, budget=budget)
    _append_post_history_then_user(messages, runtime_bundle.get("post_history_rules") or "", last_user_msg, budget=budget)
    return messages


def _build_hybrid_mode_messages(
    runtime_bundle: dict[str, Any],
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    recent_message_window: int,
    budget: "TokenBudget | None" = None,
) -> list[dict[str, str]]:
    """hybrid 模式：把设定层合并为单条 system。

    World Info 注入：world_info_before 最前，world_info_after 最后。
    """
    messages: list[dict[str, str]] = []
    depth_prompt = runtime_bundle.get("depth_prompt")
    history, last_user_msg = _split_last_user_message(recent_messages)

    wi_before = (runtime_bundle.get("world_info_before") or "").strip()
    wi_after = (runtime_bundle.get("world_info_after") or "").strip()

    related_text = _related_assets_text(runtime_bundle)
    layer_pairs: list[tuple[str, str]] = []
    if wi_before:
        layer_pairs.append(("【世界信息-前置】", wi_before))
    if related_text:
        layer_pairs.append(("", related_text))
    for title, content in [
        ("【角色底稿】", runtime_bundle.get("base_profile") or _get_field(character, "description", "")),
        ("【性格与表达风格】", runtime_bundle.get("personality") or ""),
        ("【当前关系与剧情场景】", runtime_bundle.get("scenario") or ""),
        ("【世界规则/补充设定】", runtime_bundle.get("world_rules") or ""),
        ("【示例对话风格参考】", runtime_bundle.get("examples") or ""),
    ]:
        if content:
            layer_pairs.append((title, content))
    alt_text = _alternate_samples_text(runtime_bundle.get("alternate_greetings") or [])
    if alt_text:
        layer_pairs.append(("", alt_text))
    if wi_after:
        layer_pairs.append(("【世界信息-后置】", wi_after))

    primary = runtime_bundle.get("primary_system_prompt") or _get_field(character, "system_prompt", "")
    system_text = _build_single_system_prompt(primary, layer_pairs, budget=budget)
    if system_text:
        messages.append({"role": "system", "content": system_text})

    _append_memory_and_history(messages, memory_summary, history, recent_message_window, depth_prompt=depth_prompt, budget=budget)
    _append_post_history_then_user(messages, runtime_bundle.get("post_history_rules") or "", last_user_msg, budget=budget)
    return messages


def _expand_bundle_macros(bundle: dict[str, Any], char_name: str, user_name: str) -> dict[str, Any]:
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


# ============================================================
# World Info 运行时关键词触发
# ============================================================
# 以下两个值从默认 budget 派生，避免与 TokenBudget 系统脱节：
# - 单次触发上限：wi_max_chars() / 平均词条长(500字) ≈ 49 条；但考虑 prompt 膨胀风险，
#   用固定上限 12 条作为安全阈值（比旧的 8 条宽松一些，但不至于失控）
# - 单条最大字符：wi_max_chars() 的 5%，与 budget 联动，避免一条词条吞掉所有 WI 预算
def _wi_max_triggered(budget: "TokenBudget | None" = None) -> int:
    """单次触发条目上限（从 budget 派生）。"""
    b = budget or _DEFAULT_BUDGET
    # wi_max_chars() / 500字(每条平均) 即最多能放几条，但不超过 20 条保底上限
    return min(20, max(4, b.wi_max_chars() // 500))


def _wi_max_chars_per_entry(budget: "TokenBudget | None" = None) -> int:
    """单条词条最大字符数（从 budget 派生）。"""
    b = budget or _DEFAULT_BUDGET
    # wi_max_chars() 的 5%，但不低于 300 字（过短的词条失去意义）
    return max(300, b.wi_max_chars() // 20)


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


def get_character_memories_from_db(
    character_id: str,
    context_text: str,
    budget: "TokenBudget | None" = None,
) -> tuple[list[str], list[str]]:
    """
    从数据库查询角色的记忆条目，并根据上下文文本匹配关键词。
    
    参数：
        character_id: 角色ID
        context_text: 用于匹配的上下文文本（用户最新消息 + 最近对话）
        budget: TokenBudget 实例，用于控制返回的条目数量和长度
    
    返回：
        (before_list, after_list) - 分别对应 position='before' 和 'after' 的匹配内容列表
    """
    # 延迟导入，避免循环依赖
    from database import get_conn
    
    conn = get_conn()
    try:
        # 获取所有启用的记忆条目
        rows = conn.execute(
            """
            SELECT keywords, trigger_logic, content, position, priority
            FROM character_memories
            WHERE character_id = %s AND is_active = 1
            ORDER BY priority ASC, id ASC
            """,
            (character_id,),
        ).fetchall()
        
        if not rows or not context_text:
            return [], []
        
        max_triggered = _wi_max_triggered(budget)
        max_per_entry = _wi_max_chars_per_entry(budget)
        wi_max = (budget or _DEFAULT_BUDGET).wi_max_chars()
        
        ctx_lower = context_text.lower()
        triggered = []
        
        for row in rows:
            keywords = [k.strip().lower() for k in row["keywords"].split(",") if k.strip()]
            if not keywords:
                continue
            
            trigger_logic = row["trigger_logic"] or "any"
            matched = []
            
            if trigger_logic == "all":
                # 所有关键词都必须匹配
                if all(kw in ctx_lower for kw in keywords):
                    matched = keywords
            else:
                # 任意关键词匹配
                matched = [kw for kw in keywords if kw in ctx_lower]
            
            if matched:
                triggered.append({
                    "content": row["content"],
                    "position": row["position"] or "before",
                    "priority": row["priority"] or 100,
                })
        
        # 按优先级排序并限制数量
        triggered.sort(key=lambda e: e["priority"])
        triggered = triggered[:max_triggered]
        
        before_list = []
        after_list = []
        wi_used = 0
        
        for entry in triggered:
            content = entry["content"].strip()
            if not content:
                continue
            
            # 截断过长的内容
            if len(content) > max_per_entry:
                content = content[:max_per_entry].rstrip() + "\n…（内容已截断）"
            
            # 检查 WI 预算
            if wi_used + len(content) > wi_max:
                break
            
            wi_used += len(content)
            
            if entry["position"] == "after":
                after_list.append(content)
            else:
                before_list.append(content)
        
        return before_list, after_list
    finally:
        conn.close()


def get_character_post_rules_from_db(
    character_id: str,
    storyline_id: int | None = None,
    story_phase: str | None = None,
    budget: "TokenBudget | None" = None,
) -> list[str]:
    """
    从数据库查询角色的后置规则。
    
    后置规则在 AI 回复后应用，用于控制输出格式、过滤内容等。
    支持按剧情线和关系阶段过滤。
    
    参数：
        character_id: 角色ID
        storyline_id: 当前剧情线ID（可选，用于过滤）
        story_phase: 当前关系阶段（可选，用于过滤）
        budget: TokenBudget 实例，用于控制返回的规则长度
    
    返回：
        匹配的后置规则内容列表（已按优先级排序）
    """
    # 延迟导入，避免循环依赖
    from database import get_conn
    
    conn = get_conn()
    try:
        # 构建查询条件
        conditions = ["character_id = %s", "is_active = 1"]
        params: list[Any] = [character_id]

        #  storyline_id 过滤：规则未指定 storyline_id（通用）或匹配当前 storyline_id
        if storyline_id is not None:
            conditions.append("(storyline_id IS NULL OR storyline_id = %s)")
            params.append(storyline_id)

        # story_phase 过滤：规则未指定 story_phase（通用，NULL或空字符串）或匹配当前 story_phase
        if story_phase:
            conditions.append("(story_phase IS NULL OR story_phase = '' OR story_phase = %s)")
            params.append(story_phase)
        
        where_clause = " AND ".join(conditions)
        
        rows = conn.execute(
            f"""
            SELECT content, priority
            FROM character_post_rules
            WHERE {where_clause}
            ORDER BY priority ASC, id ASC
            """,
            tuple(params),
        ).fetchall()
        
        if not rows:
            return []
        
        # 计算预算限制
        max_chars = budget.reserve_max_chars() if budget is not None else _LAYER_MAX_CHARS
        
        rules = []
        total_chars = 0
        
        for row in rows:
            content = row["content"].strip()
            if not content:
                continue
            
            # 检查是否超出预算
            if total_chars + len(content) > max_chars:
                # 尝试截断最后一条
                remaining = max_chars - total_chars
                if remaining > 100:  # 至少保留100字符
                    rules.append(content[:remaining].rstrip() + "\n…（内容已截断）")
                break
            
            total_chars += len(content)
            rules.append(content)
        
        return rules
    finally:
        conn.close()


def build_layered_chat_messages(
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str = "",
    recent_message_window: int = RECENT_MESSAGE_WINDOW,
    related_assets: list[Any] | None = None,
    user_name: str = "",
    character_state: dict | None = None,
    budget: "TokenBudget | None" = None,
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
    db_before, db_after = get_character_memories_from_db(char_id, ctx_text, budget=_budget)
    
    # 2. 从角色卡解析的 conditional_entries（兼容旧的角色卡导入）
    conditional_entries = runtime_bundle.get("conditional_entries") or []
    card_before, card_after = [], []
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
    db_post_rules = get_character_post_rules_from_db(
        char_id,
        storyline_id=character_state.get("storyline_id") if character_state else None,
        story_phase=character_state.get("story_phase") if character_state else None,
        budget=_budget,
    )
    
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
        _story_phase_labels = {
            "stranger": "陌生人",
            "acquaintance": "普通朋友",
            "friend": "好友",
            "lover": "恋人",
        }
        _mood_labels = {
            "neutral": "平静",
            "happy": "开心",
            "warm": "温柔",
            "melting": "心动",
            "cold": "冷淡",
            "angry": "生气",
            "sad": "难过",
            "shy": "害羞",
            "surprised": "惊讶",
        }
        affection = character_state.get("affection", 30)
        phase = character_state.get("story_phase", "stranger")
        mood = character_state.get("mood", "neutral")
        phase_label = _story_phase_labels.get(phase, phase)
        mood_label = _mood_labels.get(mood, mood)
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

        state_lines.extend([
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
            "可用心情值：neutral / happy / warm / melting / cold / angry / sad / shy / surprised",
            "关系阶段仅在里程碑时填写（story_phase），平时省略：stranger→acquaintance→friend→lover",
            "",
            "示例：",
            "  [STATE_UPDATE]{\"event\":\"deep_conversation\",\"mood\":\"warm\"}[/STATE_UPDATE]",
            "  [STATE_UPDATE]{\"event\":\"argument\",\"mood\":\"cold\",\"story_phase\":\"stranger\"}[/STATE_UPDATE]",
            "  若本轮无特殊互动，不需要输出标签。",
        ])

        state_snapshot = "\n".join(state_lines)
        # 状态快照字数保护：上限为 WI 预算的 15%，但保证至少 1000 字符
        # 状态快照对角色行为影响重大，需要保证完整性
        _state_max = max(1000, int(_budget.wi_max_chars() * 0.15))
        if len(state_snapshot) > _state_max:
            # 优先截断自定义变量部分，保留核心状态信息
            truncated_lines = state_lines[:6]  # 保留标题和核心状态（好感度、阶段、心情）
            truncated_lines.append("…（自定义变量已省略）")
            truncated_lines.extend(state_lines[state_lines.index("【状态更新指令（重要）】"):])  # 保留指令部分
            state_snapshot = "\n".join(truncated_lines)
        
        # 状态快照优先级最高：放在 world_info_after 的最前面
        # 这样即使 world_info_after 被截断，状态快照也能保留
        existing_after = runtime_bundle.get("world_info_after") or ""
        if existing_after:
            runtime_bundle["world_info_after"] = (state_snapshot + "\n\n" + existing_after).strip()
        else:
            runtime_bundle["world_info_after"] = state_snapshot

    # ── 产品层 card_type 路由（优先级高于 asset_type）─────────────────────
    # card_type 是产品侧手动标注，语义比导卡自动解析的 asset_type 更可靠
    _card_type_builders = {
        "scenario": _build_scenario_mode_messages,  # 旁白+NPC+状态机
        "world":    _build_system_mode_messages,    # 纯知识库，不扮演角色
        # intimate: 不强制，走下方 asset_type 路由
    }
    if card_type in _card_type_builders:
        builder = _card_type_builders[card_type]
        return builder(runtime_bundle, character, recent_messages, memory_summary, recent_message_window, budget=_budget)

    # ── 导卡层 asset_type 路由（intimate / 未标注 card_type 时走这里）──────
    builders = {
        "character": _build_character_mode_messages,
        "system": _build_system_mode_messages,
        "scenario": _build_scenario_mode_messages,
        "world": _build_system_mode_messages,
        "hybrid": _build_hybrid_mode_messages,
    }
    builder = builders.get(asset_type, _build_hybrid_mode_messages)
    return builder(runtime_bundle, character, recent_messages, memory_summary, recent_message_window, budget=_budget)


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
