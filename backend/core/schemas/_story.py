"""剧情/故事线/事件相关模型。"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

from constants.mood import Mood
from constants.story_phase import StoryPhase
from core.schemas._base import (
    _OptionalStorylineIdPayload,
    _OptionalUnlockedStorylineIdPayload,
    _PriorityActivePayload,
    _SortOrderActivePayload,
)

_MOOD_PATTERN = "^(" + "|".join(m.value for m in Mood) + ")$"
_STORY_PHASE_PATTERN = "^(" + "|".join(sp.value for sp in StoryPhase) + ")$"


class GreetingPayload(_OptionalStorylineIdPayload, _PriorityActivePayload):
    """多阶段开场白请求体。"""
    content: str = Field(min_length=1, max_length=2000)
    story_phase: str = Field(default="stranger", pattern=_STORY_PHASE_PATTERN)
    mood: str = Field(default="neutral", pattern=_MOOD_PATTERN)
    comment: str = Field(default="", max_length=200)


class StorylinePayload(_SortOrderActivePayload):
    """剧情线请求体。"""
    storyline_id: str = Field(default="", max_length=100)
    title: str = Field(default="", max_length=100)
    name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=500)
    unlock_score: int = Field(default=0, ge=0)
    unlock_condition: str | None = Field(default=None, max_length=500)
    stages: list[str] = Field(default_factory=list)
    is_default: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def _fill_defaults(self) -> "StorylinePayload":
        """title 和 name 互为 fallback，storyline_id 未设则自动生成。"""
        if not self.title and self.name:
            self.title = self.name
        if not self.name and self.title:
            self.name = self.title
        if not self.title and not self.name:
            raise ValueError("title 和 name 至少填一个")
        if not self.storyline_id:
            self.storyline_id = re.sub(r"[^a-zA-Z0-9_]", "", self.name.replace(" ", "_").lower()) or "auto"
        return self


class KeywordTestPayload(BaseModel):
    """关键词测试请求体。"""
    text: str = Field(min_length=1, max_length=2000)


class PostRulePayload(_OptionalStorylineIdPayload, _PriorityActivePayload):
    """后置规则请求体。"""
    name: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=5000)
    story_phase: str | None = Field(default=None)


class StoryEventPayload(_OptionalUnlockedStorylineIdPayload, _SortOrderActivePayload):
    """剧情事件请求体。"""
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)
    trigger_score: int = Field(default=0, ge=0)
    trigger_custom_key: str = Field(default="", max_length=500)
    unlocked_memory_ids: str = Field(default="", max_length=500)
    unlocked_greeting_ids: str = Field(default="", max_length=500)
    event_content: str = Field(default="", max_length=5000)
