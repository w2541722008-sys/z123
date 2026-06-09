"""Admin dashboard and config-health API behavior."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


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

    def test_config_health_returns_actionable_safe_summary(self, admin_client):
        _, client = admin_client
        env = {
            "ENV": "production",
            "AIFRIEND_API_KEY": "sk-secret-value",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USER": "noreply@example.com",
            "SMTP_PASSWORD": "smtp-secret",
            "ADMIN_EMAILS": "admin@example.com",
            "ALLOWED_ORIGINS": "https://example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            response = client.get("/api/admin/config-health")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["summary"]["ready_count"] == 5
        assert data["summary"]["warning_count"] == 1
        assert data["summary"]["error_count"] == 0
        assert {item["key"] for item in data["items"]} == {
            "runtime",
            "ai_model",
            "email",
            "admin_access",
            "cors",
            "payment",
        }
        payment = next(item for item in data["items"] if item["key"] == "payment")
        assert payment["status"] == "warning"
        assert payment["value"] == "支付网关未接入"
        assert "sk-secret-value" not in response.text
        assert "smtp-secret" not in response.text

    def test_config_health_reports_missing_required_items(self, admin_client):
        _, client = admin_client
        env = {
            "ENV": "development",
            "DEBUG": "true",
            "ALLOWED_ORIGINS": "http://localhost:8000",
        }
        with patch.dict(os.environ, env, clear=True):
            response = client.get("/api/admin/config-health")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        status_by_key = {item["key"]: item["status"] for item in data["items"]}
        assert status_by_key["runtime"] == "error"
        assert status_by_key["ai_model"] == "error"
        assert status_by_key["email"] == "error"
        assert status_by_key["admin_access"] == "error"
        assert status_by_key["cors"] == "error"

    def test_config_health_rejects_unsafe_origin_list_members(self, admin_client):
        _, client = admin_client
        base_env = {
            "ENV": "production",
            "DEBUG": "false",
            "AIFRIEND_API_KEY": "sk-secret-value",
            "RESEND_API_KEY": "re-secret-value",
            "ADMIN_EMAILS": "admin@example.com",
        }
        unsafe_origins = [
            "https://example.com,*",
            "https://example.com,http://127.0.0.1:8000",
            "https://example.com,http://0.0.0.0:8000",
            "https://example.com,http://[::1]:8000",
        ]

        for origins in unsafe_origins:
            with patch.dict(os.environ, {**base_env, "ALLOWED_ORIGINS": origins}, clear=True):
                response = client.get("/api/admin/config-health")

            assert response.status_code == 200
            status_by_key = {item["key"]: item["status"] for item in response.json()["items"]}
            assert status_by_key["cors"] == "error"

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
