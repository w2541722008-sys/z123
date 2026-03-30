"""
聊天路由 - 处理 AI 对话（同步和流式）

端点：
    POST /api/chat/send         - 同步发送消息
    POST /api/chat/stream       - 流式发送消息（SSE）
    POST /api/chat/guest-stream - 游客试聊（无需登录）

流式响应格式（Server-Sent Events）：
    - event: chunk, data: {text: "..."}      # 逐字返回
    - event: done, data: {reply: "...", character_state: {...}}  # 完成

主要流程：
    1. 准备聊天上下文（角色信息、历史消息、记忆摘要）
    2. 构建分层提示词（系统提示 + 记忆 + 历史消息）
    3. 调用 AI 生成回复（同步或流式）
    4. 保存消息到数据库
    5. 更新角色状态（好感度、心情等）
    6. 触发后台记忆摘要（异步）
"""

from __future__ import annotations

# 标准库导入
import os
from typing import Any

# 第三方库导入
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

# 本地模块导入
from auth import CurrentUser, get_current_user
from config import (
    AI_CHAT_MAX_OUTPUT_TOKENS,
    CHAT_RATE_LIMIT_COUNT,
    CHAT_RATE_LIMIT_WINDOW_SECONDS,
    GUEST_CHAT_RATE_LIMIT_COUNT,
    GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS,
)
from database import get_conn
from model_adapter import get_ai_config, stream_chat_completion
from models import ChatSendPayload, GuestChatPayload
from services.plan_service import GUEST_PLAN, get_plan_policy
from services.rate_limit import enforce_rate_limit, get_request_client_ip
from services.usage_guard import (
    enforce_daily_budget,
    estimate_messages_tokens,
    estimate_text_tokens,
    get_daily_usage,
    log_ai_request,
)
from services.character_state import get_character_state
from services.chat_service import (
    build_layered_chat_messages,
    build_mock_reply,
    build_reply_with_fallback,
    count_chat_messages,
    format_sse,
    get_character_or_404,
    get_linked_assets,
    prepare_chat_context,
    save_assistant_message,
    store_user_message,
)
from services.memory_service import (
    normalize_reply_text,
    parse_state_update_tag,
    run_memory_summary_background,
    sanitize_stream_chunk,
)

router = APIRouter()


def _build_guest_quota_payload(conn, guest_ip: str) -> dict[str, Any]:
    """返回游客体验额度的简化状态，供前端轻提示展示。"""
    plan_policy = get_plan_policy(GUEST_PLAN)
    token_limit = max(0, int(plan_policy["token_limit"] or 0))
    usage = get_daily_usage(conn, guest_ip=guest_ip)
    used_tokens = max(0, int(usage["total_tokens"] or 0))
    remaining_tokens = max(0, token_limit - used_tokens)
    remaining_percent = int(remaining_tokens * 100 / token_limit) if token_limit > 0 else 100

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


@router.get("/chat/guest-quota")
def chat_guest_quota(request: Request) -> dict[str, Any]:
    """获取游客当前剩余体验额度，用于前端游客专属提示。"""
    conn = get_conn()
    try:
        guest_ip = get_request_client_ip(request)
        return _build_guest_quota_payload(conn, guest_ip)
    finally:
        conn.close()


@router.post("/chat/send")
def chat_send(
    payload: ChatSendPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    同步发送聊天消息。

    流程：
        1. 准备聊天上下文（角色、历史消息、记忆摘要）
        2. 构建分层提示词
        3. 调用 AI 生成回复（带降级策略）
        4. 保存消息到数据库
        5. 返回完整回复和角色状态

    Args:
        payload: 聊天请求体（角色ID、消息内容）
        user: 当前登录用户

    Returns:
        包含 AI 回复、历史消息数、角色状态的对象
    """
    enforce_rate_limit(
        "chat_user",
        str(user.id),
        limit=CHAT_RATE_LIMIT_COUNT,
        window_seconds=CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail="聊天请求过于频繁",
    )

    conn = get_conn()
    try:
        guest_ip = get_request_client_ip(request)
        plan_policy = get_plan_policy(user.effective_plan)
        ai_config = get_ai_config(os.environ, profile=plan_policy["model_profile"])

        # 先预览上下文，不立刻写入用户消息，避免预算超限时留下孤儿消息
        character, clean_text, recent_messages, memory_summary = prepare_chat_context(
            conn,
            user.id,
            payload.character_id,
            payload.message,
            persist_user_message=False,
            viewer_plan=user.effective_plan,
        )
        related_assets = get_linked_assets(conn, payload.character_id)
        character_state = get_character_state(conn, user.id, payload.character_id)
        preview_messages = build_layered_chat_messages(
            character,
            recent_messages,
            memory_summary,
            related_assets=related_assets,
            user_name=user.nickname,
            character_state=character_state,
        )
        estimate = estimate_messages_tokens(preview_messages)
        planned_tokens = estimate["tokens"] + AI_CHAT_MAX_OUTPUT_TOKENS
        enforce_daily_budget(
            conn,
            user_id=user.id,
            planned_tokens=planned_tokens,
            token_limit=plan_policy["token_limit"],
            token_limit_detail="你今天的 AI 使用额度已达上限，请明天再来",
        )

        # 预算通过后再落库
        store_user_message(conn, user.id, payload.character_id, clean_text)

        # 步骤 3：生成回复（带降级策略）
        reply, new_state, used_fallback = build_reply_with_fallback(
            character, recent_messages, memory_summary,
            related_assets=related_assets, user_name=user.nickname,
            conn=conn, user_id=user.id,
            ai_config=ai_config,
        )

        # 步骤 4：保存消息
        save_assistant_message(conn, user.id, payload.character_id, reply)
        history_count = count_chat_messages(conn, user.id, payload.character_id)

        # 步骤 5：读取最新状态（过滤内部字段）
        raw_state = get_character_state(conn, user.id, payload.character_id)
        character_state = {k: v for k, v in raw_state.items() if not k.startswith("_")}

        actual_output_tokens = estimate_text_tokens(reply)
        log_ai_request(
            conn,
            user_id=user.id,
            guest_ip=guest_ip,
            character_id=payload.character_id,
            endpoint="/api/chat/send",
            request_chars=estimate["chars"],
            estimated_input_tokens=estimate["tokens"],
            estimated_output_tokens=actual_output_tokens,
            total_estimated_tokens=estimate["tokens"] + actual_output_tokens,
            used_fallback=used_fallback,
            status="fallback" if used_fallback else "success",
        )
    finally:
        conn.close()

    return {
        "reply": reply,
        "history_count": history_count,
        "summary_enabled": True,
        "character_state": character_state,
    }


@router.post("/chat/stream")
def chat_stream(
    payload: ChatSendPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    """
    流式发送聊天消息（Server-Sent Events）。
    
    前端通过 EventSource 接收：
        - event: chunk, data: {text: "..."}      # 逐字返回
        - event: done, data: {reply: "...", character_state: {...}}  # 完成
    """
    enforce_rate_limit(
        "chat_user",
        str(user.id),
        limit=CHAT_RATE_LIMIT_COUNT,
        window_seconds=CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail="聊天请求过于频繁",
    )

    conn = get_conn()
    try:
        guest_ip = get_request_client_ip(request)
        plan_policy = get_plan_policy(user.effective_plan)
        ai_config = get_ai_config(os.environ, profile=plan_policy["model_profile"])
        character, clean_text, recent_messages, memory_summary = prepare_chat_context(
            conn,
            user.id,
            payload.character_id,
            payload.message,
            persist_user_message=False,
            viewer_plan=user.effective_plan,
        )
        related_assets = get_linked_assets(conn, payload.character_id)
        character_state = get_character_state(conn, user.id, payload.character_id)
        stream_messages = build_layered_chat_messages(
            character, recent_messages, memory_summary,
            related_assets=related_assets, user_name=user.nickname,
            character_state=character_state,
        )
        estimate = estimate_messages_tokens(stream_messages)
        planned_tokens = estimate["tokens"] + AI_CHAT_MAX_OUTPUT_TOKENS
        enforce_daily_budget(
            conn,
            user_id=user.id,
            planned_tokens=planned_tokens,
            token_limit=plan_policy["token_limit"],
            token_limit_detail="你今天的 AI 使用额度已达上限，请明天再来",
        )
        store_user_message(conn, user.id, payload.character_id, clean_text)
    finally:
        conn.close()

    # 保存到闭包
    _user_id = user.id
    _character_id = payload.character_id
    _character = character
    _character_dict = dict(character)
    _guest_ip = guest_ip
    _estimate = estimate
    _ai_config = ai_config

    def event_generator():
        full_reply = ""
        stream_state = {"buffer": "", "in_think": False}
        used_mock = False

        try:
            for chunk in stream_chat_completion(
                stream_messages,
                _ai_config,
                max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS,
            ):
                visible_chunk = sanitize_stream_chunk(chunk, stream_state)
                if not visible_chunk:
                    continue
                full_reply += visible_chunk
                yield format_sse("chunk", {"text": visible_chunk})

            if stream_state.get("buffer") and not stream_state.get("in_think"):
                tail = stream_state["buffer"]
                if tail:
                    full_reply += tail
                    yield format_sse("chunk", {"text": tail})

            final_reply_raw = normalize_reply_text(full_reply)
            if not final_reply_raw:
                raise RuntimeError("模型返回了空内容")
        except Exception:
            used_mock = True
            final_reply_raw = build_mock_reply(_character, clean_text)
            yield format_sse("chunk", {"text": final_reply_raw})

        # 解析状态增量
        final_reply, delta = parse_state_update_tag(final_reply_raw)

        # 保存回复并应用状态更新
        save_conn = get_conn()
        new_state: dict[str, Any] | None = None
        try:
            save_assistant_message(save_conn, _user_id, _character_id, final_reply)
            actual_output_tokens = estimate_text_tokens(final_reply)
            log_ai_request(
                save_conn,
                user_id=_user_id,
                guest_ip=_guest_ip,
                character_id=_character_id,
                endpoint="/api/chat/stream",
                request_chars=_estimate["chars"],
                estimated_input_tokens=_estimate["tokens"],
                estimated_output_tokens=actual_output_tokens,
                total_estimated_tokens=_estimate["tokens"] + actual_output_tokens,
                used_fallback=used_mock,
                status="fallback" if used_mock else "success",
            )
            if delta:
                from services.character_state import apply_state_delta
                try:
                    raw_new_state = apply_state_delta(save_conn, _user_id, _character_id, delta)
                    new_state = {k: v for k, v in raw_new_state.items() if not k.startswith("_")}
                except Exception:
                    pass
            if new_state is None:
                raw_state = get_character_state(save_conn, _user_id, _character_id)
                new_state = {k: v for k, v in raw_state.items() if not k.startswith("_")}
        finally:
            save_conn.close()

        # 后台异步触发记忆摘要
        run_memory_summary_background(_user_id, _character_id, _character_dict)

        yield format_sse("done", {
            "reply": final_reply,
            "fallback": used_mock,
            "summary_enabled": True,
            "character_state": new_state,
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat/guest-stream")
def chat_guest_stream(payload: GuestChatPayload, request: Request) -> StreamingResponse:
    """
    游客试聊流式接口（无需登录）。
    
    - 不要求 token，不写数据库
    - 前端传入 guest_history（临时历史，最多 10 条）
    - 每次只做一次无状态的 AI 调用
    """
    enforce_rate_limit(
        "guest_chat_ip",
        get_request_client_ip(request),
        limit=GUEST_CHAT_RATE_LIMIT_COUNT,
        window_seconds=GUEST_CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail="发送太快了",
    )

    conn = get_conn()
    try:
        guest_ip = get_request_client_ip(request)
        plan_policy = get_plan_policy(GUEST_PLAN)
        ai_config = get_ai_config(os.environ, profile=plan_policy["model_profile"])
        character = get_character_or_404(conn, payload.character_id, viewer_plan=GUEST_PLAN)

        fake_history = [
            {"role": item.role, "content": item.content}
            for item in payload.guest_history
        ]
        try:
            preview_messages = build_layered_chat_messages(
                character=character,
                recent_messages=fake_history,
                memory_summary="",
                related_assets=[],
                user_name="访客",
                character_state=None,
            )
            preview_messages.append({"role": "user", "content": payload.message.strip()})
        except Exception:
            preview_messages = [
                {"role": "system", "content": f"你是{character['name']}，{character.get('subtitle', '一个有温度的 AI 角色')}。"},
                {"role": "user", "content": payload.message.strip()},
            ]

        estimate = estimate_messages_tokens(preview_messages)
        planned_tokens = estimate["tokens"] + AI_CHAT_MAX_OUTPUT_TOKENS
        enforce_daily_budget(
            conn,
            guest_ip=guest_ip,
            planned_tokens=planned_tokens,
            token_limit=plan_policy["token_limit"],
            token_limit_detail="今日游客体验额度已用完，登录后可继续聊天",
        )
    finally:
        conn.close()

    _character = character
    _clean_text = payload.message.strip()
    _guest_ip = guest_ip
    _estimate = estimate
    _ai_config = ai_config

    def _build_guest_messages():
        """组装游客对话的消息列表。"""
        fake_history = [
            {"role": item.role, "content": item.content}
            for item in payload.guest_history
        ]
        try:
            msgs = build_layered_chat_messages(
                character=character,
                recent_messages=fake_history,
                memory_summary="",
                related_assets=[],
                user_name="访客",
                character_state=None,
            )
            msgs.append({"role": "user", "content": _clean_text})
            return msgs
        except Exception:
            # 降级方案
            return [
                {"role": "system", "content": f"你是{character['name']}，{character.get('subtitle', '一个有温度的 AI 角色')}。"},
                {"role": "user", "content": _clean_text},
            ]

    stream_messages = _build_guest_messages()

    def event_generator():
        full_reply = ""
        stream_state = {"buffer": "", "in_think": False}
        used_mock = False
        try:
            for chunk in stream_chat_completion(
                stream_messages,
                _ai_config,
                max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS,
            ):
                visible_chunk = sanitize_stream_chunk(chunk, stream_state)
                if not visible_chunk:
                    continue
                full_reply += visible_chunk
                yield format_sse("chunk", {"text": visible_chunk})

            if stream_state.get("buffer") and not stream_state.get("in_think"):
                tail = stream_state["buffer"]
                if tail:
                    full_reply += tail
                    yield format_sse("chunk", {"text": tail})

            final_reply_raw = normalize_reply_text(full_reply)
            if not final_reply_raw:
                raise RuntimeError("模型返回了空内容")
        except Exception:
            used_mock = True
            final_reply_raw = build_mock_reply(_character, _clean_text)
            yield format_sse("chunk", {"text": final_reply_raw})

        # 游客接口：不解析 STATE_UPDATE，不写库
        final_reply, _ = parse_state_update_tag(final_reply_raw)

        log_conn = get_conn()
        try:
            actual_output_tokens = estimate_text_tokens(final_reply)
            log_ai_request(
                log_conn,
                user_id=None,
                guest_ip=_guest_ip,
                character_id=payload.character_id,
                endpoint="/api/chat/guest-stream",
                request_chars=_estimate["chars"],
                estimated_input_tokens=_estimate["tokens"],
                estimated_output_tokens=actual_output_tokens,
                total_estimated_tokens=_estimate["tokens"] + actual_output_tokens,
                used_fallback=used_mock,
                status="fallback" if used_mock else "success",
            )
        finally:
            log_conn.close()

        yield format_sse("done", {
            "reply": final_reply,
            "fallback": used_mock,
            "guest": True,
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")
