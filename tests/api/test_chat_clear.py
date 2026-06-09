"""
聊天功能集成测试 — 清除聊天记录 / 重置状态

覆盖端点：
  - POST /api/chat/clear       — 清空聊天并选择开场白
  - POST /api/character/state/reset — 重置角色关系状态
  - GET  /api/chat/history     — 获取聊天历史

测试策略：
  - 认证守卫：未登录 → 401
  - 路由注册：端点存在且响应正确
  - 输入校验：缺少必填字段 → 422
"""

import pytest

from core.auth import CurrentUser, get_current_user, get_optional_user
from tests.support.app import override_db
from tests.support.db import FakeDummyConn
from core.database import get_db_dep


# ── 认证守卫 ─────────────────────────────────────────────────────

class TestChatClearAuthGuards:
    """清除聊天记录端点需要登录。"""

    def test_clear_chat_unauthenticated_returns_401(self, app_client):
        _, client = app_client
        response = client.post("/api/chat/clear", json={"character_id": "luna"})
        assert response.status_code == 401

    def test_reset_state_unauthenticated_returns_401(self, app_client):
        _, client = app_client
        response = client.post("/api/character/state/reset?character_id=luna")
        assert response.status_code == 401

    def test_chat_history_unauthenticated_returns_401(self, app_client):
        _, client = app_client
        response = client.get("/api/chat/history?character_id=luna")
        assert response.status_code == 401


# ── 输入校验 ──────────────────────────────────────────────

class TestChatClearInputValidation:
    """输入校验测试。"""

    def test_clear_chat_missing_character_id_returns_422(self, admin_client):
        app, client = admin_client
        conn = FakeDummyConn()
        with override_db(app, conn):
            response = client.post("/api/chat/clear", json={})
        assert response.status_code == 422


# ── 路由注册 ──────────────────────────────────────────────

class TestChatClearRouteRegistration:
    """验证聊天清除相关端点完整注册。"""

    @pytest.mark.parametrize("method,path", [
        ("POST", "/api/chat/clear"),
        ("POST", "/api/character/state/reset"),
        ("GET", "/api/chat/history"),
    ])
    def test_endpoint_exists(self, app_module, method, path):
        routes = {
            (m, route.path)
            for route in app_module.routes
            for m in getattr(route, "methods", set())
        }
        assert (method, path) in routes


class TestCharacterClientSerialization:
    def test_serialized_character_exposes_affection_visibility_config(self):
        from routers.characters import _serialize_character_for_client

        row = FakeDummyConn().fetchone() or {
            "id": "luna",
            "name": "露娜",
            "abbr": "露",
            "subtitle": "陪你聊天",
            "avatar_url": "",
            "cover_url": "",
            "description": "",
            "opening_message": "你好",
            "tags": "[]",
            "card_type": "intimate",
            "required_plan": "guest",
            "home_priority": 0,
            "affection_enabled": 0,
            "affection_rules_json": {"show_bar": False},
        }

        result = _serialize_character_for_client(FakeDummyConn(), row, user_id=None, overrides_map={})

        assert result["affection_enabled"] == 0
        assert result["affection_rules_json"] == '{"show_bar": false}'
