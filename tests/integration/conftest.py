"""集成测试共享配置 — 真实 PostgreSQL 数据库连接。

集成测试标记为 @pytest.mark.integration，默认不执行。
运行方式：pytest -m integration

设计原则：
  - 使用真实 PostgreSQL 实例执行 SQL
  - 每个测试在事务中运行，测试完回滚，保持数据库干净
  - 需要 DATABASE_URL 环境变量指向测试数据库
  - 测试数据库与生产数据库隔离
"""
from __future__ import annotations

import os

import pytest


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set, skipping integration tests")
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
    conn = _db_engine.getconn()
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()
    _db_engine.putconn(conn)


@pytest.fixture
def db_conn_auto_commit(_db_engine):
    """需要手动控制事务的集成测试（如测试 commit 边界）。"""
    conn = _db_engine.getconn()
    conn.autocommit = False
    yield conn
    try:
        conn.rollback()
    except Exception:
        pass
    conn.close()
    _db_engine.putconn(conn)
