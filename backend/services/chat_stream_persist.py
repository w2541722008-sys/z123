from __future__ import annotations

import logging
from typing import Any

from core.database import get_conn
from services.chat_send import (
    format_done_event,
    save_assistant_message,
    store_user_message,
    _log_successful_chat_request,
    _resolve_public_character_state,
)
from services.chat_retry import save_regenerated_version
from services.memory_service import run_memory_summary_background
from services.usage_guard import estimate_text_tokens, log_ai_request
from services.chat_stream_infra import (
    _emit_stream_persist_failure,
    _build_stream_done_payload,
    _build_stream_done_payload_from_persisted_result,
)

logger = logging.getLogger(__name__)


def _persist_stream_result(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    final_reply: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str | None = None,
) -> dict[str, Any]:
    save_conn = get_conn()
    message_id = None
    try:
        if user_message:
            store_user_message(save_conn, user_id, character_id, user_message, commit=False)
        message_id = save_assistant_message(save_conn, user_id, character_id, final_reply, commit=False)
        _log_successful_chat_request(
            save_conn, user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint="/api/chat/stream", estimate=estimate, reply_text=final_reply,
        )
        character_state = _resolve_public_character_state(
            save_conn, user_id=user_id, character_id=character_id, delta=delta,
        )
        save_conn.commit()
        return {"character_state": character_state, "message_id": message_id}
    except Exception:
        save_conn.rollback()
        raise
    finally:
        save_conn.close()


def _postprocess_main_stream_result(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    final_text: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str,
    character: dict[str, Any],
):
    try:
        persisted_result = _persist_stream_result(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            final_reply=final_text, estimate=estimate, delta=delta, user_message=user_message,
        )
    except Exception as exc:
        yield _emit_stream_persist_failure(
            user_id=user_id, guest_ip=guest_ip, character_id=character_id,
            endpoint="/api/chat/stream", estimate=estimate,
            error_detail=f"persist_failed: {exc}", reply_text=final_text,
            client_message="消息保存失败，请稍后再试",
        )
        return
    run_memory_summary_background(user_id, character_id, character)
    yield format_done_event(
        _build_stream_done_payload_from_persisted_result(reply=final_text, persisted_result=persisted_result)
    )


def _postprocess_regenerate_or_continue_result(
    *,
    user_id: int | str,
    guest_ip: str,
    character_id: str,
    message_id: str,
    endpoint: str,
    estimate: dict[str, int],
    is_append: bool,
    base_reply: str,
    operation: str,
    final_text: str,
    delta: dict[str, Any] | None,
):
    try:
        save_conn = get_conn()
        try:
            save_regenerated_version(save_conn, message_id, final_text, is_append=is_append, commit=False)
            _log_successful_chat_request(
                save_conn, user_id=user_id, guest_ip=guest_ip, character_id=character_id,
                endpoint=endpoint, estimate=estimate, reply_text=final_text,
            )
            raw_state = _resolve_public_character_state(
                save_conn, user_id=user_id, character_id=character_id, delta=delta,
            )
            save_conn.commit()
        except Exception as exc:
            save_conn.rollback()
            yield _emit_stream_persist_failure(
                user_id=user_id, guest_ip=guest_ip, character_id=character_id,
                endpoint=endpoint, estimate=estimate,
                error_detail=f"persist_failed: {exc}", reply_text=final_text,
                client_message="保存失败，请稍后再试",
            )
            return
        finally:
            save_conn.close()
    except Exception as outer_exc:
        logger.warning(f"[{endpoint.split('/')[-1]}] outer error before done: {outer_exc}", exc_info=True)
        from services.chat_send import format_error_event
        yield format_error_event("保存失败，请稍后再试")
        return

    yield format_done_event(
        _build_stream_done_payload(
            reply=f"{base_reply}{final_text}" if is_append else final_text,
            fallback=False, character_state=raw_state, message_id=message_id,
            operation=operation, appended_text=final_text if is_append else None,
            summary_enabled=True,
        )
    )


def _postprocess_guest_stream_result_impl(
    reply_text: str,
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    log_conn = get_conn()
    try:
        output_tokens = estimate_text_tokens(reply_text)
        log_ai_request(
            log_conn, user_id=None, guest_ip=guest_ip, character_id=character_id,
            endpoint="/api/chat/guest-stream",
            request_chars=estimate["chars"],
            estimated_input_tokens=estimate["tokens"],
            estimated_output_tokens=output_tokens,
            total_estimated_tokens=estimate["tokens"] + output_tokens,
            used_fallback=False, status="success", error_detail="",
        )
        log_conn.commit()
    except Exception:
        log_conn.rollback()
    finally:
        log_conn.close()
    return {"reply": reply_text, "history_count": 0, "summary_enabled": False, "character_state": None}


def _postprocess_guest_stream_result(
    final_text: str,
    delta: dict[str, Any] | None = None,
    *,
    guest_ip: str,
    character_id: str,
    estimate: dict[str, int],
):
    _ = delta
    yield format_done_event(
        _postprocess_guest_stream_result_impl(
            final_text, guest_ip=guest_ip, character_id=character_id, estimate=estimate,
        )
    )
