"""回归测试 — 游标生命周期 + commit 后 fetchone 行为。

验证 FakeConn 正确模拟 psycopg2 行为：commit 后旧游标失效，
新 execute 创建新游标可正常 fetchone。这是此前线上 bug 的回归保护。
"""
import pytest
from conftest import FakeSequenceConn, FakeCursorConn, FakeRow, FakeQueryResult


class TestCursorInvalidationRegression:
    """回归：commit 后 fetchone 必须抛异常，防止生产环境 commit→fetchone 静默返回 None。"""

    def test_fake_sequence_conn_commit_invalidates_cursor(self):
        conn = FakeSequenceConn([
            FakeRow({"id": 1}),
            FakeRow({"id": 2}),
        ])
        cursor = conn.execute("SELECT 1")
        conn.commit()
        with pytest.raises(RuntimeError, match="commit"):
            cursor.fetchone()

    def test_fake_cursor_conn_commit_invalidates(self):
        conn = FakeCursorConn([FakeRow({"id": 1}), FakeRow({"id": 2})])
        conn.execute("SELECT 1")
        conn.commit()
        with pytest.raises(RuntimeError, match="commit"):
            conn.fetchone()

    def test_new_execute_after_commit_works(self):
        """commit 后可以执行新 SQL，新游标可正常 fetchone。"""
        conn = FakeSequenceConn([
            FakeRow({"id": 1}),
            FakeRow({"id": 2}),
        ])
        conn.execute("SELECT 1")
        conn.commit()
        # New execute creates new cursor
        cursor2 = conn.execute("SELECT 2")
        result = cursor2.fetchone()
        assert result["id"] == 2

    def test_fake_cursor_conn_new_execute_after_commit(self):
        conn = FakeCursorConn([FakeRow({"id": 1}), FakeRow({"id": 2})])
        conn.execute("SELECT 1")
        conn.commit()
        conn.execute("SELECT 2")
        result = conn.fetchone()
        assert result["id"] == 2


class TestFetchoneBeforeCommitWorks:
    """正常流程：先 fetchone 再 commit，必须正常工作。"""

    def test_sequence_conn_fetchone_then_commit(self):
        conn = FakeSequenceConn([FakeRow({"id": 42})])
        cursor = conn.execute("SELECT 1")
        result = cursor.fetchone()
        assert result["id"] == 42
        conn.commit()  # Should not raise

    def test_cursor_conn_fetchone_then_commit(self):
        conn = FakeCursorConn([FakeRow({"id": 42})])
        conn.execute("SELECT 1")
        result = conn.fetchone()
        assert result["id"] == 42
        conn.commit()


class TestFetchallInvalidation:
    """fetchall 在 commit 后也必须失效。"""

    def test_fetchall_after_commit_raises(self):
        conn = FakeSequenceConn([
            FakeQueryResult(many=[FakeRow({"id": 1}), FakeRow({"id": 2})]),
        ])
        cursor = conn.execute("SELECT all")
        conn.commit()
        with pytest.raises(RuntimeError, match="commit"):
            cursor.fetchall()


class TestRealWorldScenario:
    """模拟真实的仓库函数调用序列。"""

    def test_select_then_commit_then_select(self):
        """典型场景：先查询→处理→提交→再查询。"""
        conn = FakeSequenceConn([
            FakeRow({"count": 5}),   # first SELECT
            FakeRow({"id": 99}),     # second SELECT after commit
        ])
        # Step 1: Query + fetchone + commit
        cursor1 = conn.execute("SELECT count")
        count = cursor1.fetchone()["count"]
        assert count == 5
        conn.commit()

        # Step 2: New query after commit
        cursor2 = conn.execute("SELECT id")
        result = cursor2.fetchone()
        assert result["id"] == 99

    def test_save_regenerate_pattern(self):
        """save_regenerated_version 调用序列：SELECT→UPDATE→commit。"""
        conn = FakeSequenceConn([
            FakeRow({"content": "old"}),  # SELECT content
            FakeQueryResult(rowcount=1),   # UPDATE
        ])
        cursor = conn.execute("SELECT content FROM chat_messages WHERE id = %s")
        row = cursor.fetchone()
        assert row["content"] == "old"
        conn.execute("UPDATE chat_messages SET content = %s WHERE id = %s")
        conn.commit()
