"""chat_stream_service 单元测试。

覆盖 SSE 响应构建、Done payload 序列化安全、流后处理绑定等纯逻辑。
"""

import json
from unittest.mock import patch

from services.chat_stream import (
    _bind_stream_postprocess,
    _build_main_stream_postprocess,
    _build_guest_stream_postprocess,
    _build_retry_stream_postprocess,
)
from services.chat_stream._sse import (
    _build_stream_done_payload,
    _build_stream_done_payload_from_persisted_result,
    _default_stream_headers,
    _default_stream_error_message,
    _build_sse_response,
)


# ============================================================
# _build_stream_done_payload — 核心 Done 事件 Payload 构建
# ============================================================
class TestBuildStreamDonePayload:
    def test_all_optional_fields_combined(self):
        result = _build_stream_done_payload(
            reply="hello",
            fallback=True,
            character_state={"affection": 50},
            message_id="m1",
            operation="regenerate",
            appended_text=" extra",
            guest=True,
            summary_enabled=True,
        )
        assert result["reply"] == "hello"
        assert result["fallback"] is True
        assert result["character_state"] == {"affection": 50}
        assert result["message_id"] == "m1"
        assert result["operation"] == "regenerate"
        assert result["appended_text"] == " extra"
        assert result["guest"] is True
        assert result["summary_enabled"] is True

    def test_payload_is_json_serializable(self):
        result = _build_stream_done_payload(
            reply="hello",
            fallback=False,
            character_state={"affection": 50, "mood": "warm"},
            message_id="abc-123",
        )
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        assert parsed == result

    def test_reply_with_special_characters_preserved(self):
        result = _build_stream_done_payload(
            reply="你好\n世界\t\"quoted\"",
            fallback=False,
        )
        assert "你好" in result["reply"]
        assert "\n" in result["reply"]
        assert '"quoted"' in result["reply"]

    def test_character_state_included_when_provided(self):
        result = _build_stream_done_payload(
            reply="hi", fallback=False, character_state={"affection": 60}
        )
        assert "character_state" in result
        assert result["character_state"]["affection"] == 60

    def test_optional_fields_omitted_when_none(self):
        result = _build_stream_done_payload(reply="hi", fallback=False)
        assert "character_state" not in result
        assert "message_id" not in result
        assert "guest" not in result

    def test_summary_enabled_false_included(self):
        result = _build_stream_done_payload(reply="hi", fallback=False, summary_enabled=False)
        assert result["summary_enabled"] is False


# ============================================================
# _build_stream_done_payload_from_persisted_result
# ============================================================
class TestFromPersistedResult:
    def test_merges_persisted_fields(self):
        persisted = {"character_state": {"affection": 60}, "message_id": "msg-1"}
        result = _build_stream_done_payload_from_persisted_result(
            reply="hello", persisted_result=persisted
        )
        assert result["reply"] == "hello"
        assert result["character_state"] == {"affection": 60}
        assert result["message_id"] == "msg-1"

    def test_summary_enabled_defaults_to_true(self):
        persisted = {"character_state": {}, "message_id": "msg-2"}
        result = _build_stream_done_payload_from_persisted_result(
            reply="hi", persisted_result=persisted
        )
        assert result["summary_enabled"] is True


# ============================================================
# 默认 Headers / Error Message
# ============================================================
class TestDefaults:
    def test_stream_headers_include_no_cache(self):
        headers = _default_stream_headers()
        assert headers["Cache-Control"] == "no-cache"
        assert headers["X-Accel-Buffering"] == "no"

    def test_stream_error_message_non_empty(self):
        msg = _default_stream_error_message()
        assert isinstance(msg, str)
        assert len(msg) > 0


# ============================================================
# _build_sse_response — SSE StreamingResponse 构建
# ============================================================
class TestBuildSseResponse:
    def test_returns_streaming_response_with_correct_media_type(self):
        def gen():
            yield "data: test\n\n"

        resp = _build_sse_response(gen)
        from starlette.responses import StreamingResponse
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"

    def test_custom_headers_merged(self):
        def gen():
            yield "data: test\n\n"

        resp = _build_sse_response(gen, headers={"X-Custom": "yes"})
        assert resp.headers["x-custom"] == "yes"


# ============================================================
# _bind_stream_postprocess — 流后处理柯里化
# ============================================================
class TestBindStreamPostprocess:
    def test_bound_function_receives_extra_kwargs(self):
        calls = []

        def mock_postprocess(final_text, delta=None, **kwargs):
            calls.append({"final_text": final_text, "delta": delta, **kwargs})
            return iter(["result"])

        bound = _bind_stream_postprocess(
            mock_postprocess, user_id=1, character_id="c1"
        )
        result = list(bound("hello", delta={"mood": "warm"}))
        assert result == ["result"]
        assert calls[0]["user_id"] == 1
        assert calls[0]["character_id"] == "c1"
        assert calls[0]["final_text"] == "hello"


# ============================================================
# Stream Postprocess Builders — 三种后处理工厂
# ============================================================
class TestStreamPostprocessBuilders:
    """验证三种 builder 返回可调用对象，且调用时将 kwargs 正确传递给底层函数。"""

    def test_main_builder_invokes_postprocess_with_merged_kwargs(self):
        with patch(
            "services.chat_stream._postprocess_main_stream_result"
        ) as mock_post:
            mock_post.return_value = iter(["ok"])
            fn = _build_main_stream_postprocess(
                user_id=1, guest_ip="127.0.0.1", character_id="c1",
                estimate={"chars": 10, "tokens": 5}, user_message="hi", character={"name": "Test"},
            )
            result = list(fn("hello", delta={"mood": "warm"}))
            assert result == ["ok"]
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["final_text"] == "hello"
            assert call_kwargs["delta"] == {"mood": "warm"}
            assert call_kwargs["user_id"] == 1
            assert call_kwargs["character_id"] == "c1"
            assert call_kwargs["user_message"] == "hi"
            assert call_kwargs["character"] == {"name": "Test"}

    def test_guest_builder_invokes_postprocess_with_merged_kwargs(self):
        with patch(
            "services.chat_stream._postprocess_guest_stream_result"
        ) as mock_post:
            mock_post.return_value = iter(["ok"])
            fn = _build_guest_stream_postprocess(
                guest_ip="10.0.0.1", character_id="c2",
                estimate={"chars": 5, "tokens": 2},
            )
            list(fn("hi"))
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["final_text"] == "hi"
            assert call_kwargs["guest_ip"] == "10.0.0.1"
            assert call_kwargs["character_id"] == "c2"

    def test_retry_builder_invokes_postprocess_with_merged_kwargs(self):
        with patch(
            "services.chat_stream._postprocess_regenerate_or_continue_result"
        ) as mock_post:
            mock_post.return_value = iter(["ok"])
            fn = _build_retry_stream_postprocess(
                user_id=1, guest_ip="127.0.0.1", character_id="c3",
                message_id="m99", endpoint="/api/chat/regenerate",
                estimate={"chars": 10, "tokens": 5},
                is_append=True, base_reply="old reply", operation="regenerate",
            )
            list(fn("new reply", delta={"affection": 5}))
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["final_text"] == "new reply"
            assert call_kwargs["delta"] == {"affection": 5}
            assert call_kwargs["message_id"] == "m99"
            assert call_kwargs["is_append"] is True
            assert call_kwargs["base_reply"] == "old reply"
            assert call_kwargs["operation"] == "regenerate"

    def test_bound_fn_preserves_kwargs_across_multiple_calls(self):
        """多次调用同一 bound 函数时，kwargs 在每次调用中保持一致。"""
        with patch(
            "services.chat_stream._postprocess_main_stream_result"
        ) as mock_post:
            mock_post.return_value = iter(["a"])
            fn = _build_main_stream_postprocess(
                user_id=42, guest_ip="127.0.0.1", character_id="c1",
                estimate={"chars": 10, "tokens": 5}, user_message="hi", character={},
            )
            list(fn("first"))
            list(fn("second"))
            assert mock_post.call_count == 2
            assert mock_post.call_args_list[0].kwargs["final_text"] == "first"
            assert mock_post.call_args_list[1].kwargs["final_text"] == "second"
            assert mock_post.call_args_list[0].kwargs["user_id"] == 42
            assert mock_post.call_args_list[1].kwargs["user_id"] == 42
