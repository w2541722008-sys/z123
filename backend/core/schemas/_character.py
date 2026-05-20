"""角色相关模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from core.schemas._base import _validate_required_trimmed


class _CharacterIdPayload(BaseModel):
    character_id: str

    @field_validator('character_id')
    @classmethod
    def validate_character_id(cls, v: str) -> str:
        return _validate_required_trimmed(v, '角色ID不能为空')


class CharacterProfileUpdatePayload(_CharacterIdPayload):
    """更新用户对某个角色的个性化配置。"""
    remark: str = Field(default="", max_length=40)
    custom_signature: str = Field(default="", max_length=100)


class CharacterActionPayload(_CharacterIdPayload):
    """角色相关操作的通用请求体（只传角色 ID）。"""


class ClearChatPayload(_CharacterIdPayload):
    """
    清空聊天并重新选择剧情线入口。

    greeting_index：
      - None / -1 → 使用角色默认开场白
      - 0          → 同上
      - 1, 2, …   → alternate_greetings 列表下标
      - 也支持字符串格式的 DB 主键 ID
    """
    greeting_index: int | str = Field(default=-1)
