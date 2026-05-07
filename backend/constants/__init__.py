"""
常量与枚举统一定义模块

项目规则：枚举常量只一处定义。
- Mood 以 character_state.py 的 9 种为准
- StoryPhase 统一为 Enum
"""

from constants.mood import Mood, MOOD_LABELS, SCENARIO_MOOD_LABELS
from constants.story_phase import StoryPhase, STORY_PHASE_LABELS, SCENARIO_PHASE_LABELS

__all__ = [
    "Mood", "MOOD_LABELS", "SCENARIO_MOOD_LABELS",
    "StoryPhase", "STORY_PHASE_LABELS", "SCENARIO_PHASE_LABELS",
]
