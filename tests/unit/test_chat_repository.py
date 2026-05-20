"""chat_repository 单元测试 — 验证消息查询参数与返回值。"""
from __future__ import annotations

import pytest

from conftest import FakeRow, FakeSequenceConn


class TestGetChatHistory:
    def test_returns_formatted_list(self):
        from repositories.chat_repository import get_chat_history
        rows = [
            FakeRow({"role": "user", "content": "hi", "created_at": "2026-05-03"}),
            FakeRow({"role": "assistant", "content": "hello", "created_at": "2026-05-03"}),
        ]
        conn = FakeSequenceConn([rows])
        result = get_chat_history(conn, user_id=1, character_id="c1")
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["content"] == "hello"

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

    def test_message_order_descending_by_id(self):
        from repositories.chat_repository import get_chat_history
        rows = [
            FakeRow({"role": "user", "content": "first", "created_at": "2026-05-01"}),
            FakeRow({"role": "user", "content": "second", "created_at": "2026-05-02"}),
        ]
        conn = FakeSequenceConn([rows])
        result = get_chat_history(conn, user_id=1, character_id="c1")
        assert result[0]["content"] == "first"

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


class TestSearchMessages:
    def test_returns_matching_messages(self):
        from repositories.chat_repository import search_messages
        rows = [
            FakeRow({
                "id": 1, "user_id": 1, "character_id": "c1",
                "role": "user", "content": "hello world",
                "created_at": "2026-05-01", "is_summarized": 0, "rank": 0.5,
            }),
        ]
        conn = FakeSequenceConn([rows])
        result = search_messages(conn, user_id=1, query="hello", character_id="c1")
        assert len(result) == 1
        assert "hello" in result[0]["content"]

    def test_no_matches_returns_empty(self):
        from repositories.chat_repository import search_messages
        conn = FakeSequenceConn([[]])
        result = search_messages(conn, user_id=1, query="zzz", character_id="c1")
        assert result == []

    def test_query_param_passed_correctly(self):
        from repositories.chat_repository import search_messages
        conn = FakeSequenceConn([[]])
        search_messages(conn, user_id=1, query="test", character_id="c1")
        sql, params = conn.executed[0]
        assert params[1] == "test"


class TestCountSearchResults:
    def test_returns_total(self):
        from repositories.chat_repository import count_search_results
        conn = FakeSequenceConn([FakeRow({"total": 3})])
        result = count_search_results(conn, user_id=1, query="word", character_id="c1")
        assert result == 3
