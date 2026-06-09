"""Auth session, refresh, and logout API behavior."""

from unittest.mock import patch

from fastapi import HTTPException

from core.auth import CurrentUser, get_current_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


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
