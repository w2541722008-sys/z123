"""
Schema 契约测试 - 验证 Pydantic 模型输入校验与规范化
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestInputValidation:
    """验证 Pydantic 输入验证完整性。"""

    def test_register_payload_requires_email(self):
        """注册接口必须验证邮箱格式。"""
        from core.schemas import RegisterPayload

        with pytest.raises(Exception):
            RegisterPayload(email="", password="test123")

        with pytest.raises(Exception):
            RegisterPayload(email="not-an-email", password="test123")

    def test_register_payload_password_min_length(self):
        """注册接口密码应有最小长度要求。"""
        from core.schemas import RegisterPayload

        with pytest.raises(Exception):
            RegisterPayload(email="test@example.com", password="123")

    def test_login_payload_validation(self):
        """登录接口应验证必填字段。"""
        from core.schemas import LoginPayload

        with pytest.raises(Exception):
            LoginPayload(email="", password="")

    def test_chat_payload_message_not_empty(self):
        """聊天接口消息不能为空。"""
        from core.schemas import ChatSendPayload

        with pytest.raises(Exception):
            ChatSendPayload(character_id="char_1", message="   ")

    def test_register_payload_normalizes_email(self):
        """注册接口邮箱应复用统一规范化逻辑。"""
        from core.schemas import RegisterPayload

        payload = RegisterPayload(email="  TEST@EXAMPLE.COM  ", password="test1234")

        assert payload.email == "test@example.com"

    def test_regenerate_and_continue_payload_require_message_id(self):
        """重新生成与继续生成请求都应要求 message_id。"""
        from core.schemas import ContinuePayload, RegeneratePayload

        with pytest.raises(Exception):
            RegeneratePayload(message_id="")

        with pytest.raises(Exception):
            ContinuePayload(message_id="")

        assert RegeneratePayload(message_id="msg-1").message_id == "msg-1"
        assert ContinuePayload(message_id="msg-2").message_id == "msg-2"

    def test_password_reset_payloads_normalize_email(self):
        """密码重置相关模型应统一规范化邮箱。"""
        from core.schemas import ForgotPasswordPayload, ResetPasswordPayload, VerifyCodePayload

        forgot = ForgotPasswordPayload(email="  USER@Example.com ")
        verify = VerifyCodePayload(email="  USER@Example.com ", code="123456")
        reset = ResetPasswordPayload(email="  USER@Example.com ", code="123456", new_password="test1234")

        assert forgot.email == "user@example.com"
        assert verify.email == "user@example.com"
        assert reset.email == "user@example.com"

    def test_character_id_payloads_trim_and_require_value(self):
        """共享 character_id 基类应统一处理去空白与必填约束。"""
        from core.schemas import CharacterActionPayload, CharacterProfileUpdatePayload, ClearChatPayload

        with pytest.raises(Exception):
            CharacterActionPayload(character_id="   ")

        profile = CharacterProfileUpdatePayload(character_id="  char_1  ")
        clear_chat = ClearChatPayload(character_id="  char_2  ")

        assert profile.character_id == "char_1"
        assert clear_chat.character_id == "char_2"

    def test_advanced_config_optional_ids_trim_and_collapse_blank_to_none(self):
        """高级配置中的可选 ID 字段应统一去空白，并把空字符串折叠为 None。"""
        from core.schemas import GreetingPayload, MemoryEntryPayload, PostRulePayload, StoryEventPayload

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
        from core.schemas import GreetingPayload, MemoryCategoryPayload, MemoryEntryPayload, StoryEventPayload, StorylinePayload

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
