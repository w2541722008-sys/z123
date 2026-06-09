"""billing_repository 单元测试 — 验证参数传递与 SQL 结构。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.support.db import FakeRow, FakeSequenceConn


# ── fetch_order_by_no ──────────────────────────────────────

class TestFetchOrderByNo:
    def test_without_user_id(self):
        from repositories.billing_repository import fetch_order_by_no
        row = FakeRow({"order_no": "ORD001", "status": "pending"})
        conn = FakeSequenceConn([row])
        result = fetch_order_by_no(conn, order_no="ORD001")
        assert result is row
        sql, params = conn.executed[0]
        assert "WHERE order_no = %s" in sql
        assert "user_id" not in sql
        assert params == ("ORD001",)

    def test_with_user_id(self):
        from repositories.billing_repository import fetch_order_by_no
        row = FakeRow({"order_no": "ORD001", "status": "pending"})
        conn = FakeSequenceConn([row])
        result = fetch_order_by_no(conn, order_no="ORD001", user_id=5)
        sql, params = conn.executed[0]
        assert "AND user_id = %s" in sql
        assert params == ("ORD001", 5)


# ── find_pending_order ────────────────────────────────────

class TestFindPendingOrder:
    def test_params_alignment(self):
        from repositories.billing_repository import find_pending_order
        conn = FakeSequenceConn([None])
        find_pending_order(conn, user_id=1, plan_type="vip", status="pending")
        sql, params = conn.executed[0]
        assert "user_id = %s" in sql
        assert "plan_type = %s" in sql
        assert "status = %s" in sql
        assert params == (1, "vip", "pending")
        assert sql.count("%s") == len(params)


# ── insert_order ──────────────────────────────────────────

class TestInsertOrder:
    def test_params_alignment(self):
        from repositories.billing_repository import insert_order
        conn = FakeSequenceConn([FakeRow()])
        expires = datetime(2026, 5, 10, tzinfo=timezone.utc)
        insert_order(
            conn,
            order_no="ORD001",
            user_id=1,
            plan_type="vip",
            amount_cents=9900,
            duration_days=30,
            status="pending",
            expires_at=expires,
        )
        sql, params = conn.executed[0]
        assert "INSERT INTO membership_orders" in sql
        assert sql.count("%s") == len(params)
        assert params[0] == "ORD001"
        assert params[1] == 1


# ── close_pending_order ──────────────────────────────────

class TestClosePendingOrder:
    def test_returns_rowcount(self):
        from repositories.billing_repository import close_pending_order
        result_obj = FakeRow()
        result_obj.rowcount = 1
        conn = FakeSequenceConn([result_obj])
        count = close_pending_order(
            conn, order_no="ORD001", user_id=1,
            current_status="pending", new_status="closed",
        )
        assert count == 1
        sql, params = conn.executed[0]
        assert "UPDATE membership_orders" in sql
        assert "status = %s" in sql
        assert params == ("closed", "ORD001", 1, "pending")


# ── list_user_orders ─────────────────────────────────────

class TestListUserOrders:
    def test_returns_list(self):
        from repositories.billing_repository import list_user_orders
        rows = [FakeRow({"order_no": "ORD001"})]
        conn = FakeSequenceConn([rows])
        result = list_user_orders(conn, user_id=1, limit=10)
        assert result is rows
        sql, params = conn.executed[0]
        assert params == (1, 10)
