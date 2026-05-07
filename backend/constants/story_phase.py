"""
StoryPhase 关系阶段枚举

统一 character_state.py 的 _VALID_STORY_PHASES 元组为标准 Enum。
"""

from enum import Enum


class StoryPhase(str, Enum):
    """关系阶段枚举（4 种，与 character_state._VALID_STORY_PHASES 一致）。"""
    STRANGER = "stranger"          # 陌生人
    ACQUAINTANCE = "acquaintance"  # 熟人
    FRIEND = "friend"              # 朋友
    LOVER = "lover"                # 恋人


# 关系阶段中文标签映射 — 对话陪伴
STORY_PHASE_LABELS: dict[str, str] = {
    StoryPhase.STRANGER.value: "陌生人",
    StoryPhase.ACQUAINTANCE.value: "普通朋友",
    StoryPhase.FRIEND.value: "好友",
    StoryPhase.LOVER.value: "恋人",
}

# 关系阶段中文标签映射 — 剧情沙盒（同一枚举值，不同展示语义）
SCENARIO_PHASE_LABELS: dict[str, str] = {
    StoryPhase.STRANGER.value: "初入",
    StoryPhase.ACQUAINTANCE.value: "探索",
    StoryPhase.FRIEND.value: "深入",
    StoryPhase.LOVER.value: "终章",
}

