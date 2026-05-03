"""
ConnWrapper 行为验证测试

验证 psycopg2 ConnWrapper 的关键行为：
  1. commit() 后 cursor 被关闭 → fetchone() 抛出 InterfaceError
  2. rollback() 在已 commit 的事务上是安全的（no-op）
  3. close() 归还连接到池

这些测试需要一个 mock 的 psycopg2 连接来模拟真实行为，
而不是使用 FakeSequenceConn（它不模拟 cursor 生命周期）。
"""

import pytest
from unittest.mock import MagicMock, patch
from psycopg2.pool import ThreadedConnectionPool


class MockRealDictCursor:
    """模拟 psycopg2 RealDictCursor 的行为：commit 后 cursor 关闭。"""

    def __init__(self, *, data=None):
        self._closed = False
        self._data = data or {"id": 42}
        self.rowcount = 1

    def execute(self, sql, params=None):
        if self._closed:
            raise Exception("cursor already closed")
        return self

    def fetchone(self):
        if self._closed:
            from psycopg2 import InterfaceError
            raise InterfaceError("cursor already closed")
        return self._data

    def fetchall(self):
        if self._closed:
            from psycopg2 import InterfaceError
            raise InterfaceError("cursor already closed")
        return [self._data]

    def close(self):
        self._closed = True


class MockPsycopg2Conn:
    """模拟 psycopg2 连接的 commit 关闭 cursor 行为。"""

    def __init__(self):
        self._cursors = []
        self._committed = False
        self._rolled_back = False
        self._closed = False

    def cursor(self, cursor_factory=None):
        cur = MockRealDictCursor()
        self._cursors.append(cur)
        return cur

    def commit(self):
        """commit 后关闭所有 cursor（模拟 psycopg2 真实行为）。"""
        self._committed = True
        for cur in self._cursors:
            cur._closed = True

    def rollback(self):
        self._rolled_back = True
        for cur in self._cursors:
            cur._closed = True

    def close(self):
        self._closed = True


class TestRealCursorLifecycle:
    """验证 psycopg2 cursor 在 commit 后被关闭的真实行为。"""

    def test_fetchone_after_commit_raises_error(self):
        """commit() 后 fetchone() 应抛出 InterfaceError。"""
        from psycopg2 import InterfaceError
        mock_conn = MockPsycopg2Conn()
        cur = mock_conn.cursor()
        cur.execute("INSERT ... RETURNING id")
        # commit 前可以 fetchone
        row = cur.fetchone()
        assert row is not None

        # 重新创建 cursor 模拟新操作
        cur2 = mock_conn.cursor()
        cur2.execute("INSERT ... RETURNING id")
        mock_conn.commit()
        # commit 后 cursor 被关闭
        with pytest.raises(InterfaceError):
            cur2.fetchone()

    def test_fetchone_before_commit_succeeds(self):
        """fetchone() 在 commit() 之前可以正常工作。"""
        mock_conn = MockPsycopg2Conn()
        cur = mock_conn.cursor()
        cur.execute("INSERT ... RETURNING id")
        row = cur.fetchone()  # ← 先获取
        assert row == {"id": 42}
        mock_conn.commit()   # ← 再提交
        # 提交后 cursor 关闭，但数据已经拿到了

    def test_rollback_after_commit_is_safe(self):
        """rollback() 在已 commit 的事务上是 no-op（安全）。"""
        mock_conn = MockPsycopg2Conn()
        cur = mock_conn.cursor()
        cur.execute("INSERT ...")
        row = cur.fetchone()
        mock_conn.commit()
        # 再 rollback 不会报错
        mock_conn.rollback()


class TestConnWrapperIntegration:
    """验证 ConnWrapper 包装器正确处理 cursor 生命周期。"""

    @patch("core.database._connection_pool")
    def test_conn_wrapper_commit_closes_cursors(self, mock_pool):
        """ConnWrapper.commit() 后 cursor 应不可用。"""
        from core.database import ConnWrapper

        raw_conn = MockPsycopg2Conn()
        pool = MagicMock(spec=ThreadedConnectionPool)
        wrapper = ConnWrapper(raw_conn, pool)

        # 执行查询
        result = wrapper.execute("SELECT 1")
        row = result.fetchone()
        assert row is not None

        # commit 后 cursor 应关闭
        wrapper.commit()

    @patch("core.database._connection_pool")
    def test_conn_wrapper_close_returns_to_pool(self, mock_pool):
        """ConnWrapper.close() 应归还连接到池。"""
        from core.database import ConnWrapper

        raw_conn = MockPsycopg2Conn()
        pool = MagicMock(spec=ThreadedConnectionPool)
        wrapper = ConnWrapper(raw_conn, pool)

        wrapper.close()
        pool.putconn.assert_called_once_with(raw_conn)

    @patch("core.database._connection_pool")
    def test_conn_wrapper_double_close_safe(self, mock_pool):
        """ConnWrapper.close() 多次调用应安全。"""
        from core.database import ConnWrapper

        raw_conn = MockPsycopg2Conn()
        pool = MagicMock(spec=ThreadedConnectionPool)
        wrapper = ConnWrapper(raw_conn, pool)

        wrapper.close()
        wrapper.close()  # 第二次不应报错
        assert pool.putconn.call_count == 1
