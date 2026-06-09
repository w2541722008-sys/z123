from unittest.mock import patch

from fastapi import HTTPException

from core.auth import CurrentUser, get_admin_user, get_current_user
from core.database import get_db_dep
from tests.support.assertions import assert_detail_as_list, assert_detail_as_string
from tests.support.db import (
    FakeDummyConn,
    FakeQueryResult,
    FakeSequenceConn,
)


def test_auth_login_missing_payload_returns_422(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
    try:
        response = client.post("/api/auth/login", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert_detail_as_list(response.json())


def test_auth_reset_password_invalid_code_length_returns_422(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
    try:
        response = client.post(
            "/api/auth/reset-password",
            json={"email": "user@example.com", "code": "123", "new_password": "newpass123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert_detail_as_list(response.json())


def test_auth_me_without_token_returns_401_contract(app_client):
    _, client = app_client

    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert_detail_as_string(response.json(), "未登录或登录已过期")


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
    assert_detail_as_string(response.json(), "你没有管理后台权限")


def test_billing_create_order_invalid_plan_returns_422(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1,
        email="u@example.com",
        nickname="u",
        effective_plan="free",
    )
    app.dependency_overrides[get_db_dep] = lambda: FakeDummyConn()
    try:
        response = client.post("/api/billing/orders", json={"plan_type": "free"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert_detail_as_list(response.json())


def test_billing_cancel_paid_order_returns_409_contract(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=101,
        email="vip@example.com",
        nickname="vip",
        effective_plan="free",
    )
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
    assert_detail_as_string(response.json(), "已支付订单不能取消")
    assert conn.committed is False
    assert conn.rolled_back is True


def test_auth_verify_code_wrong_code_returns_400_string_detail(app_client):
    _, client = app_client
    conn = FakeSequenceConn([
        FakeQueryResult(one={"id": 9, "code": "112233", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0}),
        FakeQueryResult(),  # UPDATE attempt_count
    ])
    app = client.app
    app.dependency_overrides[get_db_dep] = lambda: conn

    with patch("routers.auth.enforce_rate_limit"):
        response = client.post(
            "/api/auth/verify-code",
            json={"email": "user@example.com", "code": "999999"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert_detail_as_string(response.json(), "验证码已过期或无效")


def test_billing_get_order_not_found_returns_404_string_detail(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=101,
        email="vip@example.com",
        nickname="vip",
        effective_plan="free",
    )
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
    assert_detail_as_string(response.json(), "订单不存在")


def test_auth_login_invalid_password_returns_401_expected_message(app_client):
    _, client = app_client
    conn = FakeSequenceConn([
        FakeQueryResult(one={
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
    app = client.app
    app.dependency_overrides[get_db_dep] = lambda: conn

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.verify_password",
        return_value=False,
    ):
        response = client.post(
            "/api/auth/login",
            json={"email": "user@example.com", "password": "wrong-pass"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 401
    assert_detail_as_string(response.json(), "邮箱或密码错误")


def test_auth_forgot_password_throttled_returns_429_expected_message(app_client):
    _, client = app_client
    conn = FakeSequenceConn([
        FakeQueryResult(one={"id": 1, "email": "user@example.com"}),
        FakeQueryResult(one={"created_at": "2026-01-01T00:00:00+00:00"}),
    ])
    app = client.app
    app.dependency_overrides[get_db_dep] = lambda: conn

    with patch("routers.auth.enforce_rate_limit"):
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    app.dependency_overrides.clear()

    assert response.status_code == 429
    assert_detail_as_string(response.json(), "请求过于频繁，请 60 秒后再试")


def test_auth_reset_password_invalid_code_returns_400_expected_message(app_client):
    _, client = app_client
    conn = FakeSequenceConn([
        FakeQueryResult(one={"id": 31, "code": "223344", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0}),
        FakeQueryResult(),  # UPDATE attempt_count
    ])
    app = client.app
    app.dependency_overrides[get_db_dep] = lambda: conn

    with patch("routers.auth.enforce_rate_limit"):
        response = client.post(
            "/api/auth/reset-password",
            json={"email": "user@example.com", "code": "000000", "new_password": "newpass123"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert_detail_as_string(response.json(), "验证码无效或已过期")


def test_billing_cancel_closed_order_returns_409_expected_message(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=101,
        email="vip@example.com",
        nickname="vip",
        effective_plan="free",
    )
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
    assert_detail_as_string(response.json(), "该订单已关闭，无需重复取消")


def test_admin_requires_login_returns_401_expected_message(app_client):
    _, client = app_client

    response = client.get("/api/admin/orders")

    assert response.status_code == 401
    assert_detail_as_string(response.json(), "未登录或登录已过期")
