"""
标签提供器 - 封装心情和关系阶段的标签获取逻辑

职责：
- 根据卡片类型（对话陪伴 vs 剧情沙盒）返回对应的标签
- 消除业务逻辑在常量层的泄漏
"""

from constants.mood import Mood, MOOD_LABELS, SCENARIO_MOOD_LABELS
from constants.story_phase import StoryPhase, STORY_PHASE_LABELS, SCENARIO_PHASE_LABELS


def get_mood_label(mood: Mood | str, *, is_scenario: bool = False) -> str:
    """获取心情标签。

    Args:
        mood: 心情枚举值或字符串
        is_scenario: 是否为剧情沙盒卡

    Returns:
        对应的中文标签
    """
    mood_value = mood.value if isinstance(mood, Mood) else mood
    labels = SCENARIO_MOOD_LABELS if is_scenario else MOOD_LABELS
    return labels.get(mood_value, "未知")


def get_story_phase_label(phase: StoryPhase | str, *, is_scenario: bool = False) -> str:
    """获取关系阶段标签。

    Args:
        phase: 关系阶段枚举值或字符串
        is_scenario: 是否为剧情沙盒卡

    Returns:
        对应的中文标签
    """
    phase_value = phase.value if isinstance(phase, StoryPhase) else phase
    labels = SCENARIO_PHASE_LABELS if is_scenario else STORY_PHASE_LABELS
    return labels.get(phase_value, "未知")
