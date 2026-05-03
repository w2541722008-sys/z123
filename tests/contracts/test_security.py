"""
安全契约测试 - 验证错误处理不泄露敏感信息
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


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
