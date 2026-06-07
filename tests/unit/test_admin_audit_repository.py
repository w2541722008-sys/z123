"""admin_audit_repository 单元测试"""

from conftest import FakeRow, FakeQueryResult, FakeSequenceConn
from repositories.admin_audit_repository import insert_audit_log


class TestInsertAuditLog:
    def test_insert_basic(self):
        conn = FakeSequenceConn([FakeRow({})])
        insert_audit_log(
            conn,
            operator_id=1, operator_email="admin@test.com",
            action="update_character", target_type="character",
            target_id="char-1", detail={"field": "name"},
        )
        assert "INSERT INTO admin_audit_logs" in conn.executed[0][0]
        params = conn.executed[0][1]
        assert params[0] == 1

    def test_detail_json_serialization(self):
        conn = FakeSequenceConn([FakeRow({})])
        insert_audit_log(
            conn,
            operator_id=2, operator_email="admin@test.com",
            action="delete", target_type="memory",
            target_id="mem-1", detail={"中文字段": "值"},
        )
        params = conn.executed[0][1]
        detail_json = params[5]
        assert "中文字段" in detail_json
        assert "值" in detail_json

    def test_none_detail_defaults_to_empty_obj(self):
        conn = FakeSequenceConn([FakeRow({})])
        insert_audit_log(
            conn,
            operator_id=1, operator_email="admin@test.com",
            action="list", target_type="dashboard",
            detail=None,
        )
        params = conn.executed[0][1]
        assert params[5] == "{}"

    def test_write_failure_does_not_raise(self):
        """审计日志写入失败只记 warning，不抛异常。"""
        conn = FakeSequenceConn([RuntimeError("db error")])
        # 不应抛出异常
        try:
            insert_audit_log(
                conn,
                operator_id=1, operator_email="admin@test.com",
                action="test", target_type="test",
            )
        except Exception:
            pytest.fail("insert_audit_log 失败时不应抛出异常")
