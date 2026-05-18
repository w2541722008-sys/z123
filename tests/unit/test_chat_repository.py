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
