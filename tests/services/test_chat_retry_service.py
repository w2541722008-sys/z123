"""chat_retry 服务层测试（需要 mock DB）。

覆盖：save_regenerated_version、_build_retry_fallback_recent、
_load_retry_target_message 等涉及 DB 连接的函数。
"""
import json
from unittest.mock import patch, MagicMock

from conftest import FakeSequenceConn, FakeRow, FakeQueryResult


# ============================================================
# save_regenerated_version
# ============================================================
class TestSaveRegeneratedVersion:
    def test_regenerate_replaces_content(self):
        from services.chat_retry import save_regenerated_version
        conn = FakeSequenceConn([
            FakeRow({"content": "old content"}),  # SELECT
            FakeQueryResult(rowcount=1),           # UPDATE
        ])
        save_regenerated_version(conn, "msg-1", "new content", is_append=False, commit=True)
        assert conn.committed is True
        # Verify UPDATE SQL was executed
        update_sql = conn.executed[1][0]
        assert "UPDATE" in update_sql
        assert "chat_messages" in update_sql

    def test_continue_appends_content(self):
        from services.chat_retry import save_regenerated_version
        conn = FakeSequenceConn([
            FakeRow({"content": "base text"}),  # SELECT
            FakeQueryResult(rowcount=1),         # UPDATE
        ])
        save_regenerated_version(conn, "msg-1", " appended", is_append=True, commit=True)
        assert conn.committed is True
        # The UPDATE params should have combined content
        params = conn.executed[1][1]
        assert "base text appended" == params[0]

    def test_commit_false(self):
        from services.chat_retry import save_regenerated_version
        conn = FakeSequenceConn([
            FakeRow({"content": "old"}),
            FakeQueryResult(rowcount=1),
        ])
        save_regenerated_version(conn, "msg-1", "new", commit=False)
        assert conn.committed is False

    def test_message_not_found_still_proceeds(self):
        """When SELECT returns None, save_regenerated_version logs warning but continues."""
        from services.chat_retry import save_regenerated_version
        conn = FakeSequenceConn([
            None,  # fetchone returns None → message not found
            FakeQueryResult(rowcount=1),  # fallback UPDATE
        ])
        # Should not raise; falls through to the except handler
        save_regenerated_version(conn, "nonexistent", "new", commit=False)

    def test_versions_json_structure(self):
        from services.chat_retry import save_regenerated_version
        conn = FakeSequenceConn([
            FakeRow({"content": "old"}),
            FakeQueryResult(rowcount=1),
        ])
        save_regenerated_version(conn, "msg-1", "new", is_append=False, commit=False)
        params = conn.executed[1][1]
        versions = json.loads(params[1])
        assert isinstance(versions, list)
        assert versions[0]["operation"] == "regenerate"

    def test_continue_versions_operation(self):
        from services.chat_retry import save_regenerated_version
        conn = FakeSequenceConn([
            FakeRow({"content": "base"}),
            FakeQueryResult(rowcount=1),
        ])
        save_regenerated_version(conn, "msg-1", " extra", is_append=True, commit=False)
        params = conn.executed[1][1]
        versions = json.loads(params[1])
        assert versions[0]["operation"] == "continue"


# ============================================================
# _build_retry_fallback_recent
# ============================================================
class TestBuildRetryFallbackRecent:
    def test_basic(self):
        from services.chat_retry import _build_retry_fallback_recent
        row = {"content": "assistant reply"}
        result = _build_retry_fallback_recent(row)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "assistant reply"

    def test_missing_content(self):
        from services.chat_retry import _build_retry_fallback_recent
        row = {}
        result = _build_retry_fallback_recent(row)
        assert result[0]["content"] is None


# ============================================================
# _build_retry_prompt_args
# ============================================================
class TestBuildRetryPromptArgs:
    def test_basic(self):
        from services.chat_retry import _build_retry_prompt_args
        context = {
            "character_id": "c1",
            "message_row": {"content": "old reply"},
            "recent_messages": [{"role": "user", "content": "hi"}],
        }
        result = _build_retry_prompt_args(context, message_id="m1")
        assert result["character_id"] == "c1"
        assert result["message_id"] == "m1"
        assert result["current_content"] == "old reply"
        assert len(result["recent_messages"]) == 1

    def test_null_content(self):
        from services.chat_retry import _build_retry_prompt_args
        context = {
            "character_id": "c1",
            "message_row": {"content": None},
            "recent_messages": [],
        }
        result = _build_retry_prompt_args(context, message_id="m1")
        assert result["current_content"] == ""
