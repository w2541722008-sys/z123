"""Register and login API behavior."""

from unittest.mock import patch

from fastapi import HTTPException

from core.auth import CurrentUser, get_current_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn


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
