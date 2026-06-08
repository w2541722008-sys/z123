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


class TestBuildGuestStreamMessages:
    def test_injects_guest_state_snapshot_and_update_instruction(self):
        from services.chat_stream._guest import build_guest_stream_messages

        character = {
            "id": "c1",
            "name": "Alice",
            "description": "温柔的陪伴者",
            "card_type": "intimate",
            "affection_rules_json": "{}",
        }
        conn = FakeSequenceConn([
            [],  # World Info memory rows
            [],  # post-history rules
            FakeRow({"affection_rules_json": "{}", "affection_enabled": 1}),
        ])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "services.chat_stream._guest.get_guest_character_state_for_prompt",
                lambda guest_ip, character_id: {
                    "affection": 12,
                    "story_phase": "stranger",
                    "mood": "warm",
                    "custom_vars": {},
                },
            )

            _, messages = build_guest_stream_messages(
                character,
                "今天有点累",
                [],
                conn=conn,
                guest_ip="127.0.0.1",
            )

        prompt_text = "\n".join(message["content"] for message in messages)
        assert "当前关系状态" in prompt_text
        assert "好感度：12/100" in prompt_text
        assert "状态更新指令" in prompt_text

    def test_respects_affection_rules_disabled_for_guest_prompt(self):
        from services.chat_stream._guest import build_guest_stream_messages

        character = {
            "id": "c2",
            "name": "Alice",
            "description": "温柔的陪伴者",
            "card_type": "intimate",
            "affection_rules_json": '{"enabled": false}',
        }
        conn = FakeSequenceConn([
            [],  # World Info memory rows
            [],  # post-history rules
            FakeRow({"affection_rules_json": '{"enabled": false}', "affection_enabled": 1}),
        ])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "services.chat_stream._guest.get_guest_character_state_for_prompt",
                lambda guest_ip, character_id: {
                    "affection": 12,
                    "story_phase": "stranger",
                    "mood": "warm",
                    "custom_vars": {},
                },
            )

            _, messages = build_guest_stream_messages(
                character,
                "今天有点累",
                [],
                conn=conn,
                guest_ip="127.0.0.1",
            )

        prompt_text = "\n".join(message["content"] for message in messages)
        assert "当前关系状态" not in prompt_text
        assert "状态更新指令" not in prompt_text


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

    def test_carries_wi_state_from_stream_payload(self):
        from services.chat_send import _build_stream_prepare_result
        payload = {
            "stream_messages": [],
            "ai_config": {},
            "estimate": {},
            "wi_state": {"custom_vars": {"_wi_cooldown": {"entry": 3}}},
        }
        result = _build_stream_prepare_result(guest_ip="127.0.0.1", stream_payload=payload)
        assert result["wi_state"] == payload["wi_state"]

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
            wi_state={"custom_vars": {"_wi_sticky": {"scene": 1}}},
        )
        assert result["character"] == {"id": "c1"}
        assert result["clean_text"] == "hello"
        assert result["character_id"] == "c1"
        assert result["current_content"] == "old"
        assert result["wi_state"] == {"custom_vars": {"_wi_sticky": {"scene": 1}}}


class TestBuildUserStreamMessagesAndBudget:
    def test_returns_wi_state_without_persisting_in_prepare_phase(self):
        from types import SimpleNamespace
        from services.chat_send import _build_user_stream_messages_and_budget

        events = []
        character_state = {"custom_vars": {}}

        def fake_build_messages(context):
            context.character_state["custom_vars"]["_wi_sticky"] = {"scene": 2}
            return [{"role": "user", "content": "hi"}]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.chat_send.get_character_state", lambda *args: character_state)
            mp.setattr("services.chat_send.get_last_chat_time", lambda *args: None)
            mp.setattr("services.chat_send.build_layered_chat_messages_from_context", fake_build_messages)
            mp.setattr(
                "services.chat_send._persist_wi_state",
                lambda *args, **kwargs: events.append("persist"),
            )
            mp.setattr(
                "services.chat_send._prepare_user_ai_budget",
                lambda *args, **kwargs: {"ai_config": {}, "estimate": {"tokens": 1, "chars": 2}},
            )

            result = _build_user_stream_messages_and_budget(
                FakeSequenceConn([]),
                user=SimpleNamespace(id=1, nickname="u"),
                character_id="c1",
                character={"id": "c1"},
                prompt_messages=[],
                memory_summary="",
                related_assets=[],
            )

        assert result["wi_state"] == {"custom_vars": {"_wi_sticky": {"scene": 2}}}
        assert events == []

    def test_returns_anchor_rotation_index_with_prompt_runtime_state(self):
        from types import SimpleNamespace
        from services.chat_send import _build_user_stream_messages_and_budget

        character_state = {"custom_vars": {}}

        def fake_build_messages(context):
            context.character_state["custom_vars"]["_last_anchor_index"] = 3
            return [{"role": "user", "content": "hi"}]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.chat_send.get_character_state", lambda *args: character_state)
            mp.setattr("services.chat_send.get_last_chat_time", lambda *args: None)
            mp.setattr("services.chat_send.build_layered_chat_messages_from_context", fake_build_messages)
            mp.setattr(
                "services.chat_send._prepare_user_ai_budget",
                lambda *args, **kwargs: {"ai_config": {}, "estimate": {"tokens": 1, "chars": 2}},
            )

            result = _build_user_stream_messages_and_budget(
                FakeSequenceConn([]),
                user=SimpleNamespace(id=1, nickname="u"),
                character_id="c1",
                character={"id": "c1"},
                prompt_messages=[],
                memory_summary="",
                related_assets=[],
            )

        assert result["wi_state"] == {"custom_vars": {"_last_anchor_index": 3}}


class TestPersistWiState:
    def test_persists_anchor_rotation_index_without_dropping_existing_vars(self):
        from services.chat_send import _persist_wi_state

        conn = FakeSequenceConn([
            FakeRow({"custom_vars": '{"visible":"keep","_last_anchor_index":1}'}),
            FakeRow(),
        ])
        _persist_wi_state(
            conn,
            user_id=1,
            character_id="c1",
            character_state={"custom_vars": {"_last_anchor_index": 2}},
        )

        _, params = conn.executed[1]
        saved_custom_vars = json.loads(params[0])
        assert saved_custom_vars["visible"] == "keep"
        assert saved_custom_vars["_last_anchor_index"] == 2


class TestRunChatSendTransaction:
    def test_success_triggers_memory_summary_after_commit(self):
        from types import SimpleNamespace
        from routers.chat import _run_chat_send_transaction

        events = []

        class FakeConn:
            def commit(self):
                events.append("commit")

            def rollback(self):
                events.append("rollback")

        user = SimpleNamespace(id=1, nickname="u")
        payload = SimpleNamespace(character_id="c1")
        prepared = {
            "clean_text": "hello",
            "character": {"id": "c1", "name": "Test"},
            "ai_config": {},
            "recent_messages": [],
            "memory_summary": "",
            "related_assets": [],
            "estimate": {"tokens": 1, "chars": 2},
            "guest_ip": "127.0.0.1",
        }

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "routers.chat.store_user_message",
                lambda *args, **kwargs: events.append("user"),
            )
            mp.setattr(
                "routers.chat.build_reply_with_fallback",
                lambda *args, **kwargs: ("reply", None),
            )
            mp.setattr(
                "routers.chat.save_assistant_message",
                lambda *args, **kwargs: events.append("assistant"),
            )
            mp.setattr("routers.chat.count_chat_messages", lambda *args: 2)
            mp.setattr(
                "routers.chat._resolve_public_character_state",
                lambda *args, **kwargs: {"affection": 30},
            )
            mp.setattr(
                "routers.chat._log_successful_chat_request",
                lambda *args, **kwargs: events.append("log"),
            )
            mp.setattr(
                "routers.chat.run_memory_summary_background",
                lambda user_id, character_id, character: events.append(
                    ("summary", user_id, character_id, character)
                ),
            )

            result = _run_chat_send_transaction(
                FakeConn(),
                user=user,
                payload=payload,
                prepared=prepared,
            )

        assert result["reply"] == "reply"
        assert events.index("commit") < events.index(("summary", 1, "c1", prepared["character"]))
