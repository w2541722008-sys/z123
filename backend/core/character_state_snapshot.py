"""
CharacterStateSnapshot — 角色状态的类型化数据对象。

替代 get_character_state() 返回的 13-key 裸字典，终结 character_state.py
中 6 个 handler 函数的参数膨胀问题（当前最多 12 个参数）。

这是一个纯数据对象（dataclass），不是 Pydantic model — 它不参与 API 序列化，
只在 service 层内部传递。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CharacterStateSnapshot:
    """用户与角色的关系状态快照。

    包含公开状态（好感度、阶段、心情、自定义变量）和内部计数器（每日统计）。
    handler 流水线直接在 snapshot 上修改字段，不再需要 5+ 个独立变量传递。
    """

    user_id: int | str
    character_id: str

    # 公开状态
    affection: int = 0
    story_phase: str = "stranger"
    mood: str = "neutral"
    custom_vars: dict[str, Any] = field(default_factory=dict)
    storyline_id: int | None = None

    # 内部计数器（_ 前缀表示由服务层管理，不暴露给外部）
    daily_event_counts: dict[str, Any] = field(default_factory=dict)
    daily_affection_gained: int = 0
    last_event_timestamps: dict[str, Any] = field(default_factory=dict)
    daily_reset_date: str = ""

    # 瞬态字段（不持久化，仅在 handler 流水线中使用）
    old_phase: str = ""  # 阶段变更前的值，用于升级通知比较
    triggered_events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转为旧版 dict，兼容仍在使用字典的外部调用方。"""
        return {
            "affection": self.affection,
            "story_phase": self.story_phase,
            "mood": self.mood,
            "custom_vars": self.custom_vars,
            "storyline_id": self.storyline_id,
            "_daily_event_counts": self.daily_event_counts,
            "_daily_affection_gained": self.daily_affection_gained,
            "_last_event_timestamps": self.last_event_timestamps,
            "_daily_reset_date": self.daily_reset_date,
        }

    @classmethod
    def from_legacy_dict(
        cls, d: dict[str, Any], user_id: int | str, character_id: str
    ) -> "CharacterStateSnapshot":
        """从 get_character_state() 返回的旧版字典构建快照。"""
        return cls(
            user_id=user_id,
            character_id=character_id,
            affection=int(d.get("affection") or 0),
            story_phase=str(d.get("story_phase") or "stranger"),
            mood=str(d.get("mood") or "neutral"),
            custom_vars=dict(d.get("custom_vars") or {}),
            storyline_id=d.get("storyline_id"),
            daily_event_counts=dict(d.get("_daily_event_counts") or {}),
            daily_affection_gained=int(d.get("_daily_affection_gained") or 0),
            last_event_timestamps=dict(d.get("_last_event_timestamps") or {}),
            daily_reset_date=str(d.get("_daily_reset_date") or ""),
        )
