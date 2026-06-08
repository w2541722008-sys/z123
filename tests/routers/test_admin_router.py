"""
Admin 路由集成测试

使用 override_db + admin_client fixture，替代旧版 patch("xxx.get_conn") 模式。

测试策略：
  - 401：未登录访问 admin 端点
  - 403：非管理员访问 admin 端点
  - 422：输入校验失败
  - 404：资源不存在
  - 200/409/400：正常业务流程（CRUD）
"""

import pytest
from unittest.mock import patch

from fastapi import HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
from conftest import FakeSequenceConn, FakeQueryResult, FakeRow, FakeDummyConn, override_db


# ── 认证守卫 ─────────────────────────────────────────────────────

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


# ── Users 端点 ───────────────────────────────────────────────────

class TestAdminUsers:
    """用户管理端点。"""

    def test_list_users_returns_paginated_result(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"total": 1}),
            FakeQueryResult(many=[{
                "id": 1,
                "email": "user@example.com",
                "nickname": "用户",
                "plan_type": "free",
                "plan_expires_at": "",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/users")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "items" in data

    def test_get_user_not_found_returns_404(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),  # SELECT user
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/users/9999")
        assert response.status_code == 404
        assert response.json()["detail"] == "用户不存在"

    def test_edit_user_returns_ok(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": 1, "email": "old@example.com"}),  # SELECT user
            FakeQueryResult(rowcount=1),  # UPDATE
            FakeQueryResult(rowcount=1),  # audit log INSERT
        ])
        with override_db(app, conn), \
             patch("routers.admin.users.invalidate_user"):
            response = client.patch("/api/admin/users/1", json={"nickname": "新昵称"})
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_edit_user_not_found_returns_404(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),  # SELECT user
        ])
        with override_db(app, conn):
            response = client.patch("/api/admin/users/9999", json={"nickname": "x"})
        assert response.status_code == 404

    def test_edit_user_no_fields_returns_400(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": 1, "email": "u@example.com"}),  # SELECT user
        ])
        with override_db(app, conn):
            response = client.patch("/api/admin/users/1", json={})
        assert response.status_code == 400

    def test_delete_user_returns_ok(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": 1, "email": "del@example.com"}),  # SELECT user
            FakeQueryResult(rowcount=1),  # DELETE ai_request_logs
            FakeQueryResult(rowcount=1),  # DELETE chat_messages
            FakeQueryResult(rowcount=1),  # DELETE chat_summaries
            FakeQueryResult(rowcount=1),  # DELETE user_character_profiles
            FakeQueryResult(rowcount=1),  # DELETE character_states
            FakeQueryResult(rowcount=1),  # DELETE user_story_progress
            FakeQueryResult(rowcount=1),  # DELETE membership_orders
            FakeQueryResult(rowcount=1),  # DELETE auth_tokens
            FakeQueryResult(rowcount=1),  # DELETE password_reset_codes
            FakeQueryResult(rowcount=1),  # DELETE users
            FakeQueryResult(rowcount=1),  # audit log INSERT
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/users/1")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_delete_user_not_found_returns_404(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/users/9999")
        assert response.status_code == 404


# ── Characters 端点 ──────────────────────────────────────────────

class TestAdminCharacters:
    """角色管理端点。"""

    def test_list_characters_returns_list(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(many=[{
                "id": "luna", "name": "露娜", "abbr": "LN", "subtitle": "月光",
                "avatar_url": "/a.png", "description": "温柔",
                "tags": '["温柔"]', "card_type": "intimate",
                "required_plan": "guest", "is_visible": 1,
                "home_priority": 10, "sort_order": 10,
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/characters")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_character_not_found_returns_404(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/nonexistent")
        assert response.status_code == 404
        assert response.json()["detail"] == "角色不存在"

    def test_create_character_missing_id_returns_400(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([])
        with override_db(app, conn):
            response = client.post("/api/admin/characters", json={
                "name": "角色", "system_prompt": "你好",
            })
        assert response.status_code == 400
        assert "角色ID" in response.json()["detail"]

    def test_create_character_missing_name_returns_400(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([])
        with override_db(app, conn):
            response = client.post("/api/admin/characters", json={
                "id": "test_char", "system_prompt": "你好",
            })
        assert response.status_code == 400
        assert "角色名" in response.json()["detail"]

    def test_create_character_missing_system_prompt_returns_400(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([])
        with override_db(app, conn):
            response = client.post("/api/admin/characters", json={
                "id": "test_char", "name": "测试",
            })
        assert response.status_code == 400
        assert "主指令" in response.json()["detail"]

    def test_create_character_duplicate_id_returns_409(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),  # SELECT existing
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/characters", json={
                "id": "luna", "name": "露娜", "system_prompt": "你好",
            })
        assert response.status_code == 409

    def test_delete_character_not_found_returns_404(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/character/nonexistent")
        assert response.status_code == 404

    def test_update_character_no_fields_returns_400(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([])
        with override_db(app, conn):
            response = client.post("/api/admin/character/test", json={"updates": {}})
        assert response.status_code == 422 or response.status_code == 400

    def test_update_character_saves_life_profile_json(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna", "structured_asset_json": "{}"}),
            FakeQueryResult(rowcount=1),  # UPDATE characters
            FakeQueryResult(rowcount=1),  # audit log INSERT
        ])
        payload = {
            "updates": {
                "life_profile_json": '{"basic_info":"林深","family":"茶馆"}',
            },
        }
        with override_db(app, conn), \
             patch("routers.admin.characters_core.invalidate_character"), \
             patch("routers.admin.characters_core.invalidate_character_affection_rules"), \
             patch("routers.admin.characters_core.invalidate_character_list_all"):
            response = client.post("/api/admin/character/luna", json=payload)

        assert response.status_code == 200
        assert "life_profile_json" in response.json()["updated"]
        update_sql, update_params = conn.executed[1]
        assert "life_profile_json = %s" in update_sql
        assert update_params[0] == '{"basic_info":"林深","family":"茶馆"}'

    def test_update_character_rejects_invalid_card_type(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna", "structured_asset_json": "{}"}),
        ])
        with override_db(app, conn):
            response = client.post(
                "/api/admin/character/luna",
                json={"updates": {"card_type": "world"}},
            )

        assert response.status_code == 400
        assert "card_type" in response.json()["detail"]

    def test_update_character_rejects_invalid_required_plan(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna", "structured_asset_json": "{}"}),
        ])
        with override_db(app, conn):
            response = client.post(
                "/api/admin/character/luna",
                json={"updates": {"required_plan": "premium"}},
            )

        assert response.status_code == 400
        assert "required_plan" in response.json()["detail"]

    def test_update_character_rejects_invalid_life_profile_json(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna", "structured_asset_json": "{}"}),
        ])
        with override_db(app, conn):
            response = client.post(
                "/api/admin/character/luna",
                json={"updates": {"life_profile_json": "[]"}},
            )

        assert response.status_code == 400
        assert "life_profile_json" in response.json()["detail"]


# ── Orders 端点 ──────────────────────────────────────────────────

class TestAdminOrders:
    """订单管理端点。"""

    def test_list_orders_returns_paginated_result(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"total": 0}),
            FakeQueryResult(many=[]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/orders")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "orders" in data

    def test_get_order_not_found_returns_404(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/orders/9999")
        assert response.status_code == 404
        assert response.json()["detail"] == "订单不存在"


# ── Dashboard 端点 ───────────────────────────────────────────────

class TestAdminDashboard:
    """仪表盘端点。"""

    def test_dashboard_stats_returns_dict(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"cnt": 10}),    # total_users
            FakeQueryResult(one={"cnt": 2}),     # today_new
            FakeQueryResult(one={"cnt": 3}),     # paid_users
            FakeQueryResult(one={"cnt": 1}),     # today_orders
            FakeQueryResult(one={"total": 1990}), # today_revenue
            FakeQueryResult(one={"cnt": 0}),     # expiring_soon
            FakeQueryResult(many=[{"plan_type": "free", "cnt": 7}, {"plan_type": "vip", "cnt": 3}]),
            FakeQueryResult(one={"size_bytes": 31457280}),  # pg_database_size (~30MB)
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_users" in data
        assert "paid_rate" in data
        assert "storage" in data
        assert data["storage"]["size_mb"] == 30.0

    def test_audit_logs_returns_paginated_result(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"total": 0}),
            FakeQueryResult(many=[]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/audit-logs")
        assert response.status_code == 200
        assert "logs" in response.json()

    def test_db_stats_returns_ok(self, admin_client):
        app, client = admin_client
        with patch("routers.admin.dashboard.get_stats", return_value={"total": 0}):
            response = client.get("/api/admin/db-stats")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_db_stats_reset_returns_ok(self, admin_client):
        app, client = admin_client
        with patch("routers.admin.dashboard.reset_stats"):
            response = client.post("/api/admin/db-stats/reset")
        assert response.status_code == 200
        assert response.json()["ok"] is True
