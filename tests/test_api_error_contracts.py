from unittest.mock import patch

from fastapi import HTTPException

from auth import CurrentUser, get_admin_user, get_current_user


class _QueryResult:
    def __init__(self, *, one=None, rowcount=0):
        self._one = one
        self.rowcount = rowcount

    def fetchone(self):
        return self._one


class _SequenceConn:
    def __init__(self, results):
        self._results = list(results)
        self.committed = False
        self.rolled_back = False

    def execute(self, sql, params=None):
        if not self._results:
            raise AssertionError(f"Unexpected SQL: {sql}")
        return self._results.pop(0)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _assert_detail_as_list(payload: dict):
    assert isinstance(payload.get("detail"), list)
    assert len(payload["detail"]) > 0


def _assert_detail_as_string(payload: dict, expected: str):
    assert payload == {"detail": expected}
    assert isinstance(payload["detail"], str)


def test_auth_login_missing_payload_returns_422(app_client):
    _, client = app_client

    response = client.post("/api/auth/login", json={})

    assert response.status_code == 422
    _assert_detail_as_list(response.json())


def test_auth_reset_password_invalid_code_length_returns_422(app_client):
    _, client = app_client

    response = client.post(
        "/api/auth/reset-password",
        json={"email": "user@example.com", "code": "123", "new_password": "newpass123"},
    )

    assert response.status_code == 422
    _assert_detail_as_list(response.json())


def test_auth_me_without_token_returns_401_contract(app_client):
    _, client = app_client

    response = client.get("/api/auth/me")

    assert response.status_code == 401
    _assert_detail_as_string(response.json(), "未登录或登录已过期")


def test_admin_users_non_admin_returns_403_contract(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_admin_user] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail="你没有管理后台权限")
    )
    try:
        response = client.get("/api/admin/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    _assert_detail_as_string(response.json(), "你没有管理后台权限")


def test_billing_create_order_invalid_plan_returns_422(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1,
        email="u@example.com",
        nickname="u",
        effective_plan="free",
    )
    try:
        response = client.post("/api/billing/orders", json={"plan_type": "free"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    _assert_detail_as_list(response.json())


def test_billing_cancel_paid_order_returns_409_contract(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=101,
        email="vip@example.com",
        nickname="vip",
        effective_plan="free",
    )
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
    _assert_detail_as_string(response.json(), "已支付订单不能取消")
    assert conn.committed is False
    assert conn.rolled_back is True


def test_auth_verify_code_wrong_code_returns_400_string_detail(app_client):
    _, client = app_client
    conn = _SequenceConn([
        _QueryResult(one={"id": 9, "code": "112233", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0}),
    ])

    with patch("routers.auth.enforce_rate_limit"), patch("routers.auth.get_conn", return_value=conn):
        response = client.post(
            "/api/auth/verify-code",
            json={"email": "user@example.com", "code": "999999"},
        )

    assert response.status_code == 400
    _assert_detail_as_string(response.json(), "验证码错误")


def test_billing_get_order_not_found_returns_404_string_detail(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=101,
        email="vip@example.com",
        nickname="vip",
        effective_plan="free",
    )
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
    _assert_detail_as_string(response.json(), "订单不存在")


def test_auth_login_invalid_password_returns_401_expected_message(app_client):
    _, client = app_client
    conn = _SequenceConn([
        _QueryResult(one={
            "id": 1,
            "email": "user@example.com",
            "password_hash": "hash_x",
            "password_algo": "bcrypt",
            "nickname": "tester",
            "plan_type": "free",
            "plan_expires_at": "",
            "avatar_url": "",
        }),
    ])

    with patch("routers.auth.enforce_rate_limit"), patch("routers.auth.get_conn", return_value=conn), patch(
        "routers.auth.verify_password",
        return_value=False,
    ):
        response = client.post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "wrong-pass"},
        )

    assert response.status_code == 401
    _assert_detail_as_string(response.json(), "邮箱或密码错误")


def test_auth_forgot_password_throttled_returns_429_expected_message(app_client):
    _, client = app_client
    conn = _SequenceConn([
        _QueryResult(one={"id": 1, "email": "user@example.com"}),
        _QueryResult(one={"created_at": "2026-01-01T00:00:00+00:00"}),
    ])

    with patch("routers.auth.enforce_rate_limit"), patch("routers.auth.get_conn", return_value=conn):
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 429
    _assert_detail_as_string(response.json(), "请求过于频繁，请 60 秒后再试")


def test_auth_reset_password_invalid_code_returns_400_expected_message(app_client):
    _, client = app_client
    conn = _SequenceConn([
        _QueryResult(one={"id": 31, "code": "223344", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0}),
    ])

    with patch("routers.auth.enforce_rate_limit"), patch("routers.auth.get_conn", return_value=conn):
        response = client.post(
            "/api/auth/reset-password",
            json={"email": "user@example.com", "code": "000000", "new_password": "newpass123"},
        )

    assert response.status_code == 400
    _assert_detail_as_string(response.json(), "验证码无效或已过期")


def test_billing_cancel_closed_order_returns_409_expected_message(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=101,
        email="vip@example.com",
        nickname="vip",
        effective_plan="free",
    )
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
    _assert_detail_as_string(response.json(), "该订单已关闭，无需重复取消")


def test_admin_requires_login_returns_401_expected_message(app_client):
    _, client = app_client

    response = client.get("/api/admin/orders")

    assert response.status_code == 401
    _assert_detail_as_string(response.json(), "未登录或登录已过期")
