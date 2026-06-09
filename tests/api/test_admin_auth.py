"""Admin API authentication and shared guard behavior."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


def test_admin_short_path_serves_admin_page(app_client):
    """文档中的 /admin 入口应和 /admin.html 一样可直接访问。"""
    _, client = app_client

    response = client.get("/admin")

    assert response.status_code == 200
    assert "角色卡管理后台" in response.text


class TestAdminAuthGuards:
    """Admin 端点必须要求管理员权限。"""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/orders"),
        ("GET", "/api/admin/characters"),
        ("GET", "/api/admin/dashboard/stats"),
        ("GET", "/api/admin/audit-logs"),
    ])
    def test_unauthenticated_returns_401(self, app_client, method, path):
        _, client = app_client
        response = client.request(method, path)
        assert response.status_code == 401

    def test_non_admin_returns_403(self, app_client):
        _, client = app_client
        app = client.app
        normal = CurrentUser(
            id=2, email="user@example.com", nickname="user",
            plan_type="free", effective_plan="free", is_admin=False)
        saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_current_user] = lambda: normal
        app.dependency_overrides[get_optional_user] = lambda: normal
        app.dependency_overrides[get_admin_user] = lambda: (
            _ for _ in ()
        ).throw(HTTPException(status_code=403, detail="你没有管理后台权限"))
        try:
            response = client.get("/api/admin/users")
        finally:
            app.dependency_overrides = saved
        assert response.status_code == 403

    @pytest.mark.parametrize("path", [
        "/api/admin/users",
        "/api/admin/orders",
        "/api/admin/dashboard/stats",
        "/api/admin/characters",
    ])
    def test_admin_routes_share_rate_limit_guard(self, admin_client, path):
        """所有 admin 业务域都应走同一套后台限流。"""
        app, client = admin_client
        from routers.admin._helpers import _admin_rate_limit

        def reject_admin_requests(*args, **kwargs):
            raise HTTPException(status_code=429, detail="请求过于频繁")

        saved_override = app.dependency_overrides.pop(_admin_rate_limit, None)
        try:
            with patch("services.rate_limit.enforce_rate_limit", side_effect=reject_admin_requests):
                response = client.get(path)
        finally:
            if saved_override is not None:
                app.dependency_overrides[_admin_rate_limit] = saved_override

        assert response.status_code == 429

    def test_character_route_runs_shared_rate_limit_once(self, admin_client):
        """父子路由同时声明同一限流依赖时，不应重复扣同一次请求。"""
        app, client = admin_client
        from routers.admin._helpers import _admin_rate_limit

        conn = FakeSequenceConn([
            FakeQueryResult(many=[]),
        ])

        saved_override = app.dependency_overrides.pop(_admin_rate_limit, None)
        try:
            with override_db(app, conn), patch("services.rate_limit.enforce_rate_limit") as mock_limit:
                response = client.get("/api/admin/characters")
        finally:
            if saved_override is not None:
                app.dependency_overrides[_admin_rate_limit] = saved_override

        assert response.status_code == 200
        mock_limit.assert_called_once()
