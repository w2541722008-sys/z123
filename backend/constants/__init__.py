"""
常量与枚举统一定义模块

项目规则：枚举常量只一处定义。
- Mood 以 character_state.py 的 9 种为准
- StoryPhase 统一为 Enum
"""

from constants.mood import Mood
from constants.story_phase import StoryPhase

__all__ = ["Mood", "StoryPhase"]
