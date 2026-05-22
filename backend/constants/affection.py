"""好感度系统业务常量 — 规则表、冷却时间、阈值等纯数据。

从 services/character_affection.py 提取，消除跨模块私有符号泄漏。
"""

# 对话陪伴 + 冒险剧情共用的基础事件好感度
AFFECTION_BASE_RULES: dict[str, int] = {
    "deep_conversation": 4, "light_chat": 1, "compliment": 2, "gift": 6,
    "help": 3, "shared_secret": 5, "first_meeting": 3, "comfort": 3,
    "flirt": 2, "date": 5, "confession": 10, "intimate_moment": 6,
    "argument": -5, "rude": -3, "ignore": -2, "lie": -4, "betray": -8, "insult": -6,
}

# 各事件冷却时间（秒）
AFFECTION_COOLDOWN_SECONDS: dict[str, int] = {
    "deep_conversation": 3600, "light_chat": 300, "compliment": 1800, "gift": 86400,
    "help": 3600, "shared_secret": 7200, "first_meeting": 604800, "comfort": 1800,
    "argument": 3600, "rude": 1800, "ignore": 1800, "lie": 3600, "betray": 604800, "insult": 3600,
    "explore": 300, "discover": 1800, "problem_resolved": 86400, "challenge_won": 3600,
    "obstacle_cleared": 604800, "choice_made": 7200, "npc_helped": 3600,
    "secret_found": 86400, "milestone": 43200, "setback": 1800,
    "unexpected_danger": 1200, "relationship_lost": 86400, "opportunity_missed": 3600,
    "flirt": 1200, "date": 43200, "first_hug": 604800, "kiss": 604800, "confession": 604800,
    "intimate_moment": 86400, "jealousy": 3600, "misunderstanding": 7200, "reconciliation": 86400,
    "love_rival_appears": 604800, "heartfelt_talk": 3600, "surprise_gift": 86400,
}

# 好感度衰减系数（第四次及以后同类事件不再累加）
AFFECTION_DIMINISHING_RETURNS: list[float] = [1.0, 0.6, 0.3, 0.0]

# 默认每日好感度上限（daily_cap=0 表示不限制，适合剧情沙盒角色）
DAILY_AFFECTION_CAP_DEFAULT = 15

# 好感度阶段阈值
PHASE_THRESHOLDS: dict[str, int] = {"acquaintance": 20, "friend": 50, "lover": 80}

# 各阶段好感度增长倍率
PHASE_GAIN_MULTIPLIER: dict[str, float] = {
    "stranger": 1.0, "acquaintance": 0.8, "friend": 0.6, "lover": 0.4,
}

# 单次事件好感度最大变化值
AFFECTION_DELTA_MAX = 10

# 旧事件名→新事件名迁移映射（向后兼容：运营自定义规则中可能仍使用旧名）
EVENT_NAME_MIGRATION: dict[str, str] = {
    "battle_won": "challenge_won",
    "boss_defeated": "obstacle_cleared",
    "battle_lost": "setback",
    "trap_triggered": "unexpected_danger",
    "puzzle_solved": "problem_resolved",
    "ally_lost": "relationship_lost",
    "clue_missed": "opportunity_missed",
    "chat": "light_chat",
    "deep_talk": "deep_conversation",
    "intimate": "intimate_moment",
    "cold": "ignore",
}
