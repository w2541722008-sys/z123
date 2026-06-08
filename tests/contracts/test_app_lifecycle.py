"""
应用生命周期与基础端点契约测试
"""

from unittest.mock import MagicMock, patch


class TestLifespanMigration:
    """验证 FastAPI Lifespan 迁移正确性。"""

    def test_app_has_lifespan_context(self, app_module):
        """应用应使用 lifespan 而非 on_event。"""
        assert app_module.router.lifespan_context is not None

    def test_default_allowed_origins_contains_local_development_hosts(self):
        from main import _default_allowed_origins

        assert _default_allowed_origins() == [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]

    def test_load_allowed_origins_reads_env_and_strips_values(self):
        from main import _load_allowed_origins

        result = _load_allowed_origins(
            {"ALLOWED_ORIGINS": " https://a.com , http://b.com ,, "}
        )

        assert result == ["https://a.com", "http://b.com"]

    def test_tracked_request_paths_covers_auth_and_chat_endpoints(self):
        from main import _tracked_request_paths

        assert _tracked_request_paths() == {
            "/api/auth/register",
            "/api/auth/login",
            "/api/chat/send",
            "/api/chat/stream",
            "/api/chat/guest-stream",
            "/api/chat/regenerate",
            "/api/chat/continue",
        }

    def test_background_db_tasks_can_be_disabled_for_tests(self):
        from main import _should_start_background_db_tasks

        assert _should_start_background_db_tasks({}) is True
        assert _should_start_background_db_tasks(
            {"AIFRIEND_DISABLE_BACKGROUND_DB_TASKS": "1"}
        ) is False
        assert _should_start_background_db_tasks(
            {"AIFRIEND_DISABLE_BACKGROUND_DB_TASKS": "true"}
        ) is False

    def test_register_api_routers_registers_all_main_routers(self):
        from main import _register_api_routers

        fake_app = MagicMock()
        _register_api_routers(fake_app)

        assert len(fake_app.include_router.call_args_list) == 6
        prefixes = [
            call.kwargs["prefix"] for call in fake_app.include_router.call_args_list
        ]
        assert prefixes == ["/api"] * 6

    def test_serve_html_file_returns_404_when_missing(self, tmp_path):
        from main import _serve_html_file

        response = _serve_html_file(tmp_path / "missing.html", "<h1>not found</h1>")

        assert response.status_code == 404
        assert response.body.decode("utf-8") == "<h1>not found</h1>"

    def test_serve_html_file_reads_existing_file(self, tmp_path):
        from main import _serve_html_file

        file_path = tmp_path / "index.html"
        file_path.write_text("<h1>Hello</h1>", encoding="utf-8")

        response = _serve_html_file(file_path, "<h1>not found</h1>")

        assert response.status_code == 200
        assert response.body.decode("utf-8") == "<h1>Hello</h1>"

    def test_startup_initializes_db(self):
        """启动时应初始化数据库连接池。"""
        with patch("main.init_db_pool") as mock_init, patch("main.close_db_pool"):
            from fastapi.testclient import TestClient
            from main import app

            with TestClient(app):
                pass

        assert mock_init.called

    def test_shutdown_closes_db_pool(self):
        """关闭时应清理数据库连接池。"""
        with patch("main.close_db_pool") as mock_close:
            from fastapi.testclient import TestClient
            from main import app

            with TestClient(app):
                pass

        assert mock_close.called


class TestHealthCheckOptimization:
    """验证健康检查端点优化。"""

    def test_health_check_returns_basic_info(self, app_client):
        """健康检查应返回基本状态信息。"""
        _, client = app_client
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "time" in data

    def test_health_check_supports_head_method(self, app_client):
        """外部监控使用 HEAD 请求时也应返回 200。"""
        _, client = app_client
        response = client.head("/api/health")

        assert response.status_code == 200
        assert response.content == b""
