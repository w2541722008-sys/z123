"""
共享基础模型和校验工具函数。

所有域模型文件从此模块导入校验函数和基类。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ── 校验工具函数 ──

def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if '@' not in value or '.' not in value.split('@')[-1]:
        raise ValueError('无效的邮箱格式')
    return value


def _normalize_optional_email(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_email(value)


def _validate_password_length(value: str) -> str:
    if len(value) < 8:
        raise ValueError('密码至少需要8位')
    if len(value) > 64:
        raise ValueError('密码不能超过64位')
    # 至少包含一个字母和一个数字
    if not any(c.isalpha() for c in value):
        raise ValueError('密码需包含至少一个字母')
    if not any(c.isdigit() for c in value):
        raise ValueError('密码需包含至少一个数字')
    return value


def _strip_text(value: str) -> str:
    return value.strip()


def _normalize_optional_trimmed(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _validate_required_trimmed(value: str, error_message: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(error_message)
    return value


# ── 共享基类 ──

class _PriorityActivePayload(BaseModel):
    priority: int = Field(default=100, ge=0, le=9999)
    is_active: int = Field(default=1, ge=0, le=1)


class _SortOrderPayload(BaseModel):
    sort_order: int = Field(default=0)


class _SortOrderActivePayload(_SortOrderPayload):
    is_active: int = Field(default=1, ge=0, le=1)


class _OptionalCategoryIdPayload(BaseModel):
    category_id: str | None = Field(default=None)

    @field_validator('category_id')
    @classmethod
    def validate_category_id(cls, v: str | None) -> str | None:
        return _normalize_optional_trimmed(v)


class _OptionalStorylineIdPayload(BaseModel):
    storyline_id: str | None = Field(default=None)

    @field_validator('storyline_id')
    @classmethod
    def validate_storyline_id(cls, v: str | None) -> str | None:
        return _normalize_optional_trimmed(v)


class _OptionalUnlockedStorylineIdPayload(BaseModel):
    unlocked_storyline_id: str | None = Field(default=None)

    @field_validator('unlocked_storyline_id')
    @classmethod
    def validate_unlocked_storyline_id(cls, v: str | None) -> str | None:
        return _normalize_optional_trimmed(v)
