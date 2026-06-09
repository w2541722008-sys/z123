"""集成测试数据库连接保护。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[3]
CONFTST_PATH = PROJECT_DIR / "tests" / "integration" / "conftest.py"


def _load_integration_conftest():
    spec = importlib.util.spec_from_file_location(
        "integration_conftest_under_test",
        CONFTST_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_integration_db_url_requires_test_database_url(monkeypatch):
    module = _load_integration_conftest()
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:pass@prod-db.example.com:5432/aifriend",
    )

    with pytest.raises(pytest.skip.Exception, match="TEST_DATABASE_URL"):
        module._get_database_url()


def test_integration_db_url_allows_local_test_database(monkeypatch):
    module = _load_integration_conftest()
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql://user:pass@localhost:5432/aifriend",
    )

    assert module._get_database_url() == "postgresql://user:pass@localhost:5432/aifriend"
    assert module.os.environ["DATABASE_URL"] == "postgresql://user:pass@localhost:5432/aifriend"


def test_integration_db_url_rejects_unclear_remote_database(monkeypatch):
    module = _load_integration_conftest()
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql://user:pass@prod-db.example.com:5432/aifriend",
    )

    with pytest.raises(pytest.fail.Exception, match="clearly named test database"):
        module._get_database_url()
