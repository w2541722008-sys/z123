"""
Chat 路由元数据契约测试 - 验证路由注册完整性
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


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
