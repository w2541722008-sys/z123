"""认证相关模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from core.schemas._base import (
    _normalize_email,
    _normalize_optional_email,
    _strip_text,
    _validate_password_length,
)


class _EmailPayload(BaseModel):
    email: str = Field(max_length=255)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        return _normalize_email(v)


class _OptionalEmailPayload(BaseModel):
    email: str | None = Field(default=None, max_length=255)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        return _normalize_optional_email(v)


class LoginPayload(_EmailPayload):
    """登录接口请求体。密码长度不限制，兼容旧版短密码。"""
    password: str = Field(min_length=1, max_length=64)


class RegisterPayload(_EmailPayload):
    """注册接口的请求体。nickname 可选，不填时用邮箱前缀代替。"""
    password: str = Field(min_length=8, max_length=64)
    nickname: str = Field(default="", max_length=20)

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_length(v)

    @field_validator('nickname')
    @classmethod
    def validate_nickname(cls, v: str) -> str:
        return _strip_text(v)


class ForgotPasswordPayload(_EmailPayload):
    """请求发送密码重置验证码。"""


class VerifyCodePayload(_EmailPayload):
    """验证密码重置验证码。"""
    code: str = Field(min_length=6, max_length=6)


class ResetPasswordPayload(_EmailPayload):
    """重置密码请求体。"""
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=64)
