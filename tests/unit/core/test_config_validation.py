"""生产配置校验单元测试。"""

import os
from unittest.mock import patch

import pytest


def test_validate_production_config_accepts_complete_required_env():
    from core.config import validate_production_config

    env = {
        "ENV": "production",
        "DEBUG": "false",
        "AIFRIEND_API_KEY": "sk-test",
        "RESEND_API_KEY": "re-test",
        "ADMIN_EMAILS": "admin@example.com",
        "ALLOWED_ORIGINS": "https://example.com",
    }

    with patch.dict(os.environ, env, clear=True):
        assert validate_production_config() == []


def test_validate_production_config_requires_smtp_password():
    from core.config import validate_production_config

    env = {
        "ENV": "production",
        "DEBUG": "false",
        "AIFRIEND_API_KEY": "sk-test",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_USER": "noreply@example.com",
        "ADMIN_EMAILS": "admin@example.com",
        "ALLOWED_ORIGINS": "https://example.com",
    }

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_config()

    assert "SMTP_HOST+SMTP_USER+SMTP_PASSWORD" in str(exc_info.value)


def test_validate_production_config_reads_current_admin_emails_env():
    from core.config import validate_production_config

    env = {
        "ENV": "production",
        "DEBUG": "false",
        "AIFRIEND_API_KEY": "sk-test",
        "RESEND_API_KEY": "re-test",
        "ALLOWED_ORIGINS": "https://example.com",
    }

    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_config()

    assert "ADMIN_EMAILS" in str(exc_info.value)
