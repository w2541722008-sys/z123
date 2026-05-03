"""billing_order_service 单元测试 — 订单超时关闭逻辑。"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import FakeRow, FakeSequenceConn


class TestCloseExpiredPendingOrders:
    def test_global_close_returns_rowcount(self):
        from services.billing_order_service import close_expired_pending_orders
        result_obj = FakeRow()
        result_obj.rowcount = 3
        conn = FakeSequenceConn([result_obj])
        count = close_expired_pending_orders(conn, commit=False)
        assert count == 3
        sql, params = conn.executed[0]
        assert "status = %s" in sql
        assert "expires_at <= %s" in sql
        # 全局模式没有 user_id 的 WHERE 条件
        assert "WHERE user_id" not in sql

    def test_user_specific_close(self):
        from services.billing_order_service import close_expired_pending_orders
        result_obj = FakeRow()
        result_obj.rowcount = 1
        conn = FakeSequenceConn([result_obj])
        count = close_expired_pending_orders(conn, user_id=5, commit=False)
        sql, params = conn.executed[0]
        assert "user_id = %s" in sql
        assert 5 in params

    def test_commit_flag_true(self):
        from services.billing_order_service import close_expired_pending_orders
        result_obj = FakeRow()
        result_obj.rowcount = 0
        conn = FakeSequenceConn([result_obj])
        close_expired_pending_orders(conn, commit=True)
        assert conn.committed is True

    def test_commit_flag_false(self):
        from services.billing_order_service import close_expired_pending_orders
        result_obj = FakeRow()
        result_obj.rowcount = 0
        conn = FakeSequenceConn([result_obj])
        close_expired_pending_orders(conn, commit=False)
        assert conn.committed is False

    def test_returns_zero_when_no_expired(self):
        from services.billing_order_service import close_expired_pending_orders
        result_obj = FakeRow()
        result_obj.rowcount = 0
        conn = FakeSequenceConn([result_obj])
        count = close_expired_pending_orders(conn, commit=False)
        assert count == 0
