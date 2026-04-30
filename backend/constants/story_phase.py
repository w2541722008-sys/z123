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
