from unittest.mock import patch

from fastapi import HTTPException

from auth import CurrentUser, get_current_user


class _SequenceConn:
    def __init__(self, one_results):
        self._one_results = list(one_results)
        self._current_one = None
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._current_one = self._one_results.pop(0) if self._one_results else None
        return self

    def fetchone(self):
        return self._current_one

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


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
    assert payload["nickname"] == "admin"
    assert payload["is_admin"] is True
    assert payload["avatar_url"] == "/avatar.png"
    assert payload["plan_type"] == "vip"


def test_auth_logout_deletes_bearer_token(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1,
        email="u@example.com",
        nickname="u",
        effective_plan="free",
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
        id=2,
        email="u2@example.com",
        nickname="u2",
        effective_plan="free",
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
    conn = _SequenceConn([None])

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.get_conn",
        return_value=conn,
    ), patch("routers.auth.send_reset_code_email") as mock_send_email:
        response = client.post("/api/auth/forgot-password", json={"email": "none@example.com"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "如果该邮箱已注册" in response.json()["message"]
    assert conn.committed is False
    assert conn.rolled_back is False
    assert conn.closed is True
    mock_send_email.assert_not_called()


def test_forgot_password_success_commits_and_sends_email(app_client):
    _, client = app_client
    conn = _SequenceConn([
        {"id": 11, "email": "user@example.com"},
        None,
        None,
    ])

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.get_conn",
        return_value=conn,
    ), patch("routers.auth.generate_reset_code", return_value="123456"), patch(
        "routers.auth.send_reset_code_email",
        return_value=True,
    ) as mock_send_email:
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True
    mock_send_email.assert_called_once_with("user@example.com", "123456")


def test_forgot_password_recent_code_returns_429_and_rolls_back(app_client):
    _, client = app_client
    conn = _SequenceConn([
        {"id": 11, "email": "user@example.com"},
        {"created_at": "2026-01-01T00:00:00+00:00"},
    ])

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.get_conn",
        return_value=conn,
    ):
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 429
    assert "60 秒后再试" in response.json()["detail"]
    assert conn.committed is False
    assert conn.rolled_back is True


def test_verify_code_success(app_client):
    _, client = app_client
    conn = _SequenceConn([
        {"id": 9, "code": "112233", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0},
    ])

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.get_conn",
        return_value=conn,
    ):
        response = client.post(
            "/api/auth/verify-code",
            json={"email": "user@example.com", "code": "112233"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert conn.closed is True


def test_verify_code_wrong_code_returns_400(app_client):
    _, client = app_client
    conn = _SequenceConn([
        {"id": 9, "code": "112233", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0},
    ])

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.get_conn",
        return_value=conn,
    ):
        response = client.post(
            "/api/auth/verify-code",
            json={"email": "user@example.com", "code": "999999"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "验证码错误"


def test_reset_password_success_updates_password_and_marks_code_used(app_client):
    _, client = app_client
    conn = _SequenceConn([
        {"id": 31, "code": "223344", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0},
        {"id": 8, "email": "user@example.com"},
        None,
        None,
        None,
    ])

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.get_conn",
        return_value=conn,
    ), patch("routers.auth.hash_password_bcrypt", return_value="new_hash"), patch(
        "routers.auth.utc_now_iso",
        return_value="2026-04-24T10:00:00+00:00",
    ):
        response = client.post(
            "/api/auth/reset-password",
            json={"email": "user@example.com", "code": "223344", "new_password": "newpass123"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True


def test_reset_password_invalid_code_returns_400_and_rolls_back(app_client):
    _, client = app_client
    conn = _SequenceConn([
        {"id": 31, "code": "223344", "expires_at": "2099-01-01T00:00:00+00:00", "used": 0},
    ])

    with patch("routers.auth.enforce_rate_limit"), patch(
        "routers.auth.get_conn",
        return_value=conn,
    ):
        response = client.post(
            "/api/auth/reset-password",
            json={"email": "user@example.com", "code": "000000", "new_password": "newpass123"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "验证码无效或已过期"
    assert conn.committed is False
    assert conn.rolled_back is True


def test_forgot_password_rate_limit_returns_429(app_client):
    _, client = app_client
    with patch(
        "routers.auth.enforce_rate_limit",
        side_effect=HTTPException(status_code=429, detail="找回密码请求过于频繁"),
    ):
        response = client.post("/api/auth/forgot-password", json={"email": "user@example.com"})

    assert response.status_code == 429
