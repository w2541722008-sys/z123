from unittest.mock import patch

from auth import get_admin_user


ADMIN_ENDPOINTS = [
    "/api/admin/users",
    "/api/admin/orders",
    "/api/admin/dashboard/stats",
    "/api/admin/media-missing",
]


class _AuthConn:
    def execute(self, sql, params=None):
        return self

    def fetchone(self):
        return None

    def close(self):
        pass


def test_admin_endpoints_require_login(app_client):
    _, client = app_client

    for url in ADMIN_ENDPOINTS:
        response = client.get(url)
        assert response.status_code == 401
        assert response.json()["detail"] == "未登录或登录已过期"


def test_admin_endpoints_reject_non_admin_user(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_admin_user] = lambda: (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(status_code=403, detail="你没有管理后台权限")
    )
    try:
        for url in ADMIN_ENDPOINTS:
            response = client.get(url)
            assert response.status_code == 403
            assert response.json()["detail"] == "你没有管理后台权限"
    finally:
        app.dependency_overrides.clear()


def test_admin_endpoints_reject_invalid_token(app_client):
    _, client = app_client

    with patch("auth.get_conn", return_value=_AuthConn()):
        for url in ADMIN_ENDPOINTS:
            response = client.get(url, headers={"Authorization": "Bearer invalid_token"})
            assert response.status_code == 401
            assert response.json()["detail"] == "未登录或登录已过期"


def test_admin_endpoints_propagate_auth_dependency_error(app_client):
    _, client = app_client
    app = client.app
    app.dependency_overrides[get_admin_user] = lambda: (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(status_code=401, detail="token 已失效")
    )
    try:
        response = client.get("/api/admin/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "token 已失效"
