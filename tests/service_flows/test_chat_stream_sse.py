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
from services.chat_stream._postprocess import (
    _persist_stream_result,
    _postprocess_regenerate_or_continue_result,
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


class TestRetryPostprocessStateUpdates:
    def test_regenerate_does_not_apply_state_delta_again(self):
        events = []
        state_deltas = []

        class FakeConn:
            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

            def close(self):
                events.append("close")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.chat_stream._postprocess.get_conn", lambda: FakeConn())
            mp.setattr(
                "services.chat_stream._postprocess.save_regenerated_version",
                lambda conn, message_id, final_text, is_append, commit: events.append(
                    ("save", message_id, final_text, is_append, commit)
                ),
            )
            mp.setattr(
                "services.chat_stream._postprocess._log_successful_chat_request",
                lambda *args, **kwargs: events.append(("log", kwargs["endpoint"])),
            )

            def capture_state_delta(*args, **kwargs):
                state_deltas.append(kwargs.get("delta"))
                return {"affection": 12}

            mp.setattr(
                "services.chat_stream._postprocess._resolve_public_character_state",
                capture_state_delta,
            )
            mp.setattr(
                "services.chat_stream._postprocess.run_memory_summary_background",
                lambda *args, **kwargs: events.append("summary"),
            )

            output = list(
                _postprocess_regenerate_or_continue_result(
                    user_id=1,
                    guest_ip="127.0.0.1",
                    character_id="c1",
                    message_id="m1",
                    endpoint="/api/chat/regenerate",
                    estimate={"chars": 10, "tokens": 5},
                    is_append=False,
                    base_reply="",
                    operation="regenerate",
                    final_text="new reply",
                    delta={"event": "compliment", "mood": "shy"},
                )
            )

        assert any("event: done" in item for item in output)
        assert ("save", "m1", "new reply", False, False) in events
        assert state_deltas == [None]
        assert "commit" in events


class TestMainStreamPostprocessWorldInfoState:
    def test_persists_opening_message_before_stream_messages(self):
        events = []

        class FakeConn:
            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

            def close(self):
                events.append("close")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.chat_stream._postprocess.get_conn", lambda: FakeConn())
            mp.setattr(
                "services.chat_stream._postprocess.ensure_opening_message",
                lambda *args, **kwargs: events.append(("opening", kwargs["commit"])),
                raising=False,
            )
            mp.setattr(
                "services.chat_stream._postprocess.store_user_message",
                lambda *args, **kwargs: events.append(("user", kwargs["commit"])),
            )
            mp.setattr(
                "services.chat_stream._postprocess.save_assistant_message",
                lambda *args, **kwargs: events.append(("assistant", kwargs["commit"])) or "m1",
            )
            mp.setattr(
                "services.chat_stream._postprocess._log_successful_chat_request",
                lambda *args, **kwargs: events.append("log"),
            )
            mp.setattr(
                "services.chat_stream._postprocess._resolve_public_character_state",
                lambda *args, **kwargs: events.append("state") or {"affection": 30},
            )
            mp.setattr(
                "services.chat_stream._postprocess.tick_passive_character_state",
                lambda *args, **kwargs: events.append("tick") or {"affection": 30},
            )

            result = _persist_stream_result(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="c1",
                final_reply="hi",
                estimate={"tokens": 5, "chars": 10},
                delta=None,
                user_message="hello",
            )

        assert result["message_id"] == "m1"
        assert events.index(("opening", False)) < events.index(("user", False))
        assert events.index(("user", False)) < events.index(("assistant", False))
        assert events.index(("assistant", False)) < events.index("commit")
        assert "tick" in events

    def test_uses_state_delta_instead_of_passive_tick_when_delta_exists(self):
        events = []

        class FakeConn:
            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

            def close(self):
                events.append("close")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.chat_stream._postprocess.get_conn", lambda: FakeConn())
            mp.setattr(
                "services.chat_stream._postprocess.ensure_opening_message",
                lambda *args, **kwargs: events.append("opening"),
                raising=False,
            )
            mp.setattr(
                "services.chat_stream._postprocess.store_user_message",
                lambda *args, **kwargs: events.append("user"),
            )
            mp.setattr(
                "services.chat_stream._postprocess.save_assistant_message",
                lambda *args, **kwargs: events.append("assistant") or "m1",
            )
            mp.setattr(
                "services.chat_stream._postprocess._log_successful_chat_request",
                lambda *args, **kwargs: events.append("log"),
            )
            mp.setattr(
                "services.chat_stream._postprocess._resolve_public_character_state",
                lambda *args, **kwargs: events.append(("state", kwargs["delta"])) or {"affection": 31},
            )
            mp.setattr(
                "services.chat_stream._postprocess.tick_passive_character_state",
                lambda *args, **kwargs: events.append("tick") or {"affection": 30},
                raising=False,
            )

            result = _persist_stream_result(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="c1",
                final_reply="hi",
                estimate={"tokens": 5, "chars": 10},
                delta={"event": "compliment"},
                user_message="hello",
            )

        assert result["character_state"] == {"affection": 31}
        assert ("state", {"event": "compliment"}) in events
        assert "tick" not in events

    def test_persists_wi_state_before_commit_in_save_transaction(self):
        events = []

        class FakeConn:
            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

            def close(self):
                events.append("close")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.chat_stream._postprocess.get_conn", lambda: FakeConn())
            mp.setattr(
                "services.chat_stream._postprocess.ensure_opening_message",
                lambda *args, **kwargs: events.append("opening"),
                raising=False,
            )
            mp.setattr(
                "services.chat_stream._postprocess.store_user_message",
                lambda *args, **kwargs: events.append("user"),
            )
            mp.setattr(
                "services.chat_stream._postprocess.save_assistant_message",
                lambda *args, **kwargs: events.append("assistant") or "m1",
            )
            mp.setattr(
                "services.chat_stream._postprocess._log_successful_chat_request",
                lambda *args, **kwargs: events.append("log"),
            )
            mp.setattr(
                "services.chat_stream._postprocess._resolve_public_character_state",
                lambda *args, **kwargs: events.append("state") or {"affection": 30},
            )
            mp.setattr(
                "services.chat_stream._postprocess.tick_passive_character_state",
                lambda *args, **kwargs: events.append("tick") or {"affection": 30},
                raising=False,
            )

            def capture_wi_state(conn, user_id, character_id, character_state):
                events.append(("wi", user_id, character_id, character_state))

            mp.setattr(
                "services.chat_stream._postprocess._persist_wi_state",
                capture_wi_state,
            )

            result = _persist_stream_result(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="c1",
                final_reply="hi",
                estimate={"tokens": 5, "chars": 10},
                delta=None,
                user_message="hello",
                wi_state={"custom_vars": {"_wi_sticky": {"scene": 2}}},
            )

        wi_event = ("wi", 1, "c1", {"custom_vars": {"_wi_sticky": {"scene": 2}}})

        assert result["message_id"] == "m1"
        assert events.index("tick") < events.index(wi_event)
        assert events.index(wi_event) < events.index("commit")

    def test_skips_wi_persistence_when_no_wi_state(self):
        events = []

        class FakeConn:
            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

            def close(self):
                events.append("close")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.chat_stream._postprocess.get_conn", lambda: FakeConn())
            mp.setattr(
                "services.chat_stream._postprocess.save_assistant_message",
                lambda *args, **kwargs: "m1",
            )
            mp.setattr(
                "services.chat_stream._postprocess._log_successful_chat_request",
                lambda *args, **kwargs: None,
            )
            mp.setattr(
                "services.chat_stream._postprocess._resolve_public_character_state",
                lambda *args, **kwargs: {"affection": 30},
            )
            mp.setattr(
                "services.chat_stream._postprocess.tick_passive_character_state",
                lambda *args, **kwargs: {"affection": 30},
            )
            mp.setattr(
                "services.chat_stream._postprocess._persist_wi_state",
                lambda *args, **kwargs: events.append("wi"),
            )

            _persist_stream_result(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="c1",
                final_reply="hi",
                estimate={"tokens": 5, "chars": 10},
                delta=None,
            )

        assert "wi" not in events
        assert "commit" in events
