from datetime import datetime, timezone
from unittest.mock import patch

from core.auth import CurrentUser, get_current_user
from core.database import get_db_dep
from tests.support.db import FakeQueryResult, FakeSequenceConn


def _override_user(app, *, user_id=101, email="vip@example.com"):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=user_id,
        email=email,
        nickname="vip",
        effective_plan="free",
    )


def test_billing_create_order_success(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(one=None),
        FakeQueryResult(rowcount=1),
        FakeQueryResult(one={
            "order_no": "AF202601010101AA",
            "plan_type": "vip",
            "amount_cents": 1990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "pending",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "",
        }),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        with patch("routers.billing._build_order_no", return_value="AF202601010101AA"), patch(
            "routers.billing._pending_order_expires_at",
            return_value=datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        ):
            response = client.post("/api/billing/orders", json={"plan_type": "vip"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["reused_pending_order"] is False
    assert payload["order"]["order_no"] == "AF202601010101AA"
    assert payload["order"]["plan_type"] == "vip"
    assert conn.committed is True
    assert conn.rolled_back is False


def test_billing_create_order_reuses_pending_order(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(one={
            "order_no": "AFREUSE001",
            "plan_type": "vip",
            "amount_cents": 1990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "pending",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "",
        }),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.post("/api/billing/orders", json={"plan_type": "vip"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["reused_pending_order"] is True
    assert payload["order"]["order_no"] == "AFREUSE001"
    assert conn.committed is True


def test_billing_list_orders_returns_serialized_orders(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(many=[
            {
                "order_no": "AF001",
                "plan_type": "vip",
                "amount_cents": 1990,
                "currency": "CNY",
                "duration_days": 30,
                "status": "pending",
                "payment_provider": "",
                "provider_trade_no": "",
                "checkout_url": "",
                "created_at": "2026-01-01T00:00:00+00:00",
                "paid_at": "",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "closed_at": "",
            }
        ]),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.get("/api/billing/orders", params={"limit": 20})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["orders"]) == 1
    assert payload["orders"][0]["order_no"] == "AF001"
    assert payload["orders"][0]["can_cancel"] is True


def test_billing_get_order_not_found_returns_404(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(one=None),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.get("/api/billing/orders/NOTEXIST")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "订单不存在"


def test_billing_cancel_order_success(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(one={
            "order_no": "AFCAN001",
            "plan_type": "vip",
            "amount_cents": 1990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "pending",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "",
        }),
        FakeQueryResult(rowcount=1),
        FakeQueryResult(one={
            "order_no": "AFCAN001",
            "plan_type": "vip",
            "amount_cents": 1990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "closed",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "2026-01-02T00:00:00+00:00",
        }),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.post("/api/billing/orders/AFCAN001/cancel")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["order"]["status"] == "closed"
    assert conn.committed is True
    assert conn.rolled_back is False


def test_billing_cancel_paid_order_returns_409(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(one={
            "order_no": "AFPAID001",
            "plan_type": "vip",
            "amount_cents": 1990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "paid",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "2026-01-01T01:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "",
        }),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.post("/api/billing/orders/AFPAID001/cancel")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "已支付订单不能取消"
    assert conn.committed is False
    assert conn.rolled_back is True


def test_billing_plans_returns_products_payload(app_client):
    _, client = app_client

    response = client.get("/api/billing/plans")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["plans"]) == 2
    assert {item["plan_type"] for item in payload["plans"]} == {"vip", "svip"}
    assert all(item["payment_ready"] is False for item in payload["plans"])


def test_billing_list_orders_clamps_limit_to_min_1(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(many=[]),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.get("/api/billing/orders", params={"limit": 0})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"orders": []}
    assert conn.executed[1][1] == (101, 1)


def test_billing_list_orders_clamps_limit_to_max_100(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(many=[]),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.get("/api/billing/orders", params={"limit": 999})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"orders": []}
    assert conn.executed[1][1] == (101, 100)


def test_billing_cancel_closed_order_returns_409(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(one={
            "order_no": "AFCLOSE001",
            "plan_type": "vip",
            "amount_cents": 1990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "closed",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "2026-01-02T00:00:00+00:00",
        }),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        response = client.post("/api/billing/orders/AFCLOSE001/cancel")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "该订单已关闭，无需重复取消"
    assert conn.committed is False
    assert conn.rolled_back is True


# ============================================================
# 缓存失效验证
# ============================================================
def test_billing_cancel_order_invalidates_user_cache(app_client):
    """取消订单后应调用 invalidate_user 刷新缓存。"""
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),
        FakeQueryResult(one={
            "order_no": "AFCANCEL001",
            "plan_type": "vip",
            "amount_cents": 2990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "pending",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "",
        }),
        FakeQueryResult(rowcount=1),
        FakeQueryResult(one={
            "order_no": "AFCANCEL001",
            "plan_type": "vip",
            "amount_cents": 2990,
            "currency": "CNY",
            "duration_days": 30,
            "status": "closed",
            "payment_provider": "",
            "provider_trade_no": "",
            "checkout_url": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "paid_at": "",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "closed_at": "2026-01-01T01:00:00+00:00",
        }),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        with patch("routers.billing.invalidate_user") as mock_invalidate:
            response = client.post("/api/billing/orders/AFCANCEL001/cancel")
            mock_invalidate.assert_called_once_with("101")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_billing_list_orders_with_expired_invalidates_cache(app_client):
    """订单列表关闭过期订单后应刷新缓存。"""
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=2),  # 关闭了2笔过期订单
        FakeQueryResult(many=[]),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        with patch("routers.billing.invalidate_user") as mock_invalidate:
            response = client.get("/api/billing/orders")
            mock_invalidate.assert_called_once_with("101")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_billing_list_orders_no_expired_skips_invalidate(app_client):
    """没有过期订单关闭时不应刷新缓存。"""
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = FakeSequenceConn([
        FakeQueryResult(rowcount=0),  # 没有关闭任何过期订单
        FakeQueryResult(many=[]),
    ])
    app.dependency_overrides[get_db_dep] = lambda: conn

    try:
        with patch("routers.billing.invalidate_user") as mock_invalidate:
            response = client.get("/api/billing/orders")
            mock_invalidate.assert_not_called()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
