"""集成测试共享配置 — 真实 PostgreSQL 数据库连接。

集成测试标记为 @pytest.mark.integration，默认不执行。
运行方式：pytest -m integration

设计原则：
  - 使用真实 PostgreSQL 实例执行 SQL
  - 每个测试在事务中运行，测试完回滚，保持数据库干净
  - 需要 TEST_DATABASE_URL 环境变量指向测试数据库
  - 测试数据库与生产数据库隔离
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from core.database import ConnWrapper


def _looks_like_test_database(url: str) -> bool:
    parsed = urlparse(url)
    database_name = parsed.path.rsplit("/", 1)[-1].lower()
    hostname = (parsed.hostname or "").lower()
    return (
        "test" in database_name
        or "test" in hostname
        or hostname in {"localhost", "127.0.0.1", "::1"}
    )


def _get_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set, skipping integration tests")
    if not _looks_like_test_database(url):
        pytest.fail(
            "TEST_DATABASE_URL must point to a local or clearly named test database"
        )
    os.environ["DATABASE_URL"] = url
    return url


@pytest.fixture(scope="session")
def _db_engine():
    """会话级数据库引擎。"""
    try:
        import psycopg2
        from psycopg2 import pool
    except ImportError:
        pytest.skip("psycopg2 not installed")

    url = _get_database_url()
    try:
        eng = pool.ThreadedConnectionPool(1, 5, url)
    except Exception as e:
        pytest.skip(f"Cannot connect to test database: {e}")
        return

    yield eng
    eng.closeall()


@pytest.fixture
def db_conn(_db_engine):
    """每个测试获取独立连接，测试后回滚保持干净。"""
    raw_conn = _db_engine.getconn()
    raw_conn.autocommit = False
    conn = ConnWrapper(raw_conn, _db_engine)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


@pytest.fixture
def db_conn_auto_commit(_db_engine):
    """需要手动控制事务的集成测试（如测试 commit 边界）。"""
    raw_conn = _db_engine.getconn()
    raw_conn.autocommit = False
    conn = ConnWrapper(raw_conn, _db_engine)
    yield conn
    try:
        conn.rollback()
    except Exception:
        pass
    conn.close()
