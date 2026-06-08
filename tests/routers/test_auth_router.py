"""
routers/auth 路由集成测试

覆盖：
  - /auth/me 端点
  - /auth/logout 端点
  - /auth/register 端点（注册正向流程）
  - /auth/login 端点（登录正向流程，bcrypt 用户）
  - /auth/forgot-password 端点
  - /auth/verify-code 端点
  - /auth/reset-password 端点
"""

import pytest
from unittest.mock import patch

from fastapi import HTTPException

from core.auth import CurrentUser, get_current_user
from conftest import FakeCursorConn, FakeSequenceConn, FakeQueryResult, FakeRow, override_db


def test_auth_me_returns_current_user_payload(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=7,
        email="admin@example.com",
        nickname="admin",
        plan_type="vip",
        effective_plan="vip",
        plan_expires_at="2099-01-01T00:00:00+00:00",
        is_admin=True,
        avatar_url="/avatar.png",
    )
    try:
        response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 7
    assert payload["email"] == "admin@example.com"
    assert payload["is_admin"] is True
    assert payload["plan_type"] == "vip"


def test_auth_logout_deletes_bearer_token(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1, email="u@example.com", nickname="u", effective_plan="free",
    )
    try:
        with patch("routers.auth.delete_token") as mock_delete_token:
            response = client.post(
                "/api/auth/logout",
                headers={"Authorization": "Bearer test_token_123"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_delete_token.assert_called_once_with("test_token_123")


def test_auth_logout_without_authorization_still_ok(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=2, email="u2@example.com", nickname="u2", effective_plan="free",
    )
    try:
        with patch("routers.auth.delete_token") as mock_delete_token:
            response = client.post("/api/auth/logout")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_delete_token.assert_not_called()


def test_forgot_password_returns_generic_message_for_unknown_email(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([FakeQueryResult(one=None)])

    with override_db(app, conn), patch("routers.auth.enforce_rate_limit"), \
         patch("routers.auth.send_reset_code_email") as mock_send_email:
        response = client.post("/api/auth/forgot-password", json={"email": "none@example.com"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_send_email.assert_not_called()


def test_forgot_password_success_commits_and_sends_email(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({"id": 11, "email": "user@example.com"})),
        FakeQueryResult(one=None),
        FakeQueryResult(one=None),
    ])

    with override_db(app, conn), patch("routers.auth.enforce_rate_limit"), \
         patch("services.password_reset_service.generate_reset_code", return_value="123456"), \
         patch("routers.auth.send_reset_code_email", return_value=True) as mock_send_email:
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert conn.committed is True
    mock_send_email.assert_called_once_with("user@example.com", "123456")


def test_forgot_password_recent_code_returns_429_and_rolls_back(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({"id": 11, "email": "user@example.com"})),
        FakeQueryResult(one=FakeRow({"created_at": "2026-01-01T00:00:00+00:00"})),
    ])

    with override_db(app, conn), patch("routers.auth.enforce_rate_limit"):
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 429
    assert "秒后再试" in response.json()["detail"]
    assert conn.rolled_back is True


def test_verify_code_success(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({
            "id": 9, "code": "112233",
            "expires_at": "2099-01-01T00:00:00+00:00", "used": 0,
        })),
    ])

    with override_db(app, conn), patch("routers.auth.enforce_rate_limit"):
        response = client.post(
            "/api/auth/verify-code",
            json={"email": "user@example.com", "code": "112233"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_verify_code_wrong_code_returns_400(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({
            "id": 9, "code": "112233",
            "expires_at": "2099-01-01T00:00:00+00:00", "used": 0, "attempt_count": 0,
        })),
        FakeQueryResult(rowcount=1),  # UPDATE attempt_count = attempt_count + 1
    ])

    with override_db(app, conn), patch("routers.auth.enforce_rate_limit"):
        response = client.post(
            "/api/auth/verify-code",
            json={"email": "user@example.com", "code": "999999"},
        )

    assert response.status_code == 400
    assert "验证码已过期或无效" in response.json()["detail"]


def test_reset_password_success_updates_password_and_marks_code_used(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({
            "id": 31, "code": "223344",
            "expires_at": "2099-01-01T00:00:00+00:00", "used": 0,
        })),
        FakeQueryResult(one=FakeRow({"id": 8, "email": "user@example.com"})),
        FakeQueryResult(one=None),
        FakeQueryResult(one=None),
        FakeQueryResult(one=None),
        FakeQueryResult(rowcount=0),  # DELETE access tokens (revoke)
        FakeQueryResult(rowcount=0),  # DELETE refresh tokens (revoke)
    ])

    with override_db(app, conn), patch("routers.auth.enforce_rate_limit"), \
         patch("services.password_reset_service.hash_password_bcrypt", return_value="new_hash"):
        response = client.post(
            "/api/auth/reset-password",
            json={"email": "user@example.com", "code": "223344", "new_password": "newpass123"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert conn.committed is True


def test_reset_password_invalid_code_returns_400_and_rolls_back(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({
            "id": 31, "code": "223344",
            "expires_at": "2099-01-01T00:00:00+00:00", "used": 0,
        })),
        FakeQueryResult(rowcount=1),  # UPDATE attempt_count
    ])

    with override_db(app, conn), patch("routers.auth.enforce_rate_limit"):
        response = client.post(
            "/api/auth/reset-password",
            json={"email": "user@example.com", "code": "000000", "new_password": "newpass123"},
        )

    assert response.status_code == 400
    assert "验证码无效或已过期" in response.json()["detail"]
    assert conn.rolled_back is True


def test_forgot_password_rate_limit_returns_429(app_client):
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([])

    with override_db(app, conn), patch(
        "routers.auth.enforce_rate_limit",
        side_effect=HTTPException(status_code=429, detail="找回密码请求过于频繁"),
    ):
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 429


# ============================================================
# /auth/register 正向流程
# ============================================================

def test_register_happy_path_creates_user_and_sets_auth_cookies(app_client):
    """正向流程：注册新用户，仅通过 HttpOnly Cookie 下发 token。"""
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=None),                          # 1. check_email_exists → 未注册
        FakeQueryResult(one=FakeRow({"id": 42})),           # 2. insert_user RETURNING id
        FakeQueryResult(rowcount=0),                        # 3. _cleanup_expired_tokens (refresh)
        FakeQueryResult(rowcount=1),                        # 4. INSERT refresh token
        FakeQueryResult(rowcount=0),                        # 5. _cleanup_expired_tokens (access)
        FakeQueryResult(rowcount=1),                        # 6. INSERT access token
    ])

    with override_db(app, conn), \
         patch("routers.auth.enforce_rate_limit"), \
         patch("routers.auth.hash_password_bcrypt", return_value="$2b$12$hashed_for_test"):
        response = client.post("/api/auth/register", json={
            "email": "newuser@example.com",
            "password": "SecurePass123!",
            "nickname": "NewUser",
        })

    assert response.status_code == 200
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert body["expires_in"] > 0
    assert body["user"]["id"] == 42
    assert body["user"]["email"] == "newuser@example.com"
    assert body["user"]["nickname"] == "NewUser"
    assert body["user"]["plan_type"] == "free"
    assert conn.committed is True

    # 验证 HttpOnly Cookie（响应体不能暴露 token）
    set_cookie = response.headers.get("set-cookie", "")
    assert "aifriend_session" in set_cookie
    assert "aifriend_refresh" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api" in set_cookie


def test_register_email_taken_returns_400(app_client):
    """重复邮箱注册返回 400。"""
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({"1": 1})),             # check_email_exists → 已注册
    ])

    with override_db(app, conn), \
         patch("routers.auth.enforce_rate_limit"):
        response = client.post("/api/auth/register", json={
            "email": "existing@example.com",
            "password": "SecurePass123!",
        })

    assert response.status_code == 400
    assert response.json()["detail"] == "该邮箱已被注册"
    assert conn.rolled_back is True


# ============================================================
# /auth/login 正向流程
# ============================================================

def test_login_happy_path_bcrypt_user_sets_auth_cookies(app_client):
    """正向流程：bcrypt 密码用户登录，仅通过 HttpOnly Cookie 下发 token。"""
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({
            "id": 7,
            "email": "bcryptuser@example.com",
            "nickname": "BCryptUser",
            "password_hash": "$2b$12$hashed_for_test",
            "password_algo": "bcrypt",
            "plan_type": "vip",
            "plan_expires_at": "2099-01-01T00:00:00+00:00",
            "avatar_url": "/avatars/7.png",
        })),                                                 # 1. find_user_by_email
        FakeQueryResult(rowcount=0),                         # 2. _cleanup_expired_tokens (refresh)
        FakeQueryResult(rowcount=1),                         # 3. INSERT refresh token
        FakeQueryResult(rowcount=0),                         # 4. _cleanup_expired_tokens (access)
        FakeQueryResult(rowcount=1),                         # 5. INSERT access token
    ])

    with override_db(app, conn), \
         patch("routers.auth.enforce_rate_limit"), \
         patch("routers.auth.verify_password", return_value=True):
        response = client.post("/api/auth/login", json={
            "email": "bcryptuser@example.com",
            "password": "SecurePass123!",
        })

    assert response.status_code == 200
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert body["expires_in"] > 0
    assert body["user"]["id"] == 7
    assert body["user"]["email"] == "bcryptuser@example.com"
    assert body["user"]["plan_type"] == "vip"
    assert conn.committed is True

    # 验证 HttpOnly Cookie
    set_cookie = response.headers.get("set-cookie", "")
    assert "aifriend_session" in set_cookie
    assert "aifriend_refresh" in set_cookie
    assert "HttpOnly" in set_cookie


def test_refresh_uses_refresh_cookie_and_does_not_return_access_token(app_client):
    """refresh 成功时设置新 access cookie，但响应体不暴露 access token。"""
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([])

    with override_db(app, conn), patch("routers.auth.rotate_access_token", return_value="new_access_token"):
        response = client.post(
            "/api/auth/refresh",
            cookies={"aifriend_refresh": "refresh_token_cookie"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "access_token" not in body
    set_cookie = response.headers.get("set-cookie", "")
    assert "aifriend_session" in set_cookie
    assert "HttpOnly" in set_cookie


def test_refresh_ignores_authorization_header_without_refresh_cookie(app_client):
    """refresh 不接受 JS 可读 Authorization token 作为 refresh token 来源。"""
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([])

    with override_db(app, conn), patch("routers.auth.rotate_access_token") as mock_rotate:
        response = client.post(
            "/api/auth/refresh",
            headers={"Authorization": "Bearer header_refresh_token"},
        )

    assert response.status_code == 401
    mock_rotate.assert_not_called()


def test_logout_others_ignores_authorization_refresh_fallback(app_client):
    """踢出其他设备只用 HttpOnly refresh cookie 保留当前设备，不接受 JS 可读 header fallback。"""
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=7, email="u@example.com", nickname="u", effective_plan="free",
    )
    conn = FakeSequenceConn([])

    try:
        with override_db(app, conn), patch("routers.auth.revoke_user_device_tokens", return_value=3) as mock_revoke:
            response = client.post(
                "/api/auth/logout-others",
                headers={"Authorization": "Bearer header_refresh_token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["deleted_devices"] == 3
    mock_revoke.assert_called_once_with(7, "", conn=conn)


def test_login_wrong_password_returns_401(app_client):
    """密码错误返回 401，不区分邮箱不存在和密码错误。"""
    _, client = app_client
    app = client.app
    conn = FakeSequenceConn([
        FakeQueryResult(one=FakeRow({
            "id": 7,
            "email": "test@example.com",
            "nickname": "TestUser",
            "password_hash": "$2b$12$hashed",
            "password_algo": "bcrypt",
            "plan_type": "free",
            "plan_expires_at": "",
            "avatar_url": None,
        })),
    ])

    with override_db(app, conn), \
         patch("routers.auth.enforce_rate_limit"), \
         patch("routers.auth.verify_password", return_value=False):
        response = client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "wrongpassword",
        })

    assert response.status_code == 401
    assert response.json()["detail"] == "邮箱或密码错误"
    assert conn.rolled_back is True
