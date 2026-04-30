"""
核心 API 集成测试

测试项目核心功能：
1. 健康检查端点
2. 认证流程（注册/登录/Token 验证）
3. Pydantic 输入验证
4. XSS 防护机制

注意：这些测试需要 mock 数据库连接，
真实集成测试需要在测试数据库环境中运行。
"""

import json
import pytest
from unittest.mock import MagicMock, call, patch

from auth import CurrentUser, get_admin_user, get_current_user, get_optional_user


class _QueryResult:
    def __init__(self, *, one=None, many=None):
        self._one = one
        self._many = many or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _SequenceConn:
    def __init__(self, results):
        self._results = list(results)

    def execute(self, sql, params=None):
        if not self._results:
            raise AssertionError(f"unexpected query: {sql}")
        return self._results.pop(0)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


# ============================================================
# 健康检查端点测试
# ============================================================

class TestHealthEndpoint:
    """测试健康检查端点功能。"""

    def test_health_endpoint_returns_structure(self, app_client):
        """健康检查应返回正确的响应结构。"""
        _, client = app_client

        with patch("main.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []

            response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "time" in data
            assert "database" in data
            assert "config" in data
            assert "media" in data
            assert "media_missing" in data

    def test_health_endpoint_db_failure(self, app_client):
        """数据库失败时健康检查应返回 degraded 状态。"""
        _, client = app_client
        from main import _db_health_cache
        from main import _media_health_cache

        _db_health_cache["ts"] = 0
        _media_health_cache["ts"] = 0
        with patch("main.get_conn", side_effect=RuntimeError("db down")):
            response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is False
        assert "time" in data
        assert "config" in data
        assert "media" in data
        assert "media_missing" in data

    def test_health_endpoint_media_missing_marks_degraded(self, app_client):
        """媒体资源缺失时健康检查应降级并返回缺失数量。"""
        _, client = app_client
        from main import _db_health_cache
        from main import _media_health_cache

        _db_health_cache["ok"] = True
        _db_health_cache["ts"] = 0
        _media_health_cache["ts"] = 0

        with patch("main.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                {"id": "c1", "avatar_url": "avatars/missing.jpg", "cover_url": None}
            ]

            response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["media"] is False
        assert data["media_missing"] >= 1

    def test_admin_media_missing_returns_list_payload(self, app_client):
        """管理后台媒体缺失接口应返回稳定结构。"""
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch(
                "main._check_media_health",
                return_value={
                    "ok": False,
                    "missing_count": 7,
                    "samples": ["c1:avatar_url:avatars/missing.jpg", "c2:cover_url:covers/missing.jpg"],
                },
            ) as mock_check:
                response = client.get("/api/admin/media-missing")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": False,
            "missing_count": 7,
            "items": ["c1:avatar_url:avatars/missing.jpg", "c2:cover_url:covers/missing.jpg"],
            "truncated": True,
        }
        mock_check.assert_called_once_with(force=False)

    def test_admin_media_missing_supports_refresh_query(self, app_client):
        """管理后台媒体缺失接口应支持 refresh 强制刷新缓存。"""
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch(
                "main._check_media_health",
                return_value={"ok": True, "missing_count": 0, "samples": []},
            ) as mock_check:
                response = client.get("/api/admin/media-missing", params={"refresh": "true"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "missing_count": 0,
            "items": [],
            "truncated": False,
        }
        mock_check.assert_called_once_with(force=True)


# ============================================================
# 认证流程测试
# ============================================================

class TestAuthFlow:
    """测试认证流程。"""

    def test_login_validation_requires_email(self):
        """登录接口应验证邮箱必填。"""
        from models import LoginPayload

        with pytest.raises(Exception):
            LoginPayload(email="", password="test123")

    def test_login_validation_requires_password(self):
        """登录接口应验证密码必填。"""
        from models import LoginPayload

        with pytest.raises(Exception):
            LoginPayload(email="test@example.com", password="")

    def test_login_validation_invalid_email_format(self):
        """登录接口应验证邮箱格式。"""
        from models import LoginPayload

        with pytest.raises(Exception):
            LoginPayload(email="not-an-email", password="test123")

    def test_login_validation_valid_input(self):
        """登录接口应接受有效输入。"""
        from models import LoginPayload

        payload = LoginPayload(email="test@example.com", password="test123")
        assert payload.email == "test@example.com"
        assert payload.password == "test123"

    def test_register_validation_email_format(self):
        """注册接口应验证邮箱格式。"""
        from models import RegisterPayload

        with pytest.raises(Exception):
            RegisterPayload(email="invalid", password="test123")

    def test_register_validation_password_min_length(self):
        """注册接口密码应有最小长度。"""
        from models import RegisterPayload

        with pytest.raises(Exception):
            RegisterPayload(email="test@example.com", password="12345")

    def test_register_validation_nickname_sanitization(self):
        """注册接口应处理昵称前后空格。"""
        from models import RegisterPayload

        payload = RegisterPayload(
            email="test@example.com",
            password="test123",
            nickname="  testuser  "
        )
        assert payload.nickname == "testuser"


# ============================================================
# Chat API 测试
# ============================================================

class TestChatAPI:
    """测试聊天相关 API。"""

    def test_chat_send_payload_requires_character_id(self):
        """聊天发送应验证角色 ID。"""
        from models import ChatSendPayload

        with pytest.raises(Exception):
            ChatSendPayload(character_id="", message="Hello")

    def test_chat_send_payload_requires_message(self):
        """聊天发送应验证消息内容。"""
        from models import ChatSendPayload

        with pytest.raises(Exception):
            ChatSendPayload(character_id="char_1", message="   ")

    def test_chat_send_payload_message_max_length(self):
        """聊天消息应有最大长度限制。"""
        from models import ChatSendPayload

        with pytest.raises(Exception):
            ChatSendPayload(
                character_id="char_1",
                message="x" * 3000
            )

    def test_guest_message_role_validation(self):
        """游客消息应验证 role 字段。"""
        from models import GuestMessageItem

        with pytest.raises(Exception):
            GuestMessageItem(role="invalid", content="Hello")

    def test_guest_message_valid_input(self):
        """游客消息应接受有效输入。"""
        from models import GuestMessageItem

        item = GuestMessageItem(role="user", content="Hello")
        assert item.role == "user"
        assert item.content == "Hello"

    def test_guest_message_content_sanitization(self):
        """游客消息内容应去除前后空格。"""
        from models import GuestMessageItem

        item = GuestMessageItem(role="user", content="  Hello  ")
        assert item.content == "Hello"


# ============================================================
# Pydantic 模型增强测试
# ============================================================

class TestPydanticValidation:
    """测试 Pydantic 模型验证增强。"""

    def test_email_lowercase_conversion(self):
        """邮箱应转换为小写。"""
        from models import LoginPayload

        payload = LoginPayload(email="TEST@EXAMPLE.COM", password="test123")
        assert payload.email == "test@example.com"

    def test_email_whitespace_trimming(self):
        """邮箱应去除前后空格。"""
        from models import LoginPayload

        payload = LoginPayload(email="  test@example.com  ", password="test123")
        assert payload.email == "test@example.com"

    def test_password_max_length(self):
        """密码应有最大长度限制。"""
        from models import RegisterPayload

        with pytest.raises(Exception):
            RegisterPayload(
                email="test@example.com",
                password="x" * 100
            )

    def test_message_content_stripping(self):
        """消息内容应去除前后空格。"""
        from models import ChatSendPayload

        payload = ChatSendPayload(
            character_id="char_1",
            message="  Hello World  "
        )
        assert payload.message == "Hello World"

    def test_register_payload_shares_email_normalizer(self):
        """注册模型应与登录模型保持一致的邮箱规范化行为。"""
        from models import LoginPayload, RegisterPayload

        login_payload = LoginPayload(email="  USER@Example.com  ", password="test123")
        register_payload = RegisterPayload(email="  USER@Example.com  ", password="test123")

        assert login_payload.email == "user@example.com"
        assert register_payload.email == "user@example.com"

    def test_regenerate_and_continue_payload_share_message_id_contract(self):
        """重新生成与继续生成应共享相同 message_id 契约。"""
        from models import ContinuePayload, RegeneratePayload

        assert RegeneratePayload(message_id="abc").message_id == "abc"
        assert ContinuePayload(message_id="def").message_id == "def"

        with pytest.raises(Exception):
            RegeneratePayload(message_id="")

        with pytest.raises(Exception):
            ContinuePayload(message_id="")

    def test_password_reset_models_share_email_normalizer(self):
        """密码重置相关模型应复用统一邮箱规范化逻辑。"""
        from models import ForgotPasswordPayload, ResetPasswordPayload, VerifyCodePayload

        forgot = ForgotPasswordPayload(email="  USER@Example.com ")
        verify = VerifyCodePayload(email="  USER@Example.com ", code="123456")
        reset = ResetPasswordPayload(email="  USER@Example.com ", code="123456", new_password="test123")

        assert forgot.email == "user@example.com"
        assert verify.email == "user@example.com"
        assert reset.email == "user@example.com"

    def test_admin_user_edit_optional_email_is_normalized(self):
        """管理后台用户编辑模型的可选邮箱应在传值时被规范化。"""
        from models import AdminUserEditPayload

        payload = AdminUserEditPayload(email="  USER@Example.com ")
        empty_payload = AdminUserEditPayload()

        assert payload.email == "user@example.com"
        assert empty_payload.email is None

    def test_character_id_models_share_trimmed_contract(self):
        """多个 character_id 请求体应共享去空白后的统一约束。"""
        from models import CharacterActionPayload, CharacterProfileUpdatePayload, ClearChatPayload, GuestChatPayload

        action = CharacterActionPayload(character_id="  char_1  ")
        profile = CharacterProfileUpdatePayload(character_id="  char_2  ")
        clear_chat = ClearChatPayload(character_id="  char_3  ")
        guest = GuestChatPayload(character_id="  char_4  ", message="hello")

        assert action.character_id == "char_1"
        assert profile.character_id == "char_2"
        assert clear_chat.character_id == "char_3"
        assert guest.character_id == "char_4"

        with pytest.raises(Exception):
            GuestChatPayload(character_id="   ", message="hello")

    def test_advanced_config_optional_ids_share_trimmed_contract(self):
        """高级配置模型的可选 ID 字段应共享相同去空白契约。"""
        from models import GreetingPayload, MemoryEntryPayload, PostRulePayload, StoryEventPayload

        greeting = GreetingPayload(content="hello", storyline_id="  story-1  ")
        memory = MemoryEntryPayload(keywords="k", content="c", category_id="  category-1  ")
        post_rule = PostRulePayload(name="rule", content="body", storyline_id="   ")
        event = StoryEventPayload(unlocked_storyline_id="  storyline-9  ")

        assert greeting.storyline_id == "story-1"
        assert memory.category_id == "category-1"
        assert post_rule.storyline_id is None
        assert event.unlocked_storyline_id == "storyline-9"

    def test_advanced_config_shared_default_fields_are_preserved(self):
        """高级配置共享基类重构后，默认值应保持不变。"""
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


class TestPlanServiceContracts:
    def test_serialize_plan_info_handles_active_and_expired_paid_membership(self):
        from services.plan_service import serialize_plan_info

        active = serialize_plan_info(" vip ", "2099-01-01T00:00:00+00:00")
        expired = serialize_plan_info("svip", "2000-01-01T00:00:00+00:00")

        assert active == {
            "plan_type": "vip",
            "effective_plan": "vip",
            "plan_expires_at": "2099-01-01T00:00:00+00:00",
            "plan_display_name": "VIP",
            "is_paid_plan": True,
            "membership_expired": False,
        }
        assert expired == {
            "plan_type": "svip",
            "effective_plan": "free",
            "plan_expires_at": "2000-01-01T00:00:00+00:00",
            "plan_display_name": "注册用户",
            "is_paid_plan": False,
            "membership_expired": True,
        }

    def test_plan_access_and_policy_share_stable_membership_semantics(self):
        from fastapi import HTTPException
        from services.plan_service import can_access_required_plan, ensure_plan_access, get_plan_policy

        assert can_access_required_plan("vip", "free") is True
        assert can_access_required_plan("free", "vip") is False

        ensure_plan_access("svip", "vip")

        with pytest.raises(HTTPException) as exc_info:
            ensure_plan_access("free", "svip")

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "当前内容仅 SVIP 可访问"

        policy = get_plan_policy(" unknown ")
        assert policy["plan_type"] == "guest"
        assert policy["display_name"] == "游客"
        assert policy["model_profile"] == "basic"
        assert isinstance(policy["token_limit"], int)
        assert policy["token_limit"] > 0
        assert isinstance(policy["max_output_tokens"], int)
        assert policy["max_output_tokens"] > 0

    def test_serialize_character_for_client_exposes_required_plan_semantics(self):
        from routers.characters import _serialize_character_for_client

        conn = _SequenceConn([])
        row = _Row(
            {
                "id": "char_vip",
                "name": "VIP角色",
                "abbr": "VIP",
                "subtitle": "仅会员可见",
                "avatar_url": "avatar.png",
                "cover_url": "",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["romance"]',
                "card_type": None,
                "home_priority": 9,
                "required_plan": " vip ",
            }
        )

        result = _serialize_character_for_client(conn, row)

        assert result["required_plan"] == "vip"
        assert result["required_plan_label"] == "VIP"
        assert result["avatar_url"] == "/api/avatar/char_vip"
        assert result["cover_url"] == "/api/cover/char_vip"
        assert result["display_name"] == "VIP角色"
        assert result["sign"] == "仅会员可见"

    def test_character_list_filters_by_viewer_plan_and_keeps_labels_stable(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=12, email="vip@example.com", nickname="vip", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(many=[
                _Row({
                    "id": "char_guest",
                    "name": "游客角色",
                    "abbr": "G",
                    "subtitle": "guest",
                    "avatar_url": "",
                    "cover_url": "",
                    "description": "guest desc",
                    "opening_message": "hello",
                    "tags": '[]',
                    "card_type": "intimate",
                    "home_priority": 1,
                    "is_visible": 1,
                    "required_plan": "guest",
                }),
                _Row({
                    "id": "char_vip",
                    "name": "VIP角色",
                    "abbr": "V",
                    "subtitle": "vip",
                    "avatar_url": "",
                    "cover_url": "",
                    "description": "vip desc",
                    "opening_message": "hi",
                    "tags": '[]',
                    "card_type": "intimate",
                    "home_priority": 2,
                    "is_visible": 1,
                    "required_plan": "vip",
                }),
                _Row({
                    "id": "char_svip",
                    "name": "SVIP角色",
                    "abbr": "S",
                    "subtitle": "svip",
                    "avatar_url": "",
                    "cover_url": "",
                    "description": "svip desc",
                    "opening_message": "yo",
                    "tags": '[]',
                    "card_type": "intimate",
                    "home_priority": 3,
                    "is_visible": 1,
                    "required_plan": "svip",
                }),
            ]),
            _QueryResult(many=[]),
        ])

        app.dependency_overrides[get_optional_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn), patch(
                "routers.characters.cache_get",
                return_value=None,
            ), patch("routers.characters.cache_set"):
                response = client.get("/api/characters")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "char_guest",
                "name": "游客角色",
                "abbr": "G",
                "subtitle": "guest",
                "avatar_url": "",
                "cover_url": "",
                "avatarImg": "",
                "coverImg": "",
                "description": "guest desc",
                "opening_message": "hello",
                "first_message": "hello",
                "tags": [],
                "card_type": "intimate",
                "required_plan": "guest",
                "required_plan_label": "游客",
                "home_priority": 1,
                "remark": "",
                "custom_signature": "",
                "display_name": "游客角色",
                "sign": "guest",
            },
            {
                "id": "char_vip",
                "name": "VIP角色",
                "abbr": "V",
                "subtitle": "vip",
                "avatar_url": "",
                "cover_url": "",
                "avatarImg": "",
                "coverImg": "",
                "description": "vip desc",
                "opening_message": "hi",
                "first_message": "hi",
                "tags": [],
                "card_type": "intimate",
                "required_plan": "vip",
                "required_plan_label": "VIP",
                "home_priority": 2,
                "remark": "",
                "custom_signature": "",
                "display_name": "VIP角色",
                "sign": "vip",
            },
        ]

    def test_character_list_cache_miss_stores_full_rows_before_viewer_plan_filter(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=18, email="cache@example.com", nickname="cache", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(many=[
                _Row({"id": "char_guest", "name": "游客角色", "abbr": "G", "subtitle": "guest", "avatar_url": "", "cover_url": "", "description": "guest desc", "opening_message": "hello", "tags": '[]', "card_type": "intimate", "home_priority": 1, "is_visible": 1, "required_plan": "guest"}),
                _Row({"id": "char_vip", "name": "VIP角色", "abbr": "V", "subtitle": "vip", "avatar_url": "", "cover_url": "", "description": "vip desc", "opening_message": "hi", "tags": '[]', "card_type": "intimate", "home_priority": 2, "is_visible": 1, "required_plan": "vip"}),
                _Row({"id": "char_svip", "name": "SVIP角色", "abbr": "S", "subtitle": "svip", "avatar_url": "", "cover_url": "", "description": "svip desc", "opening_message": "yo", "tags": '[]', "card_type": "intimate", "home_priority": 3, "is_visible": 1, "required_plan": "svip"}),
            ]),
            _QueryResult(many=[]),
        ])

        app.dependency_overrides[get_optional_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn), patch(
                "routers.characters.cache_get",
                return_value=None,
            ), patch("routers.characters.cache_set") as mock_cache_set:
                response = client.get("/api/characters")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == ["char_guest", "char_vip"]
        mock_cache_set.assert_called_once()
        cache_key, cached_rows = mock_cache_set.call_args.args[:2]
        assert cache_key == "character_list_all"
        assert [row["id"] for row in cached_rows] == ["char_guest", "char_vip", "char_svip"]
        assert mock_cache_set.call_args.kwargs["ttl"] == 300

    def test_character_list_cache_miss_stores_raw_rows_instead_of_serialized_payloads(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=21, email="cache3@example.com", nickname="cache3", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(many=[
                _Row({
                    "id": "char_cache_miss",
                    "name": "缓存未命中角色",
                    "abbr": "M",
                    "subtitle": "原始副标题",
                    "avatar_url": "avatar.png",
                    "cover_url": "",
                    "description": "desc",
                    "opening_message": "hello",
                    "tags": '["tag1"]',
                    "card_type": None,
                    "home_priority": 1,
                    "is_visible": 1,
                    "required_plan": " vip ",
                }),
            ]),
            _QueryResult(many=[]),
        ])

        app.dependency_overrides[get_optional_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn), patch(
                "routers.characters.cache_get",
                return_value=None,
            ), patch("routers.characters.cache_set") as mock_cache_set:
                response = client.get("/api/characters")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "char_cache_miss",
                "name": "缓存未命中角色",
                "abbr": "M",
                "subtitle": "原始副标题",
                "avatar_url": "/api/avatar/char_cache_miss",
                "cover_url": "/api/cover/char_cache_miss",
                "avatarImg": "/api/avatar/char_cache_miss",
                "coverImg": "/api/cover/char_cache_miss",
                "description": "desc",
                "opening_message": "hello",
                "first_message": "hello",
                "tags": ["tag1"],
                "card_type": "intimate",
                "required_plan": "vip",
                "required_plan_label": "VIP",
                "home_priority": 1,
                "remark": "",
                "custom_signature": "",
                "display_name": "缓存未命中角色",
                "sign": "原始副标题",
            }
        ]
        mock_cache_set.assert_called_once()
        _, cached_rows = mock_cache_set.call_args.args[:2]
        assert cached_rows == [
            {
                "id": "char_cache_miss",
                "name": "缓存未命中角色",
                "abbr": "M",
                "subtitle": "原始副标题",
                "avatar_url": "avatar.png",
                "cover_url": "",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": None,
                "home_priority": 1,
                "is_visible": 1,
                "required_plan": " vip ",
            }
        ]
        assert cached_rows[0]["avatar_url"] != response.json()[0]["avatar_url"]
        assert cached_rows[0]["tags"] != response.json()[0]["tags"]
        assert cached_rows[0]["required_plan"] != response.json()[0]["required_plan"]

    def test_character_list_cache_hit_reuses_shared_rows_and_filters_per_viewer_plan(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=20, email="cache2@example.com", nickname="cache2", effective_plan="vip")
        cached_rows = [
            {"id": "char_guest", "name": "游客角色", "abbr": "G", "subtitle": "guest", "avatar_url": "", "cover_url": "", "description": "guest desc", "opening_message": "hello", "tags": '[]', "card_type": "intimate", "home_priority": 1, "is_visible": 1, "required_plan": "guest"},
            {"id": "char_vip", "name": "VIP角色", "abbr": "V", "subtitle": "vip", "avatar_url": "", "cover_url": "", "description": "vip desc", "opening_message": "hi", "tags": '[]', "card_type": "intimate", "home_priority": 2, "is_visible": 1, "required_plan": "vip"},
            {"id": "char_svip", "name": "SVIP角色", "abbr": "S", "subtitle": "svip", "avatar_url": "", "cover_url": "", "description": "svip desc", "opening_message": "yo", "tags": '[]', "card_type": "intimate", "home_priority": 3, "is_visible": 1, "required_plan": "svip"},
        ]
        conn = _SequenceConn([
            _QueryResult(many=[]),
            _QueryResult(many=[]),
        ])

        with patch("routers.characters.get_conn", return_value=conn), patch(
            "routers.characters.cache_get",
            return_value=cached_rows,
        ) as mock_cache_get, patch("routers.characters.cache_set") as mock_cache_set:
            app.dependency_overrides[get_optional_user] = lambda: None
            guest_response = client.get("/api/characters")
            app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
                id=19,
                email="vip2@example.com",
                nickname="vip2",
                effective_plan="vip",
            )
            vip_response = client.get("/api/characters")
            app.dependency_overrides.clear()

        assert guest_response.status_code == 200
        assert [item["id"] for item in guest_response.json()] == ["char_guest"]
        assert vip_response.status_code == 200
        assert [item["id"] for item in vip_response.json()] == ["char_guest", "char_vip"]
        assert mock_cache_get.call_count == 2
        mock_cache_set.assert_not_called()

    def test_character_list_cache_hit_keeps_raw_rows_and_serializes_per_request(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=20, email="cache2@example.com", nickname="cache2", effective_plan="vip")
        cached_rows = [
            {
                "id": "char_cached",
                "name": "缓存原名",
                "abbr": "C",
                "subtitle": "缓存原签名",
                "avatar_url": "avatar.png",
                "cover_url": "",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": None,
                "home_priority": 1,
                "is_visible": 1,
                "required_plan": " vip ",
            }
        ]
        conn = _SequenceConn([
            _QueryResult(many=[]),
        ])

        app.dependency_overrides[get_optional_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn), patch(
                "routers.characters.cache_get",
                return_value=cached_rows,
            ), patch("routers.characters.cache_set") as mock_cache_set:
                response = client.get("/api/characters")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "char_cached",
                "name": "缓存原名",
                "abbr": "C",
                "subtitle": "缓存原签名",
                "avatar_url": "/api/avatar/char_cached",
                "cover_url": "/api/cover/char_cached",
                "avatarImg": "/api/avatar/char_cached",
                "coverImg": "/api/cover/char_cached",
                "description": "desc",
                "opening_message": "hello",
                "first_message": "hello",
                "tags": ["tag1"],
                "card_type": "intimate",
                "required_plan": "vip",
                "required_plan_label": "VIP",
                "home_priority": 1,
                "remark": "",
                "custom_signature": "",
                "display_name": "缓存原名",
                "sign": "缓存原签名",
            }
        ]
        assert cached_rows == [
            {
                "id": "char_cached",
                "name": "缓存原名",
                "abbr": "C",
                "subtitle": "缓存原签名",
                "avatar_url": "avatar.png",
                "cover_url": "",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": None,
                "home_priority": 1,
                "is_visible": 1,
                "required_plan": " vip ",
            }
        ]
        mock_cache_set.assert_not_called()

    def test_character_profile_route_returns_personalized_display_fields(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=15, email="profile@example.com", nickname="profile", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "avatar.png",
                "cover_url": "cover.png",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": "intimate",
                "home_priority": 5,
                "required_plan": "vip",
            })),
            _QueryResult(one=_Row({
                "remark": "专属称呼",
                "custom_signature": "今晚只陪你",
            })),
        ])

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn):
                response = client.get("/api/character/profile", params={"character_id": "char_profile"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "character": {
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "/api/avatar/char_profile",
                "cover_url": "/api/cover/char_profile",
                "avatarImg": "/api/avatar/char_profile",
                "coverImg": "/api/cover/char_profile",
                "description": "desc",
                "opening_message": "hello",
                "first_message": "hello",
                "tags": ["tag1"],
                "card_type": "intimate",
                "required_plan": "vip",
                "required_plan_label": "VIP",
                "home_priority": 5,
                "remark": "专属称呼",
                "custom_signature": "今晚只陪你",
                "display_name": "专属称呼",
                "sign": "今晚只陪你",
            },
            "remark": "专属称呼",
            "custom_signature": "今晚只陪你",
        }

    def test_character_profile_route_keeps_top_level_fields_consistent_with_character_payload(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=22, email="profile-consistency@example.com", nickname="profile-consistency", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_profile_consistent",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "avatar.png",
                "cover_url": "cover.png",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": None,
                "home_priority": 6,
                "required_plan": " vip ",
            })),
            _QueryResult(one=_Row({
                "remark": "一致性备注",
                "custom_signature": "一致性签名",
            })),
        ])

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn):
                response = client.get(
                    "/api/character/profile",
                    params={"character_id": "char_profile_consistent"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        payload = response.json()
        assert payload["remark"] == payload["character"]["remark"] == "一致性备注"
        assert payload["custom_signature"] == payload["character"]["custom_signature"] == "一致性签名"
        assert payload["character"]["display_name"] == "一致性备注"
        assert payload["character"]["sign"] == "一致性签名"
        assert payload["character"]["required_plan"] == "vip"
        assert payload["character"]["required_plan_label"] == "VIP"
        assert payload["character"]["card_type"] == "intimate"

    def test_character_profile_update_route_returns_updated_personalized_fields(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=16, email="profile-update@example.com", nickname="profile", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "avatar.png",
                "cover_url": "cover.png",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": "intimate",
                "home_priority": 5,
                "required_plan": "vip",
            })),
            _QueryResult(one=_Row({
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "avatar.png",
                "cover_url": "cover.png",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": "intimate",
                "home_priority": 5,
                "required_plan": "vip",
            })),
            _QueryResult(one=_Row({
                "remark": "新的备注",
                "custom_signature": "新的签名",
            })),
        ])

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn):
                response = client.post(
                    "/api/character/profile",
                    json={
                        "character_id": "char_profile",
                        "remark": "新的备注",
                        "custom_signature": "新的签名",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "character": {
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "/api/avatar/char_profile",
                "cover_url": "/api/cover/char_profile",
                "avatarImg": "/api/avatar/char_profile",
                "coverImg": "/api/cover/char_profile",
                "description": "desc",
                "opening_message": "hello",
                "first_message": "hello",
                "tags": ["tag1"],
                "card_type": "intimate",
                "required_plan": "vip",
                "required_plan_label": "VIP",
                "home_priority": 5,
                "remark": "新的备注",
                "custom_signature": "新的签名",
                "display_name": "新的备注",
                "sign": "新的签名",
            },
        }

    def test_character_profile_update_route_keeps_empty_overrides_but_falls_back_for_display_fields(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=17, email="profile-empty@example.com", nickname="profile-empty", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "avatar.png",
                "cover_url": "cover.png",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": "intimate",
                "home_priority": 5,
                "required_plan": " vip ",
            })),
            _QueryResult(one=_Row({
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "avatar.png",
                "cover_url": "cover.png",
                "description": "desc",
                "opening_message": "hello",
                "tags": '["tag1"]',
                "card_type": None,
                "home_priority": 5,
                "required_plan": " vip ",
            })),
            _QueryResult(one=_Row({
                "remark": "",
                "custom_signature": "",
            })),
        ])

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn):
                response = client.post(
                    "/api/character/profile",
                    json={
                        "character_id": "char_profile",
                        "remark": "",
                        "custom_signature": "",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "character": {
                "id": "char_profile",
                "name": "原始角色名",
                "abbr": "P",
                "subtitle": "原始签名",
                "avatar_url": "/api/avatar/char_profile",
                "cover_url": "/api/cover/char_profile",
                "avatarImg": "/api/avatar/char_profile",
                "coverImg": "/api/cover/char_profile",
                "description": "desc",
                "opening_message": "hello",
                "first_message": "hello",
                "tags": ["tag1"],
                "card_type": "intimate",
                "required_plan": "vip",
                "required_plan_label": "VIP",
                "home_priority": 5,
                "remark": "",
                "custom_signature": "",
                "display_name": "原始角色名",
                "sign": "原始签名",
            },
        }


# ============================================================
# 性能基准测试
# ============================================================

class TestPerformanceBaselines:
    """性能基准测试。"""

    def test_health_check_uses_cache(self):
        """健康检查应使用缓存避免频繁数据库查询。"""
        from main import _check_db_health, _db_health_cache

        with patch("main.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn

            _db_health_cache["ts"] = 0
            result1 = _check_db_health()
            result2 = _check_db_health()

            assert mock_get_conn.call_count <= 2

    def test_password_hashing_performance(self):
        """密码哈希应在合理时间内完成。"""
        import time
        from auth import hash_password_bcrypt

        start = time.time()
        result = hash_password_bcrypt("test_password_123")
        elapsed = time.time() - start

        assert result is not None
        assert elapsed < 1.0
        assert elapsed > 0.01


# ============================================================
# 阶段四：集成测试骨架
# ============================================================

class TestAPIIntegration:
    """API 集成测试骨架，后续逐步补充。"""

    def test_auth_register_flow(self, app_client):
        """注册流程应完整可用。"""
        _, client = app_client
        response = client.post("/api/auth/register", json={})
        assert response.status_code == 422

    def test_auth_login_flow(self, app_client):
        """登录流程应完整可用。"""
        _, client = app_client
        response = client.post("/api/auth/login", json={})
        assert response.status_code == 422

    def test_chat_send_flow(self, app_client):
        """聊天流程应完整可用。"""
        _, client = app_client
        response = client.post(
            "/api/chat/send",
            json={"character_id": "demo", "message": "hello"},
        )
        assert response.status_code == 401

    def test_billing_order_flow(self, app_client):
        """订单流程应完整可用。"""
        _, client = app_client
        response = client.post("/api/billing/orders", json={"plan_type": "vip"})
        assert response.status_code == 401

    def test_character_greetings_route_deduplicates_and_falls_back(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=1, email="test@example.com", nickname="tester", effective_plan="free")
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_1",
                "name": "角色",
                "opening_message": "你好",
                "structured_asset_json": '{"alternate_greetings": ["你好", "第二句"]}',
                "required_plan": "guest",
            })),
            _QueryResult(many=[]),
        ])

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn):
                response = client.get("/api/character/greetings", params={"character_id": "char_1"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data == {
            "first_mes": "你好",
            "alternate_greetings": ["第二句"],
            "greetings": [
                {"index": 0, "label": "默认开场", "preview": "你好", "content": "你好"},
                {"index": 2, "label": "备选开场 2", "preview": "第二句", "content": "第二句"},
            ],
            "total": 2,
        }

    def test_character_greetings_route_prefers_db_rows_and_deduplicates_default_opening(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=2, email="greetings@example.com", nickname="greeter", effective_plan="vip")
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_2",
                "name": "角色二号",
                "opening_message": "默认开场白",
                "structured_asset_json": '{"alternate_greetings": ["structured 备选", "另一句"]}',
                "required_plan": "vip",
            })),
            _QueryResult(many=[
                _Row({"id": 31, "content": "默认开场白", "story_phase": "stranger", "mood": "calm", "storyline_id": 7, "storyline_name": "初见剧情"}),
                _Row({"id": 32, "content": "数据库独有开场", "story_phase": "stranger", "mood": "warm", "storyline_id": None, "storyline_name": ""}),
                _Row({"id": 33, "content": "  ", "story_phase": "stranger", "mood": "warm", "storyline_id": None, "storyline_name": ""}),
            ]),
        ])

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn", return_value=conn):
                response = client.get("/api/character/greetings", params={"character_id": "char_2"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data == {
            "first_mes": "默认开场白",
            "alternate_greetings": ["数据库独有开场"],
            "greetings": [
                {"index": 0, "label": "默认开场", "preview": "默认开场白", "content": "默认开场白"},
                {"index": 32, "label": "stranger / warm", "preview": "数据库独有开场", "content": "数据库独有开场"},
            ],
            "total": 2,
        }

    def test_character_state_reset_route_returns_service_state_contract(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=23, email="state-reset@example.com", nickname="state-reset", effective_plan="vip")

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn") as mock_get_conn, patch(
                "routers.characters._get_accessible_character",
                return_value={"id": "char_state"},
            ), patch(
                "routers.characters.reset_character_chat_state",
                return_value={
                    "ok": True,
                    "state": {
                        "affection": 0,
                        "story_phase": "stranger",
                        "mood": "neutral",
                        "storyline_id": None,
                        "custom_vars": {},
                    },
                },
            ) as mock_reset:
                response = client.post("/api/character/state/reset", params={"character_id": "char_state"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "message": "关系状态已重置",
            "state": {
                "affection": 0,
                "story_phase": "stranger",
                "mood": "neutral",
                "storyline_id": None,
                "custom_vars": {},
            },
        }
        mock_reset.assert_called_once_with(
            mock_get_conn.return_value,
            user_id=23,
            character_id="char_state",
            clear_state=True,
        )

    def test_character_state_route_filters_internal_fields(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=25, email="state@example.com", nickname="state-user", effective_plan="vip")

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn") as mock_get_conn, patch(
                "routers.characters._get_accessible_character",
                return_value={"id": "char_state"},
            ), patch(
                "routers.characters.get_character_state",
                return_value={
                    "affection": 88,
                    "story_phase": "friend",
                    "mood": "warm",
                    "storyline_id": 3,
                    "custom_vars": {"gift": 1},
                    "_internal_prompt": "hidden",
                    "_debug_meta": {"raw": True},
                },
            ) as mock_state:
                response = client.get("/api/character/state", params={"character_id": "char_state"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "state": {
                "affection": 88,
                "story_phase": "friend",
                "mood": "warm",
                "storyline_id": 3,
                "custom_vars": {"gift": 1},
            }
        }
        mock_state.assert_called_once_with(mock_get_conn.return_value, 25, "char_state")

    def test_clear_chat_route_forwards_greeting_index_and_returns_service_greeting(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(id=24, email="chat-clear@example.com", nickname="chat-clear", effective_plan="vip")

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.characters.get_conn") as mock_get_conn, patch(
                "routers.characters._get_accessible_character",
                return_value={"id": "char_clear"},
            ), patch(
                "routers.characters.clear_chat_history_with_greeting",
                return_value="重新开始吧",
            ) as mock_clear:
                response = client.post(
                    "/api/chat/clear",
                    json={"character_id": "char_clear", "greeting_index": "storyline-42"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True, "greeting": "重新开始吧"}
        mock_clear.assert_called_once_with(
            mock_get_conn.return_value,
            user_id=24,
            character_id="char_clear",
            greeting_index="storyline-42",
        )

    def test_admin_message_preview_route_clamps_affection_and_uses_fallbacks(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_1",
                "structured_asset_json": '{"runtime_layers": {"base_profile": "角色设定"}}',
            })),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_insights.get_conn", return_value=conn), patch(
                "routers.admin.characters_insights.build_message_preview",
                return_value={},
            ):
                response = client.get(
                    "/api/admin/character/char_1/message-preview",
                    params={"affection": 999, "story_phase": "friend", "mood": "happy"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "character_id": "char_1",
            "character_state": {
                "affection": 100,
                "story_phase": "friend",
                "mood": "happy",
                "storyline_id": None,
                "custom_vars": {},
            },
            "message_count": 0,
            "messages": [],
            "runtime_layers": {"base_profile": "角色设定"},
            "related_assets": [],
        }

    def test_admin_character_config_summary_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_1",
                "name": "露娜",
                "subtitle": None,
                "opening_message": "你好",
                "system_prompt": "你是露娜",
                "is_visible": 1,
                "card_type": "scenario",
                "affection_enabled": 1,
                "affection_rules_json": "{}",
                "structured_asset_json": '{"runtime_layers":{"base_profile":"设定","examples":"示例"}}',
            })),
            _QueryResult(one=_Row({"count": 2})),
            _QueryResult(one=_Row({"count": 1})),
            _QueryResult(one=_Row({"count": 3})),
            _QueryResult(one=_Row({"count": 1})),
            _QueryResult(one=_Row({"count": 2})),
            _QueryResult(one=_Row({"count": 1})),
            _QueryResult(one=_Row({"count": 1})),
            _QueryResult(one=_Row({"count": 2})),
            _QueryResult(one=_Row({"count": 1})),
            _QueryResult(one=_Row({"count": 0})),
            _QueryResult(one=_Row({"count": 1})),
            _QueryResult(many=[_Row({"story_phase": "friend"}), _Row({"story_phase": "lover"})]),
            _QueryResult(one=_Row({"id": 91})),
            _QueryResult(one=_Row({"count": 1})),
            _QueryResult(many=[
                _Row({
                    "id": 501,
                    "unlocked_memory_ids": "m1,m2",
                    "unlocked_greeting_ids": "g1",
                    "unlocked_storyline_id": "91",
                    "event_content": "触发剧情",
                })
            ]),
            _QueryResult(many=[_Row({"id": "m1"}), _Row({"id": "m2"})]),
            _QueryResult(many=[_Row({"id": "g1"})]),
            _QueryResult(many=[_Row({"id": "91"})]),
            _QueryResult(one=_Row({"max": "2026-10-01T00:00:00+00:00"})),
            _QueryResult(one=_Row({"max": None})),
            _QueryResult(one=_Row({"max": "2026-10-03T00:00:00+00:00"})),
            _QueryResult(one=_Row({"max": "2026-10-02T00:00:00+00:00"})),
            _QueryResult(one=_Row({"max": None})),
            _QueryResult(one=_Row({"max": "2026-10-04T00:00:00+00:00"})),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_insights.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/config-summary")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "character_id": "char_1",
            "name": "露娜",
            "subtitle": "",
            "runtime_layer_count": 2,
            "default_storyline_id": 91,
            "last_updated": "2026-10-04T00:00:00+00:00",
            "completeness": 100,
            "warnings": [
                "角色已设为可见，但副标题为空",
                "启用中的记忆条目较少，建议至少准备 3 条高频记忆",
                "存在后置规则，但全部处于禁用状态",
            ],
            "stats": {
                "memories": 2,
                "active_memories": 1,
                "categories": 1,
                "greetings": 3,
                "active_greetings": 2,
                "greeting_phase_coverage": 2,
                "storylines": 1,
                "active_storylines": 1,
                "post_rules": 2,
                "active_post_rules": 0,
                "events": 1,
                "active_events": 1,
                "empty_unlock_events": 0,
                "empty_event_content_events": 0,
            },
        }

    def test_admin_character_config_summary_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=None),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_insights.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing/config-summary")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}

    def test_admin_test_keywords_route_returns_matches_with_normalized_logic(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(many=[
                _Row({
                    "id": 801,
                    "keywords": "月亮, 夜晚",
                    "trigger_logic": "all",
                    "content": "记忆一",
                }),
                _Row({
                    "id": 802,
                    "keywords": "车站,离别",
                    "trigger_logic": None,
                    "content": "记忆二",
                }),
                _Row({
                    "id": 803,
                    "keywords": "   ",
                    "trigger_logic": "any",
                    "content": "空关键词",
                }),
            ]),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_insights.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/char_1/test-keywords",
                    json={"text": "那个夜晚的月亮和离别车站让我难忘"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 801,
                "keywords": "月亮, 夜晚",
                "content": "记忆一",
                "matched_keywords": ["月亮", "夜晚"],
                "trigger_logic": "all",
            },
            {
                "id": 802,
                "keywords": "车站,离别",
                "content": "记忆二",
                "matched_keywords": ["车站", "离别"],
                "trigger_logic": "any",
            },
        ]

    def test_admin_test_keywords_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=None),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_insights.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing/test-keywords",
                    json={"text": "任意文本"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}

    def test_admin_users_route_returns_stable_membership_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({"total": 1})),
            _QueryResult(many=[
                _Row({
                    "id": 7,
                    "email": "vip@example.com",
                    "nickname": "",
                    "plan_type": "vip",
                    "plan_expires_at": "2099-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                })
            ]),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn):
                response = client.get(
                    "/api/admin/users",
                    params={"search": "vip", "plan": "vip", "page": 2, "limit": 150},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400

    def test_admin_users_route_returns_stable_membership_payload_with_valid_limit(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({"total": 1})),
            _QueryResult(many=[
                _Row({
                    "id": 7,
                    "email": "vip@example.com",
                    "nickname": "",
                    "plan_type": "vip",
                    "plan_expires_at": "2099-01-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                })
            ]),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn):
                response = client.get(
                    "/api/admin/users",
                    params={"search": "vip", "plan": "vip", "page": 2, "limit": 100},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "total": 1,
            "page": 2,
            "limit": 100,
            "items": [
                {
                    "id": 7,
                    "email": "vip@example.com",
                    "nickname": "vip",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "plan_type": "vip",
                    "effective_plan": "vip",
                    "plan_expires_at": "2099-01-01T00:00:00+00:00",
                    "plan_display_name": "VIP",
                    "is_paid_plan": True,
                    "membership_expired": False,
                }
            ],
        }

    def test_admin_update_user_plan_route_returns_stable_free_plan_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": 9,
                "email": "freeuser@example.com",
                "nickname": "",
            })),
            _QueryResult(),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/9/plan",
                    json={"plan_type": "free", "duration_days": 30},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "message": "已将用户 freeuser@example.com 设置为 注册用户",
            "user": {
                "id": 9,
                "email": "freeuser@example.com",
                "nickname": "freeuser",
                "plan_type": "free",
                "effective_plan": "free",
                "plan_expires_at": "",
                "plan_display_name": "注册用户",
                "is_paid_plan": False,
                "membership_expired": False,
            },
        }
        mock_audit_log.assert_called_once()

    def test_admin_update_user_plan_route_returns_404_when_user_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=None),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/404/plan",
                    json={"plan_type": "vip", "duration_days": 30},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "用户不存在"}
        mock_audit_log.assert_not_called()

    def test_admin_update_user_plan_route_returns_paid_plan_payload_with_expiry(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": 10,
                "email": "vipuser@example.com",
                "nickname": "小月",
            })),
            _QueryResult(),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/10/plan",
                    json={"plan_type": "vip", "duration_days": 30},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["message"] == "已将用户 vipuser@example.com 设置为 VIP"
        assert payload["user"] == {
            "id": 10,
            "email": "vipuser@example.com",
            "nickname": "小月",
            "plan_type": "vip",
            "effective_plan": "vip",
            "plan_expires_at": payload["user"]["plan_expires_at"],
            "plan_display_name": "VIP",
            "is_paid_plan": True,
            "membership_expired": False,
        }
        assert payload["user"]["plan_expires_at"]
        assert payload["user"]["plan_expires_at"].endswith("+00:00")
        mock_audit_log.assert_called_once()

    def test_admin_update_user_plan_route_writes_audit_detail_with_final_expiry(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": 11,
                "email": "audit@example.com",
                "nickname": "审计用户",
            })),
            _QueryResult(),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/11/plan",
                    json={"plan_type": "svip", "duration_days": 45},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["operator_id"] == 1
        assert audit_kwargs["operator_email"] == "admin@example.com"
        assert audit_kwargs["action"] == "update_user_plan"
        assert audit_kwargs["target_type"] == "user"
        assert audit_kwargs["target_id"] == "11"
        assert audit_kwargs["detail"]["email"] == "audit@example.com"
        assert audit_kwargs["detail"]["nickname"] == "审计用户"
        assert audit_kwargs["detail"]["new_plan"] == "svip"
        assert audit_kwargs["detail"]["duration_days"] == 45
        assert audit_kwargs["detail"]["plan_expires_at"] == response.json()["user"]["plan_expires_at"]
        assert audit_kwargs["detail"]["plan_expires_at"].endswith("+00:00")
        assert response.json()["user"]["plan_display_name"] == "SVIP"

    def test_admin_update_user_plan_route_rejects_invalid_plan_type(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn") as mock_get_conn, patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/9/plan",
                    json={"plan_type": "pro", "duration_days": 30},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "plan_type"]
        mock_get_conn.assert_not_called()
        mock_audit_log.assert_not_called()

    def test_admin_update_user_plan_route_rejects_out_of_range_duration_days(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn") as mock_get_conn, patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/9/plan",
                    json={"plan_type": "vip", "duration_days": 0},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "duration_days"]
        mock_get_conn.assert_not_called()
        mock_audit_log.assert_not_called()

    def test_admin_edit_user_route_returns_trimmed_updated_fields_and_audit_detail(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({"id": 12, "email": "before@example.com"})),
            _QueryResult(),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.patch(
                    "/api/admin/users/12",
                    json={"email": "  NewUser@Example.com  ", "nickname": "  新昵称  "},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "message": "用户 before@example.com 信息已更新",
            "updated_fields": ["email", "nickname"],
        }
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["operator_id"] == 1
        assert audit_kwargs["operator_email"] == "admin@example.com"
        assert audit_kwargs["action"] == "edit_user"
        assert audit_kwargs["target_type"] == "user"
        assert audit_kwargs["target_id"] == "12"
        assert audit_kwargs["detail"] == {
            "updated_fields": {
                "email": "newuser@example.com",
                "nickname": "新昵称",
            },
            "target_email": "before@example.com",
        }

    def test_admin_edit_user_route_returns_404_when_user_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=None),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.patch(
                    "/api/admin/users/404",
                    json={"nickname": "仍然不会生效"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "用户不存在"}
        mock_audit_log.assert_not_called()

    def test_admin_edit_user_route_rejects_empty_updates_after_user_lookup(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({"id": 13, "email": "noop@example.com"})),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.patch(
                    "/api/admin/users/13",
                    json={},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "没有提供任何更新字段"}
        mock_audit_log.assert_not_called()

    def test_admin_edit_user_route_rejects_invalid_email_before_db_access(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn") as mock_get_conn, patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.patch(
                    "/api/admin/users/12",
                    json={"email": "not-an-email"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "email"]
        mock_get_conn.assert_not_called()
        mock_audit_log.assert_not_called()

    def test_admin_delete_user_route_returns_success_payload_and_deletes_in_order(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 21, "email": "delete@example.com"})),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.delete("/api/admin/users/21")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "message": "用户 delete@example.com（ID: 21）已删除，关联数据已清理",
        }
        assert conn.execute.call_args_list == [
            call("SELECT id, email FROM users WHERE id = %s", ("21",)),
            call("DELETE FROM ai_request_logs WHERE user_id = %s", ("21",)),
            call("DELETE FROM chat_messages WHERE user_id = %s", ("21",)),
            call("DELETE FROM user_character_profiles WHERE user_id = %s", ("21",)),
            call("DELETE FROM membership_orders WHERE user_id = %s", ("21",)),
            call("DELETE FROM users WHERE id = %s", ("21",)),
        ]
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["operator_id"] == 1
        assert audit_kwargs["operator_email"] == "admin@example.com"
        assert audit_kwargs["action"] == "delete_user"
        assert audit_kwargs["target_type"] == "user"
        assert audit_kwargs["target_id"] == "21"
        assert audit_kwargs["detail"] == {"deleted_email": "delete@example.com"}
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_user_route_returns_404_when_user_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.delete("/api/admin/users/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "用户不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id, email FROM users WHERE id = %s", ("404",)),
        ]
        mock_audit_log.assert_not_called()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_storyline_route_returns_ok_and_unlinks_dependencies_before_delete(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 51, "name": "主线一"})),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story._write_audit_log"
            ) as mock_audit_log:
                response = client.delete("/api/admin/character/char_1/storylines/51")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id, name FROM character_storylines WHERE id = %s AND character_id = %s",
                ("51", "char_1"),
            ),
            call(
                "UPDATE character_greetings SET storyline_id = NULL WHERE storyline_id = %s",
                ("51",),
            ),
            call(
                "UPDATE character_post_rules SET storyline_id = NULL WHERE storyline_id = %s",
                ("51",),
            ),
            call(
                "UPDATE story_events SET unlocked_storyline_id = NULL WHERE unlocked_storyline_id = %s",
                ("51",),
            ),
            call(
                "DELETE FROM character_storylines WHERE id = %s",
                ("51",),
            ),
        ]
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["operator_id"] == 1
        assert audit_kwargs["operator_email"] == "admin@example.com"
        assert audit_kwargs["action"] == "delete_storyline"
        assert audit_kwargs["target_type"] == "storyline"
        assert audit_kwargs["target_id"] == "51"
        assert audit_kwargs["detail"] == {
            "character_id": "char_1",
            "storyline_name": "主线一",
        }
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_storyline_route_returns_404_without_side_effects(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story._write_audit_log"
            ) as mock_audit_log:
                response = client.delete("/api/admin/character/char_1/storylines/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "剧情线不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id, name FROM character_storylines WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        mock_audit_log.assert_not_called()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_character_route_returns_success_payload_and_invalidates_list_cache(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=None),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn), patch(
                "routers.admin.characters_core._write_audit_log"
            ) as mock_audit_log, patch(
                "routers.admin.characters_core.cache_delete"
            ) as mock_cache_delete:
                response = client.post(
                    "/api/admin/characters",
                    json={
                        "id": "  char_new  ",
                        "name": "  Luna  ",
                        "system_prompt": "  stay warm  ",
                        "abbr": "  LN  ",
                        "subtitle": "  companion  ",
                        "description": "  desc  ",
                        "opening_message": "  hello  ",
                        "tags": '["healing", "night"]',
                        "card_type": "friend",
                        "required_plan": "vip",
                        "avatar_url": "  https://img/avatar.png  ",
                        "cover_url": "  https://img/cover.png  ",
                        "home_priority": 8,
                        "is_visible": False,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "id": "char_new",
            "message": "角色 'Luna' 创建成功",
        }
        assert conn.execute.call_args_list[0] == call(
            "SELECT id FROM characters WHERE id = %s",
            ("char_new",),
        )
        insert_sql, insert_params = conn.execute.call_args_list[1].args
        assert "INSERT INTO characters" in insert_sql
        assert insert_params == (
            "char_new", "Luna", "LN", "companion", "https://img/avatar.png", "https://img/cover.png", "desc",
            "stay warm", "hello", '["healing", "night"]',
            "friend", "vip", 8, 0, 8,
            "温柔、体贴、会关心人", "character", "manual", "",
            "json", "", "{}",
            "[]", 0, 1, "{}"
        )
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["operator_id"] == 1
        assert audit_kwargs["operator_email"] == "admin@example.com"
        assert audit_kwargs["action"] == "create_character"
        assert audit_kwargs["target_type"] == "character"
        assert audit_kwargs["target_id"] == "char_new"
        assert audit_kwargs["detail"] == {
            "name": "Luna",
            "card_type": "friend",
            "required_plan": "vip",
        }
        mock_cache_delete.assert_called_once_with("character_list_all")
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_character_route_returns_409_when_id_already_exists(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=_Row({"id": "char_existing"}))

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn), patch(
                "routers.admin.characters_core._write_audit_log"
            ) as mock_audit_log, patch(
                "routers.admin.characters_core.cache_delete"
            ) as mock_cache_delete:
                response = client.post(
                    "/api/admin/characters",
                    json={
                        "id": "char_existing",
                        "name": "Luna",
                        "system_prompt": "stay warm",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 409
        assert response.json() == {"detail": "角色ID 'char_existing' 已存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_existing",)),
        ]
        mock_audit_log.assert_not_called()
        mock_cache_delete.assert_not_called()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_character_route_rejects_invalid_tags_json_without_side_effects(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn), patch(
                "routers.admin.characters_core._write_audit_log"
            ) as mock_audit_log, patch(
                "routers.admin.characters_core.cache_delete"
            ) as mock_cache_delete:
                response = client.post(
                    "/api/admin/characters",
                    json={
                        "id": "char_bad_tags",
                        "name": "Luna",
                        "system_prompt": "stay warm",
                        "tags": "{bad json}",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "tags格式错误，必须是有效的JSON"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_bad_tags",)),
        ]
        mock_audit_log.assert_not_called()
        mock_cache_delete.assert_not_called()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_list_characters_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(many=[
                _Row({
                    "id": "char_1",
                    "name": "露娜",
                    "abbr": "Luna",
                    "subtitle": None,
                    "avatar_url": None,
                    "description": "x" * 105,
                    "tags": '["healing", "night"]',
                    "card_type": None,
                    "required_plan": None,
                    "is_visible": 1,
                    "home_priority": 3,
                    "sort_order": 8,
                })
            ]),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn):
                response = client.get("/api/admin/characters")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": "char_1",
                "name": "露娜",
                "abbr": "Luna",
                "subtitle": "",
                "avatar_url": "",
                "description": ("x" * 100) + "...",
                "tags": ["healing", "night"],
                "card_type": "intimate",
                "required_plan": "guest",
                "is_visible": True,
                "home_priority": 3,
                "sort_order": 8,
            }
        ]

    def test_admin_get_character_route_returns_runtime_layers_from_structured_asset_fallback(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": "char_1",
                "name": "露娜",
                "abbr": "Luna",
                "subtitle": None,
                "avatar_url": None,
                "cover_url": None,
                "description": None,
                "tags": '["healing"]',
                "opening_message": None,
                "system_prompt": None,
                "sort_order": 8,
                "is_visible": 1,
                "home_priority": 3,
                "card_type": None,
                "required_plan": None,
                "affection_enabled": 0,
                "affection_rules_json": None,
                "import_locked": 1,
                "source_kind": "manual",
                "source_path": "/tmp/luna.json",
                "asset_type": None,
                "embedded_format": None,
                "mock_reply_style": None,
                "import_diagnostics": None,
                "runtime_cache_json": "{}",
                "structured_asset_json": '{"runtime_layers":{"base_profile":["设定1","设定2"],"examples":"示例文本"}}',
            })),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "id": "char_1",
            "name": "露娜",
            "abbr": "Luna",
            "subtitle": "",
            "avatar_url": "",
            "cover_url": "",
            "description": "",
            "tags": ["healing"],
            "opening_message": "",
            "system_prompt": "",
            "sort_order": 8,
            "is_visible": True,
            "home_priority": 3,
            "card_type": "intimate",
            "required_plan": "guest",
            "affection_enabled": False,
            "affection_rules_json": "{}",
            "import_locked": True,
            "source_kind": "manual",
            "source_path": "/tmp/luna.json",
            "asset_type": "character",
            "embedded_format": "json",
            "mock_reply_style": "",
            "import_diagnostics": "[]",
            "runtime_layers": {
                "base_profile": "设定1\n---\n设定2",
                "examples": "示例文本",
            },
        }

    def test_admin_get_character_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=None),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}

    def test_admin_update_character_route_updates_direct_and_runtime_layers_and_invalidates_cache(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({
                "id": "char_1",
                "structured_asset_json": '{"runtime_layers":{"base_profile":["旧设定"],"examples":"旧示例"}}',
            })),
            _QueryResult(),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn), patch(
                "routers.admin.characters_core.invalidate_character"
            ) as mock_invalidate, patch(
                "routers.admin.characters_core.cache_delete"
            ) as mock_cache_delete:
                response = client.post(
                    "/api/admin/character/char_1",
                    json={
                        "updates": {
                            "name": "新露娜",
                            "is_visible": False,
                            "rl__base_profile": "第一段\n---\n第二段",
                            "rl__examples": "新的示例",
                        }
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "updated": ["name", "is_visible", "rl__base_profile", "rl__examples"],
        }
        assert conn.execute.call_args_list[0] == call(
            "SELECT id, structured_asset_json FROM characters WHERE id = %s",
            ("char_1",),
        )
        assert conn.execute.call_args_list[1] == call(
            "UPDATE characters SET name = %s, is_visible = %s WHERE id = %s",
            ["新露娜", False, "char_1"],
        )
        runtime_sql, runtime_params = conn.execute.call_args_list[2].args
        assert runtime_sql == "UPDATE characters SET structured_asset_json = %s, runtime_cache_json = %s WHERE id = %s"
        assert runtime_params[2] == "char_1"
        assert json.loads(runtime_params[0]) == {
            "runtime_layers": {
                "base_profile": ["第一段", "第二段"],
                "examples": "新的示例",
            }
        }
        assert json.loads(runtime_params[1]) == {
            "base_profile": ["第一段", "第二段"],
            "examples": "新的示例",
        }
        mock_invalidate.assert_called_once_with("char_1")
        mock_cache_delete.assert_called_once_with("character_list_all")
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_character_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing",
                    json={"updates": {"name": "不会生效"}},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id, structured_asset_json FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_character_route_deletes_related_rows_and_invalidates_cache(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1", "name": "露娜"})),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn), patch(
                "routers.admin.characters_core._write_audit_log"
            ) as mock_audit_log, patch(
                "routers.admin.characters_core.invalidate_character"
            ) as mock_invalidate, patch(
                "routers.admin.characters_core.cache_delete"
            ) as mock_cache_delete:
                response = client.delete("/api/admin/character/char_1")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True, "id": "char_1", "name": "露娜"}
        assert conn.execute.call_args_list == [
            call("SELECT id, name FROM characters WHERE id = %s", ("char_1",)),
            call("DELETE FROM user_character_profiles WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM character_states WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM character_greetings WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM character_memories WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM memory_categories WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM character_post_rules WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM story_events WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM character_storylines WHERE character_id = %s", ("char_1",)),
            call("DELETE FROM characters WHERE id = %s", ("char_1",)),
        ]
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["action"] == "delete_character"
        assert audit_kwargs["target_id"] == "char_1"
        assert audit_kwargs["detail"] == {"name": "露娜"}
        mock_invalidate.assert_called_once_with("char_1")
        mock_cache_delete.assert_called_once_with("character_list_all")
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_character_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        app.dependency_overrides[get_current_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_core.get_conn", return_value=conn), patch(
                "routers.admin.characters_core._write_audit_log"
            ) as mock_audit_log, patch(
                "routers.admin.characters_core.invalidate_character"
            ) as mock_invalidate, patch(
                "routers.admin.characters_core.cache_delete"
            ) as mock_cache_delete:
                response = client.delete("/api/admin/character/missing")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id, name FROM characters WHERE id = %s", ("missing",)),
        ]
        mock_audit_log.assert_not_called()
        mock_invalidate.assert_not_called()
        mock_cache_delete.assert_not_called()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_storyline_delete_impact_route_returns_stable_dependency_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 91, "name": "校园线", "is_default": 1})),
            _QueryResult(many=[
                _Row({"id": 301, "story_phase": "friend", "content": "欢迎来到校园生活，这是一段很长的内容用来测试截断"})
            ]),
            _QueryResult(many=[
                _Row({"id": 601, "name": ""})
            ]),
            _QueryResult(many=[
                _Row({"id": 501, "title": None})
            ]),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/storylines/91/delete-impact")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "character_id": "char_1",
            "storyline": {"id": 91, "name": "校园线", "is_default": True},
            "impact": {
                "greetings": [
                    {"id": 301, "label": "friend / 欢迎来到校园生活，这是一段很长的内容用来测试截断"}
                ],
                "post_rules": [
                    {"id": 601, "label": "规则#601"}
                ],
                "unlock_events": [
                    {"id": 501, "label": "事件#501"}
                ],
            },
            "summary": {
                "greeting_count": 1,
                "post_rule_count": 1,
                "unlock_event_count": 1,
            },
        }
        assert conn.execute.call_args_list == [
            call(
                """
            SELECT id, name, is_default
            FROM character_storylines
            WHERE id = %s AND character_id = %s
            """,
                ("91", "char_1"),
            ),
            call(
                """
            SELECT id, story_phase, content
            FROM character_greetings
            WHERE character_id = %s AND storyline_id = %s
            ORDER BY id ASC
            """,
                ("char_1", "91"),
            ),
            call(
                """
            SELECT id, name
            FROM character_post_rules
            WHERE character_id = %s AND storyline_id = %s
            ORDER BY id ASC
            """,
                ("char_1", "91"),
            ),
            call(
                """
            SELECT id, title
            FROM story_events
            WHERE character_id = %s AND unlocked_storyline_id = %s
            ORDER BY id ASC
            """,
                ("char_1", "91"),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_storyline_delete_impact_route_returns_404_when_storyline_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/storylines/404/delete-impact")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "剧情线不存在"}
        assert conn.execute.call_args_list == [
            call(
                """
            SELECT id, name, is_default
            FROM character_storylines
            WHERE id = %s AND character_id = %s
            """,
                ("404", "char_1"),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_memory_category_delete_impact_route_returns_stable_dependency_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 701, "name": "核心设定"})),
            _QueryResult(many=[
                _Row({"id": 801, "keywords": "月亮,夜晚", "comment": ""}),
                _Row({"id": 802, "keywords": "", "comment": "备注优先"}),
                _Row({"id": 803, "keywords": "", "comment": ""}),
            ]),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/memory-categories/701/delete-impact")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "character_id": "char_1",
            "category": {"id": 701, "name": "核心设定"},
            "impact": {
                "memories": [
                    {"id": 801, "label": "月亮,夜晚"},
                    {"id": 802, "label": "备注优先"},
                    {"id": 803, "label": "记忆#803"},
                ]
            },
            "summary": {"memory_count": 3},
        }
        assert conn.execute.call_args_list == [
            call(
                """
            SELECT id, name
            FROM memory_categories
            WHERE id = %s AND character_id = %s
            """,
                ("701", "char_1"),
            ),
            call(
                """
            SELECT id, keywords, comment
            FROM character_memories
            WHERE character_id = %s AND category_id = %s
            ORDER BY priority ASC, id ASC
            """,
                ("char_1", "701"),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_memory_category_delete_impact_route_returns_404_when_category_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/memory-categories/404/delete-impact")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "记忆分类不存在"}
        assert conn.execute.call_args_list == [
            call(
                """
            SELECT id, name
            FROM memory_categories
            WHERE id = %s AND character_id = %s
            """,
                ("404", "char_1"),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_create_storyline_route_resets_other_defaults_before_insert(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(),
            _QueryResult(one=_Row({"id": 77})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-01-02T03:04:05+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/storylines",
                    json={
                        "name": "主线一",
                        "description": "起始剧情",
                        "unlock_score": 10,
                        "is_default": True,
                        "is_active": True,
                        "sort_order": 2,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"id": 77, "ok": True}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "UPDATE character_storylines SET is_default = 0 WHERE character_id = %s",
                ("char_1",),
            ),
            call(
                """
            INSERT INTO character_storylines
            (character_id, name, description,
             unlock_score, is_default, is_active, sort_order, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
                (
                    "char_1",
                    "主线一",
                    "起始剧情",
                    10,
                    True,
                    True,
                    2,
                    "2026-01-02T03:04:05+00:00",
                    "2026-01-02T03:04:05+00:00",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_storyline_route_skips_default_reset_when_not_default(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=_Row({"id": 78})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-02-03T04:05:06+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/storylines",
                    json={
                        "name": "支线",
                        "description": "分支剧情",
                        "unlock_score": 0,
                        "is_default": False,
                        "is_active": True,
                        "sort_order": 5,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"id": 78, "ok": True}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            INSERT INTO character_storylines
            (character_id, name, description,
             unlock_score, is_default, is_active, sort_order, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
                (
                    "char_1",
                    "支线",
                    "分支剧情",
                    0,
                    False,
                    True,
                    5,
                    "2026-02-03T04:05:06+00:00",
                    "2026-02-03T04:05:06+00:00",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_storyline_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing/storylines",
                    json={
                        "name": "主线一",
                        "description": "起始剧情",
                        "unlock_score": 10,
                        "is_default": True,
                        "is_active": True,
                        "sort_order": 2,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_storyline_route_resets_other_defaults_before_update(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 91})),
            _QueryResult(),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-03-04T05:06:07+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/storylines/91",
                    json={
                        "name": "主线终章",
                        "description": "收束剧情",
                        "unlock_score": 99,
                        "is_default": True,
                        "is_active": False,
                        "sort_order": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("91", "char_1"),
            ),
            call(
                """UPDATE character_storylines SET is_default = 0
                   WHERE character_id = %s AND id != %s""",
                ("char_1", "91"),
            ),
            call(
                """
            UPDATE character_storylines SET
                name = %s,
                description = %s,
                unlock_score = %s,
                is_default = %s,
                is_active = %s,
                sort_order = %s,
                updated_at = %s
            WHERE id = %s
            """,
                (
                    "主线终章",
                    "收束剧情",
                    99,
                    True,
                    False,
                    1,
                    "2026-03-04T05:06:07+00:00",
                    "91",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_storyline_route_skips_default_reset_when_not_default(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 92})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-04-05T06:07:08+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/storylines/92",
                    json={
                        "name": "支线修订",
                        "description": "补完剧情",
                        "unlock_score": 20,
                        "is_default": False,
                        "is_active": True,
                        "sort_order": 6,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("92", "char_1"),
            ),
            call(
                """
            UPDATE character_storylines SET
                name = %s,
                description = %s,
                unlock_score = %s,
                is_default = %s,
                is_active = %s,
                sort_order = %s,
                updated_at = %s
            WHERE id = %s
            """,
                (
                    "支线修订",
                    "补完剧情",
                    20,
                    False,
                    True,
                    6,
                    "2026-04-05T06:07:08+00:00",
                    "92",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_storyline_route_returns_404_when_storyline_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/storylines/404",
                    json={
                        "name": "不存在",
                        "description": "不会生效",
                        "unlock_score": 0,
                        "is_default": False,
                        "is_active": True,
                        "sort_order": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "剧情线不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_greeting_route_returns_created_id_when_storyline_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=_Row({"id": 91})),
            _QueryResult(one=_Row({"id": 301})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-05-06T07:08:09+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/greetings",
                    json={
                        "story_phase": "friend",
                        "mood": "happy",
                        "content": "欢迎回来",
                        "storyline_id": "91",
                        "priority": 7,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"id": 301, "ok": True}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("91", "char_1"),
            ),
            call(
                """
            INSERT INTO character_greetings
            (character_id, story_phase, mood, content, storyline_id,
             priority, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
                (
                    "char_1",
                    "friend",
                    "happy",
                    "欢迎回来",
                    "91",
                    7,
                    1,
                    "2026-05-06T07:08:09+00:00",
                    "2026-05-06T07:08:09+00:00",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_greeting_route_rejects_storyline_not_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=None),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-05-06T07:08:09+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/greetings",
                    json={
                        "story_phase": "friend",
                        "mood": "happy",
                        "content": "欢迎回来",
                        "storyline_id": "999",
                        "priority": 7,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "剧情线不存在或不属于该角色"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("999", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_greeting_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing/greetings",
                    json={
                        "story_phase": "friend",
                        "mood": "happy",
                        "content": "欢迎回来",
                        "storyline_id": None,
                        "priority": 7,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_greeting_route_returns_ok_when_storyline_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 301})),
            _QueryResult(one=_Row({"id": 91})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-06-07T08:09:10+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/greetings/301",
                    json={
                        "story_phase": "lover",
                        "mood": "happy",
                        "content": "今晚也在这里",
                        "storyline_id": "91",
                        "priority": 9,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
                ("301", "char_1"),
            ),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("91", "char_1"),
            ),
            call(
                """
            UPDATE character_greetings SET
                story_phase = %s,
                mood = %s,
                content = %s,
                storyline_id = %s,
                priority = %s,
                is_active = %s,
                updated_at = %s
            WHERE id = %s
            """,
                (
                    "lover",
                    "happy",
                    "今晚也在这里",
                    "91",
                    9,
                    0,
                    "2026-06-07T08:09:10+00:00",
                    "301",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_greeting_route_rejects_storyline_not_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 301})),
            _QueryResult(one=None),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn), patch(
                "routers.admin.characters_story.utc_now_iso",
                return_value="2026-06-07T08:09:10+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/greetings/301",
                    json={
                        "story_phase": "lover",
                        "mood": "happy",
                        "content": "今晚也在这里",
                        "storyline_id": "999",
                        "priority": 9,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "剧情线不存在或不属于该角色"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
                ("301", "char_1"),
            ),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("999", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_greeting_route_returns_404_when_greeting_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/greetings/404",
                    json={
                        "story_phase": "lover",
                        "mood": "happy",
                        "content": "不会生效",
                        "storyline_id": None,
                        "priority": 9,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "开场白不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_greeting_route_returns_ok_and_deletes_target(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 301})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/greetings/301")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
                ("301", "char_1"),
            ),
            call(
                "DELETE FROM character_greetings WHERE id = %s",
                ("301",),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_greeting_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/greetings/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "开场白不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_story_event_route_returns_created_id_when_unlock_refs_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(many=[_Row({"id": "m1"}), _Row({"id": "m2"})]),
            _QueryResult(many=[_Row({"id": "g1"})]),
            _QueryResult(one=_Row({"id": "s1"})),
            _QueryResult(one=_Row({"id": 501})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn), patch(
                "routers.admin.characters_rules_events.uuid.uuid4",
                return_value="evt-fixed-uuid",
            ), patch(
                "routers.admin.characters_rules_events.utc_now_iso",
                return_value="2026-07-08T09:10:11+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/story-events",
                    json={
                        "title": "相遇事件",
                        "description": "完成首次解锁",
                        "trigger_score": 20,
                        "unlocked_memory_ids": "m1,m2",
                        "unlocked_greeting_ids": "g1",
                        "unlocked_storyline_id": "s1",
                        "event_content": "特殊剧情",
                        "sort_order": 4,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"id": 501, "ok": True}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM character_memories WHERE character_id = %s AND is_active = 1",
                ("char_1",),
            ),
            call(
                "SELECT id FROM character_greetings WHERE character_id = %s AND is_active = 1",
                ("char_1",),
            ),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s AND is_active = 1",
                ("s1", "char_1"),
            ),
            call(
                """
            INSERT INTO story_events
            (character_id, event_id, title, description, trigger_score,
             unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
             event_content, sort_order, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
                (
                    "char_1",
                    "evt-fixed-uuid",
                    "相遇事件",
                    "完成首次解锁",
                    20,
                    "m1,m2",
                    "g1",
                    "s1",
                    "特殊剧情",
                    4,
                    1,
                    "2026-07-08T09:10:11+00:00",
                    "2026-07-08T09:10:11+00:00",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_story_event_route_rejects_invalid_memory_unlock_ids(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(many=[_Row({"id": "m1"})]),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/char_1/story-events",
                    json={
                        "title": "相遇事件",
                        "description": "完成首次解锁",
                        "trigger_score": 20,
                        "unlocked_memory_ids": "m1,m2",
                        "unlocked_greeting_ids": "",
                        "unlocked_storyline_id": None,
                        "event_content": "特殊剧情",
                        "sort_order": 4,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "存在无效或已禁用的记忆解锁对象：['m2']"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM character_memories WHERE character_id = %s AND is_active = 1",
                ("char_1",),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_story_event_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing/story-events",
                    json={
                        "title": "相遇事件",
                        "description": "完成首次解锁",
                        "trigger_score": 20,
                        "unlocked_memory_ids": "",
                        "unlocked_greeting_ids": "",
                        "unlocked_storyline_id": None,
                        "event_content": "特殊剧情",
                        "sort_order": 4,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_story_event_route_returns_ok_when_unlock_refs_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 501})),
            _QueryResult(many=[_Row({"id": "m1"})]),
            _QueryResult(many=[_Row({"id": "g1"}), _Row({"id": "g2"})]),
            _QueryResult(one=_Row({"id": "s1"})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn), patch(
                "routers.admin.characters_rules_events.utc_now_iso",
                return_value="2026-08-09T10:11:12+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/story-events/501",
                    json={
                        "title": "终章事件",
                        "description": "完成最终解锁",
                        "trigger_score": 88,
                        "unlocked_memory_ids": "m1",
                        "unlocked_greeting_ids": "g1,g2",
                        "unlocked_storyline_id": "s1",
                        "event_content": "终章剧情",
                        "sort_order": 9,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
                ("501", "char_1"),
            ),
            call(
                "SELECT id FROM character_memories WHERE character_id = %s AND is_active = 1",
                ("char_1",),
            ),
            call(
                "SELECT id FROM character_greetings WHERE character_id = %s AND is_active = 1",
                ("char_1",),
            ),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s AND is_active = 1",
                ("s1", "char_1"),
            ),
            call(
                """
            UPDATE story_events SET
                title = %s,
                description = %s,
                trigger_score = %s,
                unlocked_memory_ids = %s,
                unlocked_greeting_ids = %s,
                unlocked_storyline_id = %s,
                event_content = %s,
                sort_order = %s,
                is_active = %s,
                updated_at = %s
            WHERE id = %s
            """,
                (
                    "终章事件",
                    "完成最终解锁",
                    88,
                    "m1",
                    "g1,g2",
                    "s1",
                    "终章剧情",
                    9,
                    0,
                    "2026-08-09T10:11:12+00:00",
                    "501",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_story_event_route_rejects_invalid_greeting_unlock_ids(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 501})),
            _QueryResult(many=[_Row({"id": "m1"})]),
            _QueryResult(many=[_Row({"id": "g1"})]),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/story-events/501",
                    json={
                        "title": "终章事件",
                        "description": "完成最终解锁",
                        "trigger_score": 88,
                        "unlocked_memory_ids": "m1",
                        "unlocked_greeting_ids": "g1,g2",
                        "unlocked_storyline_id": None,
                        "event_content": "终章剧情",
                        "sort_order": 9,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "存在无效或已禁用的开场白解锁对象：['g2']"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
                ("501", "char_1"),
            ),
            call(
                "SELECT id FROM character_memories WHERE character_id = %s AND is_active = 1",
                ("char_1",),
            ),
            call(
                "SELECT id FROM character_greetings WHERE character_id = %s AND is_active = 1",
                ("char_1",),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_story_event_route_returns_404_when_event_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/story-events/404",
                    json={
                        "title": "不存在",
                        "description": "不会生效",
                        "trigger_score": 0,
                        "unlocked_memory_ids": "",
                        "unlocked_greeting_ids": "",
                        "unlocked_storyline_id": None,
                        "event_content": "",
                        "sort_order": 0,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "剧情事件不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_story_event_route_returns_ok_and_deletes_target(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 501})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/story-events/501")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
                ("501", "char_1"),
            ),
            call(
                "DELETE FROM story_events WHERE id = %s",
                ("501",),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_story_event_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/story-events/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "剧情事件不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_post_rule_route_returns_created_id_when_storyline_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=_Row({"id": 91})),
            _QueryResult(one=_Row({"id": 601})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn), patch(
                "routers.admin.characters_rules_events.utc_now_iso",
                return_value="2026-08-09T10:11:12+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/post-rules",
                    json={
                        "name": "格式约束",
                        "content": "输出必须简洁",
                        "storyline_id": "91",
                        "story_phase": "friend",
                        "priority": 5,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"id": 601, "ok": True}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("91", "char_1"),
            ),
            call(
                """
            INSERT INTO character_post_rules
            (character_id, name, content, storyline_id, story_phase,
             priority, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
                (
                    "char_1",
                    "格式约束",
                    "输出必须简洁",
                    "91",
                    "friend",
                    5,
                    1,
                    "2026-08-09T10:11:12+00:00",
                    "2026-08-09T10:11:12+00:00",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_post_rule_route_rejects_storyline_not_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=None),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/char_1/post-rules",
                    json={
                        "name": "格式约束",
                        "content": "输出必须简洁",
                        "storyline_id": "999",
                        "story_phase": "friend",
                        "priority": 5,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "剧情线不存在或不属于该角色"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("999", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_post_rule_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing/post-rules",
                    json={
                        "name": "格式约束",
                        "content": "输出必须简洁",
                        "storyline_id": None,
                        "story_phase": "friend",
                        "priority": 5,
                        "is_active": 1,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_post_rule_route_returns_ok_and_normalizes_empty_story_phase(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 601})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn), patch(
                "routers.admin.characters_rules_events.utc_now_iso",
                return_value="2026-08-10T11:12:13+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/post-rules/601",
                    json={
                        "name": "风格约束",
                        "content": "禁止重复句式",
                        "storyline_id": None,
                        "story_phase": None,
                        "priority": 8,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
                ("601", "char_1"),
            ),
            call(
                """
            UPDATE character_post_rules SET
                name = %s,
                content = %s,
                storyline_id = %s,
                story_phase = %s,
                priority = %s,
                is_active = %s,
                updated_at = %s
            WHERE id = %s
            """,
                (
                    "风格约束",
                    "禁止重复句式",
                    None,
                    "",
                    8,
                    0,
                    "2026-08-10T11:12:13+00:00",
                    "601",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_post_rule_route_rejects_storyline_not_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 601})),
            _QueryResult(one=None),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/post-rules/601",
                    json={
                        "name": "风格约束",
                        "content": "禁止重复句式",
                        "storyline_id": "999",
                        "story_phase": "lover",
                        "priority": 8,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "剧情线不存在或不属于该角色"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
                ("601", "char_1"),
            ),
            call(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
                ("999", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_post_rule_route_returns_404_when_rule_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/post-rules/404",
                    json={
                        "name": "不会生效",
                        "content": "不会生效",
                        "storyline_id": None,
                        "story_phase": None,
                        "priority": 8,
                        "is_active": 0,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "后置规则不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_post_rule_route_returns_ok_and_deletes_target(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 601})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/post-rules/601")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
                ("601", "char_1"),
            ),
            call(
                "DELETE FROM character_post_rules WHERE id = %s",
                ("601",),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_post_rule_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/post-rules/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "后置规则不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_memory_category_route_returns_created_id(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=_Row({"id": 701})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn), patch(
                "routers.admin.characters_memory.utc_now_iso",
                return_value="2026-09-10T11:12:13+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/memory-categories",
                    json={
                        "name": "核心设定",
                        "description": "长期设定集合",
                        "color": "#FF6B6B",
                        "sort_order": 3,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"id": 701, "ok": True}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            INSERT INTO memory_categories
            (character_id, name, description, color, sort_order, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
                (
                    "char_1",
                    "核心设定",
                    "长期设定集合",
                    "#FF6B6B",
                    3,
                    "2026-09-10T11:12:13+00:00",
                    "2026-09-10T11:12:13+00:00",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_memory_category_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing/memory-categories",
                    json={
                        "name": "核心设定",
                        "description": "长期设定集合",
                        "color": "#FF6B6B",
                        "sort_order": 3,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_memory_category_route_returns_ok(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 701})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn), patch(
                "routers.admin.characters_memory.utc_now_iso",
                return_value="2026-09-11T12:13:14+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/memory-categories/701",
                    json={
                        "name": "新设定",
                        "description": "更新后的说明",
                        "color": "#1890FF",
                        "sort_order": 8,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("701", "char_1"),
            ),
            call(
                """
            UPDATE memory_categories SET
                name = %s,
                description = %s,
                color = %s,
                sort_order = %s,
                updated_at = %s
            WHERE id = %s
            """,
                (
                    "新设定",
                    "更新后的说明",
                    "#1890FF",
                    8,
                    "2026-09-11T12:13:14+00:00",
                    "701",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_memory_category_route_returns_404_when_category_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/memory-categories/404",
                    json={
                        "name": "不会生效",
                        "description": "不会生效",
                        "color": "#1890FF",
                        "sort_order": 8,
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "记忆分类不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_memory_category_route_returns_ok_when_no_dependent_memories(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 701})),
            _QueryResult(one=_Row({"count": 0})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/memory-categories/701")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("701", "char_1"),
            ),
            call(
                "SELECT COUNT(*) FROM character_memories WHERE category_id = %s",
                ("701",),
            ),
            call(
                "DELETE FROM memory_categories WHERE id = %s",
                ("701",),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_memory_category_route_rejects_when_dependent_memories_exist(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 701})),
            _QueryResult(one=_Row({"count": 2})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/memory-categories/701")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "该分类下还有 2 个记忆条目，请先移除或修改这些条目"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("701", "char_1"),
            ),
            call(
                "SELECT COUNT(*) FROM character_memories WHERE category_id = %s",
                ("701",),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_memory_category_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/memory-categories/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "记忆分类不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_memory_route_returns_created_id_when_category_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=_Row({"id": 701})),
            _QueryResult(one=_Row({"id": 801})),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn), patch(
                "routers.admin.characters_memory.utc_now_iso",
                return_value="2026-10-11T12:13:14+00:00",
            ):
                response = client.post(
                    "/api/admin/character/char_1/memories",
                    json={
                        "keywords": "月亮,夜晚",
                        "trigger_logic": "all",
                        "content": "她记得那个夜晚",
                        "category_id": "701",
                        "position": "after",
                        "priority": 6,
                        "is_active": 1,
                        "comment": "核心记忆",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"id": 801, "ok": True}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("701", "char_1"),
            ),
            call(
                """
            INSERT INTO character_memories
            (character_id, keywords, trigger_logic, content, category_id, position,
             priority, is_active, comment, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
                (
                    "char_1",
                    "月亮,夜晚",
                    "all",
                    "她记得那个夜晚",
                    "701",
                    "after",
                    6,
                    1,
                    "核心记忆",
                    "2026-10-11T12:13:14+00:00",
                    "2026-10-11T12:13:14+00:00",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_create_memory_route_rejects_category_not_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(one=None),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/char_1/memories",
                    json={
                        "keywords": "月亮,夜晚",
                        "trigger_logic": "all",
                        "content": "她记得那个夜晚",
                        "category_id": "999",
                        "position": "after",
                        "priority": 6,
                        "is_active": 1,
                        "comment": "核心记忆",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "分类不存在或不属于该角色"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("999", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_create_memory_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.post(
                    "/api/admin/character/missing/memories",
                    json={
                        "keywords": "月亮,夜晚",
                        "trigger_logic": "all",
                        "content": "她记得那个夜晚",
                        "category_id": None,
                        "position": "after",
                        "priority": 6,
                        "is_active": 1,
                        "comment": "核心记忆",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_memory_route_returns_ok_when_category_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 801})),
            _QueryResult(one=_Row({"id": 701})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn), patch(
                "routers.admin.characters_memory.utc_now_iso",
                return_value="2026-10-12T13:14:15+00:00",
            ):
                response = client.put(
                    "/api/admin/character/char_1/memories/801",
                    json={
                        "keywords": "雨天,车站",
                        "trigger_logic": "any",
                        "content": "她想起离别的车站",
                        "category_id": "701",
                        "position": "before",
                        "priority": 4,
                        "is_active": 0,
                        "comment": "更新后的备注",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
                ("801", "char_1"),
            ),
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("701", "char_1"),
            ),
            call(
                """
            UPDATE character_memories SET
                keywords = %s,
                trigger_logic = %s,
                content = %s,
                category_id = %s,
                position = %s,
                priority = %s,
                is_active = %s,
                comment = %s,
                updated_at = %s
            WHERE id = %s
            """,
                (
                    "雨天,车站",
                    "any",
                    "她想起离别的车站",
                    "701",
                    "before",
                    4,
                    0,
                    "更新后的备注",
                    "2026-10-12T13:14:15+00:00",
                    "801",
                ),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_update_memory_route_rejects_category_not_owned(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 801})),
            _QueryResult(one=None),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/memories/801",
                    json={
                        "keywords": "雨天,车站",
                        "trigger_logic": "any",
                        "content": "她想起离别的车站",
                        "category_id": "999",
                        "position": "before",
                        "priority": 4,
                        "is_active": 0,
                        "comment": "更新后的备注",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400
        assert response.json() == {"detail": "分类不存在或不属于该角色"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
                ("801", "char_1"),
            ),
            call(
                "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
                ("999", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_update_memory_route_returns_404_when_memory_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.put(
                    "/api/admin/character/char_1/memories/404",
                    json={
                        "keywords": "不会生效",
                        "trigger_logic": "any",
                        "content": "不会生效",
                        "category_id": None,
                        "position": "before",
                        "priority": 4,
                        "is_active": 0,
                        "comment": "不会生效",
                    },
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "记忆条目不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_delete_memory_route_returns_ok_and_deletes_target(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": 801})),
            _QueryResult(),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/memories/801")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
                ("801", "char_1"),
            ),
            call(
                "DELETE FROM character_memories WHERE id = %s",
                ("801",),
            ),
        ]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_admin_delete_memory_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.delete("/api/admin/character/char_1/memories/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "记忆条目不存在"}
        assert conn.execute.call_args_list == [
            call(
                "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
                ("404", "char_1"),
            ),
        ]
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_admin_list_memories_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(
                many=[
                    _Row(
                        {
                            "id": 801,
                            "keywords": "月亮,夜晚",
                            "trigger_logic": "all",
                            "content": "她记得那个夜晚",
                            "category_id": 701,
                            "position": "after",
                            "priority": 6,
                            "is_active": 1,
                            "comment": None,
                            "created_at": "2026-10-11T12:13:14+00:00",
                            "updated_at": "2026-10-12T13:14:15+00:00",
                        }
                    )
                ]
            ),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/memories")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 801,
                "keywords": "月亮,夜晚",
                "trigger_logic": "all",
                "content": "她记得那个夜晚",
                "category_id": 701,
                "position": "after",
                "priority": 6,
                "is_active": True,
                "comment": "",
                "created_at": "2026-10-11T12:13:14+00:00",
                "updated_at": "2026-10-12T13:14:15+00:00",
            }
        ]
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            SELECT id, keywords, trigger_logic, content, category_id, position,
                   priority, is_active, comment, created_at, updated_at
            FROM character_memories
            WHERE character_id = %s
            ORDER BY priority ASC, id ASC
            """,
                ("char_1",),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_list_memories_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing/memories")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.close.assert_called_once()

    def test_admin_list_memory_categories_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(
                many=[
                    _Row(
                        {
                            "id": 701,
                            "name": "核心设定",
                            "description": None,
                            "color": None,
                            "sort_order": 3,
                            "created_at": "2026-09-10T11:12:13+00:00",
                            "updated_at": "2026-09-11T12:13:14+00:00",
                        }
                    )
                ]
            ),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/memory-categories")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 701,
                "name": "核心设定",
                "description": "",
                "color": "#1890FF",
                "sort_order": 3,
                "created_at": "2026-09-10T11:12:13+00:00",
                "updated_at": "2026-09-11T12:13:14+00:00",
            }
        ]
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            SELECT id, name, description, color, sort_order, created_at, updated_at
            FROM memory_categories
            WHERE character_id = %s
            ORDER BY sort_order ASC, id ASC
            """,
                ("char_1",),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_list_memory_categories_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_memory.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing/memory-categories")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.close.assert_called_once()

    def test_admin_list_post_rules_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(
                many=[
                    _Row(
                        {
                            "id": 601,
                            "name": "格式约束",
                            "content": "输出必须简洁",
                            "storyline_id": 91,
                            "story_phase": "friend",
                            "priority": 5,
                            "is_active": 1,
                            "created_at": "2026-08-09T10:11:12+00:00",
                            "updated_at": "2026-08-10T11:12:13+00:00",
                        }
                    )
                ]
            ),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/post-rules")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 601,
                "name": "格式约束",
                "content": "输出必须简洁",
                "storyline_id": 91,
                "story_phase": "friend",
                "priority": 5,
                "is_active": True,
                "created_at": "2026-08-09T10:11:12+00:00",
                "updated_at": "2026-08-10T11:12:13+00:00",
            }
        ]
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            SELECT id, name, content, storyline_id, story_phase,
                   priority, is_active, created_at, updated_at
            FROM character_post_rules
            WHERE character_id = %s
            ORDER BY priority ASC, id ASC
            """,
                ("char_1",),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_list_post_rules_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing/post-rules")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.close.assert_called_once()

    def test_admin_list_story_events_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(
                many=[
                    _Row(
                        {
                            "id": 501,
                            "title": "初遇",
                            "description": None,
                            "trigger_score": 10,
                            "unlocked_memory_ids": None,
                            "unlocked_greeting_ids": "g1,g2",
                            "unlocked_storyline_id": 91,
                            "event_content": None,
                            "sort_order": 2,
                            "is_active": 1,
                            "created_at": "2026-07-08T09:10:11+00:00",
                            "updated_at": "2026-07-09T10:11:12+00:00",
                        }
                    )
                ]
            ),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/story-events")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 501,
                "title": "初遇",
                "description": "",
                "trigger_score": 10,
                "unlocked_memory_ids": "",
                "unlocked_greeting_ids": "g1,g2",
                "unlocked_storyline_id": 91,
                "event_content": "",
                "sort_order": 2,
                "is_active": True,
                "created_at": "2026-07-08T09:10:11+00:00",
                "updated_at": "2026-07-09T10:11:12+00:00",
            }
        ]
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            SELECT id, title, description, trigger_score,
                   unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
                   event_content, sort_order, is_active, created_at, updated_at
            FROM story_events
            WHERE character_id = %s
            ORDER BY trigger_score ASC, sort_order ASC, id ASC
            """,
                ("char_1",),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_list_story_events_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_rules_events.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing/story-events")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.close.assert_called_once()

    def test_admin_list_greetings_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(
                many=[
                    _Row(
                        {
                            "id": 301,
                            "story_phase": "friend",
                            "mood": "happy",
                            "content": "欢迎回来",
                            "storyline_id": 91,
                            "priority": 2,
                            "is_active": 1,
                            "use_count": 7,
                            "comment": None,
                            "created_at": "2026-06-01T10:00:00+00:00",
                            "updated_at": "2026-06-02T11:00:00+00:00",
                        }
                    )
                ]
            ),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/greetings")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 301,
                "story_phase": "friend",
                "mood": "happy",
                "content": "欢迎回来",
                "storyline_id": 91,
                "priority": 2,
                "is_active": True,
                "use_count": 7,
                "comment": "",
                "created_at": "2026-06-01T10:00:00+00:00",
                "updated_at": "2026-06-02T11:00:00+00:00",
            }
        ]
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            SELECT id, story_phase, mood, content, storyline_id,
                   priority, is_active, use_count, comment, created_at, updated_at
            FROM character_greetings
            WHERE character_id = %s
            ORDER BY story_phase, priority ASC, id ASC
            """,
                ("char_1",),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_list_greetings_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing/greetings")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.close.assert_called_once()

    def test_admin_list_storylines_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.side_effect = [
            _QueryResult(one=_Row({"id": "char_1"})),
            _QueryResult(
                many=[
                    _Row(
                        {
                            "id": 91,
                            "name": "校园线",
                            "description": None,
                            "unlock_score": 10,
                            "is_default": 1,
                            "is_active": 0,
                            "sort_order": 3,
                            "created_at": "2026-05-01T09:00:00+00:00",
                            "updated_at": "2026-05-02T09:30:00+00:00",
                        }
                    )
                ]
            ),
        ]

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.get("/api/admin/character/char_1/storylines")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 91,
                "name": "校园线",
                "description": "",
                "unlock_score": 10,
                "is_default": True,
                "is_active": False,
                "sort_order": 3,
                "created_at": "2026-05-01T09:00:00+00:00",
                "updated_at": "2026-05-02T09:30:00+00:00",
            }
        ]
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("char_1",)),
            call(
                """
            SELECT id, name, description, unlock_score, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM character_storylines
            WHERE character_id = %s
            ORDER BY sort_order ASC, id ASC
            """,
                ("char_1",),
            ),
        ]
        conn.close.assert_called_once()

    def test_admin_list_storylines_route_returns_404_when_character_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = MagicMock()
        conn.execute.return_value = _QueryResult(one=None)

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.characters_story.get_conn", return_value=conn):
                response = client.get("/api/admin/character/missing/storylines")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "角色不存在"}
        assert conn.execute.call_args_list == [
            call("SELECT id FROM characters WHERE id = %s", ("missing",)),
        ]
        conn.close.assert_called_once()

    def test_admin_orders_route_returns_stable_list_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({"total": 1})),
            _QueryResult(many=[
                _Row({
                    "id": 11,
                    "order_no": "ORD-001",
                    "user_id": 7,
                    "user_email": "vip@example.com",
                    "user_nickname": "测试会员",
                    "plan_type": "svip",
                    "amount_cents": 9900,
                    "currency": "CNY",
                    "duration_days": 30,
                    "status": "paid",
                    "payment_provider": "mockpay",
                    "provider_trade_no": "TRADE-1",
                    "checkout_url": "https://example.com/pay/1",
                    "created_at": "2026-01-01T00:00:00Z",
                    "paid_at": "2026-01-01T00:05:00Z",
                    "expires_at": "2026-01-31T00:00:00Z",
                    "closed_at": None,
                })
            ]),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.orders.get_conn", return_value=conn):
                response = client.get(
                    "/api/admin/orders",
                    params={"search": "ORD", "status": "paid", "page": 3, "limit": 50},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "total": 1,
            "page": 3,
            "limit": 50,
            "orders": [
                {
                    "id": 11,
                    "order_no": "ORD-001",
                    "user_id": 7,
                    "user_email": "vip@example.com",
                    "user_nickname": "测试会员",
                    "plan_type": "svip",
                    "plan_label": "SVIP",
                    "amount_cents": 9900,
                    "currency": "CNY",
                    "duration_days": 30,
                    "status": "paid",
                    "payment_provider": "mockpay",
                    "provider_trade_no": "TRADE-1",
                    "checkout_url": "https://example.com/pay/1",
                    "created_at": "2026-01-01T00:00:00Z",
                    "paid_at": "2026-01-01T00:05:00Z",
                    "expires_at": "2026-01-31T00:00:00Z",
                    "closed_at": None,
                }
            ],
        }

    def test_admin_export_orders_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(many=[
                _Row({
                    "id": 12,
                    "order_no": "ORD-002",
                    "user_id": 8,
                    "user_email": "svip@example.com",
                    "user_nickname": "高级会员",
                    "plan_type": "vip",
                    "amount_cents": 4900,
                    "currency": "CNY",
                    "duration_days": 30,
                    "status": "pending",
                    "payment_provider": "mockpay",
                    "provider_trade_no": "TRADE-2",
                    "checkout_url": "https://example.com/pay/2",
                    "created_at": "2026-01-02T00:00:00Z",
                    "paid_at": None,
                    "expires_at": None,
                    "closed_at": None,
                })
            ]),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.orders.get_conn", return_value=conn):
                response = client.get("/api/admin/orders/export")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == [
            {
                "id": 12,
                "order_no": "ORD-002",
                "user_id": 8,
                "user_email": "svip@example.com",
                "user_nickname": "高级会员",
                "plan_type": "vip",
                "plan_label": "VIP",
                "amount_cents": 4900,
                "currency": "CNY",
                "duration_days": 30,
                "status": "pending",
                "payment_provider": "mockpay",
                "provider_trade_no": "TRADE-2",
                "checkout_url": "https://example.com/pay/2",
                "created_at": "2026-01-02T00:00:00Z",
                "paid_at": None,
                "expires_at": None,
                "closed_at": None,
            }
        ]

    def test_admin_get_order_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({
                "id": 12,
                "order_no": "ORD-002",
                "user_id": 8,
                "user_email": "svip@example.com",
                "user_nickname": "高级会员",
                "plan_type": "vip",
                "amount_cents": 4900,
                "currency": "CNY",
                "duration_days": 30,
                "status": "pending",
                "payment_provider": "mockpay",
                "provider_trade_no": "TRADE-2",
                "checkout_url": "https://example.com/pay/2",
                "created_at": "2026-01-02T00:00:00Z",
                "paid_at": None,
                "expires_at": None,
                "closed_at": None,
            })),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.orders.get_conn", return_value=conn):
                response = client.get("/api/admin/orders/12")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "id": 12,
            "order_no": "ORD-002",
            "user_id": 8,
            "user_email": "svip@example.com",
            "user_nickname": "高级会员",
            "plan_type": "vip",
            "plan_label": "VIP",
            "amount_cents": 4900,
            "currency": "CNY",
            "duration_days": 30,
            "status": "pending",
            "payment_provider": "mockpay",
            "provider_trade_no": "TRADE-2",
            "checkout_url": "https://example.com/pay/2",
            "created_at": "2026-01-02T00:00:00Z",
            "paid_at": None,
            "expires_at": None,
            "closed_at": None,
        }

    def test_admin_get_order_route_returns_404_when_target_missing(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=None),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.orders.get_conn", return_value=conn):
                response = client.get("/api/admin/orders/404")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
        assert response.json() == {"detail": "订单不存在"}

    def test_admin_dashboard_stats_route_returns_stable_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(one=_Row({"cnt": 10})),
            _QueryResult(one=_Row({"cnt": 2})),
            _QueryResult(one=_Row({"cnt": 4})),
            _QueryResult(one=_Row({"cnt": 3})),
            _QueryResult(one=_Row({"total": 9900})),
            _QueryResult(one=_Row({"cnt": 1})),
            _QueryResult(many=[
                _Row({"plan_type": "vip", "cnt": 4}),
                _Row({"plan_type": None, "cnt": 6}),
            ]),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.dashboard.get_conn", return_value=conn):
                response = client.get("/api/admin/dashboard/stats")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "total_users": 10,
            "today_new_users": 2,
            "paid_users": 4,
            "paid_rate": 40.0,
            "today_orders": 3,
            "today_revenue": 9900,
            "avg_order_value": 3300,
            "expiring_soon": 1,
            "plan_distribution": {"vip": 4, "free": 6},
        }

    def test_admin_dashboard_trend_route_returns_stable_payload_with_clamped_days(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(many=[
                _Row({"day": "2026-01-01T00:00:00+00:00"}),
                _Row({"day": "2026-01-02T00:00:00+00:00"}),
            ]),
            _QueryResult(one=_Row({"cnt": 1})),
            _QueryResult(one=_Row({"cnt": 2})),
            _QueryResult(one=_Row({"total": 4900})),
            _QueryResult(one=_Row({"cnt": 0})),
            _QueryResult(one=_Row({"cnt": 1})),
            _QueryResult(one=_Row({"total": 9900})),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.dashboard.get_conn", return_value=conn):
                response = client.get("/api/admin/dashboard/trend", params={"days": 99})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "trend": [
                {"date": "2026-01-01", "new_users": 1, "new_orders": 2, "revenue": 4900},
                {"date": "2026-01-02", "new_users": 0, "new_orders": 1, "revenue": 9900},
            ],
            "days": 30,
        }

    def test_admin_batch_update_plan_route_returns_success_payload_and_audit_detail(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/batch-plan",
                    json={"user_ids": ["u1", "u2"], "plan_type": "svip", "duration_days": 45},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        payload = response.json()
        assert payload == {
            "ok": True,
            "message": "已为 2 位用户设置为 SVIP",
            "updated_count": 2,
        }
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["operator_id"] == 1
        assert audit_kwargs["operator_email"] == "admin@example.com"
        assert audit_kwargs["action"] == "batch_update"
        assert audit_kwargs["target_type"] == "user"
        assert audit_kwargs["target_id"] is None
        assert audit_kwargs["detail"] == {
            "user_ids": ["u1", "u2"],
            "plan_type": "svip",
            "duration_days": 45,
        }

    def test_admin_batch_update_plan_route_returns_free_plan_success_payload(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )
        conn = _SequenceConn([
            _QueryResult(),
            _QueryResult(),
            _QueryResult(),
        ])

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn", return_value=conn), patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/batch-plan",
                    json={"user_ids": ["u3", "u4", "u5"], "plan_type": "free", "duration_days": 30},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "message": "已为 3 位用户设置为 注册用户",
            "updated_count": 3,
        }
        mock_audit_log.assert_called_once()
        audit_kwargs = mock_audit_log.call_args.kwargs
        assert audit_kwargs["detail"] == {
            "user_ids": ["u3", "u4", "u5"],
            "plan_type": "free",
            "duration_days": 30,
        }

    def test_admin_batch_update_plan_route_rejects_empty_user_ids_before_db_access(self, app_client):
        _, client = app_client
        app = client.app
        admin_user = CurrentUser(
            id=1,
            email="admin@example.com",
            nickname="admin",
            effective_plan="vip",
            is_admin=True,
        )

        app.dependency_overrides[get_admin_user] = lambda: admin_user
        try:
            with patch("routers.admin.users.get_conn") as mock_get_conn, patch(
                "routers.admin.users._write_audit_log"
            ) as mock_audit_log:
                response = client.post(
                    "/api/admin/users/batch-plan",
                    json={"user_ids": [], "plan_type": "vip", "duration_days": 30},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "user_ids"]
        mock_get_conn.assert_not_called()
        mock_audit_log.assert_not_called()


class TestChatRouteContracts:
    def test_chat_send_route_returns_stable_sync_payload(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(
            id=8,
            email="chat@example.com",
            nickname="tester",
            effective_plan="vip",
        )
        expected = {
            "reply": "你好呀",
            "history_count": 6,
            "summary_enabled": True,
            "character_state": {
                "affection": 88,
                "story_phase": "friend",
                "mood": "warm",
            },
        }

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.chat._enforce_user_chat_rate_limit") as mock_rate_limit, patch(
                "routers.chat._build_chat_send_route_response",
                return_value=expected,
            ) as mock_builder:
                response = client.post(
                    "/api/chat/send",
                    json={"character_id": "char_1", "message": "你好"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == expected
        mock_rate_limit.assert_called_once_with(user.id, detail="聊天请求过于频繁")
        assert mock_builder.call_args.kwargs["user"] == user
        assert mock_builder.call_args.kwargs["payload"].character_id == "char_1"
        assert mock_builder.call_args.kwargs["payload"].message == "你好"
        assert mock_builder.call_args.kwargs["request"].url.path == "/api/chat/send"

    @pytest.mark.parametrize(
        ("endpoint", "operation", "is_append"),
        [
            ("/api/chat/regenerate", "regenerate", False),
            ("/api/chat/continue", "continue", True),
        ],
    )
    def test_retry_routes_delegate_to_rate_limited_builder(
        self,
        app_client,
        endpoint,
        operation,
        is_append,
    ):
        _, client = app_client
        app = client.app
        user = CurrentUser(
            id=9,
            email="retry@example.com",
            nickname="retrier",
            effective_plan="vip",
        )
        expected = {"ok": True, "operation": operation}

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.chat._enforce_user_chat_rate_limit") as mock_rate_limit, patch(
                "routers.chat._build_retry_route_response",
                return_value=expected,
            ) as mock_builder:
                response = client.post(endpoint, json={"message_id": "msg_1"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == expected
        mock_rate_limit.assert_called_once_with(user.id, detail="操作过于频繁")
        assert mock_builder.call_args.kwargs["user"] == user
        assert mock_builder.call_args.kwargs["message_id"] == "msg_1"
        assert mock_builder.call_args.kwargs["operation"] == operation
        assert mock_builder.call_args.kwargs["endpoint"] == endpoint
        assert mock_builder.call_args.kwargs["is_append"] is is_append
        assert mock_builder.call_args.kwargs["request"].url.path == endpoint

    def test_chat_stream_route_delegates_to_main_builder(self, app_client):
        _, client = app_client
        app = client.app
        user = CurrentUser(
            id=10,
            email="stream@example.com",
            nickname="streamer",
            effective_plan="vip",
        )
        expected = {"ok": True, "route": "main-stream"}

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("routers.chat._build_main_route_response", return_value=expected) as mock_builder:
                response = client.post(
                    "/api/chat/stream",
                    json={"character_id": "char_1", "message": "你好"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == expected
        assert mock_builder.call_args.kwargs["user"] == user
        assert mock_builder.call_args.kwargs["payload"].character_id == "char_1"
        assert mock_builder.call_args.kwargs["payload"].message == "你好"
        assert mock_builder.call_args.kwargs["request"].url.path == "/api/chat/stream"

    def test_chat_guest_stream_route_delegates_to_guest_builder(self, app_client):
        _, client = app_client
        expected = {"ok": True, "route": "guest-stream"}

        with patch("routers.chat._build_guest_route_response", return_value=expected) as mock_builder:
            response = client.post(
                "/api/chat/guest-stream",
                json={"character_id": "char_guest", "message": "嗨"},
            )

        assert response.status_code == 200
        assert response.json() == expected
        assert mock_builder.call_args.kwargs["payload"].character_id == "char_guest"
        assert mock_builder.call_args.kwargs["payload"].message == "嗨"
        assert mock_builder.call_args.kwargs["request"].url.path == "/api/chat/guest-stream"
