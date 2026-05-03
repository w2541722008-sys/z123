"""chat_send 纯函数单元测试。

覆盖：build_mock_reply / format_sse / format_done_event /
format_error_event / _build_prompt_context_payload /
_prepare_prompt_context_result / _build_guest_fallback_messages /
_build_chat_send_response / _build_stream_prepare_result。
"""
import json

from services.chat_send import (
    build_mock_reply,
    format_sse,
    format_done_event,
    format_error_event,
    _build_prompt_context_payload,
    _prepare_prompt_context_result,
    _build_guest_fallback_messages,
    _build_chat_send_response,
    _build_stream_prepare_result,
)


# ============================================================
# build_mock_reply
# ============================================================
class TestBuildMockReply:
    def test_no_styles_returns_default(self):
        char = {"mock_reply_style": "[]"}
        result = build_mock_reply(char, "hello")
        assert result == "我在，你继续说。"

    def test_with_styles(self):
        char = {"mock_reply_style": '["style A", "style B"]'}
        result = build_mock_reply(char, "hello")
        assert result in ("style A", "style B")

    def test_styles_as_list(self):
        char = {"mock_reply_style": ["style A", "style B"]}
        result = build_mock_reply(char, "hello")
        assert result in ("style A", "style B")

    def test_emotional_keyword_tired(self):
        char = {"mock_reply_style": '["嗯嗯"]'}
        result = build_mock_reply(char, "我好累")
        assert "先别想别的" in result

    def test_emotional_keyword_love(self):
        char = {"mock_reply_style": '["嗯嗯"]'}
        result = build_mock_reply(char, "我想你了")
        assert "我听到了" in result

    def test_fingerprint_deterministic(self):
        char = {"mock_reply_style": '["A", "B", "C"]'}
        r1 = build_mock_reply(char, "test message")
        r2 = build_mock_reply(char, "test message")
        assert r1 == r2


# ============================================================
# format_sse
# ============================================================
class TestFormatSse:
    def test_basic(self):
        result = format_sse("chunk", {"text": "hello"})
        assert result.startswith("event: chunk\n")
        assert "hello" in result
        assert result.endswith("\n\n")

    def test_json_encoding(self):
        result = format_sse("chunk", {"text": "你好"})
        data = json.loads(result.split("data: ", 1)[1].strip())
        assert data["text"] == "你好"


# ============================================================
# format_done_event
# ============================================================
class TestFormatDoneEvent:
    def test_basic(self):
        result = format_done_event({"reply": "hello"})
        assert "event: done" in result
        assert "hello" in result


# ============================================================
# format_error_event
# ============================================================
class TestFormatErrorEvent:
    def test_basic(self):
        result = format_error_event("出错了")
        assert "event: error" in result
        assert "出错了" in result


# ============================================================
# _build_prompt_context_payload
# ============================================================
class TestBuildPromptContextPayload:
    def test_basic(self):
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


# ============================================================
# _prepare_prompt_context_result
# ============================================================
class TestPreparePromptContextResult:
    def test_basic(self):
        context_tuple = (
            {"id": "c1"},  # character
            "memory summary",  # memory_summary
            [{"role": "user", "content": "hi"}],  # prompt_messages
            [],  # related_assets
        )
        result = _prepare_prompt_context_result(
            current_content="",
            context_tuple=context_tuple,
        )
        assert result["character"]["id"] == "c1"
        assert result["memory_summary"] == "memory summary"
        assert len(result["prompt_messages"]) == 1

    def test_none_prompt_messages_uses_fallback(self):
        context_tuple = (
            {"id": "c1"},
            "mem",
            None,  # prompt_messages is None
            [],
        )
        result = _prepare_prompt_context_result(
            current_content="",
            context_tuple=context_tuple,
            fallback_prompt_messages=[{"role": "system", "content": "fallback"}],
        )
        assert result["prompt_messages"] == [{"role": "system", "content": "fallback"}]

    def test_none_prompt_messages_no_fallback(self):
        context_tuple = (
            {"id": "c1"},
            "mem",
            None,
            [],
        )
        result = _prepare_prompt_context_result(
            current_content="",
            context_tuple=context_tuple,
        )
        assert result["prompt_messages"] == []


# ============================================================
# _build_guest_fallback_messages
# ============================================================
class TestBuildGuestFallbackMessages:
    def test_basic(self):
        char = {"name": "Alice", "subtitle": "测试角色", "description": "desc"}
        result = _build_guest_fallback_messages(char, "hello")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "Alice" in result[0]["content"]
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "hello"

    def test_no_subtitle(self):
        char = {"name": "Bob", "description": "desc"}
        result = _build_guest_fallback_messages(char, "hi")
        assert "Bob" in result[0]["content"]

    def test_no_description(self):
        char = {"name": "Carol"}
        result = _build_guest_fallback_messages(char, "hi")
        assert "Carol" in result[0]["content"]


# ============================================================
# _build_chat_send_response
# ============================================================
class TestBuildChatSendResponse:
    def test_basic(self):
        result = _build_chat_send_response(
            reply="hello",
            history_count=5,
            character_state={"affection": 50},
        )
        assert result["reply"] == "hello"
        assert result["history_count"] == 5
        assert result["summary_enabled"] is True
        assert result["character_state"]["affection"] == 50


# ============================================================
# _build_stream_prepare_result
# ============================================================
class TestBuildStreamPrepareResult:
    def test_minimal(self):
        payload = {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"model": "gpt-4"},
            "estimate": {"chars": 10, "tokens": 5},
        }
        result = _build_stream_prepare_result(
            guest_ip="127.0.0.1",
            stream_payload=payload,
        )
        assert result["guest_ip"] == "127.0.0.1"
        assert result["stream_messages"] == payload["stream_messages"]
        assert "character" not in result

    def test_with_optional_fields(self):
        payload = {
            "stream_messages": [],
            "ai_config": {},
            "estimate": {},
        }
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
