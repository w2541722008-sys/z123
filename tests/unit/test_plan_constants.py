"""plan_constants 单元测试 — 纯函数档位逻辑验证。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from core.plan_constants import (
    FREE_PLAN, VIP_PLAN, SVIP_PLAN, GUEST_PLAN,
    normalize_user_plan, normalize_required_plan,
    plan_display_name, resolve_effective_plan,
    get_plan_level, can_access_required_plan,
    serialize_plan_info,
)


class TestNormalizeUserPlan:
    def test_valid_plans(self):
        assert normalize_user_plan("free") == FREE_PLAN
        assert normalize_user_plan("vip") == VIP_PLAN
        assert normalize_user_plan("svip") == SVIP_PLAN

    def test_case_insensitive(self):
        assert normalize_user_plan("VIP") == VIP_PLAN
        assert normalize_user_plan("Free") == FREE_PLAN

    def test_none_defaults_to_free(self):
        assert normalize_user_plan(None) == FREE_PLAN

    def test_empty_defaults_to_free(self):
        assert normalize_user_plan("") == FREE_PLAN

    def test_invalid_defaults_to_free(self):
        assert normalize_user_plan("premium") == FREE_PLAN

    def test_whitespace_stripped(self):
        assert normalize_user_plan("  vip  ") == VIP_PLAN


class TestNormalizeRequiredPlan:
    def test_valid_plans(self):
        assert normalize_required_plan("guest") == GUEST_PLAN
        assert normalize_required_plan("free") == FREE_PLAN

    def test_none_defaults_to_guest(self):
        assert normalize_required_plan(None) == GUEST_PLAN

    def test_invalid_defaults_to_guest(self):
        assert normalize_required_plan("unknown") == GUEST_PLAN


class TestPlanDisplayName:
    def test_known_plans(self):
        assert plan_display_name("guest") == "游客"
        assert plan_display_name("free") == "注册用户"
        assert plan_display_name("vip") == "VIP"
        assert plan_display_name("svip") == "SVIP"

    def test_unknown_defaults_guest(self):
        assert plan_display_name("unknown") == "游客"


class TestResolveEffectivePlan:
    def test_free_never_expires(self):
        assert resolve_effective_plan("free", None) == FREE_PLAN

    def test_vip_not_expired(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        assert resolve_effective_plan("vip", future) == VIP_PLAN

    def test_vip_expired(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert resolve_effective_plan("vip", past) == FREE_PLAN

    def test_vip_no_expiry_stays_vip(self):
        assert resolve_effective_plan("vip", None) == VIP_PLAN

    def test_svip_expired(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert resolve_effective_plan("svip", past) == FREE_PLAN

    def test_datetime_object_not_expired(self):
        future_dt = datetime.now(timezone.utc) + timedelta(days=10)
        assert resolve_effective_plan("vip", future_dt) == VIP_PLAN

    def test_datetime_object_expired(self):
        past_dt = datetime.now(timezone.utc) - timedelta(days=1)
        assert resolve_effective_plan("vip", past_dt) == FREE_PLAN

    def test_naive_datetime_treated_as_utc(self):
        future_naive = datetime.now() + timedelta(days=10)
        assert resolve_effective_plan("vip", future_naive) == VIP_PLAN


class TestGetPlanLevel:
    def test_hierarchy(self):
        assert get_plan_level("guest") == 0
        assert get_plan_level("free") == 1
        assert get_plan_level("vip") == 2
        assert get_plan_level("svip") == 3

    def test_unknown_is_zero(self):
        assert get_plan_level("unknown") == 0


class TestCanAccessRequiredPlan:
    def test_guest_cannot_access_free(self):
        assert can_access_required_plan("guest", "free") is False

    def test_free_can_access_guest(self):
        assert can_access_required_plan("free", "guest") is True

    def test_free_cannot_access_vip(self):
        assert can_access_required_plan("free", "vip") is False

    def test_vip_can_access_free(self):
        assert can_access_required_plan("vip", "free") is True

    def test_svip_can_access_all(self):
        assert can_access_required_plan("svip", "guest") is True
        assert can_access_required_plan("svip", "free") is True
        assert can_access_required_plan("svip", "vip") is True
        assert can_access_required_plan("svip", "svip") is True


class TestSerializePlanInfo:
    def test_free_user(self):
        info = serialize_plan_info("free", None)
        assert info["plan_type"] == FREE_PLAN
        assert info["effective_plan"] == FREE_PLAN
        assert info["is_paid_plan"] is False
        assert info["membership_expired"] is False

    def test_active_vip(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        info = serialize_plan_info("vip", future)
        assert info["plan_type"] == VIP_PLAN
        assert info["effective_plan"] == VIP_PLAN
        assert info["is_paid_plan"] is True
        assert info["membership_expired"] is False

    def test_expired_vip(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        info = serialize_plan_info("vip", past)
        assert info["plan_type"] == VIP_PLAN
        assert info["effective_plan"] == FREE_PLAN
        assert info["membership_expired"] is True

    def test_datetime_expires_at(self):
        future_dt = datetime.now(timezone.utc) + timedelta(days=10)
        info = serialize_plan_info("vip", future_dt)
        assert info["plan_expires_at"] == future_dt.isoformat()
