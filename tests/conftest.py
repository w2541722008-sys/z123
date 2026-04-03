"""
测试共享配置 - Mock fixtures 和工具函数

设计原则：
  - 所有需要数据库/外部服务的依赖都通过 mock 隔离
  - 纯逻辑函数不使用任何 mock，直接测试
  - 每个测试文件独立可运行，不依赖执行顺序
"""

import sys
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone

# 确保后端模块在 import 路径中
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(BACKEND_DIR))


# ============================================================
# Mock 数据库连接（替代真实的 Supabase 连接）
# ============================================================
class FakeConn:
    """模拟数据库连接，记录执行的 SQL 并返回预设结果。"""

    def __init__(self):
        self.executed_sql = []
        self._committed = False
        self._rolled_back = False

    def execute(self, sql, params=None):
        self.executed_sql.append((sql, params))
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    @property
    def rowcount(self):
        return 0

    def commit(self):
        self._committed = True

    def rollback(self):
        self._rolled_back = True

    def close(self):
        pass


class FakeRow(dict):
    """模拟 psycopg2 RealDictRow，支持 dict 和属性访问。"""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def make_fake_conn(return_rows=None, rowcount=0):
    """
    创建一个预设返回值的 FakeConn。

    Args:
        return_rows: fetchone/fetchall 返回的行数据列表（dict 列表）
        rowcount: INSERT/UPDATE/DELETE 影响的行数
    """
    conn = FakeConn()
    conn._rows = return_rows or []
    conn._rowcount_val = rowcount

    _orig_fetchone = conn.fetchone
    _orig_fetchall = conn.fetchall

    def fake_fetchone():
        if conn._rows:
            row_data = conn._rows.pop(0)
            return FakeRow(row_data) if isinstance(row_data, dict) else row_data
        return None

    def fake_fetchall():
        rows = [FakeRow(r) if isinstance(r, dict) else r for r in conn._rows]
        conn._rows = []
        return rows

    conn.fetchone = fake_fetchone
    conn.fetchall = fake_fetchall

    @property
    def rowcount(self):
        return conn._rowcount_val

    # 绑定到实例
    type(conn).rowcount = property(lambda s: s._rowcount_val)

    return conn


# ============================================================
# 常用测试数据工厂
# ============================================================

NOW_UTC = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)


def sample_token_hash():
    """返回一个固定的 token hash 用于测试。"""
    import hashlib
    return hashlib.sha256(b"test_token_xyz_123").hexdigest()


def sample_expires_soon():
    """返回一个即将过期的时间字符串（剩余 3 天）。"""
    return (NOW_UTC + timedelta(days=3)).isoformat()


def sample_expires_later():
    """返回一个还有很久才过期的时间字符串（剩余 20 天）。"""
    return (NOW_UTC + timedelta(days=20)).isoformat()


def sample_user_row(**overrides):
    """返回一个标准的用户数据库行。"""
    defaults = {
        "id": 1,
        "email": "test@example.com",
        "nickname": "测试用户",
        "plan_type": "free",
        "plan_expires_at": "",
    }
    defaults.update(overrides)
    return defaults
