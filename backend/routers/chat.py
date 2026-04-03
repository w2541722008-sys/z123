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
import time
from typing import Any

# 第三方库导入
from fastapi import APIRouter, Depends, HTTPException, Request
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
from services.character_state import apply_state_delta, get_character_state
from services.chat_service import (
    AIChatError,
    build_layered_chat_messages,
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


SSE_STREAM_TIMEOUT = 120


def _stream_ai_completion(stream_messages: list, ai_config: dict):
    """
    公共 AI 流式调用生成器。
    
    消除 chat_stream / guest_stream / regenerate / continue 四处重复的流式循环代码。
    依次 yield SSE chunk 事件，最后返回 (final_reply_raw, error_msg) 元组。
    
    用法:
        for sse_event in _stream_ai_completion(messages, config):
            yield sse_event  # chunk 或 error 事件
        # 循环结束后，final_reply 已就绪
    """
    full_reply = ""
    stream_state = {"buffer": "", "in_think": False}
    _stream_start = time.monotonic()

    try:
        for chunk in stream_chat_completion(
            stream_messages,
            ai_config,
            max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS,
        ):
            if time.monotonic() - _stream_start > SSE_STREAM_TIMEOUT:
                raise TimeoutError(f"SSE 流式响应超时（{SSE_STREAM_TIMEOUT}秒）")
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

        return final_reply_raw, None

    except Exception as e:
        return full_reply, str(e)


def _build_guest_fallback_messages(character: dict, user_message: str) -> list[dict]:
    """
    构建游客模式的降级Prompt，在主流程失败时使用。
    
    尽可能保留角色的核心设定，确保游客也能获得完整的角色体验。
    包含：角色基础信息、详细描述、性格、世界观、示例对话等。
    
    Args:
        character: 角色数据字典
        user_message: 用户输入的消息
        
    Returns:
        组装好的消息列表，可直接用于AI调用
    """
    # 构建系统提示词，尽可能包含角色的完整设定
    system_parts = []
    
    # 1. 角色身份基础
    name = character.get('name', 'AI角色')
    subtitle = character.get('subtitle', '')
    base_identity = f"你是{name}"
    if subtitle:
        base_identity += f"，{subtitle}"
    system_parts.append(base_identity)
    
    # 2. 详细描述（description）
    description = character.get('description', '')
    if description:
        system_parts.append(f"\n【角色背景】\n{description}")
    
    # 3. 性格特征（personality）
    personality = character.get('personality', '')
    if personality:
        system_parts.append(f"\n【性格特点】\n{personality}")
    
    # 4. 世界观/场景（scenario）
    scenario = character.get('scenario', '')
    if scenario:
        system_parts.append(f"\n【世界观/场景】\n{scenario}")
    
    # 5. 角色设定前（world_info_before）
    world_info_before = character.get('world_info_before', '')
    if world_info_before:
        system_parts.append(f"\n【角色设定】\n{world_info_before}")
    
    # 6. 示例对话（example_dialogue）
    example_dialogue = character.get('example_dialogue', '')
    if example_dialogue:
        system_parts.append(f"\n【参考对话风格】\n{example_dialogue}")
    
    # 7. 角色设定后（world_info_after）
    world_info_after = character.get('world_info_after', '')
    if world_info_after:
        system_parts.append(f"\n【补充设定】\n{world_info_after}")
    
    # 8. 后置规则（post_history_rules）
    post_rules = character.get('post_history_rules', '')
    if post_rules:
        system_parts.append(f"\n【回复规则】\n{post_rules}")
    
    # 9. 系统指令
    system_parts.append("\n【重要指令】")
    system_parts.append("1. 始终保持角色设定，用第一人称回复")
    system_parts.append("2. 回复自然、有温度，符合角色性格")
    system_parts.append("3. 在回复末尾添加状态更新标签，格式：<STATE_UPDATE>{\"mood\": \"心情\", \"affection\": 数值}</STATE_UPDATE>")
    
    # 组装完整系统提示词
    system_content = "\n".join(system_parts)
    
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]


def _rollback_latest_user_message(user_id: int, character_id: str) -> None:
    """回滚最近一条用户消息（在AI回复失败时调用）。"""
    conn = get_conn()
    try:
        conn.execute(
            """
            DELETE FROM chat_messages 
            WHERE user_id = %s AND character_id = %s AND role = 'user'
            AND id = (SELECT MAX(id) FROM chat_messages WHERE user_id = %s AND character_id = %s AND role = 'user')
            """,
            (user_id, character_id, user_id, character_id)
        )
        conn.commit()
    finally:
        conn.close()


def _log_chat_failure(
    *,
    user_id: int | None,
    guest_ip: str,
    character_id: str,
    endpoint: str,
    estimate: dict[str, int],
    error_detail: str,
    estimated_output_tokens: int = 0,
) -> None:
    """尽量补记失败请求日志，避免线上排查时只看到成功请求。"""
    log_conn = get_conn()
    try:
        total_estimated_tokens = estimate["tokens"] + max(0, estimated_output_tokens)
        log_ai_request(
            log_conn,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint=endpoint,
            request_chars=estimate["chars"],
            estimated_input_tokens=estimate["tokens"],
            estimated_output_tokens=max(0, estimated_output_tokens),
            total_estimated_tokens=total_estimated_tokens,
            used_fallback=False,
            status="error",
            error_detail=error_detail,
        )
    except Exception:
        # 失败日志写入不能反过来影响主流程
        pass
    finally:
        log_conn.close()


def _persist_stream_result(
    *,
    user_id: int,
    guest_ip: str,
    character_id: str,
    final_reply: str,
    estimate: dict[str, int],
    delta: dict[str, Any] | None,
    user_message: str | None = None,  # 新增：用户消息内容
) -> dict[str, Any]:
    """统一落库用户消息、流式回复、消耗日志和角色状态，任一步失败都整体回滚。返回包含 character_state 和 message_id 的字典。"""
    save_conn = get_conn()
    message_id = None
    try:
        # 先写用户消息（如果提供了）
        if user_message:
            store_user_message(save_conn, user_id, character_id, user_message, commit=False)
        # 再写 AI 回复（获取 message_id）
        message_id = save_assistant_message(save_conn, user_id, character_id, final_reply, commit=False)
        actual_output_tokens = estimate_text_tokens(final_reply)
        log_ai_request(
            save_conn,
            user_id=user_id,
            guest_ip=guest_ip,
            character_id=character_id,
            endpoint="/api/chat/stream",
            request_chars=estimate["chars"],
            estimated_input_tokens=estimate["tokens"],
            estimated_output_tokens=actual_output_tokens,
            total_estimated_tokens=estimate["tokens"] + actual_output_tokens,
            used_fallback=False,
            status="success",
            commit=False,
        )
        if delta:
            raw_state = apply_state_delta(
                save_conn,
                user_id,
                character_id,
                delta,
                commit=False,
            )
        else:
            raw_state = get_character_state(save_conn, user_id, character_id)
        save_conn.commit()
        result = {k: v for k, v in raw_state.items() if not k.startswith("_")}
        result["message_id"] = message_id
        return result
    except Exception:
        save_conn.rollback()
        raise
    finally:
        save_conn.close()


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
            commit=False,
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
        store_user_message(conn, user.id, payload.character_id, clean_text, commit=False)

        # 步骤 3：生成回复
        # AI 失败时抛出 AIChatError，此时用户消息已写但AI回复未写，
        # 需要回滚用户消息以保持数据一致性
        try:
            reply, new_state = build_reply_with_fallback(
                character, recent_messages, memory_summary,
                related_assets=related_assets, user_name=user.nickname,
                conn=conn, user_id=user.id,
                ai_config=ai_config,
                commit=False,
            )

            # 步骤 4：保存消息、日志和状态，统一在一次事务里提交
            save_assistant_message(conn, user.id, payload.character_id, reply, commit=False)
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
                used_fallback=False,
                status="success",
                commit=False,
            )
            conn.commit()
        except AIChatError as exc:
            conn.rollback()
            _log_chat_failure(
                user_id=user.id,
                guest_ip=guest_ip,
                character_id=payload.character_id,
                endpoint="/api/chat/send",
                estimate=estimate,
                error_detail=str(exc),
            )
            raise HTTPException(status_code=503, detail="网络波动，请稍后再试")
        except Exception as exc:
            conn.rollback()
            _log_chat_failure(
                user_id=user.id,
                guest_ip=guest_ip,
                character_id=payload.character_id,
                endpoint="/api/chat/send",
                estimate=estimate,
                error_detail=str(exc),
            )
            raise
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
            commit=False,
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
        # 用户消息留到流式完成后，与 AI 回复一起在 _persist_stream_result 中统一写入
    finally:
        conn.close()

    # 保存到闭包
    _user_id = user.id
    _character_id = payload.character_id
    _character = character
    _character_dict = dict(character)
    _guest_ip = guest_ip
    _estimate = estimate
    _user_message = clean_text  # 新增：保存用户消息内容
    _ai_config = ai_config

    def event_generator():
        stream_gen = _stream_ai_completion(stream_messages, _ai_config)
        final_reply_raw = None
        stream_error = None

        try:
            while True:
                result = next(stream_gen)
                if isinstance(result, tuple):
                    final_reply_raw, stream_error = result
                    break
                yield result
        except StopIteration as _si:
            if isinstance(_si.value, tuple):
                final_reply_raw, stream_error = _si.value

        if stream_error:
            _rollback_latest_user_message(_user_id, _character_id)
            _log_chat_failure(
                user_id=_user_id,
                guest_ip=_guest_ip,
                character_id=_character_id,
                endpoint="/api/chat/stream",
                estimate=_estimate,
                error_detail=stream_error,
                estimated_output_tokens=estimate_text_tokens(final_reply_raw or ""),
            )
            yield format_sse("error", {"message": "网络波动，请稍后再试"})
            return

        # 解析状态增量
        final_reply, delta = parse_state_update_tag(final_reply_raw)

        try:
            new_state = _persist_stream_result(
                user_id=_user_id,
                guest_ip=_guest_ip,
                character_id=_character_id,
                final_reply=final_reply,
                estimate=_estimate,
                delta=delta,
                user_message=_user_message,  # 传入用户消息
            )
        except Exception as exc:
            # 用户消息还未写入，无需回滚；AI 回复写入失败，所有操作已自动回滚
            _log_chat_failure(
                user_id=_user_id,
                guest_ip=_guest_ip,
                character_id=_character_id,
                endpoint="/api/chat/stream",
                estimate=_estimate,
                error_detail=f"persist_failed: {exc}",
                estimated_output_tokens=estimate_text_tokens(final_reply),
            )
            yield format_sse("error", {"message": "消息保存失败，请稍后再试"})
            return

        # 后台异步触发记忆摘要
        run_memory_summary_background(_user_id, _character_id, _character)

        yield format_sse("done", {
            "reply": final_reply,
            "fallback": False,
            "summary_enabled": True,
            "character_state": {k: v for k, v in new_state.items() if k != "message_id"},
            "message_id": new_state.get("message_id"),
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
            # 降级方案：尽可能保留角色核心设定，给游客完整体验
            preview_messages = _build_guest_fallback_messages(character, payload.message.strip())

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
            # 降级方案：尽可能保留角色核心设定
            return _build_guest_fallback_messages(character, _clean_text)

    stream_messages = _build_guest_messages()

    def event_generator():
        stream_gen = _stream_ai_completion(stream_messages, _ai_config)
        final_reply_raw = None
        stream_error = None

        try:
            while True:
                result = next(stream_gen)
                if isinstance(result, tuple):
                    final_reply_raw, stream_error = result
                    break
                yield result
        except StopIteration as _si:
            if isinstance(_si.value, tuple):
                final_reply_raw, stream_error = _si.value

        if stream_error:
            _log_chat_failure(
                user_id=None,
                guest_ip=_guest_ip,
                character_id=payload.character_id,
                endpoint="/api/chat/guest-stream",
                estimate=_estimate,
                error_detail=stream_error,
                estimated_output_tokens=estimate_text_tokens(final_reply_raw or ""),
            )
            yield format_sse("error", {"message": "网络波动，请稍后再试"})
            return

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
                used_fallback=False,
                status="success",
            )
        finally:
            log_conn.close()

        yield format_sse("done", {
            "reply": final_reply,
            "fallback": False,
            "guest": True,
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ============================================================
# Regenerate / Continue 功能 - 新增端点
# ============================================================

from models import RegeneratePayload, ContinuePayload
from services.chat_service import (
    get_message_for_regenerate_or_continue,
    save_regenerated_version,
    prepare_regenerate_context,
    prepare_continue_context,
    get_character_or_404,
    get_linked_assets,
)
from prompt_assembler import build_layered_chat_messages
from services.memory_service import (
    normalize_reply_text,
    parse_state_update_tag,
    sanitize_stream_chunk,
)


@router.post("/chat/regenerate")
def chat_regenerate(
    payload: RegeneratePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    """
    重新生成 AI 回复（流式 SSE）。
    
    用户对当前 AI 回复不满意时，点击"重新生成"按钮调用此接口。
    
    特点：
    - 上下文完全不变（使用相同的历史消息）
    - 保留旧版本到 versions 字段
    - 流式输出新回复（和 /chat/stream 相同的 SSE 格式）
    - 更新角色状态（解析 STATE_UPDATE）
    
    请求体：
        {"message_id": 123}
    
    响应：SSE 流式
        event: chunk → {"text": "..."}
        event: done  → {"reply": "...", "character_state": {...}, "version_index": N}
        event: error → {"message": "..."}
    """
    enforce_rate_limit(
        "chat_user",
        str(user.id),
        limit=CHAT_RATE_LIMIT_COUNT,
        window_seconds=CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail="操作过于频繁",
    )

    conn = get_conn()
    try:
        guest_ip = get_request_client_ip(request)
        
        # 1. 获取目标消息和上下文
        msg_row, _raw_recent, character_id = get_message_for_regenerate_or_continue(
            conn, user.id, payload.message_id, operation="regenerate"
        )

        _all_rows = conn.execute(
            """SELECT id, role, content, created_at FROM chat_messages
               WHERE user_id = %s AND character_id = %s
               ORDER BY created_at ASC, id ASC""",
            (user.id, character_id),
        ).fetchall()
        _chronological = [
            {"id": str(r["id"]), "role": r["role"], "content": r["content"]}
            for r in _all_rows
        ]
        _target_idx = None
        for _ri, _rm in enumerate(_chronological):
            if _rm["id"] == str(payload.message_id):
                _target_idx = _ri
                break

        if _target_idx is not None:
            recent_messages = _chronological[:_target_idx]
        else:
            recent_messages = _raw_recent

        while recent_messages and recent_messages[-1].get("role") == "assistant":
            recent_messages.pop()
        if not recent_messages and _raw_recent:
            recent_messages = [_raw_recent[0]]

        # 2. 准备聊天上下文
        plan_policy = get_plan_policy(user.effective_plan)
        ai_config = get_ai_config(os.environ, profile=plan_policy["model_profile"])
        
        character, memory_summary, _, related_assets = prepare_regenerate_context(
            conn, user.id, character_id, recent_messages, viewer_plan=user.effective_plan
        )
        
        # 获取角色状态
        character_state = get_character_state(conn, user.id, character_id)
        
        # 3. 构建 Prompt（使用原始历史消息，不包含当前 AI 回复）
        stream_messages = build_layered_chat_messages(
            character, recent_messages, memory_summary,
            related_assets=related_assets, user_name=user.nickname,
            character_state=character_state,
        )

        # 4. Token 预算检查
        estimate = estimate_messages_tokens(stream_messages)
        planned_tokens = estimate["tokens"] + AI_CHAT_MAX_OUTPUT_TOKENS
        enforce_daily_budget(
            conn,
            user_id=user.id,
            planned_tokens=planned_tokens,
            token_limit=plan_policy["token_limit"],
            token_limit_detail="你今天的 AI 使用额度已达上限，请明天再来",
        )
    finally:
        conn.close()

    _user_id = user.id
    _character_id = character_id
    _message_id = payload.message_id
    _character = character
    _guest_ip = guest_ip
    _estimate = estimate
    _ai_config = ai_config

    def event_generator():
        stream_gen = _stream_ai_completion(stream_messages, _ai_config)
        final_reply_raw = None
        stream_error = None

        try:
            while True:
                result = next(stream_gen)
                if isinstance(result, tuple):
                    final_reply_raw, stream_error = result
                    break
                yield result
        except StopIteration as _si:
            if isinstance(_si.value, tuple):
                final_reply_raw, stream_error = _si.value

        if stream_error:
            _log_chat_failure(
                user_id=_user_id,
                guest_ip=_guest_ip,
                character_id=_character_id,
                endpoint="/api/chat/regenerate",
                estimate=_estimate,
                error_detail=stream_error,
                estimated_output_tokens=estimate_text_tokens(final_reply_raw or ""),
            )
            yield format_sse("error", {"message": "网络波动，请稍后再试"})
            return

        # 解析状态增量
        final_reply, delta = parse_state_update_tag(final_reply_raw)

        try:
            # 保存到数据库（含版本管理）
            save_conn = get_conn()
            try:
                # 保存新生成的版本
                save_regenerated_version(
                    save_conn, _message_id, final_reply, is_append=False, commit=False
                )
                
                # 记录请求日志
                actual_output_tokens = estimate_text_tokens(final_reply)
                log_ai_request(
                    save_conn,
                    user_id=_user_id,
                    guest_ip=_guest_ip,
                    character_id=_character_id,
                    endpoint="/api/chat/regenerate",
                    request_chars=_estimate["chars"],
                    estimated_input_tokens=_estimate["tokens"],
                    estimated_output_tokens=actual_output_tokens,
                    total_estimated_tokens=_estimate["tokens"] + actual_output_tokens,
                    used_fallback=False,
                    status="success",
                    commit=False,
                )
                
                # 应用状态增量
                new_state = None
                if delta:
                    new_state = apply_state_delta(
                        save_conn, _user_id, _character_id, delta, commit=False
                    )
                
                save_conn.commit()
                
                if new_state:
                    raw_state = {k: v for k, v in new_state.items() if not k.startswith("_")}
                else:
                    raw_state = get_character_state(save_conn, _user_id, _character_id)
                    raw_state = {k: v for k, v in raw_state.items() if not k.startswith("_")}
                    
            except Exception as exc:
                save_conn.rollback()
                _log_chat_failure(
                    user_id=_user_id,
                    guest_ip=_guest_ip,
                    character_id=_character_id,
                    endpoint="/api/chat/regenerate",
                    estimate=_estimate,
                    error_detail=f"persist_failed: {exc}",
                    estimated_output_tokens=estimate_text_tokens(final_reply),
                )
                yield format_sse("error", {"message": "消息保存失败，请稍后再试"})
                return
            finally:
                save_conn.close()
        except Exception as _regen_outer_exc:
            import logging as _regen_log
            _regen_log.getLogger(__name__).warning(f"[regenerate] outer error before done: {_regen_outer_exc}", exc_info=True)
            yield format_sse("error", {"message": "保存失败，请稍后再试"})
            return

        # 后台异步触发记忆摘要
        run_memory_summary_background(_user_id, _character_id, _character)

        yield format_sse("done", {
            "reply": final_reply,
            "fallback": False,
            "summary_enabled": True,
            "character_state": raw_state,
            "message_id": _message_id,
            "operation": "regenerate",
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/chat/continue")
def chat_continue(
    payload: ContinuePayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    """
    继续（追加）生成 AI 回复（流式 SSE）。
    
    当 AI 回复太短或被截断时，用户点击"继续"按钮追加内容。
    
    特点：
    - 在当前回复末尾追加新内容
    - 保留所有历史版本
    - 流式输出追加的内容
    
    请求体：
        {"message_id": 123}
    
    响应：SSE 流式
        event: chunk → {"text": "..."}
        event: done  → {"reply": "完整回复（原+新）", "character_state": {...}, "appended_text": "新增部分"}
        event: error → {"message": "..."}
    """
    enforce_rate_limit(
        "chat_user",
        str(user.id),
        limit=CHAT_RATE_LIMIT_COUNT,
        window_seconds=CHAT_RATE_LIMIT_WINDOW_SECONDS,
        detail="操作过于频繁",
    )

    conn = get_conn()
    try:
        guest_ip = get_request_client_ip(request)

        # 1. 获取目标消息和上下文（使用时间排序，与 regenerate 保持一致）
        msg_row, _raw_recent, character_id = get_message_for_regenerate_or_continue(
            conn, user.id, payload.message_id, operation="continue"
        )

        _all_rows = conn.execute(
            """SELECT id, role, content, created_at FROM chat_messages
               WHERE user_id = %s AND character_id = %s
               ORDER BY created_at ASC, id ASC""",
            (user.id, character_id),
        ).fetchall()
        _chronological = [
            {"id": str(r["id"]), "role": r["role"], "content": r["content"]}
            for r in _all_rows
        ]
        _target_idx = None
        for _ri, _rm in enumerate(_chronological):
            if _rm["id"] == str(payload.message_id):
                _target_idx = _ri
                break

        if _target_idx is not None:
            recent_messages = _chronological[:_target_idx]
        else:
            recent_messages = _raw_recent

        while recent_messages and recent_messages[-1].get("role") == "assistant":
            recent_messages.pop()
        if not recent_messages and _raw_recent:
            recent_messages = [_raw_recent[0]]

        current_content = msg_row["content"] or ""
        
        # 2. 准备聊天上下文（特殊：包含当前回复+继续指令）
        plan_policy = get_plan_policy(user.effective_plan)
        ai_config = get_ai_config(os.environ, profile=plan_policy["model_profile"])
        
        character, memory_summary, continue_messages, related_assets = prepare_continue_context(
            conn, user.id, character_id, payload.message_id,
            current_content, recent_messages, viewer_plan=user.effective_plan
        )
        
        # 获取角色状态
        character_state = get_character_state(conn, user.id, character_id)
        
        # 3. 构建 Prompt（包含当前回复和继续指令）
        stream_messages = build_layered_chat_messages(
            character, continue_messages, memory_summary,
            related_assets=related_assets, user_name=user.nickname,
            character_state=character_state,
        )
        
        # 4. Token 预算检查
        estimate = estimate_messages_tokens(stream_messages)
        planned_tokens = estimate["tokens"] + AI_CHAT_MAX_OUTPUT_TOKENS
        enforce_daily_budget(
            conn,
            user_id=user.id,
            planned_tokens=planned_tokens,
            token_limit=plan_policy["token_limit"],
            token_limit_detail="你今天的 AI 使用额度已达上限，请明天再来",
        )
    finally:
        conn.close()

    _user_id = user.id
    _character_id = character_id
    _message_id = payload.message_id
    _current_content = current_content
    _character = character
    _guest_ip = guest_ip
    _estimate = estimate
    _ai_config = ai_config

    def event_generator():
        stream_gen = _stream_ai_completion(stream_messages, _ai_config)
        final_appended_raw = None
        stream_error = None

        try:
            while True:
                result = next(stream_gen)
                if isinstance(result, tuple):
                    final_appended_raw, stream_error = result
                    break
                yield result
        except StopIteration as _si:
            if isinstance(_si.value, tuple):
                final_appended_raw, stream_error = _si.value

        if stream_error:
            _log_chat_failure(
                user_id=_user_id,
                guest_ip=_guest_ip,
                character_id=_character_id,
                endpoint="/api/chat/continue",
                estimate=_estimate,
                error_detail=stream_error,
                estimated_output_tokens=estimate_text_tokens(final_appended_raw or ""),
            )
            yield format_sse("error", {"message": "网络波动，请稍后再试"})
            return

        # 解析状态增量（从追加的部分解析）
        final_appended, delta = parse_state_update_tag(final_appended_raw)

        try:
            save_conn = get_conn()
            try:
                # 保存追加后的完整版本
                save_regenerated_version(
                    save_conn, _message_id, final_appended, is_append=True, commit=False
                )
                
                # 记录请求日志
                actual_output_tokens = estimate_text_tokens(final_appended)
                log_ai_request(
                    save_conn,
                    user_id=_user_id,
                    guest_ip=_guest_ip,
                    character_id=_character_id,
                    endpoint="/api/chat/continue",
                    request_chars=_estimate["chars"],
                    estimated_input_tokens=_estimate["tokens"],
                    estimated_output_tokens=actual_output_tokens,
                    total_estimated_tokens=_estimate["tokens"] + actual_output_tokens,
                    used_fallback=False,
                    status="success",
                    commit=False,
                )
                
                # 应用状态增量
                new_state = None
                if delta:
                    new_state = apply_state_delta(
                        save_conn, _user_id, _character_id, delta, commit=False
                    )
                
                save_conn.commit()
                
                if new_state:
                    raw_state = {k: v for k, v in new_state.items() if not k.startswith("_")}
                else:
                    raw_state = get_character_state(save_conn, _user_id, _character_id)
                    raw_state = {k: v for k, v in raw_state.items() if not k.startswith("_")}
                    
            except Exception as exc:
                save_conn.rollback()
                _log_chat_failure(
                    user_id=_user_id,
                    guest_ip=_guest_ip,
                    character_id=_character_id,
                    endpoint="/api/chat/continue",
                    estimate=_estimate,
                    error_detail=f"persist_failed: {exc}",
                    estimated_output_tokens=estimate_text_tokens(final_appended),
                )
                yield format_sse("error", {"message": "保存失败，请稍后再试"})
                return
            finally:
                save_conn.close()
        except Exception as _cont_outer_exc:
            import logging as _cont_log
            _cont_log.getLogger(__name__).warning(f"[continue] outer error before done: {_cont_outer_exc}", exc_info=True)
            yield format_sse("error", {"message": "保存失败，请稍后再试"})
            return

        # 计算完整的回复内容（原始 + 追加）
        full_reply = _current_content + final_appended

        yield format_sse("done", {
            "reply": full_reply,
            "fallback": False,
            "summary_enabled": True,
            "character_state": raw_state,
            "message_id": _message_id,
            "operation": "continue",
            "appended_text": final_appended,
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")
