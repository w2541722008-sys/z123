import asyncio
from functools import partial
from types import SimpleNamespace
import pytest
from unittest.mock import ANY, MagicMock, patch

from services import chat_service


async def _read_streaming_text(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(str(chunk))
    return "".join(chunks)


class TestChatModuleRefactoring:
    def test_normalize_non_empty_message_trims_and_rejects_blank_input(self):
        assert chat_service._normalize_non_empty_message("  hi  ") == "hi"

        with pytest.raises(Exception) as exc_info:
            chat_service._normalize_non_empty_message("   ")

        assert getattr(exc_info.value, "status_code", None) == 400
        assert getattr(exc_info.value, "detail", None) == "消息不能为空"

    def test_load_recent_messages_and_summary_appends_pending_user_message(self):
        conn = MagicMock()

        with patch.object(chat_service, "get_recent_messages", return_value=[{"role": "assistant", "content": "hello"}]) as mock_recent, \
             patch.object(chat_service, "get_summary_for_prompt", return_value="summary") as mock_summary:
            result = chat_service._load_recent_messages_and_summary(
                conn,
                user_id=1,
                character_id="char_1",
                clean_text="hi",
                persist_user_message=False,
            )

        assert result == (
            [
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "hi"},
            ],
            "summary",
        )
        mock_recent.assert_called_once_with(conn, 1, "char_1")
        mock_summary.assert_called_once_with(conn, 1, "char_1")

    def test_load_recent_messages_and_summary_keeps_persisted_history_unchanged(self):
        conn = MagicMock()

        with patch.object(chat_service, "get_recent_messages", return_value=[{"role": "user", "content": "saved"}]) as mock_recent, \
             patch.object(chat_service, "get_summary_for_prompt", return_value="summary") as mock_summary:
            result = chat_service._load_recent_messages_and_summary(
                conn,
                user_id=1,
                character_id="char_1",
                clean_text="saved",
                persist_user_message=True,
            )

        assert result == ([{"role": "user", "content": "saved"}], "summary")
        mock_recent.assert_called_once_with(conn, 1, "char_1")
        mock_summary.assert_called_once_with(conn, 1, "char_1")

    def test_project_message_rows_builds_message_projections(self):
        rows = [
            {"id": "1", "role": "user", "content": "hi"},
            {"id": "2", "role": "assistant", "content": "hello"},
        ]

        result = chat_service._project_message_rows(rows)

        assert result == [
            {"id": "1", "role": "user", "content": "hi"},
            {"id": "2", "role": "assistant", "content": "hello"},
        ]

    def test_find_target_message_index_returns_position_when_found(self):
        chronological = [
            {"id": "1", "role": "user", "content": "hi"},
            {"id": "2", "role": "assistant", "content": "hello"},
        ]

        result = chat_service._find_target_message_index(chronological, "2")

        assert result == 1

    def test_find_target_message_index_returns_none_when_missing(self):
        chronological = [
            {"id": "1", "role": "user", "content": "hi"},
        ]

        result = chat_service._find_target_message_index(chronological, "9")

        assert result is None

    def test_fallback_recent_messages_returns_first_fallback_message(self):
        result = chat_service._fallback_recent_messages(
            [
                {"role": "user", "content": "fallback-1"},
                {"role": "assistant", "content": "fallback-2"},
            ]
        )

        assert result == [{"role": "user", "content": "fallback-1"}]

    def test_fallback_recent_messages_returns_empty_list_when_missing(self):
        result = chat_service._fallback_recent_messages([])

        assert result == []

    def test_resolve_recent_messages_before_target_reuses_selection_helpers(self):
        chronological = [
            {"id": "1", "role": "user", "content": "hi"},
            {"id": "2", "role": "assistant", "content": "hello"},
        ]
        fallback_recent = [{"role": "user", "content": "fallback"}]

        with patch.object(chat_service, "_messages_before_target", return_value=[{"role": "assistant", "content": "hello"}]) as mock_before, \
             patch.object(chat_service, "_trim_recent_messages_tail", return_value=[{"role": "user", "content": "fallback"}]) as mock_trim:
            result = chat_service._resolve_recent_messages_before_target(
                chronological,
                target_message_id="2",
                fallback_recent=fallback_recent,
            )

        assert result == [{"role": "user", "content": "fallback"}]
        mock_before.assert_called_once_with(chronological, "2", fallback_recent)
        mock_trim.assert_called_once_with([{"role": "assistant", "content": "hello"}], fallback_recent)

    def test_messages_before_target_returns_prefix_when_target_found(self):
        chronological = [
            {"id": "1", "role": "user", "content": "hi"},
            {"id": "2", "role": "assistant", "content": "hello"},
            {"id": "3", "role": "user", "content": "again"},
        ]
        fallback_recent = [{"role": "user", "content": "fallback"}]

        result = chat_service._messages_before_target(chronological, "3", fallback_recent)

        assert result == [
            {"id": "1", "role": "user", "content": "hi"},
            {"id": "2", "role": "assistant", "content": "hello"},
        ]

    def test_trim_recent_messages_tail_drops_trailing_assistant_messages(self):
        result = chat_service._trim_recent_messages_tail(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "assistant", "content": "again"},
            ],
            [{"role": "user", "content": "fallback"}],
        )

        assert result == [
            {"role": "user", "content": "hi"},
        ]

    def test_trim_recent_messages_tail_falls_back_when_all_messages_removed(self):
        result = chat_service._trim_recent_messages_tail(
            [
                {"role": "assistant", "content": "hello"},
            ],
            [{"role": "user", "content": "fallback"}],
        )

        assert result == [{"role": "user", "content": "fallback"}]

    def test_stream_with_postprocess_reuses_shared_stream_shell(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        postprocess_calls = []

        def fake_consume(*args, **kwargs):
            yield 'event: chunk\ndata: {"text": "hi"}\n\n'
            return ("最终回复", {"mood": "warm"})

        def fake_postprocess(final_text, delta):
            postprocess_calls.append((final_text, delta))
            yield 'event: done\ndata: {"reply": "最终回复"}\n\n'

        with patch.object(chat, "_consume_stream_result", side_effect=fake_consume) as mock_consume, \
             patch.object(chat, "_log_failed_chat_request") as mock_failure:
            runner = partial(
                chat._stream_with_postprocess,
                consume_stream_result=chat._consume_stream_result,
            )
            result = list(runner(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/stream",
                estimate={"chars": 10, "tokens": 2},
                stream_error_message="网络波动，请稍后再试",
                postprocess=fake_postprocess,
            ))

        assert result == [
            'event: chunk\ndata: {"text": "hi"}\n\n',
            'event: done\ndata: {"reply": "最终回复"}\n\n',
        ]
        assert postprocess_calls == [("最终回复", {"mood": "warm"})]
        mock_consume.assert_called_once_with(
            stream_messages=[{"role": "user", "content": "hi"}],
            ai_config={"provider": "test"},
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            estimate={"chars": 10, "tokens": 2},
            stream_error_message="网络波动，请稍后再试",
        )

    def test_build_streaming_chat_response_wraps_shared_stream_shell(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        def fake_postprocess(final_text, delta):
            if False:
                yield None

        with patch.object(chat, "_build_streaming_chat_response_impl", return_value={"events": ["event: chunk\n\n"]}) as mock_impl:
            result = chat._build_streaming_chat_response(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/stream",
                estimate={"chars": 10, "tokens": 2},
                stream_error_message="网络波动，请稍后再试",
                postprocess=fake_postprocess,
                headers={"Cache-Control": "no-cache"},
            )

        assert result == {"events": ["event: chunk\n\n"]}
        mock_impl.assert_called_once_with(
            stream_messages=[{"role": "user", "content": "hi"}],
            ai_config={"provider": "test"},
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            estimate={"chars": 10, "tokens": 2},
            stream_error_message="网络波动，请稍后再试",
            postprocess=fake_postprocess,
            deps={
                "build_sse_response": chat._build_sse_response,
                "stream_with_postprocess": ANY,
            },
            headers={"Cache-Control": "no-cache"},
        )

    def test_default_stream_headers_and_error_message(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        assert chat._default_stream_headers() == {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        assert chat._default_stream_error_message() == "网络波动，请稍后再试"



    def test_build_default_stream_response_uses_default_error_and_headers(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_postprocess = object()
        with patch.object(chat, "_build_streaming_chat_response", return_value="response") as mock_response:
            result = chat._build_default_stream_response(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/stream",
                estimate={"chars": 10, "tokens": 2},
                postprocess=fake_postprocess,
            )

        assert result == "response"
        mock_response.assert_called_once_with(
            stream_messages=[{"role": "user", "content": "hi"}],
            ai_config={"provider": "test"},
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            estimate={"chars": 10, "tokens": 2},
            stream_error_message="网络波动，请稍后再试",
            postprocess=fake_postprocess,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def test_compose_stream_response_builds_postprocess_then_response(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        build_postprocess = MagicMock(return_value="postprocess")
        build_response = MagicMock(return_value="response")

        result = chat._compose_stream_response(
            build_postprocess=build_postprocess,
            postprocess_kwargs={"guest_ip": "127.0.0.1"},
            build_response=build_response,
            response_kwargs={"endpoint": "/api/chat/stream"},
        )

        assert result == "response"
        build_postprocess.assert_called_once_with(guest_ip="127.0.0.1")
        build_response.assert_called_once_with(
            endpoint="/api/chat/stream",
            postprocess="postprocess",
        )

    def test_build_retry_stream_postprocess_binds_retry_handler(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_bind_stream_postprocess", return_value="postprocess") as mock_bind, \
             patch.object(chat, "_build_retry_postprocess_deps", return_value={"dep": 1}) as mock_deps:
            result = chat._build_retry_stream_postprocess(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                message_id="msg_1",
                endpoint="/api/chat/regenerate",
                estimate={"chars": 10, "tokens": 2},
                is_append=False,
                base_reply="",
                operation="regenerate",
            )

        assert result == "postprocess"
        mock_deps.assert_called_once_with()
        mock_bind.assert_called_once_with(
            chat._postprocess_regenerate_or_continue_result_impl,
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            message_id="msg_1",
            endpoint="/api/chat/regenerate",
            estimate={"chars": 10, "tokens": 2},
            is_append=False,
            base_reply="",
            operation="regenerate",
            deps={"dep": 1},
        )

    def test_build_retry_stream_response_delegates_to_default_helper(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_postprocess = object()
        with patch.object(chat, "_build_default_stream_response", return_value="response") as mock_response:
            result = chat._build_retry_stream_response(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/regenerate",
                estimate={"chars": 10, "tokens": 2},
                postprocess=fake_postprocess,
            )

        assert result == "response"
        mock_response.assert_called_once_with(
            stream_messages=[{"role": "user", "content": "hi"}],
            ai_config={"provider": "test"},
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/regenerate",
            estimate={"chars": 10, "tokens": 2},
            postprocess=fake_postprocess,
        )

    def test_build_main_stream_postprocess_binds_main_handler(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_bind_stream_postprocess", return_value="postprocess") as mock_bind, \
             patch.object(chat, "_build_main_postprocess_deps", return_value={"dep": 2}) as mock_deps:
            result = chat._build_main_stream_postprocess(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                estimate={"chars": 10, "tokens": 2},
                user_message="hi",
                character={"id": "char_1"},
            )

        assert result == "postprocess"
        mock_deps.assert_called_once_with()
        mock_bind.assert_called_once_with(
            chat._postprocess_main_stream_result_impl,
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            estimate={"chars": 10, "tokens": 2},
            user_message="hi",
            character={"id": "char_1"},
            deps={"dep": 2},
        )

    def test_build_main_stream_response_delegates_to_default_helper(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_postprocess = object()
        with patch.object(chat, "_build_default_stream_response", return_value="response") as mock_response:
            result = chat._build_main_stream_response(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                estimate={"chars": 10, "tokens": 2},
                postprocess=fake_postprocess,
            )

        assert result == "response"
        mock_response.assert_called_once_with(
            stream_messages=[{"role": "user", "content": "hi"}],
            ai_config={"provider": "test"},
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            estimate={"chars": 10, "tokens": 2},
            postprocess=fake_postprocess,
        )

    def test_build_guest_stream_postprocess_binds_guest_handler(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_bind_stream_postprocess", return_value="postprocess") as mock_bind:
            result = chat._build_guest_stream_postprocess(
                guest_ip="127.0.0.1",
                character_id="char_1",
                estimate={"chars": 10, "tokens": 2},
            )

        assert result == "postprocess"
        mock_bind.assert_called_once_with(
            chat._postprocess_guest_stream_result,
            guest_ip="127.0.0.1",
            character_id="char_1",
            estimate={"chars": 10, "tokens": 2},
        )

    def test_build_guest_stream_response_delegates_to_default_helper(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_postprocess = object()
        with patch.object(chat, "_build_default_stream_response", return_value="response") as mock_response:
            result = chat._build_guest_stream_response(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                guest_ip="127.0.0.1",
                character_id="char_1",
                estimate={"chars": 10, "tokens": 2},
                postprocess=fake_postprocess,
            )

        assert result == "response"
        mock_response.assert_called_once_with(
            stream_messages=[{"role": "user", "content": "hi"}],
            ai_config={"provider": "test"},
            user_id=None,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/guest-stream",
            estimate={"chars": 10, "tokens": 2},
            postprocess=fake_postprocess,
        )

    def test_message_projection_helpers_build_expected_shapes(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        assert chat._message_projection("user", "hi") == chat_service._message_projection("user", "hi")
        assert chat_service._message_with_id_projection(123, "assistant", "hello") == {
            "id": "123",
            "role": "assistant",
            "content": "hello",
        }
        assert chat_service._message_projection("assistant", "reply") == {
            "role": "assistant",
            "content": "reply",
        }

    def test_build_stream_done_payload_handles_optional_fields(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        payload = chat._build_stream_done_payload(
            reply="hello",
            fallback=False,
            character_state={"mood": "warm"},
            message_id="msg_1",
            operation="continue",
            appended_text=" world",
            guest=True,
            summary_enabled=True,
        )

        assert payload == {
            "reply": "hello",
            "fallback": False,
            "character_state": {"mood": "warm"},
            "message_id": "msg_1",
            "operation": "continue",
            "appended_text": " world",
            "guest": True,
            "summary_enabled": True,
        }

    def test_build_main_postprocess_deps_reuses_shared_builder(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_build_stream_done_payload", return_value={"reply": "hello"}) as mock_build:
            deps = chat._build_main_postprocess_deps()
            result = deps["build_done_payload_from_persisted_result"](
                reply="hello",
                persisted_result={
                    "character_state": {"mood": "warm"},
                    "message_id": "msg_1",
                },
            )

        assert result == {"reply": "hello"}
        mock_build.assert_called_once_with(
            reply="hello",
            fallback=False,
            character_state={"mood": "warm"},
            message_id="msg_1",
            summary_enabled=True,
        )

    def test_persist_stream_result_delegates_to_service_impl(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_persist_stream_result_impl", return_value={"message_id": "m1"}) as mock_impl:
            result = chat._persist_stream_result(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                final_reply="hello",
                estimate={"chars": 10, "tokens": 2},
                delta={"mood": "warm"},
                user_message="hi",
            )

        assert result == {"message_id": "m1"}
        mock_impl.assert_called_once_with(
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            final_reply="hello",
            estimate={"chars": 10, "tokens": 2},
            delta={"mood": "warm"},
            user_message="hi",
            deps=chat._build_persist_stream_deps(),
        )

    def test_build_main_postprocess_deps_delegates_to_service_impl(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_build_stream_done_payload_from_persisted_result_impl", return_value={"reply": "ok"}) as mock_impl:
            deps = chat._build_main_postprocess_deps()
            result = deps["build_done_payload_from_persisted_result"](
                reply="hello",
                persisted_result={"character_state": {"mood": "warm"}, "message_id": "msg_1"},
            )

        assert result == {"reply": "ok"}
        mock_impl.assert_called_once_with(
            reply="hello",
            persisted_result={"character_state": {"mood": "warm"}, "message_id": "msg_1"},
            build_stream_done_payload=chat._build_stream_done_payload,
        )

    def test_log_successful_chat_request_uses_estimate_and_reply_text(self):
        fake_conn = MagicMock()

        with patch.object(chat_service, "estimate_text_tokens", return_value=9) as mock_estimate, \
             patch.object(chat_service, "log_ai_request") as mock_log:
            chat_service._log_successful_chat_request(
                fake_conn,
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/stream",
                estimate={"chars": 12, "tokens": 3},
                reply_text="你好呀",
            )

        mock_estimate.assert_called_once_with("你好呀")
        mock_log.assert_called_once_with(
            fake_conn,
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            request_chars=12,
            estimated_input_tokens=3,
            estimated_output_tokens=9,
            total_estimated_tokens=12,
            used_fallback=False,
            status="success",
            commit=False,
        )

    def test_prepare_ai_budget_builds_config_estimate_and_enforces_limit(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        messages = [{"role": "user", "content": "hi"}]

        with patch.object(chat_service, "get_ai_config", return_value={"provider": "test"}) as mock_config, \
             patch.object(chat_service, "estimate_messages_tokens", return_value={"chars": 20, "tokens": 5}) as mock_estimate, \
             patch.object(chat_service, "enforce_daily_budget") as mock_budget:
            result = chat_service._prepare_ai_budget(
                fake_conn,
                stream_messages=messages,
                model_profile="vip",
                token_limit=200,
                token_limit_detail="额度已用完",
                user_id=1,
            )

        assert result == {"ai_config": {"provider": "test"}, "estimate": {"chars": 20, "tokens": 5}}
        mock_config.assert_called_once()
        mock_estimate.assert_called_once_with(messages)
        mock_budget.assert_called_once_with(
            fake_conn,
            user_id=1,
            guest_ip="",
            planned_tokens=5 + chat_service.AI_CHAT_MAX_OUTPUT_TOKENS,
            token_limit=200,
            token_limit_detail="额度已用完",
        )

    def test_build_prompt_context_payload_uses_consistent_keys(self):
        result = chat_service._build_prompt_context_payload(
            current_content="旧回复",
            character={"id": "char_1"},
            memory_summary="summary",
            prompt_messages=[{"role": "user", "content": "hi"}],
            related_assets=["asset_1"],
        )

        assert result == {
            "current_content": "旧回复",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "user", "content": "hi"}],
            "related_assets": ["asset_1"],
        }

    def test_build_stream_prepare_result_uses_consistent_keys(self):
        result = chat_service._build_stream_prepare_result(
            guest_ip="127.0.0.1",
            stream_payload={
                "stream_messages": [{"role": "user", "content": "hi"}],
                "ai_config": {"provider": "test"},
                "estimate": {"chars": 2, "tokens": 1},
            },
            character={"id": "char_1"},
            clean_text="hi",
            recent_messages=[{"role": "user", "content": "hi"}],
            memory_summary="summary",
            related_assets=["asset_1"],
            character_id="char_1",
            current_content="旧回复",
        )

        assert result == {
            "guest_ip": "127.0.0.1",
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "test"},
            "estimate": {"chars": 2, "tokens": 1},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "character_id": "char_1",
            "current_content": "旧回复",
        }

    def test_read_main_stream_prepared_extracts_route_inputs(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        result = chat._read_main_stream_prepared({
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "stream_messages": [{"role": "user", "content": "hi"}],
            "estimate": {"chars": 2, "tokens": 1},
        })

        assert result == {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "stream_messages": [{"role": "user", "content": "hi"}],
            "estimate": {"chars": 2, "tokens": 1},
        }

    def test_read_guest_stream_prepared_extracts_route_inputs(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        result = chat._read_guest_stream_prepared({
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "guest"},
            "stream_messages": [{"role": "user", "content": "hi"}],
            "estimate": {"chars": 2, "tokens": 1},
        })

        assert result == {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "guest"},
            "stream_messages": [{"role": "user", "content": "hi"}],
            "estimate": {"chars": 2, "tokens": 1},
        }

    def test_read_retry_stream_prepared_includes_optional_current_content(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        result = chat._read_retry_stream_prepared({
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "current_content": "旧回复",
            "stream_messages": [{"role": "user", "content": "继续"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 2, "tokens": 1},
        })

        assert result == {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "current_content": "旧回复",
            "stream_messages": [{"role": "user", "content": "继续"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 2, "tokens": 1},
        }

    def test_read_chat_send_prepared_extracts_transaction_inputs(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        prepared = {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert chat._read_chat_send_prepared(prepared) == {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "estimate": {"chars": 2, "tokens": 1},
        }

    def test_read_stream_state_with_conn_delegates_prepare_then_reader(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_prepare_stream_request_with_conn", return_value="prepared") as mock_prepare:
            reader = MagicMock(return_value={"guest_ip": "127.0.0.1"})

            result = chat._read_stream_state_with_conn(
                chat._prepare_user_chat_request,
                reader,
                user="user",
                payload="payload",
            )

        assert result == {"guest_ip": "127.0.0.1"}
        mock_prepare.assert_called_once_with(
            chat._prepare_user_chat_request,
            user="user",
            payload="payload",
        )
        reader.assert_called_once_with("prepared")

    def test_build_main_route_response_kwargs_reuse_common_mapping(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        stream_state = {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "vip"},
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert chat._build_main_route_response_kwargs(
            stream_state=stream_state,
            user_id=1,
            character_id="char_1",
        ) == chat._build_common_stream_response_kwargs(
            stream_state=stream_state,
            character_id="char_1",
            user_id=1,
        )

    def test_build_guest_route_response_kwargs_reuse_common_mapping(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        stream_state = {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "guest"},
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert chat._build_guest_route_response_kwargs(
            stream_state=stream_state,
            character_id="char_1",
        ) == chat._build_common_stream_response_kwargs(
            stream_state=stream_state,
            character_id="char_1",
        )

    def test_build_main_route_response_builder_returns_partial_mapping(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        builder = chat._build_main_route_response_builder(user_id=1, character_id="char_1")
        stream_state = {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "vip"},
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert builder(stream_state=stream_state) == chat._build_main_route_response_kwargs(
            stream_state=stream_state,
            user_id=1,
            character_id="char_1",
        )

    def test_build_guest_route_postprocess_builder_returns_partial_mapping(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        builder = chat._build_guest_route_postprocess_builder(character_id="char_1")
        stream_state = {
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert builder(stream_state=stream_state) == chat._build_guest_route_postprocess_kwargs(
            stream_state=stream_state,
            character_id="char_1",
        )

    def test_build_guest_route_response_builder_returns_partial_mapping(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        builder = chat._build_guest_route_response_builder(character_id="char_1")
        stream_state = {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "guest"},
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert builder(stream_state=stream_state) == chat._build_guest_route_response_kwargs(
            stream_state=stream_state,
            character_id="char_1",
        )

    def test_build_main_route_postprocess_kwargs_extracts_main_fields(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        stream_state = {
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
            "clean_text": "hi",
            "character": {"id": "char_1"},
        }

        assert chat._build_main_route_postprocess_kwargs(
            stream_state=stream_state,
            user_id=1,
            character_id="char_1",
        ) == {
            "user_id": 1,
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 2, "tokens": 1},
            "user_message": "hi",
            "character": {"id": "char_1"},
        }

    def test_build_guest_route_postprocess_kwargs_extracts_guest_fields(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        stream_state = {
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert chat._build_guest_route_postprocess_kwargs(
            stream_state=stream_state,
            character_id="char_1",
        ) == {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 2, "tokens": 1},
        }

    def test_build_common_stream_response_kwargs_supports_optional_user_id(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        stream_state = {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "vip"},
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 2, "tokens": 1},
        }

        assert chat._build_common_stream_response_kwargs(
            stream_state=stream_state,
            character_id="char_1",
            user_id=1,
        ) == {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "vip"},
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 2, "tokens": 1},
            "user_id": 1,
        }

        assert chat._build_common_stream_response_kwargs(
            stream_state=stream_state,
            character_id="char_1",
        ) == {
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "vip"},
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 2, "tokens": 1},
        }

    def test_build_retry_stream_event_kwargs_reuses_stream_state_and_optional_base_reply(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        stream_state = {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "stream_messages": [{"role": "user", "content": "继续"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 2, "tokens": 1},
            "current_content": "旧回复",
        }

        assert chat._build_retry_stream_event_kwargs(
            stream_state=stream_state,
            user_id=1,
            message_id="msg_1",
            endpoint="/api/chat/continue",
            is_append=True,
            operation="continue",
        ) == {
            "user_id": 1,
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "message_id": "msg_1",
            "endpoint": "/api/chat/continue",
            "estimate": {"chars": 2, "tokens": 1},
            "ai_config": {"provider": "vip"},
            "stream_messages": [{"role": "user", "content": "继续"}],
            "is_append": True,
            "base_reply": "旧回复",
            "operation": "continue",
        }

    def test_build_composed_route_response_reads_state_then_composes_stream_response(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        prepared = {"guest_ip": "127.0.0.1", "estimate": {"chars": 2, "tokens": 1}}

        with patch.object(chat, "_read_stream_state_with_conn", return_value=prepared) as mock_state, \
             patch.object(chat, "_compose_stream_response", return_value="response") as mock_compose:
            result = chat._build_composed_route_response(
                prepare_fn="prepare_fn",
                read_fn="read_fn",
                prepare_kwargs={"payload": "payload"},
                build_postprocess="postprocess_builder",
                postprocess_kwargs_builder=lambda stream_state: {"guest_ip": stream_state["guest_ip"]},
                build_response="response_builder",
                response_kwargs_builder=lambda stream_state: {"estimate": stream_state["estimate"]},
            )

        assert result == "response"
        mock_state.assert_called_once_with("prepare_fn", "read_fn", payload="payload")
        mock_compose.assert_called_once_with(
            build_postprocess="postprocess_builder",
            postprocess_kwargs={"guest_ip": "127.0.0.1"},
            build_response="response_builder",
            response_kwargs={"estimate": {"chars": 2, "tokens": 1}},
        )

    def test_build_retry_route_response_delegates_regenerate_without_base_reply(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        user = SimpleNamespace(id=1)
        request = MagicMock()
        prepared = {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "stream_messages": [{"role": "user", "content": "hi"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 2, "tokens": 1},
        }

        with patch.object(chat, "_read_stream_state_with_conn", return_value=prepared) as mock_state, \
             patch.object(chat, "_stream_regenerate_or_continue_events", return_value="response") as mock_stream, \
             patch.object(chat, "get_request_client_ip", return_value="127.0.0.1") as mock_ip:
            result = chat._build_retry_route_response(
                user=user,
                request=request,
                message_id="msg_1",
                operation="regenerate",
                endpoint="/api/chat/regenerate",
                is_append=False,
            )

        assert result == "response"
        mock_ip.assert_called_once_with(request)
        mock_state.assert_called_once_with(
            chat._prepare_regenerate_or_continue_request,
            chat._read_retry_stream_prepared,
            user=user,
            message_id="msg_1",
            guest_ip="127.0.0.1",
            operation="regenerate",
        )
        mock_stream.assert_called_once_with(
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            message_id="msg_1",
            endpoint="/api/chat/regenerate",
            estimate={"chars": 2, "tokens": 1},
            ai_config={"provider": "vip"},
            stream_messages=[{"role": "user", "content": "hi"}],
            is_append=False,
            base_reply="",
            operation="regenerate",
        )

    def test_build_retry_route_response_delegates_continue_with_base_reply(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        user = SimpleNamespace(id=1)
        request = MagicMock()
        prepared = {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "current_content": "旧回复",
            "stream_messages": [{"role": "user", "content": "继续"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 2, "tokens": 1},
        }

        with patch.object(chat, "_read_stream_state_with_conn", return_value=prepared) as mock_state, \
             patch.object(chat, "_stream_regenerate_or_continue_events", return_value="response") as mock_stream, \
             patch.object(chat, "get_request_client_ip", return_value="127.0.0.1") as mock_ip:
            result = chat._build_retry_route_response(
                user=user,
                request=request,
                message_id="msg_2",
                operation="continue",
                endpoint="/api/chat/continue",
                is_append=True,
            )

        assert result == "response"
        mock_ip.assert_called_once_with(request)
        mock_state.assert_called_once_with(
            chat._prepare_regenerate_or_continue_request,
            chat._read_retry_stream_prepared,
            user=user,
            message_id="msg_2",
            guest_ip="127.0.0.1",
            operation="continue",
        )
        mock_stream.assert_called_once_with(
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            message_id="msg_2",
            endpoint="/api/chat/continue",
            estimate={"chars": 2, "tokens": 1},
            ai_config={"provider": "vip"},
            stream_messages=[{"role": "user", "content": "继续"}],
            is_append=True,
            base_reply="旧回复",
            operation="continue",
        )

    def test_build_retry_route_with_rate_limit_enforces_limit_then_delegates(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        user = SimpleNamespace(id=1)
        request = MagicMock()

        with patch.object(chat, "_enforce_user_chat_rate_limit") as mock_rate_limit, \
             patch.object(chat, "_build_retry_route_response", return_value="response") as mock_retry:
            result = chat._build_retry_route_with_rate_limit(
                user=user,
                request=request,
                message_id="msg_1",
                operation="regenerate",
                endpoint="/api/chat/regenerate",
                is_append=False,
            )

        assert result == "response"
        mock_rate_limit.assert_called_once_with(1, detail="操作过于频繁")
        mock_retry.assert_called_once_with(
            user=user,
            request=request,
            message_id="msg_1",
            operation="regenerate",
            endpoint="/api/chat/regenerate",
            is_append=False,
        )

    def test_chat_regenerate_delegates_to_retry_route_with_rate_limit(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        payload = MagicMock(message_id="msg_1")
        request = MagicMock()
        user = MagicMock(id=1)

        with patch.object(chat, "_build_retry_route_with_rate_limit", return_value="response") as mock_route:
            result = chat.chat_regenerate(payload=payload, request=request, user=user)

        assert result == "response"
        mock_route.assert_called_once_with(
            user=user,
            request=request,
            message_id="msg_1",
            operation="regenerate",
            endpoint="/api/chat/regenerate",
            is_append=False,
        )

    def test_chat_continue_delegates_to_retry_route_with_rate_limit(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        payload = MagicMock(message_id="msg_2")
        request = MagicMock()
        user = MagicMock(id=1)

        with patch.object(chat, "_build_retry_route_with_rate_limit", return_value="response") as mock_route:
            result = chat.chat_continue(payload=payload, request=request, user=user)

        assert result == "response"
        mock_route.assert_called_once_with(
            user=user,
            request=request,
            message_id="msg_2",
            operation="continue",
            endpoint="/api/chat/continue",
            is_append=True,
        )

    def test_build_main_route_response_delegates_stream_preparation_and_response(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        user = SimpleNamespace(id=1)
        payload = SimpleNamespace(character_id="char_1")
        request = MagicMock()
        prepared = {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "stream_messages": [{"role": "user", "content": "hi"}],
            "estimate": {"chars": 2, "tokens": 1},
        }
        fake_postprocess = object()

        with patch.object(chat, "_build_composed_route_response", return_value="response") as mock_route, \
             patch.object(chat, "get_request_client_ip", return_value="127.0.0.1") as mock_ip:
            result = chat._build_main_route_response(
                user=user,
                payload=payload,
                request=request,
            )

        assert result == "response"
        mock_ip.assert_called_once_with(request)
        mock_route.assert_called_once()
        kwargs = mock_route.call_args.kwargs
        assert kwargs["prepare_fn"] is chat._prepare_user_chat_request
        assert kwargs["read_fn"] is chat._read_main_stream_prepared
        assert kwargs["prepare_kwargs"] == {
            "user": user,
            "payload": payload,
            "guest_ip": "127.0.0.1",
        }
        assert kwargs["build_postprocess"] is chat._build_main_stream_postprocess
        assert kwargs["build_response"] is chat._build_main_stream_response
        assert kwargs["postprocess_kwargs_builder"](prepared) == chat._build_main_route_postprocess_kwargs(
            stream_state=prepared,
            user_id=1,
            character_id="char_1",
        )
        assert kwargs["response_kwargs_builder"](prepared) == chat._build_main_route_response_kwargs(
            stream_state=prepared,
            user_id=1,
            character_id="char_1",
        )

    def test_build_guest_route_response_delegates_stream_preparation_and_response(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        payload = SimpleNamespace(character_id="char_1")
        request = MagicMock()
        prepared = {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "guest"},
            "stream_messages": [{"role": "user", "content": "hi"}],
            "estimate": {"chars": 2, "tokens": 1},
        }
        fake_postprocess = object()

        with patch.object(chat, "_build_composed_route_response", return_value="response") as mock_route:
            result = chat._build_guest_route_response(
                payload=payload,
                request=request,
            )

        assert result == "response"
        mock_route.assert_called_once()
        kwargs = mock_route.call_args.kwargs
        assert kwargs["prepare_fn"] is chat._prepare_guest_stream_request
        assert kwargs["read_fn"] is chat._read_guest_stream_prepared
        assert kwargs["prepare_kwargs"] == {
            "payload": payload,
            "request": request,
        }
        assert kwargs["build_postprocess"] is chat._build_guest_stream_postprocess
        assert kwargs["build_response"] is chat._build_guest_stream_response
        assert kwargs["postprocess_kwargs_builder"](prepared) == chat._build_guest_route_postprocess_kwargs(
            stream_state=prepared,
            character_id="char_1",
        )
        assert kwargs["response_kwargs_builder"](prepared) == chat._build_guest_route_response_kwargs(
            stream_state=prepared,
            character_id="char_1",
        )

    def test_prepare_stream_request_with_conn_closes_connection(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()

        with patch.object(chat, "get_conn", return_value=fake_conn) as mock_get_conn:
            result = chat._prepare_stream_request_with_conn(
                lambda conn, **kwargs: {"conn": conn, "payload": kwargs["payload"]},
                payload="hello",
            )

        assert result == {"conn": fake_conn, "payload": "hello"}
        mock_get_conn.assert_called_once_with()
        fake_conn.close.assert_called_once_with()

    def test_prepare_guest_stream_request_reuses_shared_budget_helper(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        payload = MagicMock()
        payload.character_id = "char_1"
        payload.message = "  hi  "
        payload.guest_history = []

        with patch.object(chat, "get_request_client_ip", return_value="127.0.0.1") as mock_ip, \
             patch.object(chat, "get_plan_policy", return_value={"model_profile": "guest", "token_limit": 99}) as mock_policy, \
             patch.object(chat, "get_character_or_404", return_value={"id": "char_1"}) as mock_character, \
             patch.object(chat, "_build_guest_stream_messages", return_value=("hi", [{"role": "user", "content": "hi"}])) as mock_messages, \
             patch.object(chat, "_prepare_ai_budget", return_value={"ai_config": {"provider": "guest"}, "estimate": {"chars": 2, "tokens": 1}}) as mock_budget:
            result = chat._prepare_guest_stream_request(
                fake_conn,
                payload=payload,
                request=MagicMock(),
            )

        assert result == {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "guest"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "stream_messages": [{"role": "user", "content": "hi"}],
            "estimate": {"chars": 2, "tokens": 1},
        }
        mock_ip.assert_called_once()
        mock_policy.assert_called_once_with(chat.GUEST_PLAN)
        mock_character.assert_called_once_with(fake_conn, "char_1", viewer_plan=chat.GUEST_PLAN)
        mock_messages.assert_called_once_with({"id": "char_1"}, "  hi  ", [])
        mock_budget.assert_called_once_with(
            fake_conn,
            stream_messages=[{"role": "user", "content": "hi"}],
            model_profile="guest",
            token_limit=99,
            token_limit_detail="今日游客体验额度已用完，登录后可继续聊天",
            guest_ip="127.0.0.1",
        )


    def test_prepare_user_chat_request_returns_stream_messages_key(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, effective_plan="vip")
        payload = MagicMock(character_id="char_1", message=" hi ")

        with patch.object(chat_service, "prepare_chat_context", return_value=({"id": "char_1"}, "hi", [{"role": "user", "content": "hi"}], "summary")) as mock_prepare, \
             patch.object(chat_service, "get_linked_assets", return_value=["asset_1"]) as mock_assets, \
             patch.object(chat_service, "_build_user_stream_messages_and_budget", return_value={"stream_messages": [{"role": "system", "content": "prompt"}], "ai_config": {"provider": "vip"}, "estimate": {"chars": 10, "tokens": 2}}) as mock_stream_payload:
            result = chat_service._prepare_user_chat_request(
                fake_conn,
                user=fake_user,
                payload=payload,
                guest_ip="127.0.0.1",
            )

        assert result == {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "stream_messages": [{"role": "system", "content": "prompt"}],
            "estimate": {"chars": 10, "tokens": 2},
        }
        mock_prepare.assert_called_once_with(
            fake_conn,
            1,
            "char_1",
            " hi ",
            persist_user_message=False,
            viewer_plan="vip",
            commit=False,
        )
        mock_assets.assert_called_once_with(fake_conn, "char_1")
        mock_stream_payload.assert_called_once_with(
            fake_conn,
            user=fake_user,
            character_id="char_1",
            character={"id": "char_1"},
            prompt_messages=[{"role": "user", "content": "hi"}],
            memory_summary="summary",
            related_assets=["asset_1"],
        )

    def test_build_user_stream_messages_and_budget_reuses_shared_helpers(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, nickname="Luna")

        with patch.object(chat_service, "get_character_state", return_value={"mood": "warm"}) as mock_state, \
             patch.object(chat_service, "build_layered_chat_messages", return_value=[{"role": "system", "content": "prompt"}]) as mock_build, \
             patch.object(chat_service, "_prepare_user_ai_budget", return_value={"ai_config": {"provider": "vip"}, "estimate": {"chars": 10, "tokens": 2}}) as mock_budget:
            result = chat_service._build_user_stream_messages_and_budget(
                fake_conn,
                user=fake_user,
                character_id="char_1",
                character={"id": "char_1"},
                prompt_messages=[{"role": "user", "content": "hi"}],
                memory_summary="summary",
                related_assets=["asset_1"],
            )

        assert result == {
            "stream_messages": [{"role": "system", "content": "prompt"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 10, "tokens": 2},
        }
        mock_state.assert_called_once_with(fake_conn, 1, "char_1")
        mock_build.assert_called_once_with(
            {"id": "char_1"},
            [{"role": "user", "content": "hi"}],
            "summary",
            related_assets=["asset_1"],
            user_name="Luna",
            character_state={"mood": "warm"},
        )
        mock_budget.assert_called_once_with(
            fake_conn,
            user=fake_user,
            stream_messages=[{"role": "system", "content": "prompt"}],
        )

    def test_enforce_user_chat_rate_limit_reuses_shared_policy(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "enforce_rate_limit") as mock_rate_limit:
            chat._enforce_user_chat_rate_limit(42, detail="聊天请求过于频繁")

        mock_rate_limit.assert_called_once_with(
            "chat_user",
            "42",
            limit=chat.CHAT_RATE_LIMIT_COUNT,
            window_seconds=chat.CHAT_RATE_LIMIT_WINDOW_SECONDS,
            detail="聊天请求过于频繁",
        )

    def test_build_chat_send_route_response_delegates_prepare_and_transaction(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        request = MagicMock()
        prepared = {"stream_messages": [{"role": "system", "content": "prompt"}]}

        with patch.object(chat, "get_conn", return_value=fake_conn) as mock_get_conn, \
             patch.object(chat, "get_request_client_ip", return_value="127.0.0.1") as mock_ip, \
             patch.object(chat, "_prepare_user_chat_request", return_value=prepared) as mock_prepare, \
             patch.object(chat, "_run_chat_send_transaction", return_value={"reply": "hello"}) as mock_run:
            result = chat._build_chat_send_route_response(
                user=fake_user,
                payload=payload,
                request=request,
            )

        assert result == {"reply": "hello"}
        mock_get_conn.assert_called_once_with()
        mock_ip.assert_called_once_with(request)
        mock_prepare.assert_called_once_with(
            fake_conn,
            user=fake_user,
            payload=payload,
            guest_ip="127.0.0.1",
        )
        mock_run.assert_called_once_with(
            fake_conn,
            user=fake_user,
            payload=payload,
            prepared=prepared,
        )
        fake_conn.close.assert_called_once_with()

    def test_build_chat_send_route_response_closes_connection_when_prepare_fails(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        request = MagicMock()

        with patch.object(chat, "get_conn", return_value=fake_conn), \
             patch.object(chat, "get_request_client_ip", return_value="127.0.0.1"), \
             patch.object(chat, "_prepare_user_chat_request", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                chat._build_chat_send_route_response(
                    user=fake_user,
                    payload=payload,
                    request=request,
                )

        fake_conn.close.assert_called_once_with()

    def test_chat_send_delegates_to_route_helper_after_rate_limit(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        payload = MagicMock(character_id="char_1")
        request = MagicMock()
        fake_user = MagicMock(id=1)

        with patch.object(chat, "_enforce_user_chat_rate_limit") as mock_rate_limit, \
             patch.object(chat, "_build_chat_send_route_response", return_value={"reply": "hello"}) as mock_route:
            result = chat.chat_send(payload=payload, request=request, user=fake_user)

        assert result == {"reply": "hello"}
        mock_rate_limit.assert_called_once_with(1, detail="聊天请求过于频繁")
        mock_route.assert_called_once_with(user=fake_user, payload=payload, request=request)

    def test_build_chat_send_request_context_extracts_shared_fields(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        prepared_state = {
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 10, "tokens": 2},
        }

        assert chat._build_chat_send_request_context(
            prepared_state=prepared_state,
            character_id="char_1",
        ) == {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 10, "tokens": 2},
        }

    def test_build_chat_send_success_kwargs_extracts_success_flow_inputs(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        prepared_state = {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "estimate": {"chars": 10, "tokens": 2},
        }

        assert chat._build_chat_send_success_kwargs(
            user=fake_user,
            payload=payload,
            prepared_state=prepared_state,
        ) == {
            "user": fake_user,
            "payload": payload,
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 10, "tokens": 2},
            "character": {"id": "char_1"},
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "ai_config": {"provider": "vip"},
        }

    def test_build_chat_send_reply_kwargs_extracts_reply_generation_inputs(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_user = MagicMock(id=1, nickname="Luna")

        assert chat._build_chat_send_reply_kwargs(
            conn="conn",
            user=fake_user,
            character={"id": "char_1"},
            recent_messages=[{"role": "user", "content": "hi"}],
            memory_summary="summary",
            related_assets=["asset_1"],
            ai_config={"provider": "vip"},
        ) == {
            "character": {"id": "char_1"},
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "user_name": "Luna",
            "conn": "conn",
            "user_id": 1,
            "ai_config": {"provider": "vip"},
            "commit": False,
        }

    def test_finalize_chat_send_success_persists_logs_and_commits(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()

        with patch.object(chat, "save_assistant_message") as mock_save, \
             patch.object(chat, "count_chat_messages", return_value=3) as mock_count, \
             patch.object(chat, "_resolve_public_character_state", return_value={"mood": "warm"}) as mock_state, \
             patch.object(chat, "_log_successful_chat_request") as mock_log:
            result = chat._finalize_chat_send_success(
                fake_conn,
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                estimate={"chars": 10, "tokens": 2},
                reply="hello",
            )

        assert result == (3, {"mood": "warm"})
        mock_save.assert_called_once_with(fake_conn, 1, "char_1", "hello", commit=False)
        mock_count.assert_called_once_with(fake_conn, 1, "char_1")
        mock_state.assert_called_once_with(
            fake_conn,
            user_id=1,
            character_id="char_1",
            delta=None,
        )
        mock_log.assert_called_once_with(
            fake_conn,
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/send",
            estimate={"chars": 10, "tokens": 2},
            reply_text="hello",
        )
        fake_conn.commit.assert_called_once_with()

    def test_execute_chat_send_success_flow_reuses_reply_and_finalize_helpers(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, nickname="Luna")
        payload = MagicMock(character_id="char_1")
        reply_kwargs = {
            "character": {"id": "char_1"},
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "user_name": "Luna",
            "conn": fake_conn,
            "user_id": 1,
            "ai_config": {"provider": "vip"},
            "commit": False,
        }

        with patch.object(chat, "_build_chat_send_reply_kwargs", return_value=reply_kwargs) as mock_reply_kwargs, \
             patch.object(chat, "build_reply_with_fallback", return_value=("hello", {"mood": "warm"})) as mock_build_reply, \
             patch.object(chat, "_finalize_chat_send_success", return_value=(3, {"mood": "warm"})) as mock_finalize:
            result = chat._execute_chat_send_success_flow(
                fake_conn,
                user=fake_user,
                payload=payload,
                guest_ip="127.0.0.1",
                estimate={"chars": 10, "tokens": 2},
                character={"id": "char_1"},
                recent_messages=[{"role": "user", "content": "hi"}],
                memory_summary="summary",
                related_assets=["asset_1"],
                ai_config={"provider": "vip"},
            )

        assert result == ("hello", 3, {"mood": "warm"})
        mock_reply_kwargs.assert_called_once_with(
            conn=fake_conn,
            user=fake_user,
            character={"id": "char_1"},
            recent_messages=[{"role": "user", "content": "hi"}],
            memory_summary="summary",
            related_assets=["asset_1"],
            ai_config={"provider": "vip"},
        )
        mock_build_reply.assert_called_once_with(**reply_kwargs)
        mock_finalize.assert_called_once_with(
            fake_conn,
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            estimate={"chars": 10, "tokens": 2},
            reply="hello",
        )

    def test_run_chat_send_transaction_reuses_success_and_response_helpers(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        prepared = {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "estimate": {"chars": 10, "tokens": 2},
            "stream_messages": [{"role": "system", "content": "prompt"}],
        }

        success_kwargs = {
            "user": fake_user,
            "payload": payload,
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 10, "tokens": 2},
            "character": {"id": "char_1"},
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "ai_config": {"provider": "vip"},
        }

        with patch.object(chat, "store_user_message") as mock_store_user, \
             patch.object(chat, "_build_chat_send_success_kwargs", return_value=success_kwargs) as mock_kwargs, \
             patch.object(chat, "_execute_chat_send_success_flow", return_value=("hello", 3, {"mood": "warm"})) as mock_success, \
             patch.object(chat, "_build_chat_send_response", return_value={"reply": "hello", "history_count": 3, "summary_enabled": True, "character_state": {"mood": "warm"}}) as mock_response:
            result = chat._run_chat_send_transaction(
                fake_conn,
                user=fake_user,
                payload=payload,
                prepared=prepared,
            )

        assert result == {"reply": "hello", "history_count": 3, "summary_enabled": True, "character_state": {"mood": "warm"}}
        mock_store_user.assert_called_once_with(fake_conn, 1, "char_1", "hi", commit=False)
        mock_kwargs.assert_called_once_with(
            user=fake_user,
            payload=payload,
            prepared_state={
                "guest_ip": "127.0.0.1",
                "ai_config": {"provider": "vip"},
                "character": {"id": "char_1"},
                "clean_text": "hi",
                "recent_messages": [{"role": "user", "content": "hi"}],
                "memory_summary": "summary",
                "related_assets": ["asset_1"],
                "estimate": {"chars": 10, "tokens": 2},
            },
        )
        mock_success.assert_called_once_with(fake_conn, **success_kwargs)
        mock_response.assert_called_once_with(
            reply="hello",
            history_count=3,
            character_state={"mood": "warm"},
        )

    def test_run_chat_send_transaction_converts_ai_error_to_http_exception(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        prepared = {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "estimate": {"chars": 10, "tokens": 2},
            "stream_messages": [{"role": "system", "content": "prompt"}],
        }

        with patch.object(chat, "store_user_message") as mock_store_user, \
             patch.object(chat, "_execute_chat_send_success_flow", side_effect=chat.AIChatError("boom")) as mock_success, \
             patch.object(chat, "_process_chat_send_exception", side_effect=chat.HTTPException(status_code=503, detail="网络波动，请稍后再试")) as mock_process:
            with pytest.raises(chat.HTTPException) as exc_info:
                chat._run_chat_send_transaction(
                    fake_conn,
                    user=fake_user,
                    payload=payload,
                    prepared=prepared,
                )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "网络波动，请稍后再试"
        mock_store_user.assert_called_once_with(fake_conn, 1, "char_1", "hi", commit=False)
        mock_success.assert_called_once()
        mock_process.assert_called_once_with(
            fake_conn,
            user=fake_user,
            payload=payload,
            prepared_state={
                "guest_ip": "127.0.0.1",
                "ai_config": {"provider": "vip"},
                "character": {"id": "char_1"},
                "clean_text": "hi",
                "recent_messages": [{"role": "user", "content": "hi"}],
                "memory_summary": "summary",
                "related_assets": ["asset_1"],
                "estimate": {"chars": 10, "tokens": 2},
            },
            exc=mock_success.side_effect,
        )

    def test_run_chat_send_transaction_rethrows_unexpected_error_after_logging(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        prepared = {
            "guest_ip": "127.0.0.1",
            "ai_config": {"provider": "vip"},
            "character": {"id": "char_1"},
            "clean_text": "hi",
            "recent_messages": [{"role": "user", "content": "hi"}],
            "memory_summary": "summary",
            "related_assets": ["asset_1"],
            "estimate": {"chars": 10, "tokens": 2},
            "stream_messages": [{"role": "system", "content": "prompt"}],
        }

        with patch.object(chat, "store_user_message") as mock_store_user, \
             patch.object(chat, "_execute_chat_send_success_flow", side_effect=RuntimeError("boom")) as mock_success, \
             patch.object(chat, "_process_chat_send_exception", side_effect=RuntimeError("boom")) as mock_process:
            with pytest.raises(RuntimeError, match="boom"):
                chat._run_chat_send_transaction(
                    fake_conn,
                    user=fake_user,
                    payload=payload,
                    prepared=prepared,
                )

        mock_store_user.assert_called_once_with(fake_conn, 1, "char_1", "hi", commit=False)
        mock_success.assert_called_once()
        mock_process.assert_called_once_with(
            fake_conn,
            user=fake_user,
            payload=payload,
            prepared_state={
                "guest_ip": "127.0.0.1",
                "ai_config": {"provider": "vip"},
                "character": {"id": "char_1"},
                "clean_text": "hi",
                "recent_messages": [{"role": "user", "content": "hi"}],
                "memory_summary": "summary",
                "related_assets": ["asset_1"],
                "estimate": {"chars": 10, "tokens": 2},
            },
            exc=mock_success.side_effect,
        )

    def test_build_chat_send_failure_kwargs_extracts_failure_inputs(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        prepared_state = {
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 10, "tokens": 2},
        }

        assert chat._build_chat_send_failure_kwargs(
            user=fake_user,
            payload=payload,
            prepared_state=prepared_state,
            exc=RuntimeError("boom"),
        ) == {
            "user_id": 1,
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 10, "tokens": 2},
            "error_detail": "boom",
        }

    def test_process_chat_send_exception_reuses_failure_and_rethrow_helpers(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1)
        payload = MagicMock(character_id="char_1")
        prepared_state = {
            "guest_ip": "127.0.0.1",
            "estimate": {"chars": 10, "tokens": 2},
        }
        exc = RuntimeError("boom")
        failure_kwargs = {
            "user_id": 1,
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "estimate": {"chars": 10, "tokens": 2},
            "error_detail": "boom",
        }

        with patch.object(chat, "_build_chat_send_failure_kwargs", return_value=failure_kwargs) as mock_build_kwargs, \
             patch.object(chat, "_handle_chat_send_failure") as mock_handle_failure, \
             patch.object(chat, "_rethrow_chat_send_exception") as mock_rethrow:
            chat._process_chat_send_exception(
                fake_conn,
                user=fake_user,
                payload=payload,
                prepared_state=prepared_state,
                exc=exc,
            )

        mock_build_kwargs.assert_called_once_with(
            user=fake_user,
            payload=payload,
            prepared_state=prepared_state,
            exc=exc,
        )
        mock_handle_failure.assert_called_once_with(fake_conn, **failure_kwargs)
        mock_rethrow.assert_called_once_with(exc)

    def test_rethrow_chat_send_exception_converts_ai_errors_only(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with pytest.raises(chat.HTTPException) as ai_exc:
            chat._rethrow_chat_send_exception(chat.AIChatError("boom"))

        assert ai_exc.value.status_code == 503
        assert ai_exc.value.detail == "网络波动，请稍后再试"

        with pytest.raises(RuntimeError, match="boom"):
            chat._rethrow_chat_send_exception(RuntimeError("boom"))

    def test_prepare_prompt_context_result_builds_payload_from_context_tuple(self):
        result = chat_service._prepare_prompt_context_result(
            current_content="旧回复",
            context_tuple=(
                {"id": "char_1"},
                "summary",
                [{"role": "user", "content": "hi"}],
                ["asset_1"],
            ),
        )

        assert result == {
            "current_content": "旧回复",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "user", "content": "hi"}],
            "related_assets": ["asset_1"],
        }

    def test_prepare_prompt_context_result_uses_fallback_prompt_messages_when_missing(self):
        result = chat_service._prepare_prompt_context_result(
            current_content="",
            context_tuple=(
                {"id": "char_1"},
                "summary",
                None,
                ["asset_1"],
            ),
            fallback_prompt_messages=[{"role": "user", "content": "fallback"}],
        )

        assert result == {
            "current_content": "",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "user", "content": "fallback"}],
            "related_assets": ["asset_1"],
        }

    def test_prepare_regenerate_prompt_context_reuses_regenerate_service(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, effective_plan="vip")
        recent_messages = [{"role": "user", "content": "hi"}]

        with patch.object(chat_service, "prepare_regenerate_context", return_value=({"id": "char_1"}, "summary", None, ["asset_1"])) as mock_prepare:
            result = chat_service._prepare_regenerate_prompt_context(
                fake_conn,
                user=fake_user,
                character_id="char_1",
                recent_messages=recent_messages,
            )

        assert result == {
            "current_content": "",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": recent_messages,
            "related_assets": ["asset_1"],
        }
        mock_prepare.assert_called_once_with(
            fake_conn,
            1,
            "char_1",
            recent_messages,
            viewer_plan="vip",
        )

    def test_prepare_continue_prompt_context_reuses_continue_service(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, effective_plan="vip")
        recent_messages = [{"role": "user", "content": "hi"}]

        with patch.object(chat_service, "prepare_continue_context", return_value=({"id": "char_1"}, "summary", [{"role": "assistant", "content": "旧回复"}, {"role": "user", "content": "继续"}], ["asset_1"])) as mock_prepare:
            result = chat_service._prepare_continue_prompt_context(
                fake_conn,
                user=fake_user,
                character_id="char_1",
                message_id="msg_1",
                current_content="旧回复",
                recent_messages=recent_messages,
            )

        assert result == {
            "current_content": "旧回复",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "assistant", "content": "旧回复"}, {"role": "user", "content": "继续"}],
            "related_assets": ["asset_1"],
        }
        mock_prepare.assert_called_once_with(
            fake_conn,
            1,
            "char_1",
            "msg_1",
            "旧回复",
            recent_messages,
            viewer_plan="vip",
        )

    def test_prepare_retry_prompt_context_dispatches_to_regenerate_helper(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, effective_plan="vip")
        recent_messages = [{"role": "user", "content": "hi"}]

        with patch.object(chat_service, "_prepare_regenerate_prompt_context", return_value={
            "current_content": "",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": recent_messages,
            "related_assets": ["asset_1"],
        }) as mock_regenerate, patch.object(chat_service, "_prepare_continue_prompt_context") as mock_continue:
            result = chat_service._prepare_retry_prompt_context(
                fake_conn,
                user=fake_user,
                operation="regenerate",
                prompt_args={
                    "character_id": "char_1",
                    "message_id": "msg_1",
                    "current_content": "旧回复",
                    "recent_messages": recent_messages,
                },
            )

        assert result == {
            "current_content": "",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": recent_messages,
            "related_assets": ["asset_1"],
        }
        mock_regenerate.assert_called_once_with(
            fake_conn,
            user=fake_user,
            character_id="char_1",
            recent_messages=recent_messages,
        )
        mock_continue.assert_not_called()

    def test_prepare_retry_prompt_context_dispatches_to_continue_helper(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, effective_plan="vip")
        recent_messages = [{"role": "user", "content": "hi"}]

        with patch.object(chat_service, "_prepare_regenerate_prompt_context") as mock_regenerate, patch.object(chat_service, "_prepare_continue_prompt_context", return_value={
            "current_content": "旧回复",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "assistant", "content": "旧回复"}, {"role": "user", "content": "继续"}],
            "related_assets": ["asset_1"],
        }) as mock_continue:
            result = chat_service._prepare_retry_prompt_context(
                fake_conn,
                user=fake_user,
                operation="continue",
                prompt_args={
                    "character_id": "char_1",
                    "message_id": "msg_1",
                    "current_content": "旧回复",
                    "recent_messages": recent_messages,
                },
            )

        assert result == {
            "current_content": "旧回复",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "assistant", "content": "旧回复"}, {"role": "user", "content": "继续"}],
            "related_assets": ["asset_1"],
        }
        mock_regenerate.assert_not_called()
        mock_continue.assert_called_once_with(
            fake_conn,
            user=fake_user,
            character_id="char_1",
            message_id="msg_1",
            current_content="旧回复",
            recent_messages=recent_messages,
        )

    def test_build_retry_fallback_recent_wraps_assistant_content(self):
        result = chat_service._build_retry_fallback_recent({"id": "msg_1", "content": "旧回复"})

        assert result == [{"role": "assistant", "content": "旧回复"}]

    def test_load_retry_target_message_reuses_message_lookup(self):
        fake_conn = MagicMock()
        message_row = {"id": "msg_1", "content": "旧回复"}

        with patch.object(chat_service, "get_message_for_regenerate_or_continue", return_value=(message_row, "char_1")) as mock_lookup:
            result = chat_service._load_retry_target_message(
                fake_conn,
                user_id=1,
                message_id="msg_1",
                operation="continue",
            )

        assert result == (message_row, "char_1")
        mock_lookup.assert_called_once_with(
            fake_conn,
            1,
            "msg_1",
            operation="continue",
        )

    def test_prepare_retry_message_context_collects_retry_inputs(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1)
        recent_messages = [{"role": "user", "content": "trimmed"}]
        message_row = {"id": "msg_1", "content": "旧回复"}

        with patch.object(chat_service, "_load_retry_target_message", return_value=(message_row, "char_1")) as mock_message, \
             patch.object(chat_service, "_build_recent_messages_before_target", return_value=recent_messages) as mock_recent, \
             patch.object(chat_service, "_build_retry_fallback_recent", return_value=[{"role": "assistant", "content": "旧回复"}]) as mock_fallback:
            result = chat_service._prepare_retry_message_context(
                fake_conn,
                user=fake_user,
                message_id="msg_1",
                guest_ip="127.0.0.1",
                operation="continue",
            )

        assert result == {
            "guest_ip": "127.0.0.1",
            "message_row": message_row,
            "character_id": "char_1",
            "recent_messages": recent_messages,
        }
        mock_message.assert_called_once_with(
            fake_conn,
            user_id=1,
            message_id="msg_1",
            operation="continue",
        )
        mock_fallback.assert_called_once_with(message_row)
        mock_recent.assert_called_once_with(
            fake_conn,
            1,
            "char_1",
            "msg_1",
            [{"role": "assistant", "content": "旧回复"}],
        )

    def test_build_retry_prompt_args_extracts_character_content_and_recent_messages(self):
        message_context = {
            "guest_ip": "127.0.0.1",
            "message_row": {"id": "msg_1", "content": "旧回复"},
            "character_id": "char_1",
            "recent_messages": [{"role": "user", "content": "hi"}],
        }

        result = chat_service._build_retry_prompt_args(message_context, message_id="msg_1")

        assert result == {
            "character_id": "char_1",
            "message_id": "msg_1",
            "current_content": "旧回复",
            "recent_messages": [{"role": "user", "content": "hi"}],
        }

    def test_build_retry_stream_payload_reuses_user_stream_builder(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, effective_plan="vip")
        prompt_args = {
            "character_id": "char_1",
            "message_id": "msg_1",
            "current_content": "旧回复",
            "recent_messages": [{"role": "user", "content": "hi"}],
        }
        prompt_context = {
            "current_content": "旧回复",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "assistant", "content": "旧回复"}, {"role": "user", "content": "继续"}],
            "related_assets": ["asset_1"],
        }
        stream_payload = {
            "stream_messages": [{"role": "system", "content": "prompt"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 10, "tokens": 2},
        }

        with patch.object(chat_service, "_build_user_stream_messages_and_budget", return_value=stream_payload) as mock_builder:
            result = chat_service._build_retry_stream_payload(
                fake_conn,
                user=fake_user,
                prompt_args=prompt_args,
                prompt_context=prompt_context,
            )

        assert result == stream_payload
        mock_builder.assert_called_once_with(
            fake_conn,
            user=fake_user,
            character_id="char_1",
            character={"id": "char_1"},
            prompt_messages=[{"role": "assistant", "content": "旧回复"}, {"role": "user", "content": "继续"}],
            memory_summary="summary",
            related_assets=["asset_1"],
        )

    def test_build_retry_stream_prepare_result_reuses_retry_prompt_context_and_stream_builder(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, effective_plan="vip")
        message_context = {
            "guest_ip": "127.0.0.1",
            "message_row": {"id": "msg_1", "content": "旧回复"},
            "character_id": "char_1",
            "recent_messages": [{"role": "user", "content": "hi"}],
        }
        prompt_context = {
            "current_content": "旧回复",
            "character": {"id": "char_1"},
            "memory_summary": "summary",
            "prompt_messages": [{"role": "assistant", "content": "旧回复"}, {"role": "user", "content": "继续"}],
            "related_assets": ["asset_1"],
        }
        stream_payload = {
            "stream_messages": [{"role": "system", "content": "prompt"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 10, "tokens": 2},
        }

        with patch.object(chat_service, "_prepare_retry_prompt_context", return_value=prompt_context) as mock_prompt_context, \
             patch.object(chat_service, "_build_retry_stream_payload", return_value=stream_payload) as mock_stream_payload:
            result = chat_service._build_retry_stream_prepare_result(
                fake_conn,
                user=fake_user,
                message_context=message_context,
                message_id="msg_1",
                operation="continue",
            )

        assert result == {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "current_content": "旧回复",
            "stream_messages": [{"role": "system", "content": "prompt"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 10, "tokens": 2},
        }
        mock_prompt_context.assert_called_once_with(
            fake_conn,
            user=fake_user,
            operation="continue",
            prompt_args={
                "character_id": "char_1",
                "message_id": "msg_1",
                "current_content": "旧回复",
                "recent_messages": [{"role": "user", "content": "hi"}],
            },
        )
        mock_stream_payload.assert_called_once_with(
            fake_conn,
            user=fake_user,
            prompt_args={
                "character_id": "char_1",
                "message_id": "msg_1",
                "current_content": "旧回复",
                "recent_messages": [{"role": "user", "content": "hi"}],
            },
            prompt_context=prompt_context,
        )

    def test_prepare_regenerate_or_continue_request_for_regenerate(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, nickname="Luna", effective_plan="vip")
        message_context = {
            "guest_ip": "127.0.0.1",
            "message_row": {"id": "msg_1", "content": "旧回复"},
            "character_id": "char_1",
            "recent_messages": [{"role": "user", "content": "hi"}],
        }
        prepare_result = {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "current_content": "",
            "stream_messages": [{"role": "system", "content": "prompt"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 10, "tokens": 2},
        }

        with patch.object(chat_service, "_prepare_retry_message_context", return_value=message_context) as mock_message_context, \
             patch.object(chat_service, "_build_retry_stream_prepare_result", return_value=prepare_result) as mock_prepare_result:
            result = chat_service._prepare_regenerate_or_continue_request(
                fake_conn,
                user=fake_user,
                message_id="msg_1",
                guest_ip="127.0.0.1",
                operation="regenerate",
            )

        assert result == prepare_result
        mock_message_context.assert_called_once_with(
            fake_conn,
            user=fake_user,
            message_id="msg_1",
            guest_ip="127.0.0.1",
            operation="regenerate",
        )
        mock_prepare_result.assert_called_once_with(
            fake_conn,
            user=fake_user,
            message_context=message_context,
            message_id="msg_1",
            operation="regenerate",
        )

    def test_prepare_regenerate_or_continue_request_for_continue(self):
        fake_conn = MagicMock()
        fake_user = MagicMock(id=1, nickname="Luna", effective_plan="vip")
        message_context = {
            "guest_ip": "127.0.0.1",
            "message_row": {"id": "msg_1", "content": "旧回复"},
            "character_id": "char_1",
            "recent_messages": [{"role": "user", "content": "hi"}],
        }
        prepare_result = {
            "guest_ip": "127.0.0.1",
            "character_id": "char_1",
            "current_content": "旧回复",
            "stream_messages": [{"role": "system", "content": "prompt"}],
            "ai_config": {"provider": "vip"},
            "estimate": {"chars": 10, "tokens": 2},
        }

        with patch.object(chat_service, "_prepare_retry_message_context", return_value=message_context) as mock_message_context, \
             patch.object(chat_service, "_build_retry_stream_prepare_result", return_value=prepare_result) as mock_prepare_result:
            result = chat_service._prepare_regenerate_or_continue_request(
                fake_conn,
                user=fake_user,
                message_id="msg_1",
                guest_ip="127.0.0.1",
                operation="continue",
            )

        assert result == prepare_result
        mock_message_context.assert_called_once_with(
            fake_conn,
            user=fake_user,
            message_id="msg_1",
            guest_ip="127.0.0.1",
            operation="continue",
        )
        mock_prepare_result.assert_called_once_with(
            fake_conn,
            user=fake_user,
            message_context=message_context,
            message_id="msg_1",
            operation="continue",
        )

    def test_resolve_public_character_state_applies_delta_when_present(self):
        fake_conn = MagicMock()

        with patch.object(chat_service, "apply_state_delta", return_value={"mood": "warm", "_meta": 1}) as mock_apply, \
             patch.object(chat_service, "get_character_state") as mock_get_state:
            result = chat_service._resolve_public_character_state(
                fake_conn,
                user_id=1,
                character_id="char_1",
                delta={"mood": "warm"},
            )

        assert result == {"mood": "warm"}
        mock_apply.assert_called_once_with(fake_conn, 1, "char_1", {"mood": "warm"}, commit=False)
        mock_get_state.assert_not_called()

    def test_resolve_public_character_state_reads_current_state_without_delta(self):
        fake_conn = MagicMock()

        with patch.object(chat_service, "apply_state_delta") as mock_apply, \
             patch.object(chat_service, "get_character_state", return_value={"mood": "steady", "affection": 10, "_meta": 2}) as mock_get_state:
            result = chat_service._resolve_public_character_state(
                fake_conn,
                user_id=1,
                character_id="char_2",
                delta=None,
            )

        assert result == {"mood": "steady", "affection": 10}
        mock_apply.assert_not_called()
        mock_get_state.assert_called_once_with(fake_conn, 1, "char_2")

    def test_consume_stream_result_returns_parsed_reply_and_delta(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "_consume_stream_result_impl", return_value=iter([])) as mock_impl:
            result = list(chat._consume_stream_result(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/stream",
                estimate={"chars": 10, "tokens": 2},
                stream_error_message="网络波动，请稍后再试",
            ))

        assert result == []
        mock_impl.assert_called_once_with(
            stream_messages=[{"role": "user", "content": "hi"}],
            ai_config={"provider": "test"},
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            estimate={"chars": 10, "tokens": 2},
            stream_error_message="网络波动，请稍后再试",
            deps={
                "stream_ai_completion": chat._stream_ai_completion,
                "log_chat_failure": chat._log_failed_chat_request,
                "estimate_output_tokens": chat.estimate_text_tokens,
                "parse_stream_reply": chat.parse_state_update_tag,
                "format_error_event": ANY,
            },
        )

    def test_consume_stream_result_emits_error_when_stream_fails(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        def fake_stream_ai_completion(*args, **kwargs):
            if False:
                yield None
            return ("部分回复", "boom")

        with patch.object(chat, "_stream_ai_completion", side_effect=fake_stream_ai_completion), \
             patch.object(chat, "estimate_text_tokens", return_value=4) as mock_estimate, \
             patch.object(chat, "_log_failed_chat_request") as mock_failure:
            result = list(chat._consume_stream_result(
                stream_messages=[{"role": "user", "content": "hi"}],
                ai_config={"provider": "test"},
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/stream",
                estimate={"chars": 10, "tokens": 2},
                stream_error_message="网络波动，请稍后再试",
            ))

        assert result == ['event: error\ndata: {"message": "网络波动，请稍后再试"}\n\n']
        mock_estimate.assert_called_once_with("部分回复")
        mock_failure.assert_called_once_with(
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            estimate={"chars": 10, "tokens": 2},
            error_detail="boom",
            estimated_output_tokens=4,
        )

    def test_persist_stream_result_returns_message_and_state_fields(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_conn.commit = MagicMock()
        fake_conn.rollback = MagicMock()
        fake_conn.close = MagicMock()

        with patch.object(chat, "get_conn", return_value=fake_conn), \
             patch.object(chat, "store_user_message") as mock_store, \
             patch.object(chat, "save_assistant_message", return_value="msg_1") as mock_save, \
             patch.object(chat, "_log_successful_chat_request") as mock_log, \
             patch.object(chat, "_resolve_public_character_state", return_value={"mood": "warm"}) as mock_state:
            result = chat._persist_stream_result(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                final_reply="你好呀",
                estimate={"chars": 12, "tokens": 3},
                delta={"mood": "warm"},
                user_message="hi",
            )

        assert result == {
            "character_state": {"mood": "warm"},
            "message_id": "msg_1",
        }
        mock_store.assert_called_once_with(fake_conn, 1, "char_1", "hi", commit=False)
        mock_save.assert_called_once_with(fake_conn, 1, "char_1", "你好呀", commit=False)
        mock_log.assert_called_once()
        mock_state.assert_called_once_with(
            fake_conn,
            user_id=1,
            character_id="char_1",
            delta={"mood": "warm"},
        )
        fake_conn.commit.assert_called_once()
        fake_conn.rollback.assert_not_called()
        fake_conn.close.assert_called_once()

    def test_emit_stream_persist_failure_logs_and_returns_error_event(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        with patch.object(chat, "estimate_text_tokens", return_value=7) as mock_estimate, \
             patch.object(chat, "_log_failed_chat_request") as mock_failure:
            result = chat._emit_stream_persist_failure(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                endpoint="/api/chat/stream",
                estimate={"chars": 12, "tokens": 3},
                error_detail="persist_failed: boom",
                reply_text="最终回复",
                client_message="消息保存失败，请稍后再试",
            )

        assert result == 'event: error\ndata: {"message": "消息保存失败，请稍后再试"}\n\n'
        mock_estimate.assert_called_once_with("最终回复")
        mock_failure.assert_called_once_with(
            user_id=1,
            guest_ip="127.0.0.1",
            character_id="char_1",
            endpoint="/api/chat/stream",
            estimate={"chars": 12, "tokens": 3},
            error_detail="persist_failed: boom",
            estimated_output_tokens=7,
        )

    def test_public_character_state_filters_internal_fields(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        assert chat._public_character_state({"mood": "warm", "_meta": 1, "affection": 10}) == {
            "mood": "warm",
            "affection": 10,
        }
        assert chat._public_character_state(None) == {}

    def test_regenerate_and_continue_endpoints_registered(self, app_module):
        app = app_module

        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert ("POST", "/api/chat/regenerate") in routes
        assert ("POST", "/api/chat/continue") in routes

    def test_shared_stream_generator_returns_done_payload_for_regenerate(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_conn.commit = MagicMock()
        fake_conn.rollback = MagicMock()
        fake_conn.close = MagicMock()

        def fake_stream(*args, **kwargs):
            if False:
                yield None
            return ("你好呀", None)

        with patch.object(chat, "_stream_ai_completion", side_effect=fake_stream), \
             patch.object(chat, "get_conn", return_value=fake_conn), \
             patch.object(chat, "save_regenerated_version") as mock_save, \
             patch.object(chat, "_log_successful_chat_request") as mock_log, \
             patch.object(chat, "_resolve_public_character_state", return_value={"mood": "warm", "affection": 10}), \
             patch.object(chat, "apply_state_delta", return_value=None):
            response = chat._stream_regenerate_or_continue_events(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                message_id="msg_1",
                endpoint="/api/chat/regenerate",
                estimate={"chars": 12, "tokens": 3},
                ai_config={"provider": "test"},
                stream_messages=[{"role": "user", "content": "hi"}],
                is_append=False,
                operation="regenerate",
            )

            text = asyncio.run(_read_streaming_text(response))

        assert "event: done" in text
        assert '"reply": "你好呀"' in text
        assert '"operation": "regenerate"' in text
        assert '"message_id": "msg_1"' in text
        assert '"appended_text"' not in text
        mock_save.assert_called_once_with(fake_conn, "msg_1", "你好呀", is_append=False, commit=False)
        mock_log.assert_called_once()
        fake_conn.commit.assert_called_once()
        fake_conn.close.assert_called_once()

    def test_shared_stream_generator_returns_done_payload_for_continue(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        fake_conn = MagicMock()
        fake_conn.commit = MagicMock()
        fake_conn.rollback = MagicMock()
        fake_conn.close = MagicMock()

        def fake_stream(*args, **kwargs):
            if False:
                yield None
            return ("继续补充", None)

        with patch.object(chat, "_stream_ai_completion", side_effect=fake_stream), \
             patch.object(chat, "get_conn", return_value=fake_conn), \
             patch.object(chat, "save_regenerated_version") as mock_save, \
             patch.object(chat, "_log_successful_chat_request") as mock_log, \
             patch.object(chat, "_resolve_public_character_state", return_value={"mood": "steady"}), \
             patch.object(chat, "apply_state_delta", return_value=None):
            response = chat._stream_regenerate_or_continue_events(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                message_id="msg_2",
                endpoint="/api/chat/continue",
                estimate={"chars": 18, "tokens": 5},
                ai_config={"provider": "test"},
                stream_messages=[{"role": "assistant", "content": "old"}],
                is_append=True,
                base_reply="原回复",
                operation="continue",
            )

            text = asyncio.run(_read_streaming_text(response))

        assert "event: done" in text
        assert '"reply": "原回复继续补充"' in text
        assert '"appended_text": "继续补充"' in text
        assert '"operation": "continue"' in text
        mock_save.assert_called_once_with(fake_conn, "msg_2", "继续补充", is_append=True, commit=False)
        mock_log.assert_called_once()
        fake_conn.commit.assert_called_once()
        fake_conn.close.assert_called_once()

    def test_shared_stream_generator_returns_error_event_when_stream_fails(self):
        with patch("database.init_db_pool"), patch("database.close_db_pool"), patch("threading.Thread"):
            import routers.chat as chat

        def fake_stream(*args, **kwargs):
            if False:
                yield None
            return ("部分回复", "boom")

        with patch.object(chat, "_stream_ai_completion", side_effect=fake_stream), \
             patch.object(chat, "_log_failed_chat_request") as mock_failure:
            response = chat._stream_regenerate_or_continue_events(
                user_id=1,
                guest_ip="127.0.0.1",
                character_id="char_1",
                message_id="msg_3",
                endpoint="/api/chat/regenerate",
                estimate={"chars": 10, "tokens": 2},
                ai_config={"provider": "test"},
                stream_messages=[{"role": "user", "content": "hi"}],
                is_append=False,
                operation="regenerate",
            )

            text = asyncio.run(_read_streaming_text(response))

        assert "event: error" in text
        assert "网络波动，请稍后再试" in text
        mock_failure.assert_called_once()


class TestAdminCharactersRefactoring:
    def test_core_routes_still_registered_after_split(self, app_module):
        app = app_module

        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert ("GET", "/api/admin/characters") in routes
        assert ("POST", "/api/admin/characters") in routes
        assert ("GET", "/api/admin/character/{character_id}") in routes
        assert ("POST", "/api/admin/character/{character_id}") in routes
        assert ("DELETE", "/api/admin/character/{character_id}") in routes

    def test_core_routes_are_served_from_split_module(self, app_module):
        app = app_module

        route_map = {
            (method, route.path): route.endpoint.__module__
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert route_map[("GET", "/api/admin/characters")] == "routers.admin.characters_core"
        assert route_map[("POST", "/api/admin/characters")] == "routers.admin.characters_core"
        assert route_map[("GET", "/api/admin/character/{character_id}")] == "routers.admin.characters_core"
        assert route_map[("POST", "/api/admin/character/{character_id}")] == "routers.admin.characters_core"
        assert route_map[("DELETE", "/api/admin/character/{character_id}")] == "routers.admin.characters_core"

    def test_memory_routes_still_registered_after_split(self, app_module):
        app = app_module

        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert ("GET", "/api/admin/character/{character_id}/memories") in routes
        assert ("POST", "/api/admin/character/{character_id}/memories") in routes
        assert ("PUT", "/api/admin/character/{character_id}/memories/{memory_id}") in routes
        assert ("DELETE", "/api/admin/character/{character_id}/memories/{memory_id}") in routes
        assert ("GET", "/api/admin/character/{character_id}/memory-categories") in routes
        assert ("POST", "/api/admin/character/{character_id}/memory-categories") in routes
        assert ("PUT", "/api/admin/character/{character_id}/memory-categories/{category_id}") in routes
        assert ("DELETE", "/api/admin/character/{character_id}/memory-categories/{category_id}") in routes
        assert ("GET", "/api/admin/character/{character_id}/memory-categories/{category_id}/delete-impact") in routes

    def test_memory_routes_are_served_from_split_module(self, app_module):
        app = app_module

        route_map = {
            (method, route.path): route.endpoint.__module__
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert route_map[("GET", "/api/admin/character/{character_id}/memories")] == "routers.admin.characters_memory"
        assert route_map[("POST", "/api/admin/character/{character_id}/memories")] == "routers.admin.characters_memory"
        assert route_map[("GET", "/api/admin/character/{character_id}/memory-categories")] == "routers.admin.characters_memory"
        assert route_map[("GET", "/api/admin/character/{character_id}/memory-categories/{category_id}/delete-impact")] == "routers.admin.characters_memory"

    def test_story_routes_still_registered_after_split(self, app_module):
        app = app_module

        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert ("GET", "/api/admin/character/{character_id}/greetings") in routes
        assert ("POST", "/api/admin/character/{character_id}/greetings") in routes
        assert ("PUT", "/api/admin/character/{character_id}/greetings/{greeting_id}") in routes
        assert ("DELETE", "/api/admin/character/{character_id}/greetings/{greeting_id}") in routes
        assert ("GET", "/api/admin/character/{character_id}/storylines") in routes
        assert ("POST", "/api/admin/character/{character_id}/storylines") in routes
        assert ("PUT", "/api/admin/character/{character_id}/storylines/{storyline_id}") in routes
        assert ("DELETE", "/api/admin/character/{character_id}/storylines/{storyline_id}") in routes
        assert ("GET", "/api/admin/character/{character_id}/storylines/{storyline_id}/delete-impact") in routes

    def test_story_routes_are_served_from_split_module(self, app_module):
        app = app_module

        route_map = {
            (method, route.path): route.endpoint.__module__
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert route_map[("GET", "/api/admin/character/{character_id}/greetings")] == "routers.admin.characters_story"
        assert route_map[("POST", "/api/admin/character/{character_id}/greetings")] == "routers.admin.characters_story"
        assert route_map[("GET", "/api/admin/character/{character_id}/storylines")] == "routers.admin.characters_story"
        assert route_map[("GET", "/api/admin/character/{character_id}/storylines/{storyline_id}/delete-impact")] == "routers.admin.characters_story"

    def test_rules_events_routes_still_registered_after_split(self, app_module):
        app = app_module

        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert ("GET", "/api/admin/character/{character_id}/post-rules") in routes
        assert ("POST", "/api/admin/character/{character_id}/post-rules") in routes
        assert ("PUT", "/api/admin/character/{character_id}/post-rules/{rule_id}") in routes
        assert ("DELETE", "/api/admin/character/{character_id}/post-rules/{rule_id}") in routes
        assert ("GET", "/api/admin/character/{character_id}/story-events") in routes
        assert ("POST", "/api/admin/character/{character_id}/story-events") in routes
        assert ("PUT", "/api/admin/character/{character_id}/story-events/{event_id}") in routes
        assert ("DELETE", "/api/admin/character/{character_id}/story-events/{event_id}") in routes

    def test_rules_events_routes_are_served_from_split_module(self, app_module):
        app = app_module

        route_map = {
            (method, route.path): route.endpoint.__module__
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert route_map[("GET", "/api/admin/character/{character_id}/post-rules")] == "routers.admin.characters_rules_events"
        assert route_map[("POST", "/api/admin/character/{character_id}/post-rules")] == "routers.admin.characters_rules_events"
        assert route_map[("GET", "/api/admin/character/{character_id}/story-events")] == "routers.admin.characters_rules_events"
        assert route_map[("DELETE", "/api/admin/character/{character_id}/story-events/{event_id}")] == "routers.admin.characters_rules_events"

    def test_insights_routes_still_registered_after_split(self, app_module):
        app = app_module

        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert ("GET", "/api/admin/character/{character_id}/config-summary") in routes
        assert ("GET", "/api/admin/character/{character_id}/message-preview") in routes
        assert ("POST", "/api/admin/character/{character_id}/test-keywords") in routes

    def test_insights_routes_are_served_from_split_module(self, app_module):
        app = app_module

        route_map = {
            (method, route.path): route.endpoint.__module__
            for route in app.routes
            for method in getattr(route, "methods", set())
        }

        assert route_map[("GET", "/api/admin/character/{character_id}/config-summary")] == "routers.admin.characters_insights"
        assert route_map[("GET", "/api/admin/character/{character_id}/message-preview")] == "routers.admin.characters_insights"
        assert route_map[("POST", "/api/admin/character/{character_id}/test-keywords")] == "routers.admin.characters_insights"
