"""游客流式构建 — 降级 prompt、消息构建、配额查询。

从 chat_send.py 拆分而来，游客聊天专属逻辑。
"""

from __future__ import annotations

import logging
from typing import Any

from core.database import ConnType
from core.plan_constants import GUEST_PLAN
from services.chat_query import _normalize_non_empty_message, message_projection
from services.plan_service import get_plan_policy
from services.prompt_assembler import (
    PromptBuildContext,
    build_layered_chat_messages_from_context,
)
from services.chat_stream._postprocess import get_guest_character_state_for_prompt
from services.usage_guard import get_daily_usage

logger = logging.getLogger(__name__)


def build_guest_fallback_messages(
    character: dict[str, Any], user_message: str
) -> list[dict[str, str]]:
    """最简降级 prompt — 仅在 build_layered_chat_messages 异常时使用。"""
    name = character.get("name", "AI角色")
    subtitle = character.get("subtitle", "")
    identity = "你是" + name
    if subtitle:
        identity += "，" + subtitle
    description = character.get("description", "")
    if description:
        identity += "\n" + description

    return [
        {
            "role": "system",
            "content": identity + "\n\n请用第一人称自然回复，保持角色设定。",
        },
        {"role": "user", "content": user_message},
    ]


def build_guest_stream_messages(
    character: dict[str, Any],
    message_text: str,
    guest_history: list[Any],
    *,
    conn: ConnType | None = None,
    guest_ip: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    clean_text = _normalize_non_empty_message(message_text)
    fake_history = [
        message_projection(item.role, item.content) for item in guest_history
    ]
    fake_history.append({"role": "user", "content": clean_text})
    character_state = (
        get_guest_character_state_for_prompt(guest_ip, str(character.get("id") or ""))
        if guest_ip
        else None
    )
    try:
        messages = build_layered_chat_messages_from_context(
            PromptBuildContext(
                character=character,
                recent_messages=fake_history,
                related_assets=[],
                user_name="访客",
                character_state=character_state,
                conn=conn,
            )
        )
    except Exception as exc:
        logger.warning("游客 prompt 构建失败，使用降级 prompt: %s", exc, exc_info=True)
        messages = build_guest_fallback_messages(character, clean_text)
    return clean_text, messages


def build_guest_quota_payload(conn: ConnType, guest_ip: str) -> dict[str, Any]:
    plan_policy = get_plan_policy(GUEST_PLAN)
    token_limit = max(0, int(plan_policy["token_limit"] or 0))
    usage = get_daily_usage(conn, guest_ip=guest_ip)
    used_tokens = max(0, int(usage["total_tokens"] or 0))
    remaining_tokens = max(0, token_limit - used_tokens)
    remaining_percent = (
        int(remaining_tokens * 100 / token_limit) if token_limit > 0 else 100
    )

    if remaining_tokens <= 0:
        status_text = "额度已用完"
    elif remaining_percent <= 35:
        status_text = "额度不多"
    else:
        status_text = "额度充足"

    return {
        "guest": True,
        "status_text": status_text,
        "remaining_percent": max(0, min(100, remaining_percent)),
        "used_tokens": used_tokens,
        "remaining_tokens": remaining_tokens,
        "token_limit": token_limit,
    }
