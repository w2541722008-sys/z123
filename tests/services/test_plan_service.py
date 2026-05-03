"""plan_service 单元测试 — 档位访问权限与策略。"""
from __future__ import annotations

import pytest

from fastapi import HTTPException


# ── ensure_plan_access ────────────────────────────────

class TestEnsurePlanAccess:
    def test_free_user_can_access_guest_content(self):
        from services.plan_service import ensure_plan_access
        # 不抛异常即通过
        ensure_plan_access("free", "guest")

    def test_free_user_cannot_access_vip_content(self):
        from services.plan_service import ensure_plan_access
        with pytest.raises(HTTPException) as exc_info:
            ensure_plan_access("free", "vip")
        assert exc_info.value.status_code == 403

    def test_vip_can_access_vip(self):
        from services.plan_service import ensure_plan_access
        ensure_plan_access("vip", "vip")

    def test_svip_can_access_all(self):
        from services.plan_service import ensure_plan_access
        ensure_plan_access("svip", "vip")
        ensure_plan_access("svip", "svip")

    def test_none_viewer_denied_for_non_guest(self):
        from services.plan_service import ensure_plan_access
        with pytest.raises(HTTPException):
            ensure_plan_access(None, "vip")

    def test_none_viewer_allowed_for_guest(self):
        from services.plan_service import ensure_plan_access
        ensure_plan_access(None, "guest")

    def test_custom_detail_in_exception(self):
        from services.plan_service import ensure_plan_access
        with pytest.raises(HTTPException) as exc_info:
            ensure_plan_access("free", "vip", detail="自定义消息")
        assert exc_info.value.detail == "自定义消息"


# ── get_plan_policy ───────────────────────────────────

class TestGetPlanPolicy:
    def test_free_plan_policy(self):
        from services.plan_service import get_plan_policy, FREE_PLAN
        policy = get_plan_policy("free")
        assert policy["plan_type"] == FREE_PLAN
        assert policy["token_limit"] > 0
        assert "model_profile" in policy

    def test_vip_plan_policy(self):
        from services.plan_service import get_plan_policy, VIP_PLAN
        policy = get_plan_policy("vip")
        assert policy["plan_type"] == VIP_PLAN
        assert policy["token_limit"] > 0

    def test_guest_plan_policy(self):
        from services.plan_service import get_plan_policy, GUEST_PLAN
        policy = get_plan_policy("guest")
        assert policy["plan_type"] == GUEST_PLAN

    def test_none_defaults_to_guest(self):
        from services.plan_service import get_plan_policy, GUEST_PLAN
        policy = get_plan_policy(None)
        assert policy["plan_type"] == GUEST_PLAN

    def test_invalid_defaults_to_guest(self):
        from services.plan_service import get_plan_policy, GUEST_PLAN
        policy = get_plan_policy("unknown_plan")
        assert policy["plan_type"] == GUEST_PLAN

    def test_policy_has_display_name(self):
        from services.plan_service import get_plan_policy
        policy = get_plan_policy("vip")
        assert policy["display_name"] == "VIP"
