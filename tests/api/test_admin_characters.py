"""Admin character-management API behavior."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


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
