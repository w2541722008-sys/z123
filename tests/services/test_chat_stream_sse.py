"""chat_stream/_sse.py 纯函数单元测试 — 覆盖数据解析、事件构建、错误分类。"""

from __future__ import annotations

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from services.chat_stream._sse import (
    _default_stream_headers,
    _default_stream_error_message,
    _is_circuit_breaker_error,
    _parse_accumulated_state_update,
    _build_stream_done_payload,
    _build_stream_done_payload_from_persisted_result,
)


class TestDefaultStreamHeaders:
    def test_returns_cache_control_no_cache(self):
        assert _default_stream_headers()["Cache-Control"] == "no-cache"

    def test_returns_x_accel_buffering_no(self):
        assert _default_stream_headers()["X-Accel-Buffering"] == "no"

    def test_returns_exactly_two_keys(self):
        assert len(_default_stream_headers()) == 2


class TestDefaultStreamErrorMessage:
    def test_returns_non_empty_string(self):
        msg = _default_stream_error_message()
        assert isinstance(msg, str)
        assert len(msg) > 0


class TestIsCircuitBreakerError:
    def test_english_circuit_word(self):
        assert _is_circuit_breaker_error("circuit breaker tripped") is True

    def test_english_circuit_case_insensitive(self):
        assert _is_circuit_breaker_error("CIRCUIT OPEN") is True

    def test_chinese_rongduan(self):
        assert _is_circuit_breaker_error("熔断器触发") is True

    def test_chinese_zanshi_bukeyong(self):
        assert _is_circuit_breaker_error("服务暂时不可用") is True

    def test_normal_error_is_not_circuit(self):
        assert _is_circuit_breaker_error("timeout error") is False

    def test_empty_error_is_not_circuit(self):
        assert _is_circuit_breaker_error("") is False


class TestParseAccumulatedStateUpdate:
    def test_empty_list_returns_none(self):
        assert _parse_accumulated_state_update([]) is None

    def test_whitespace_only_returns_none(self):
        assert _parse_accumulated_state_update(["   "]) is None

    def test_valid_json_dict_returns_parsed(self):
        result = _parse_accumulated_state_update(['{"affection": 10}'])
        assert result == {"affection": 10}

    def test_nested_json_returns_parsed(self):
        result = _parse_accumulated_state_update(['{"mood": "happy", "event": "greet"}'])
        assert result == {"mood": "happy", "event": "greet"}

    def test_invalid_json_returns_none(self):
        assert _parse_accumulated_state_update(["{not valid json}"]) is None

    def test_json_array_returns_none(self):
        """非 dict 的 JSON（如数组）应返回 None。"""
        assert _parse_accumulated_state_update(["[1, 2, 3]"]) is None

    def test_json_string_returns_none(self):
        """非 dict 的 JSON（如字符串）应返回 None。"""
        assert _parse_accumulated_state_update(['"hello"']) is None

    def test_json_number_returns_none(self):
        assert _parse_accumulated_state_update(["42"]) is None

    def test_uses_only_first_part(self):
        """多片段时仅取第一个。"""
        result = _parse_accumulated_state_update(['{"a": 1}', "extra", "stuff"])
        assert result == {"a": 1}


class TestBuildStreamDonePayload:
    def test_minimal_payload(self):
        p = _build_stream_done_payload(reply="Hi", fallback=False)
        assert p == {"reply": "Hi", "fallback": False}

    def test_fallback_true(self):
        p = _build_stream_done_payload(reply="Hi", fallback=True)
        assert p["fallback"] is True

    def test_with_character_state(self):
        p = _build_stream_done_payload(
            reply="Hi", fallback=False, character_state={"affection": 50},
        )
        assert p["character_state"] == {"affection": 50}

    def test_character_state_none_excluded(self):
        p = _build_stream_done_payload(reply="Hi", fallback=False, character_state=None)
        assert "character_state" not in p

    def test_with_message_id(self):
        p = _build_stream_done_payload(
            reply="Hi", fallback=False, message_id="msg_123",
        )
        assert p["message_id"] == "msg_123"

    def test_message_id_none_excluded(self):
        p = _build_stream_done_payload(reply="Hi", fallback=False, message_id=None)
        assert "message_id" not in p

    def test_with_operation(self):
        p = _build_stream_done_payload(
            reply="Hi", fallback=False, operation="regenerate",
        )
        assert p["operation"] == "regenerate"

    def test_with_appended_text(self):
        p = _build_stream_done_payload(
            reply="Hi", fallback=False, appended_text=" extra",
        )
        assert p["appended_text"] == " extra"

    def test_guest_flag(self):
        p = _build_stream_done_payload(reply="Hi", fallback=False, guest=True)
        assert p["guest"] is True

    def test_guest_false_excluded(self):
        p = _build_stream_done_payload(reply="Hi", fallback=False, guest=False)
        assert "guest" not in p

    def test_summary_enabled(self):
        p = _build_stream_done_payload(
            reply="Hi", fallback=False, summary_enabled=True,
        )
        assert p["summary_enabled"] is True

    def test_summary_enabled_none_excluded(self):
        p = _build_stream_done_payload(reply="Hi", fallback=False, summary_enabled=None)
        assert "summary_enabled" not in p

    def test_full_payload(self):
        p = _build_stream_done_payload(
            reply="Hello World",
            fallback=False,
            character_state={"affection": 80},
            message_id="m1",
            operation="continue",
            appended_text="...",
            guest=True,
            summary_enabled=False,
        )
        assert p == {
            "reply": "Hello World",
            "fallback": False,
            "character_state": {"affection": 80},
            "message_id": "m1",
            "operation": "continue",
            "appended_text": "...",
            "guest": True,
            "summary_enabled": False,
        }


class TestBuildStreamDonePayloadFromPersistedResult:
    def test_maps_fields_correctly(self):
        persisted = {
            "character_state": {"affection": 30},
            "message_id": "msg_42",
        }
        p = _build_stream_done_payload_from_persisted_result(
            reply="Hello", persisted_result=persisted,
        )
        assert p == {
            "reply": "Hello",
            "fallback": False,
            "character_state": {"affection": 30},
            "message_id": "msg_42",
            "summary_enabled": True,
        }
