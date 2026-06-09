"""Admin order-management API behavior."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


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
