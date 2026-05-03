"""
Token 预算分配器 - 基于 Token 预算控制 Prompt 各区块的大小

设计原则：
  1. 完全 API 无关——只用字符数估算，不调用任何厂商 token 计数接口
  2. 估算比例：1600 中文字符 ≈ 1000 tokens（= 0.625 token/字符）
  3. 优先级分层（从高到低）：
     [预留] post_history 提醒 + 最新用户消息（必须发送，先扣预算）
     [高]   system prompt 各层（角色设定，硬上限保护）
     [中]   长期记忆摘要（相对稳定，按需裁剪）
     [低]   历史消息（从新到旧贪心填充，预算耗尽截止）
     [可选] World Info 词条（全局预算 25%）

从 prompt_assembler.py 拆分而来，消除该文件的多职责问题。
"""
from __future__ import annotations


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

    def summary(self) -> dict[str, int | float]:
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
DEFAULT_BUDGET = TokenBudget(context_tokens=64000, output_reserve=2048, chars_per_token=1.6)

# ── 向下兼容：保留旧的字符常量别名 ──
# 注意：这些常量是 DEFAULT_BUDGET 的别名，新增代码应直接使用 DEFAULT_BUDGET.xxx() 方法。
LAYER_MAX_CHARS        = DEFAULT_BUDGET.single_layer_max_chars()
PRIMARY_SYSTEM_MAX_CHARS = DEFAULT_BUDGET.primary_system_max_chars()
TOTAL_SYSTEM_MAX_CHARS = DEFAULT_BUDGET.system_max_chars()


def wi_max_triggered(budget: TokenBudget | None = None) -> int:
    """单次 World Info 触发条目上限（从 budget 派生）。"""
    b = budget or DEFAULT_BUDGET
    # wi_max_chars() / 500字(每条平均) 即最多能放几条，但不超过 20 条保底上限
    return min(20, max(4, b.wi_max_chars() // 500))


def wi_max_chars_per_entry(budget: TokenBudget | None = None) -> int:
    """单条 World Info 词条最大字符数（从 budget 派生）。"""
    b = budget or DEFAULT_BUDGET
    # wi_max_chars() 的 5%，但不低于 300 字（过短的词条失去意义）
    return max(300, b.wi_max_chars() // 20)
