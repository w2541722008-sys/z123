"""Admin user-management API behavior."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


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
