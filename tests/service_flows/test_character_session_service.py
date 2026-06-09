"""character_session_service 单元测试 — 聊天重置与清理逻辑。"""
from __future__ import annotations

import pytest

from tests.support.db import FakeRow, FakeSequenceConn


# ── _normalize_greeting_index ────────────────────────

class TestNormalizeGreetingIndex:
    def test_int_passthrough(self):
        from services.character_session_service import _normalize_greeting_index
        raw, index, is_non_default = _normalize_greeting_index(3)
        assert raw == 3
        assert index == 3
        assert is_non_default is True

    def test_zero_is_default(self):
        from services.character_session_service import _normalize_greeting_index
        raw, index, is_non_default = _normalize_greeting_index(0)
        assert index == 0
        assert is_non_default is False

    def test_negative_one_is_default(self):
        from services.character_session_service import _normalize_greeting_index
        raw, index, is_non_default = _normalize_greeting_index(-1)
        assert index == -1
        assert is_non_default is False

    def test_string_digit(self):
        from services.character_session_service import _normalize_greeting_index
        raw, index, is_non_default = _normalize_greeting_index("2")
        assert index == 2
        assert is_non_default is True

    def test_string_zero(self):
        from services.character_session_service import _normalize_greeting_index
        raw, index, is_non_default = _normalize_greeting_index("0")
        assert index == 0
        assert is_non_default is False

    def test_invalid_string(self):
        from services.character_session_service import _normalize_greeting_index
        raw, index, is_non_default = _normalize_greeting_index("abc")
        assert index == -1

    def test_negative_string_digit(self):
        from services.character_session_service import _normalize_greeting_index
        raw, index, is_non_default = _normalize_greeting_index("-3")
        assert index == -3


# ── reset_character_chat_state ──────────────────────

class TestResetCharacterChatState:
    def test_clear_state_true_returns_ok(self):
        from services.character_session_service import reset_character_chat_state
        from unittest.mock import patch
        # ensure_opening_message 内部逻辑复杂（多次 DB 查询），独立 mock 掉
        with patch("services.character_session_service.ensure_opening_message"):
            with patch("services.character_session_service.get_character_state", return_value={"affection": 0}):
                conn = FakeSequenceConn([
                    FakeRow(),  # DELETE chat_messages
                    FakeRow(),  # DELETE chat_summaries
                    FakeRow(),  # DELETE character_states
                    FakeRow(),  # DELETE user_story_progress
                ])
                result = reset_character_chat_state(
                    conn, user_id=1, character_id="c1", clear_state=True, commit=False,
                )
                assert result["ok"] is True
                assert "state" in result

    def test_clear_state_false_no_state_in_result(self):
        from services.character_session_service import reset_character_chat_state
        from unittest.mock import patch
        with patch("services.character_session_service.ensure_opening_message"):
            conn = FakeSequenceConn([
                FakeRow(),  # DELETE chat_messages
                FakeRow(),  # DELETE chat_summaries
                FakeRow(),  # DELETE character_states
                FakeRow(),  # DELETE user_story_progress
            ])
            result = reset_character_chat_state(
                conn, user_id=1, character_id="c1", clear_state=False, commit=False,
            )
            assert result["ok"] is True
            assert "state" not in result

    def test_commit_flag(self):
        from services.character_session_service import reset_character_chat_state
        from unittest.mock import patch
        with patch("services.character_session_service.ensure_opening_message"):
            conn = FakeSequenceConn([
                FakeRow(),  # DELETE chat_messages
                FakeRow(),  # DELETE chat_summaries
                FakeRow(),  # DELETE character_states
                FakeRow(),  # DELETE user_story_progress
            ])
            reset_character_chat_state(
                conn, user_id=1, character_id="c1", clear_state=False, commit=True,
            )
            assert conn.committed is True


# ── clear_chat_history_with_greeting ────────────────

class TestClearChatHistoryWithGreeting:
    def test_returns_greeting(self):
        from services.character_session_service import clear_chat_history_with_greeting
        conn = FakeSequenceConn([
            FakeRow(),  # DELETE chat_messages
            FakeRow(),  # DELETE chat_summaries
            FakeRow(),  # DELETE character_states
            FakeRow(),  # DELETE user_story_progress
            FakeRow({"opening_message": "你好！", "structured_asset_json": None}),  # SELECT character
            FakeRow(),  # INSERT greeting
        ])
        result = clear_chat_history_with_greeting(
            conn, user_id=1, character_id="c1", greeting_index=0, commit=False,
        )
        assert result == "你好！"

    def test_character_not_found_uses_default(self):
        from services.character_session_service import clear_chat_history_with_greeting
        conn = FakeSequenceConn([
            FakeRow(),  # DELETE chat_messages
            FakeRow(),  # DELETE chat_summaries
            FakeRow(),  # DELETE character_states
            FakeRow(),  # DELETE user_story_progress
            None,       # SELECT character (不存在)
            FakeRow(),  # INSERT greeting
        ])
        result = clear_chat_history_with_greeting(
            conn, user_id=1, character_id="nonexistent", greeting_index=0, commit=False,
        )
        assert result == "你好，很高兴认识你。"
