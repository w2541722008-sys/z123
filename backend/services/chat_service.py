"""
聊天服务 - 处理 AI 对话核心逻辑

核心功能：
- 准备聊天上下文（保存用户消息、读取历史、读取摘要）
- 构建 AI Prompt 并调用模型
- 处理流式响应
- 保存 AI 回复
- 触发后台记忆摘要

设计原则：
- 不直接处理 HTTP，只处理数据流
- 支持同步和流式两种模式
- 失败时有降级方案（mock reply）
"""

from __future__ import annotations

import json
import os
from typing import Any


class AIChatError(Exception):
    """AI 调用失败时抛出的异常，由调用方决定如何向用户展示错误。"""

    pass

from fastapi import HTTPException

from config import AI_CHAT_MAX_OUTPUT_TOKENS, logger, utc_now_iso
from model_adapter import get_ai_config, request_chat_completion
from prompt_assembler import build_layered_chat_messages
from services.plan_service import ensure_plan_access, plan_display_name
from services.character_state import apply_state_delta, get_character_state
from services.memory_service import (
    get_recent_messages,
    get_summary_for_prompt,
    normalize_reply_text,
    parse_state_update_tag,
)
from services.cache_service import get_character, set_character


# ============================================================
# 角色查询
# ============================================================
def get_character_or_404(
    conn: Any,
    character_id: str,
    viewer_plan: str | None = None,
) -> Any:
    """获取角色，不存在时抛出 404。优先从缓存读取。"""
    from fastapi import HTTPException
    
    # 尝试从缓存获取
    cached = get_character(character_id)
    if cached:
        row = cached
    else:
        # 缓存未命中，查询数据库
        row = conn.execute(
            "SELECT * FROM characters WHERE id = %s AND is_visible = 1",
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")
        # 存入缓存
        set_character(character_id, row)
    
    if viewer_plan is not None:
        required_plan = row["required_plan"] if "required_plan" in row.keys() else "guest"
        ensure_plan_access(
            viewer_plan,
            required_plan,
            detail=f"该角色仅 {plan_display_name(required_plan)} 可访问",
        )
    return row


# ============================================================
# 聊天上下文准备
# ============================================================
def get_greeting_for_phase(
    conn: Any,
    character_id: str,
    story_phase: str = "stranger",
    storyline_id: int | None = None,
) -> tuple[int | None, str | None]:
    """
    根据关系阶段获取对应的开场白。
    
    优先级：
    1. 从 character_greetings 表中查询匹配当前阶段和剧情线的开场白
    2. 如果没有匹配，返回 characters.opening_message
    
    参数：
        conn: 数据库连接
        character_id: 角色ID
        story_phase: 关系阶段 (stranger/acquaintance/friend/lover)
        storyline_id: 剧情线ID（可选），如果提供则优先匹配该剧情线的开场白
    
    返回：
        (greeting_id, 开场白内容)
        - 命中 character_greetings 时返回真实 greeting_id
        - 回退到 characters.opening_message 时返回 (None, content)
    """
    # 1. 尝试从多阶段开场白表中获取
    # 如果提供了 storyline_id，优先匹配该剧情线的开场白
    if storyline_id:
        # 将 storyline_id 转为字符串，与数据库 TEXT 类型保持一致
        storyline_id_str = str(storyline_id)
        row = conn.execute(
            """
            SELECT id, content FROM character_greetings
            WHERE character_id = %s AND story_phase = %s AND is_active = 1
              AND (storyline_id = %s OR storyline_id IS NULL)
            ORDER BY 
                CASE WHEN storyline_id = %s THEN 0 ELSE 1 END,
                priority ASC, RANDOM()
            LIMIT 1
            """,
            (character_id, story_phase, storyline_id_str, storyline_id_str),
        ).fetchone()
        
        # 如果指定了剧情线但没匹配到，记录日志（便于调试）
        if not row:
            import logging
            logging.getLogger(__name__).info(
                f"未找到剧情线 {storyline_id} 的开场白，将尝试通用开场白"
            )
    
    # 2. 如果没有指定剧情线，或指定剧情线未匹配到，尝试通用开场白
    if not row:
        row = conn.execute(
            """
            SELECT id, content FROM character_greetings
            WHERE character_id = %s AND story_phase = %s AND is_active = 1
              AND storyline_id IS NULL
            ORDER BY priority ASC, RANDOM()
            LIMIT 1
            """,
            (character_id, story_phase),
        ).fetchone()
    
    if row and row["content"]:
        return row["id"], row["content"]
    
    # 3. 回退到角色的默认开场白
    row = conn.execute(
        "SELECT opening_message FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    
    return None, (row["opening_message"] if row else None)


def ensure_opening_message(
    conn: Any,
    user_id: int,
    character_id: str,
    *,
    commit: bool = True,
) -> None:
    """
    确保用户首次和角色对话时，数据库里有一条角色的开场白。
    
    根据当前关系阶段选择对应的开场白，支持多阶段开场白系统。
    """
    # 检查是否已有消息
    row = conn.execute(
        "SELECT 1 FROM chat_messages WHERE user_id = %s AND character_id = %s LIMIT 1",
        (user_id, character_id),
    ).fetchone()
    if row:
        return  # 已有消息，不需要开场白
    
    # 获取当前关系阶段和剧情线
    from services.character_state import get_character_state
    state = get_character_state(conn, user_id, character_id)
    story_phase = state.get("story_phase", "stranger") if state else "stranger"
    storyline_id = state.get("storyline_id") if state else None
    
    # 获取对应阶段和剧情线的开场白
    greeting_id, greeting = get_greeting_for_phase(conn, character_id, story_phase, storyline_id)
    
    if not greeting:
        return
    
    # 插入开场白与更新 use_count 保持同一事务，避免半成功
    conn.execute(
        """
        INSERT INTO chat_messages(user_id, character_id, role, content, created_at, is_summarized)
        VALUES (%s, %s, 'assistant', %s, %s, 1)
        """,
        (user_id, character_id, greeting, utc_now_iso()),
    )

    if greeting_id is not None:
        conn.execute(
            """
            UPDATE character_greetings 
            SET use_count = use_count + 1 
            WHERE id = %s AND character_id = %s
            """,
            (greeting_id, character_id),
        )

    if commit:
        conn.commit()



def prepare_chat_context(
    conn: Any,
    user_id: int,
    character_id: str,
    user_message: str,
    persist_user_message: bool = True,
    viewer_plan: str | None = None,
    *,
    commit: bool = True,
) -> tuple[Any, str, list[dict[str, str]], str]:
    """
    准备聊天所需的上下文数据。
    
    返回：
        (character, clean_text, recent_messages, memory_summary)
    """
    character = get_character_or_404(conn, character_id, viewer_plan=viewer_plan)
    clean_text = user_message.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    ensure_opening_message(conn, user_id, character_id, commit=False)

    if persist_user_message:
        store_user_message(conn, user_id, character_id, clean_text, commit=False)

    # 读取最近消息和摘要
    recent_messages = get_recent_messages(conn, user_id, character_id)
    if not persist_user_message and clean_text:
        recent_messages.append({"role": "user", "content": clean_text})
    memory_summary = get_summary_for_prompt(conn, user_id, character_id)

    if commit:
        conn.commit()
    
    return character, clean_text, recent_messages, memory_summary


# ============================================================
# 消息保存和统计
# ============================================================
def save_assistant_message(
    conn: Any,
    user_id: int,
    character_id: str,
    reply: str,
    *,
    commit: bool = True,
) -> None:
    """保存 AI 助手的回复到数据库。"""
    conn.execute(
        "INSERT INTO chat_messages(user_id, character_id, role, content, created_at) VALUES (%s, %s, 'assistant', %s, %s)",
        (user_id, character_id, reply, utc_now_iso()),
    )
    if commit:
        conn.commit()


def store_user_message(
    conn: Any,
    user_id: int,
    character_id: str,
    content: str,
    *,
    commit: bool = True,
) -> None:
    """保存用户消息到数据库。"""
    conn.execute(
        "INSERT INTO chat_messages(user_id, character_id, role, content, created_at) VALUES (%s, %s, 'user', %s, %s)",
        (user_id, character_id, content, utc_now_iso()),
    )
    if commit:
        conn.commit()


def count_chat_messages(conn: Any, user_id: int, character_id: str) -> int:
    """统计用户和某角色的聊天消息总数。"""
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM chat_messages WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    ).fetchone()
    return int(row["total"]) if row else 0


def get_linked_assets(conn: Any, character_id: str) -> list[Any]:
    """
    获取角色关联的资产列表（世界卡/剧情卡等）。
    
    当前 MVP 阶段暂未建立关联表，默认返回空列表。
    """
    return []


# ============================================================
# AI 回复生成
# ============================================================
def build_reply_with_fallback(
    character: Any,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    related_assets: list[Any] | None = None,
    user_name: str = "",
    conn: Any | None = None,
    user_id: int | None = None,
    ai_config: dict[str, str] | None = None,
    *,
    commit: bool = True,
) -> tuple[str, dict[str, Any] | None]:
    """
    组装 Prompt → 调用 AI → 解析状态增量 → 返回 (cleaned_reply, new_state)。
    
    AI 调用失败时抛出 AIChatError，由调用方决定如何向用户展示错误。
    不再静默降级为 mock 回复，避免用户误以为假回复是真回复。
    
    参数：
        conn, user_id — 可选，用于读取/写入关系状态
        commit — 是否在内部提交状态更新；需要与外层事务合并时可设为 False
    
    返回：
        (reply_text, new_state)
        reply_text — 去掉 [STATE_UPDATE] 标签后的纯净回复
        new_state  — 更新后的关系状态字典，若未处理则为 None
    """
    # 读取当前关系状态
    character_state: dict[str, Any] | None = None
    if conn is not None and user_id is not None:
        character_state = get_character_state(conn, user_id, character["id"])

    messages = build_layered_chat_messages(
        character, recent_messages, memory_summary,
        related_assets=related_assets, user_name=user_name,
        character_state=character_state,
    )
    
    try:
        raw_reply = request_chat_completion(
            messages,
            ai_config or get_ai_config(os.environ),
            normalize_reply_text,
            max_tokens=AI_CHAT_MAX_OUTPUT_TOKENS,
        )
    except Exception as e:
        # AI 调用失败时直接抛出异常，由调用方决定如何处理
        # 不再静默降级返回 mock，避免用户误以为假回复是真回复
        raise AIChatError(f"AI 调用失败: {e}") from e

    # 解析状态增量
    cleaned_reply, delta = parse_state_update_tag(raw_reply)

    # 应用增量到 DB
    new_state: dict[str, Any] | None = None
    if delta and conn is not None and user_id is not None:
        try:
            new_state = apply_state_delta(conn, user_id, character["id"], delta, commit=commit)
        except Exception as exc:
            logger.warning(
                "角色状态更新失败 user_id=%s character_id=%s delta=%s error=%s",
                user_id,
                character["id"],
                delta,
                exc,
            )

    return cleaned_reply, new_state


def build_mock_reply(character: Any, user_message: str) -> str:
    """
    生成 fallback mock 回复。
    
    当真实 AI 调用失败时使用，根据 mock_reply_style 轮换回复风格。
    """
    styles = json.loads(character["mock_reply_style"])
    if not styles:
        return "我在，你继续说。"
    fingerprint = sum(ord(ch) for ch in user_message) % len(styles)
    base = styles[fingerprint]

    # 通用情感关键词额外拼接
    if any(keyword in user_message for keyword in ["累", "困", "难受", "烦", "崩溃", "委屈", "哭"]):
        return f"{base}先别想别的，先说说你现在的感受。"

    if any(keyword in user_message for keyword in ["想你", "喜欢你", "爱你", "爱上了"]):
        return f"{base}……我听到了，继续说。"

    return base


# ============================================================
# SSE 格式化
# ============================================================
def format_sse(event: str, data: dict[str, Any]) -> str:
    """
    格式化 Server-Sent Events (SSE) 消息。
    
    格式：
        event: <event_name>
        data: <json_data>
        
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
