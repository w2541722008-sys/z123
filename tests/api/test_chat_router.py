"""
Chat 路由公共行为测试

只测路由层的公共契约，不测私有函数：
  - 未登录 → 401
  - 空消息 → 422
  - 游客限流 → 429
  - 路由注册完整性
"""

import pytest
from unittest.mock import patch

from core.auth import CurrentUser, get_current_user
from tests.support.app import override_db
from tests.support.db import FakeDummyConn
from core.database import get_db_dep


# ── 认证守卫 ─────────────────────────────────────────────────────

class TestChatAuthGuards:
    """需要登录的端点，未登录应返回 401。"""

    @pytest.mark.parametrize("path", [
        "/api/chat/send",
        "/api/chat/stream",
        "/api/chat/regenerate",
        "/api/chat/continue",
    ])
    def test_unauthenticated_returns_401(self, app_client, path):
        _, client = app_client
        response = client.post(path, json={"character_id": "test", "message": "hi"})
        assert response.status_code == 401


# ── 输入校验（422） ──────────────────────────────────────────────

class TestChatInputValidation:
    """请求体不符合 schema 时应返回 422。"""

    def test_send_missing_character_id_returns_422(self, app_client):
        _, client = app_client
        app = client.app
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=1, email="u@example.com", nickname="u", effective_plan="free",
        )
        app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
        try:
            response = client.post("/api/chat/send", json={"message": "hi"})
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 422

    def test_send_blank_message_returns_422(self, app_client):
        _, client = app_client
        app = client.app
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=1, email="u@example.com", nickname="u", effective_plan="free",
        )
        app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
        try:
            response = client.post("/api/chat/send", json={"character_id": "test", "message": "   "})
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 422

    def test_regenerate_missing_message_id_returns_422(self, app_client):
        _, client = app_client
        app = client.app
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=1, email="u@example.com", nickname="u", effective_plan="free",
        )
        app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
        try:
            response = client.post("/api/chat/regenerate", json={})
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 422

    def test_continue_missing_message_id_returns_422(self, app_client):
        _, client = app_client
        app = client.app
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=1, email="u@example.com", nickname="u", effective_plan="free",
        )
        app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
        try:
            response = client.post("/api/chat/continue", json={})
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 422

    def test_guest_stream_missing_character_id_returns_422(self, app_client):
        _, client = app_client
        app = client.app
        app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
        try:
            response = client.post("/api/chat/guest-stream", json={"message": "hi"})
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 422


# ── 游客限流 ─────────────────────────────────────────────────────

class TestGuestRateLimit:
    """游客聊天应有独立限流。"""

    def test_guest_stream_respects_rate_limit(self, app_client):
        _, client = app_client
        from fastapi import HTTPException

        app = client.app
        app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
        try:
            with patch("routers.chat.enforce_rate_limit", side_effect=HTTPException(
                status_code=429, detail="游客请求过于频繁，请稍后再试或登录继续",
            )):
                response = client.post(
                    "/api/chat/guest-stream",
                    json={"character_id": "test", "message": "hi"},
                )
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 429


# ── 游客额度 ─────────────────────────────────────────────────────

class TestGuestQuota:
    """游客额度查询接口应返回当前 IP 的剩余额度。"""

    def test_guest_quota_uses_client_ip_and_returns_payload(self, app_client):
        _, client = app_client
        app = client.app
        app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()

        captured = {}

        def fake_build_guest_quota_payload(conn, guest_ip):
            captured["conn"] = conn
            captured["guest_ip"] = guest_ip
            return {
                "guest": True,
                "status_text": "额度充足",
                "remaining_percent": 80,
                "used_tokens": 20,
                "remaining_tokens": 80,
                "token_limit": 100,
            }

        try:
            with patch(
                "routers.chat.build_guest_quota_payload",
                side_effect=fake_build_guest_quota_payload,
            ):
                response = client.get("/api/chat/guest-quota")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["status_text"] == "额度充足"
        assert captured["guest_ip"] == "testclient"
        assert isinstance(captured["conn"], FakeDummyConn)


# ── 路由注册 ─────────────────────────────────────────────────────

class TestChatRouteRegistration:
    """验证 chat 路由端点完整注册。"""

    @pytest.mark.parametrize("method,path", [
        ("POST", "/api/chat/send"),
        ("POST", "/api/chat/stream"),
        ("POST", "/api/chat/guest-stream"),
        ("GET", "/api/chat/guest-quota"),
        ("POST", "/api/chat/regenerate"),
        ("POST", "/api/chat/continue"),
    ])
    def test_chat_endpoint_exists(self, app_module, method, path):
        routes = {
            (m, route.path)
            for route in app_module.routes
            for m in getattr(route, "methods", set())
        }
        assert (method, path) in routes
