"""管理后台和计费相关模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.schemas._auth import _OptionalEmailPayload


class AdminUpdatePayload(BaseModel):
    """管理后台更新角色请求体。updates: {字段名: 新值}，支持 rl__XXX 前缀写回 runtime_layers。"""
    updates: dict[str, Any]


class AdminUserPlanUpdatePayload(BaseModel):
    """管理后台手动调整用户会员档位。"""
    plan_type: str = Field(pattern="^(free|vip|svip)$")
    duration_days: int = Field(default=30, ge=1, le=3650)


class AdminUserEditPayload(_OptionalEmailPayload):
    """管理后台编辑用户信息。"""
    nickname: str | None = Field(default=None, max_length=20)


class AdminBatchPlanPayload(BaseModel):
    """管理后台批量调整用户档位。"""
    user_ids: list[str] = Field(min_length=1, max_length=100)
    plan_type: str = Field(pattern="^(free|vip|svip)$")
    duration_days: int = Field(default=30, ge=1, le=3650)


class BillingCreateOrderPayload(BaseModel):
    """创建会员订单的请求体。"""
    plan_type: str = Field(pattern="^(vip|svip)$")
