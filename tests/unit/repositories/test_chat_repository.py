"""chat_repository 单元测试 — 验证消息查询参数与返回值。"""
from __future__ import annotations

import pytest

from tests.support.db import FakeRow, FakeSequenceConn


class TestGetChatHistory:
    def test_returns_formatted_list(self):
        from repositories.chat_repository import get_chat_history
        rows = [
            FakeRow({"id": 1, "role": "user", "content": "hi", "created_at": "2026-05-03"}),
            FakeRow({"id": 2, "role": "assistant", "content": "hello", "created_at": "2026-05-03"}),
        ]
        conn = FakeSequenceConn([rows])
        result = get_chat_history(conn, user_id=1, character_id="c1")
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["content"] == "hello"

    def test_returns_message_id_for_assistant_messages_only(self):
        from repositories.chat_repository import get_chat_history
        rows = [
            FakeRow({"id": 10, "role": "user", "content": "hi", "created_at": "2026-05-03"}),
            FakeRow({"id": 11, "role": "assistant", "content": "hello", "created_at": "2026-05-03"}),
        ]
        conn = FakeSequenceConn([rows])
        result = get_chat_history(conn, user_id=1, character_id="c1")
        assert "message_id" not in result[0]
        assert result[1]["message_id"] == "11"

    def test_empty_history(self):
        from repositories.chat_repository import get_chat_history
        conn = FakeSequenceConn([[]])
        result = get_chat_history(conn, user_id=1, character_id="c1")
        assert result == []

    def test_params_alignment(self):
        from repositories.chat_repository import get_chat_history
        conn = FakeSequenceConn([[]])
        get_chat_history(conn, user_id=42, character_id="c1")
        sql, params = conn.executed[0]
        assert params == (42, "c1", 50, 0)
        assert sql.count("%s") == len(params)

    def test_limit_parameter_respected(self):
        from repositories.chat_repository import get_chat_history
        conn = FakeSequenceConn([[]])
        get_chat_history(conn, user_id=1, character_id="c1", limit=20)
        sql, params = conn.executed[0]
        assert params[2] == 20

    def test_offset_parameter_respected(self):
        from repositories.chat_repository import get_chat_history
        conn = FakeSequenceConn([[]])
        get_chat_history(conn, user_id=1, character_id="c1", offset=10)
        sql, params = conn.executed[0]
        assert params[3] == 10

    def test_latest_page_query_uses_descending_inner_order(self):
        from repositories.chat_repository import get_chat_history
        conn = FakeSequenceConn([[]])
        get_chat_history(conn, user_id=1, character_id="c1")
        sql, _ = conn.executed[0]
        assert "ORDER BY id DESC" in sql

    def test_returns_latest_page_in_chronological_order(self):
        from repositories.chat_repository import get_chat_history
        rows = [
            FakeRow({"id": 1, "role": "user", "content": "older", "created_at": "2026-05-02"}),
            FakeRow({"id": 2, "role": "assistant", "content": "newest", "created_at": "2026-05-03"}),
        ]
        conn = FakeSequenceConn([rows])
        result = get_chat_history(conn, user_id=1, character_id="c1")
        assert [item["content"] for item in result] == ["older", "newest"]

    def test_different_character_isolation(self):
        from repositories.chat_repository import get_chat_history
        conn = FakeSequenceConn([[]])
        get_chat_history(conn, user_id=1, character_id="char-a")
        sql_a, params_a = conn.executed[0]
        assert params_a[1] == "char-a"


class TestCountChatHistory:
    def test_returns_count(self):
        from repositories.chat_repository import count_chat_history
        conn = FakeSequenceConn([FakeRow({"total": 15})])
        result = count_chat_history(conn, user_id=1, character_id="c1")
        assert result == 15

    def test_no_messages_returns_zero(self):
        from repositories.chat_repository import count_chat_history
        conn = FakeSequenceConn([FakeRow({"total": 0})])
        result = count_chat_history(conn, user_id=1, character_id="c1")
        assert result == 0
