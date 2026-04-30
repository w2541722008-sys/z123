"""
Mood 心情状态枚举

以 character_state.py 的 9 种为准，替代 models/character_config.py 中只有 4 种的旧版 Mood 枚举。
"""

from enum import Enum


class Mood(str, Enum):
    """心情状态枚举（9 种，与 character_state._VALID_MOODS 一致）。"""
    NEUTRAL = "neutral"      # 一般
    HAPPY = "happy"          # 开心
    WARM = "warm"            # 温暖
    MELTING = "melting"      # 融化
    COLD = "cold"            # 冷淡
    ANGRY = "angry"          # 生气
    SAD = "sad"              # 难过
    SHY = "shy"              # 害羞
    SURPRISED = "surprised"  # 惊讶
