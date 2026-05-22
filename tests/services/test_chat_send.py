"""chat_send 单元测试 — SSE 格式化、mock 回复、消息存储。"""
from __future__ import annotations

import json

import pytest

from conftest import FakeRow, FakeSequenceConn


# ── format_sse ────────────────────────────────────────

class TestFormatSse:
    def test_basic_event(self):
        from services.chat_send import format_sse
        result = format_sse("message", {"text": "hello"})
        assert result.startswith("event: message\n")
        assert "data: " in result
        assert result.endswith("\n\n")

    def test_done_event(self):
        from services.chat_send import format_done_event
        result = format_done_event({"reply": "hi"})
        assert result.startswith("event: done\n")

    def test_error_event(self):
        from services.chat_send import format_error_event
        result = format_error_event("出错了")
        parsed = json.loads(result.split("data: ")[1].strip())
        assert parsed["message"] == "出错了"

    def test_unicode_in_data(self):
        from services.chat_send import format_sse
        result = format_sse("msg", {"text": "你好世界🎉"})
        assert "你好世界" in result
        # ensure_ascii=False 应保留 Unicode
        assert "\\u" not in result.split("data: ")[1]


# ── build_mock_reply ─────────────────────────────────

class TestBuildMockReply:
    def test_no_styles_returns_default(self):
        from services.chat_send import build_mock_reply
        char = {"mock_reply_style": []}
        result = build_mock_reply(char, "你好")
        assert result == "我在，你继续说。"

    def test_no_styles_none(self):
        from services.chat_send import build_mock_reply
        char = {}
        result = build_mock_reply(char, "你好")
        assert result == "我在，你继续说。"

    def test_style_rotation(self):
        from services.chat_send import build_mock_reply
        char = {"mock_reply_style": ["风格A", "风格B", "风格C"]}
        r1 = build_mock_reply(char, "a")  # ord('a')=97, 97%3=1 → 风格B
        r2 = build_mock_reply(char, "b")  # ord('b')=98, 98%3=2 → 风格C
        assert "风格B" in r1
        assert "风格C" in r2

    def test_emotional_keyword_累(self):
        from services.chat_send import build_mock_reply
        char = {"mock_reply_style": ["嗯，"]}
        result = build_mock_reply(char, "我好累")
        assert "先别想别的" in result

    def test_emotional_keyword_想你(self):
        from services.chat_send import build_mock_reply
        char = {"mock_reply_style": ["嗯，"]}
        result = build_mock_reply(char, "我想你了")
        assert "我听到了" in result

    def test_text_style_json_parsing(self):
        """jsonb 列值（已解析为 list）和 text 格式（需 json.loads）都应兼容。"""
        from services.chat_send import build_mock_reply
        # jsonb 场景：psycopg2 已解析为 list
        char_jsonb = {"mock_reply_style": ["风格A"]}
        assert "风格A" in build_mock_reply(char_jsonb, "x")

        # text 场景：需要 json.loads
        char_text = {"mock_reply_style": '["风格A"]'}
        assert "风格A" in build_mock_reply(char_text, "x")


# ── save_assistant_message ───────────────────────────

class TestSaveAssistantMessage:
    def test_returns_id_on_success(self):
        from services.chat_send import save_assistant_message
        row = FakeRow({"id": 42})
        conn = FakeSequenceConn([row])
        result = save_assistant_message(conn, user_id=1, character_id="c1", reply="hi", commit=False)
        assert result == "42"

    def test_returns_empty_on_no_row(self):
        from services.chat_send import save_assistant_message
        conn = FakeSequenceConn([None])
        result = save_assistant_message(conn, user_id=1, character_id="c1", reply="hi", commit=False)
        assert result == ""

    def test_commit_flag(self):
        from services.chat_send import save_assistant_message
        row = FakeRow({"id": 1})
        conn = FakeSequenceConn([row])
        save_assistant_message(conn, user_id=1, character_id="c1", reply="hi", commit=True)
        assert conn.committed is True


# ── store_user_message ───────────────────────────────

class TestStoreUserMessage:
    def test_executes_insert(self):
        from services.chat_send import store_user_message
        conn = FakeSequenceConn([FakeRow()])
        store_user_message(conn, user_id=1, character_id="c1", content="hello", commit=False)
        sql, params = conn.executed[0]
        assert "INSERT INTO chat_messages" in sql
        assert "role" in sql
        assert params[2] == "hello"

    def test_no_commit_flag(self):
        from services.chat_send import store_user_message
        conn = FakeSequenceConn([FakeRow()])
        store_user_message(conn, user_id=1, character_id="c1", content="hello", commit=False)
        assert conn.committed is False


# ── 以下测试从 test_chat_send_extra.py 合并而来 ──

class TestBuildMockReplyExtra:
    def test_fingerprint_deterministic(self):
        from services.chat_send import build_mock_reply
        char = {"mock_reply_style": '["A", "B", "C"]'}
        r1 = build_mock_reply(char, "test message")
        r2 = build_mock_reply(char, "test message")
        assert r1 == r2


class TestFormatSseExtra:
    def test_json_encoding_unicode(self):
        from services.chat_send import format_sse
        result = format_sse("chunk", {"text": "你好"})
        data = json.loads(result.split("data: ", 1)[1].strip())
        assert data["text"] == "你好"


class TestBuildPromptContextPayload:
    def test_assembles_all_fields(self):
        from services.chat_send import _build_prompt_context_payload
        result = _build_prompt_context_payload(
            current_content="",
            character={"id": "c1"},
            memory_summary="mem",
            prompt_messages=[{"role": "user", "content": "hi"}],
            related_assets=[],
        )
        assert result["current_content"] == ""
        assert result["character"] == {"id": "c1"}
        assert result["memory_summary"] == "mem"
        assert len(result["prompt_messages"]) == 1


class TestPreparePromptContextResult:
    def test_with_valid_context(self):
        from services.chat_send import _prepare_prompt_context_result
        context_tuple = (
            {"id": "c1"},
            "memory summary",
            [{"role": "user", "content": "hi"}],
            [],
        )
        result = _prepare_prompt_context_result(current_content="", context_tuple=context_tuple)
        assert result["character"]["id"] == "c1"
        assert result["memory_summary"] == "memory summary"
        assert len(result["prompt_messages"]) == 1

    def test_none_messages_uses_fallback(self):
        from services.chat_send import _prepare_prompt_context_result
        context_tuple = ({"id": "c1"}, "mem", None, [])
        result = _prepare_prompt_context_result(
            current_content="",
            context_tuple=context_tuple,
            fallback_prompt_messages=[{"role": "system", "content": "fallback"}],
        )
        assert result["prompt_messages"] == [{"role": "system", "content": "fallback"}]

    def test_none_messages_no_fallback_returns_empty(self):
        from services.chat_send import _prepare_prompt_context_result
        context_tuple = ({"id": "c1"}, "mem", None, [])
        result = _prepare_prompt_context_result(current_content="", context_tuple=context_tuple)
        assert result["prompt_messages"] == []


class TestBuildGuestFallbackMessages:
    def test_builds_system_and_user(self):
        from services.chat_stream._guest import build_guest_fallback_messages as _build_guest_fallback_messages
        char = {"name": "Alice", "subtitle": "测试角色", "description": "desc"}
        result = _build_guest_fallback_messages(char, "hello")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "Alice" in result[0]["content"]
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "hello"

    def test_name_only_sufficient(self):
        from services.chat_stream._guest import build_guest_fallback_messages as _build_guest_fallback_messages
        char = {"name": "Carol"}
        result = _build_guest_fallback_messages(char, "hi")
        assert "Carol" in result[0]["content"]


class TestBuildChatSendResponse:
    def test_includes_all_keys(self):
        from services.chat_send import _build_chat_send_response
        result = _build_chat_send_response(
            reply="hello",
            history_count=5,
            character_state={"affection": 50},
        )
        assert result["reply"] == "hello"
        assert result["history_count"] == 5
        assert result["summary_enabled"] is True
        assert result["character_state"]["affection"] == 50


class TestBuildStreamPrepareResult:
    def test_minimal_payload(self):
        from services.chat_send import _build_stream_prepare_result
        payload = {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"model": "gpt-4"},
            "estimate": {"chars": 10, "tokens": 5},
        }
        result = _build_stream_prepare_result(guest_ip="127.0.0.1", stream_payload=payload)
        assert result["guest_ip"] == "127.0.0.1"
        assert result["stream_messages"] == payload["stream_messages"]
        assert "character" not in result

    def test_with_all_optional_fields(self):
        from services.chat_send import _build_stream_prepare_result
        payload = {"stream_messages": [], "ai_config": {}, "estimate": {}}
        result = _build_stream_prepare_result(
            guest_ip="127.0.0.1",
            stream_payload=payload,
            character={"id": "c1"},
            clean_text="hello",
            recent_messages=[],
            memory_summary="mem",
            related_assets=[],
            character_id="c1",
            current_content="old",
        )
        assert result["character"] == {"id": "c1"}
        assert result["clean_text"] == "hello"
        assert result["character_id"] == "c1"
        assert result["current_content"] == "old"
