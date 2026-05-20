"""聊天相关模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from core.schemas._base import _strip_text, _validate_required_trimmed
from core.schemas._character import _CharacterIdPayload


class ChatSendPayload(_CharacterIdPayload):
    """发送聊天消息的请求体。"""
    message: str = Field(min_length=1, max_length=2000)

    @field_validator('message')
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = _validate_required_trimmed(v, '消息不能为空')
        if len(v) > 2000:
            raise ValueError('消息不能超过2000字符')
        return v


class GuestMessageItem(BaseModel):
    """游客前端临时历史消息条目（不存库，仅用于单次上下文）。"""
    role: str
    content: str = Field(min_length=1, max_length=2000)

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ('user', 'assistant'):
            raise ValueError('role 必须是 user 或 assistant')
        return v

    @field_validator('content')
    @classmethod
    def validate_content(cls, v: str) -> str:
        return _strip_text(v)


class GuestChatPayload(_CharacterIdPayload):
    """游客试聊接口请求体。不需要 token，不存消息，只做一次 AI 调用。"""
    message: str = Field(min_length=1, max_length=500)
    guest_history: list[GuestMessageItem] = Field(default_factory=list, max_length=10)


class MergeGuestHistoryPayload(_CharacterIdPayload):
    """游客登录后将聊天历史合并到用户账号。"""
    messages: list[GuestMessageItem] = Field(default_factory=list, max_length=50)


class _MessageIdPayload(BaseModel):
    message_id: str = Field(min_length=1)


class RegeneratePayload(_MessageIdPayload):
    """重新生成 AI 回复的请求体。"""


class ContinuePayload(_MessageIdPayload):
    """继续（追加）生成 AI 回复的请求体。"""
