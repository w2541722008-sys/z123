from unittest.mock import patch

from auth import CurrentUser, get_current_user


class _QueryResult:
    def __init__(self, *, one=None, many=None, rowcount=0):
        self._one = one
        self._many = many or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _SequenceConn:
    def __init__(self, results):
        self._results = list(results)
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql, params=None):
        if not self._results:
            raise AssertionError(f"Unexpected SQL: {sql}")
        result = self._results.pop(0)
        self.executed.append((sql, params))
        return result

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


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
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(one=None),
        _QueryResult(rowcount=1),
        _QueryResult(one={
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

    try:
        with patch("routers.billing.get_conn", return_value=conn), patch(
            "routers.billing._build_order_no",
            return_value="AF202601010101AA",
        ), patch("routers.billing.utc_now_iso", return_value="2026-01-01T00:00:00+00:00"), patch(
            "routers.billing._pending_order_expires_at",
            return_value="2099-01-01T00:00:00+00:00",
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
    assert conn.closed is True


def test_billing_create_order_reuses_pending_order(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(one={
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

    try:
        with patch("routers.billing.get_conn", return_value=conn):
            response = client.post("/api/billing/orders", json={"plan_type": "vip"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["reused_pending_order"] is True
    assert payload["order"]["order_no"] == "AFREUSE001"
    assert conn.committed is True
    assert conn.closed is True


def test_billing_list_orders_returns_serialized_orders(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(many=[
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

    try:
        with patch("routers.billing.get_conn", return_value=conn):
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
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(one=None),
    ])

    try:
        with patch("routers.billing.get_conn", return_value=conn):
            response = client.get("/api/billing/orders/NOTEXIST")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "订单不存在"


def test_billing_cancel_order_success(app_client):
    _, client = app_client
    app = client.app
    _override_user(app)
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(one={
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
        _QueryResult(rowcount=1),
        _QueryResult(one={
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

    try:
        with patch("routers.billing.get_conn", return_value=conn), patch(
            "routers.billing.utc_now_iso",
            return_value="2026-01-02T00:00:00+00:00",
        ):
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
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(one={
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

    try:
        with patch("routers.billing.get_conn", return_value=conn):
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
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(many=[]),
    ])

    try:
        with patch("routers.billing.get_conn", return_value=conn):
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
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(many=[]),
    ])

    try:
        with patch("routers.billing.get_conn", return_value=conn):
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
    conn = _SequenceConn([
        _QueryResult(rowcount=0),
        _QueryResult(one={
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

    try:
        with patch("routers.billing.get_conn", return_value=conn):
            response = client.post("/api/billing/orders/AFCLOSE001/cancel")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "该订单已关闭，无需重复取消"
    assert conn.committed is False
    assert conn.rolled_back is True
