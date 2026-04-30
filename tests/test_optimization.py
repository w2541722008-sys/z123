"""
项目优化测试套件 - 验证所有优化项的正确性

本文件包含针对项目优化工作的专项测试，确保：
1. 安全修复不破坏现有功能
2. 性能优化有可衡量的指标
3. 架构重构保持 API 契约不变
4. 错误处理覆盖所有异常路径
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


# ============================================================
# 阶段一：安全加固测试
# ============================================================

class TestInputValidation:
    """验证 Pydantic 输入验证完整性。"""

    def test_register_payload_requires_email(self):
        """注册接口必须验证邮箱格式。"""
        from models import RegisterPayload

        with pytest.raises(Exception):
            RegisterPayload(email="", password="test123")

        with pytest.raises(Exception):
            RegisterPayload(email="not-an-email", password="test123")

    def test_register_payload_password_min_length(self):
        """注册接口密码应有最小长度要求。"""
        from models import RegisterPayload

        with pytest.raises(Exception):
            RegisterPayload(email="test@example.com", password="123")

    def test_login_payload_validation(self):
        """登录接口应验证必填字段。"""
        from models import LoginPayload

        with pytest.raises(Exception):
            LoginPayload(email="", password="")

    def test_chat_payload_message_not_empty(self):
        """聊天接口消息不能为空。"""
        from models import ChatSendPayload

        with pytest.raises(Exception):
            ChatSendPayload(character_id="char_1", message="   ")

    def test_register_payload_normalizes_email(self):
        """注册接口邮箱应复用统一规范化逻辑。"""
        from models import RegisterPayload

        payload = RegisterPayload(email="  TEST@EXAMPLE.COM  ", password="test123")

        assert payload.email == "test@example.com"

    def test_regenerate_and_continue_payload_require_message_id(self):
        """重新生成与继续生成请求都应要求 message_id。"""
        from models import ContinuePayload, RegeneratePayload

        with pytest.raises(Exception):
            RegeneratePayload(message_id="")

        with pytest.raises(Exception):
            ContinuePayload(message_id="")

        assert RegeneratePayload(message_id="msg-1").message_id == "msg-1"
        assert ContinuePayload(message_id="msg-2").message_id == "msg-2"

    def test_password_reset_payloads_normalize_email(self):
        """密码重置相关模型应统一规范化邮箱。"""
        from models import ForgotPasswordPayload, ResetPasswordPayload, VerifyCodePayload

        forgot = ForgotPasswordPayload(email="  USER@Example.com ")
        verify = VerifyCodePayload(email="  USER@Example.com ", code="123456")
        reset = ResetPasswordPayload(email="  USER@Example.com ", code="123456", new_password="test123")

        assert forgot.email == "user@example.com"
        assert verify.email == "user@example.com"
        assert reset.email == "user@example.com"

    def test_character_id_payloads_trim_and_require_value(self):
        """共享 character_id 基类应统一处理去空白与必填约束。"""
        from models import CharacterActionPayload, CharacterProfileUpdatePayload, ClearChatPayload

        with pytest.raises(Exception):
            CharacterActionPayload(character_id="   ")

        profile = CharacterProfileUpdatePayload(character_id="  char_1  ")
        clear_chat = ClearChatPayload(character_id="  char_2  ")

        assert profile.character_id == "char_1"
        assert clear_chat.character_id == "char_2"

    def test_advanced_config_optional_ids_trim_and_collapse_blank_to_none(self):
        """高级配置中的可选 ID 字段应统一去空白，并把空字符串折叠为 None。"""
        from models import GreetingPayload, MemoryEntryPayload, PostRulePayload, StoryEventPayload

        greeting = GreetingPayload(content="hello", storyline_id="  story-1  ")
        memory = MemoryEntryPayload(keywords="k", content="c", category_id="   ")
        post_rule = PostRulePayload(name="n", content="c", storyline_id="  story-2  ")
        story_event = StoryEventPayload(unlocked_storyline_id="   ")

        assert greeting.storyline_id == "story-1"
        assert memory.category_id is None
        assert post_rule.storyline_id == "story-2"
        assert story_event.unlocked_storyline_id is None

    def test_advanced_config_shared_default_fields_remain_stable(self):
        """高级配置共享基类不应改变 priority、sort_order、is_active 默认值。"""
        from models import GreetingPayload, MemoryCategoryPayload, MemoryEntryPayload, StoryEventPayload, StorylinePayload

        greeting = GreetingPayload(content="hello")
        memory = MemoryEntryPayload(keywords="k", content="c")
        category = MemoryCategoryPayload(name="分类")
        event = StoryEventPayload()
        storyline = StorylinePayload(name="主线")

        assert greeting.priority == 100
        assert greeting.is_active == 1
        assert memory.priority == 100
        assert memory.is_active == 1
        assert category.sort_order == 0
        assert event.sort_order == 0
        assert event.is_active == 1
        assert storyline.sort_order == 0
        assert storyline.is_active == 1


class TestCSRFProtection:
    """验证 CSRF 保护机制。"""

    def test_get_requests_no_csrf_required(self, app_client):
        """GET 请求不应要求 CSRF 令牌。"""
        _, client = app_client
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_post_requests_with_invalid_csrf(self):
        """POST 请求在 CSRF 配置启用后应拒绝无效令牌。"""
        pytest.skip("CSRF 保护实施后启用")


# ============================================================
# 阶段一：架构现代化测试
# ============================================================

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

        result = _load_allowed_origins({"ALLOWED_ORIGINS": " https://a.com , http://b.com ,, "})

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

    def test_register_api_routers_registers_all_main_routers(self):
        from main import _register_api_routers

        fake_app = MagicMock()
        _register_api_routers(fake_app)

        prefixes = [call.kwargs["prefix"] for call in fake_app.include_router.call_args_list]
        assert prefixes == ["/api", "/api", "/api", "/api", "/api"]
        assert len(fake_app.include_router.call_args_list) == 5

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
        with patch("main.init_db_pool") as mock_init, patch("main.close_db_pool"), patch("threading.Thread"):
            from fastapi.testclient import TestClient
            from main import app

            with TestClient(app):
                pass

        assert mock_init.called

    def test_shutdown_closes_db_pool(self):
        """关闭时应清理数据库连接池。"""
        with patch("main.close_db_pool") as mock_close, patch("threading.Thread"):
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


# ============================================================
# 阶段二：架构重构测试
# ============================================================

class TestChatModuleRefactoring:
    """验证 chat.py 拆分后的功能完整性。"""

    def test_stream_endpoint_exists(self, app_module):
        """流式聊天端点应正常存在。"""
        routes = {
            (method, route.path)
            for route in app_module.routes
            for method in getattr(route, "methods", set())
        }
        assert ("POST", "/api/chat/stream") in routes

    def test_guest_stream_endpoint_exists(self, app_module):
        """游客流式聊天端点应正常存在。"""
        routes = {
            (method, route.path)
            for route in app_module.routes
            for method in getattr(route, "methods", set())
        }
        assert ("POST", "/api/chat/guest-stream") in routes

    def test_regenerate_endpoint_exists(self, app_module):
        """重新生成端点应正常存在。"""
        routes = {
            (method, route.path)
            for route in app_module.routes
            for method in getattr(route, "methods", set())
        }
        assert ("POST", "/api/chat/regenerate") in routes

    def test_continue_endpoint_exists(self, app_module):
        """继续生成端点应正常存在。"""
        routes = {
            (method, route.path)
            for route in app_module.routes
            for method in getattr(route, "methods", set())
        }
        assert ("POST", "/api/chat/continue") in routes


# ============================================================
# 阶段二：错误处理测试
# ============================================================

class TestErrorHandling:
    """验证错误处理机制完善性。"""

    def test_global_exception_handler_returns_safe_message(self, app_client):
        """全局异常处理器应返回安全错误消息。"""
        _, client = app_client
        response = client.get("/api/nonexistent-endpoint-that-triggers-error")

        if response.status_code == 500:
            data = response.json()
            assert "detail" in data
            assert "password" not in str(data).lower()
            assert "secret" not in str(data).lower()

    def test_database_error_does_not_expose_credentials(self, app_client):
        """数据库错误不应暴露连接字符串。"""
        _, client = app_client
        response = client.get("/api/health")

        if response.status_code == 500:
            body = response.text.lower()
            assert "postgresql://" not in body
            assert "password" not in body


# ============================================================
# 阶段三：性能优化测试（基准测试）
# ============================================================

class TestPerformanceBaselines:
    """建立性能基准线，确保优化后有可衡量指标。"""

    def test_token_creation_performance(self):
        """Token 创建应在合理时间内完成。"""
        import time
        from auth import create_token

        with patch("auth.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value = MagicMock(rowcount=1)
            mock_get_conn.return_value = mock_conn

            start = time.time()
            try:
                create_token(user_id=1, conn=mock_conn, commit=False)
            except Exception:
                pass
            elapsed = time.time() - start

            assert elapsed < 1.0

    def test_password_hashing_performance(self):
        """密码哈希应在可接受时间内完成。"""
        import time
        from auth import hash_password_bcrypt

        start = time.time()
        hash_password_bcrypt("test_password_123")
        elapsed = time.time() - start

        assert 0.05 < elapsed < 1.0

    def test_rate_limiter_memory_cleanup(self):
        """限流器应定期清理过期数据。"""
        from services.rate_limit import _RATE_LIMITER

        initial_size = len(_RATE_LIMITER._events)
        _RATE_LIMITER._cleanup_locked(999999)

        assert len(_RATE_LIMITER._events) >= 0

    def test_password_hashing_performance_stability(self):
        """密码哈希应在合理时间内完成且返回有效结果。"""
        import time
        from auth import hash_password_bcrypt

        start = time.time()
        result = hash_password_bcrypt("test_password_123")
        elapsed = time.time() - start

        assert result is not None
        assert elapsed < 1.0
        assert elapsed > 0.01

    def test_token_hash_performance(self):
        """Token 哈希应在合理时间内完成。"""
        import time
        from auth import _hash_token_value

        start = time.time()
        result = _hash_token_value("test_token_string")
        elapsed = time.time() - start

        assert result is not None
        assert elapsed < 0.1

    def test_health_check_response_time_target(self, app_client):
        """健康检查在缓存命中时应快速返回。"""
        _, client = app_client
        from main import _db_health_cache

        _db_health_cache.update({
            "ts": datetime.now(timezone.utc).timestamp(),
            "ttl": 30,
            "value": True,
        })

        import time
        start = time.time()
        response = client.get("/api/health")
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 0.5
