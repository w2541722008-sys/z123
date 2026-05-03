"""chat_stream_service 纯函数单元测试。

覆盖：SSE 响应构建、Done payload 构建、后处理绑定等纯逻辑函数。
"""
from services.chat_stream_service import (
    _build_stream_done_payload,
    _build_stream_done_payload_from_persisted_result,
    _default_stream_headers,
    _default_stream_error_message,
    _build_sse_response,
    _bind_stream_postprocess,
    _build_main_stream_postprocess,
    _build_guest_stream_postprocess,
    _build_retry_stream_postprocess,
    _emit_stream_persist_failure,
)
from starlette.responses import StreamingResponse


# ============================================================
# _build_stream_done_payload
# ============================================================
class TestBuildStreamDonePayload:
    def test_minimal(self):
        result = _build_stream_done_payload(reply="hello", fallback=False)
        assert result == {"reply": "hello", "fallback": False}

    def test_with_character_state(self):
        result = _build_stream_done_payload(
            reply="hello", fallback=False, character_state={"affection": 50}
        )
        assert result["character_state"] == {"affection": 50}

    def test_with_message_id(self):
        result = _build_stream_done_payload(
            reply="hello", fallback=False, message_id="abc-123"
        )
        assert result["message_id"] == "abc-123"

    def test_with_operation(self):
        result = _build_stream_done_payload(
            reply="hello", fallback=False, operation="regenerate"
        )
        assert result["operation"] == "regenerate"

    def test_with_appended_text(self):
        result = _build_stream_done_payload(
            reply="hello world", fallback=False, appended_text=" world"
        )
        assert result["appended_text"] == " world"

    def test_guest_flag(self):
        result = _build_stream_done_payload(reply="hi", fallback=True, guest=True)
        assert result["guest"] is True

    def test_summary_enabled(self):
        result = _build_stream_done_payload(
            reply="hi", fallback=False, summary_enabled=True
        )
        assert result["summary_enabled"] is True

    def test_summary_disabled(self):
        result = _build_stream_done_payload(
            reply="hi", fallback=False, summary_enabled=False
        )
        assert result["summary_enabled"] is False

    def test_none_fields_omitted(self):
        result = _build_stream_done_payload(reply="hi", fallback=False)
        assert "character_state" not in result
        assert "message_id" not in result
        assert "operation" not in result
        assert "appended_text" not in result
        assert "guest" not in result
        assert "summary_enabled" not in result

    def test_all_fields(self):
        result = _build_stream_done_payload(
            reply="hello",
            fallback=True,
            character_state={"mood": "warm"},
            message_id="m1",
            operation="continue",
            appended_text=" extra",
            guest=True,
            summary_enabled=True,
        )
        assert result["reply"] == "hello"
        assert result["fallback"] is True
        assert result["character_state"] == {"mood": "warm"}
        assert result["message_id"] == "m1"
        assert result["operation"] == "continue"
        assert result["appended_text"] == " extra"
        assert result["guest"] is True
        assert result["summary_enabled"] is True


# ============================================================
# _build_stream_done_payload_from_persisted_result
# ============================================================
class TestBuildStreamDonePayloadFromPersistedResult:
    def test_basic(self):
        persisted = {
            "character_state": {"affection": 60},
            "message_id": "msg-1",
        }
        result = _build_stream_done_payload_from_persisted_result(
            reply="hello", persisted_result=persisted
        )
        assert result["reply"] == "hello"
        assert result["fallback"] is False
        assert result["character_state"] == {"affection": 60}
        assert result["message_id"] == "msg-1"
        assert result["summary_enabled"] is True


# ============================================================
# _default_stream_headers / _default_stream_error_message
# ============================================================
class TestDefaults:
    def test_stream_headers(self):
        headers = _default_stream_headers()
        assert headers["Cache-Control"] == "no-cache"
        assert headers["X-Accel-Buffering"] == "no"

    def test_stream_error_message(self):
        msg = _default_stream_error_message()
        assert isinstance(msg, str)
        assert len(msg) > 0


# ============================================================
# _build_sse_response
# ============================================================
class TestBuildSseResponse:
    def test_returns_streaming_response(self):
        def gen():
            yield "data: test\n\n"

        resp = _build_sse_response(gen)
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"

    def test_custom_headers(self):
        def gen():
            yield "data: test\n\n"

        resp = _build_sse_response(gen, headers={"X-Custom": "yes"})
        assert resp.headers.get("x-custom") == "yes"


# ============================================================
# _bind_stream_postprocess
# ============================================================
class TestBindStreamPostprocess:
    def test_bound_function_passes_kwargs(self):
        calls = []

        def mock_postprocess(final_text, delta=None, **kwargs):
            calls.append({"final_text": final_text, "delta": delta, **kwargs})
            return iter(["result"])

        bound = _bind_stream_postprocess(
            mock_postprocess, user_id=1, character_id="c1"
        )
        result = list(bound("hello", delta={"mood": "warm"}))
        assert result == ["result"]
        assert len(calls) == 1
        assert calls[0]["final_text"] == "hello"
        assert calls[0]["delta"] == {"mood": "warm"}
        assert calls[0]["user_id"] == 1
        assert calls[0]["character_id"] == "c1"


# ============================================================
# _build_*_stream_postprocess
# ============================================================
class TestStreamPostprocessBuilders:
    def test_main_stream_postprocess_returns_callable(self):
        fn = _build_main_stream_postprocess(
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="c1",
            estimate={"chars": 10, "tokens": 5},
            user_message="hi",
            character={},
        )
        assert callable(fn)

    def test_guest_stream_postprocess_returns_callable(self):
        fn = _build_guest_stream_postprocess(
            guest_ip="127.0.0.1",
            character_id="c1",
            estimate={"chars": 10, "tokens": 5},
        )
        assert callable(fn)

    def test_retry_stream_postprocess_returns_callable(self):
        fn = _build_retry_stream_postprocess(
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="c1",
            message_id="m1",
            endpoint="/api/chat/regenerate",
            estimate={"chars": 10, "tokens": 5},
            is_append=False,
            base_reply="old",
            operation="regenerate",
        )
        assert callable(fn)
