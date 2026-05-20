"""记忆（World Info）相关模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.schemas._base import (
    _OptionalCategoryIdPayload,
    _PriorityActivePayload,
    _SortOrderPayload,
)


class MemoryEntryPayload(_OptionalCategoryIdPayload, _PriorityActivePayload):
    """记忆条目（World Info）请求体。"""
    keywords: str = Field(min_length=1, max_length=500)
    trigger_logic: str = Field(default="any", pattern="^(any|all)$")
    content: str = Field(min_length=1, max_length=4000)
    position: str = Field(default="before", pattern="^(before|after)$")
    comment: str = Field(default="", max_length=200)
    selective: int = Field(default=1, ge=0, le=1)
    constant: int = Field(default=0, ge=0, le=1)
    sticky: int = Field(default=0, ge=0, le=999)
    cooldown: int = Field(default=0, ge=0, le=999)


class MemoryCategoryPayload(_SortOrderPayload):
    """记忆分类请求体。"""
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=500)
    color: str = Field(default="#1890FF", max_length=7)
