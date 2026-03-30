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
import sqlite3
from typing import Any

from fastapi import HTTPException

from config import AI_CHAT_MAX_OUTPUT_TOKENS, utc_now_iso
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


# ============================================================
# 角色查询
# ============================================================
def get_character_or_404(
    conn: sqlite3.Connection,
    character_id: str,
    viewer_plan: str | None = None,
) -> sqlite3.Row:
    """获取角色，不存在时抛出 404。"""
    from fastapi import HTTPException
    row = conn.execute(
        "SELECT * FROM characters WHERE id = ? AND is_visible = 1",
        (character_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")
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
    conn: sqlite3.Connection,
    character_id: str,
    story_phase: str = "stranger",
) -> str | None:
    """
    根据关系阶段获取对应的开场白。
    
    优先级：
    1. 从 character_greetings 表中查询匹配当前阶段的开场白
    2. 如果没有匹配，返回 characters.opening_message
    
    参数：
        conn: 数据库连接
        character_id: 角色ID
        story_phase: 关系阶段 (stranger/acquaintance/friend/lover)
    
    返回：
        开场白内容，或 None
    """
    # 1. 尝试从多阶段开场白表中获取
    row = conn.execute(
        """
        SELECT content FROM character_greetings
        WHERE character_id = ? AND story_phase = ? AND is_active = 1
        ORDER BY priority ASC, RANDOM()
        LIMIT 1
        """,
        (character_id, story_phase),
    ).fetchone()
    
    if row and row["content"]:
        return row["content"]
    
    # 2. 回退到角色的默认开场白
    row = conn.execute(
        "SELECT opening_message FROM characters WHERE id = ?",
        (character_id,),
    ).fetchone()
    
    return row["opening_message"] if row else None


def ensure_opening_message(
    conn: sqlite3.Connection,
    user_id: int,
    character_id: str,
) -> None:
    """
    确保用户首次和角色对话时，数据库里有一条角色的开场白。
    
    根据当前关系阶段选择对应的开场白，支持多阶段开场白系统。
    """
    # 检查是否已有消息
    row = conn.execute(
        "SELECT 1 FROM chat_messages WHERE user_id = ? AND character_id = ? LIMIT 1",
        (user_id, character_id),
    ).fetchone()
    if row:
        return  # 已有消息，不需要开场白
    
    # 获取当前关系阶段
    from services.character_state import get_character_state
    state = get_character_state(conn, user_id, character_id)
    story_phase = state.get("story_phase", "stranger") if state else "stranger"
    
    # 获取对应阶段的开场白
    greeting = get_greeting_for_phase(conn, character_id, story_phase)
    
    if not greeting:
        return
    
    # 插入开场白作为第一条消息
    conn.execute(
        """
        INSERT INTO chat_messages(user_id, character_id, role, content, created_at, is_summarized)
        VALUES (?, ?, 'assistant', ?, ?, 1)
        """,
        (user_id, character_id, greeting, utc_now_iso()),
    )
    conn.commit()
    
    # 更新开场白使用次数
    conn.execute(
        """
        UPDATE character_greetings 
        SET use_count = use_count + 1 
        WHERE character_id = ? AND story_phase = ? AND is_active = 1
        AND content = ?
        """,
        (character_id, story_phase, greeting),
    )
    conn.commit()


def prepare_chat_context(
    conn: sqlite3.Connection,
    user_id: int,
    character_id: str,
    user_message: str,
    persist_user_message: bool = True,
    viewer_plan: str | None = None,
) -> tuple[sqlite3.Row, str, list[dict[str, str]], str]:
    """
    准备聊天所需的上下文数据。
    
    返回：
        (character, clean_text, recent_messages, memory_summary)
    """
    character = get_character_or_404(conn, character_id, viewer_plan=viewer_plan)
    clean_text = user_message.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    ensure_opening_message(conn, user_id, character_id)

    if persist_user_message:
        store_user_message(conn, user_id, character_id, clean_text)

    # 读取最近消息和摘要
    recent_messages = get_recent_messages(conn, user_id, character_id)
    if not persist_user_message and clean_text:
        recent_messages.append({"role": "user", "content": clean_text})
    memory_summary = get_summary_for_prompt(conn, user_id, character_id)
    
    return character, clean_text, recent_messages, memory_summary


# ============================================================
# 消息保存和统计
# ============================================================
def save_assistant_message(conn: sqlite3.Connection, user_id: int, character_id: str, reply: str) -> None:
    """保存 AI 助手的回复到数据库。"""
    conn.execute(
        "INSERT INTO chat_messages(user_id, character_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
        (user_id, character_id, reply, utc_now_iso()),
    )
    conn.commit()


def store_user_message(conn: sqlite3.Connection, user_id: int, character_id: str, content: str) -> None:
    """保存用户消息到数据库。"""
    conn.execute(
        "INSERT INTO chat_messages(user_id, character_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
        (user_id, character_id, content, utc_now_iso()),
    )
    conn.commit()


def count_chat_messages(conn: sqlite3.Connection, user_id: int, character_id: str) -> int:
    """统计用户和某角色的聊天消息总数。"""
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM chat_messages WHERE user_id = ? AND character_id = ?",
        (user_id, character_id),
    ).fetchone()
    return int(row["total"]) if row else 0


def get_linked_assets(conn: sqlite3.Connection, character_id: str) -> list[sqlite3.Row]:
    """
    获取角色关联的资产列表（世界卡/剧情卡等）。
    
    当前 MVP 阶段暂未建立关联表，默认返回空列表。
    """
    return []


# ============================================================
# AI 回复生成
# ============================================================
def build_reply_with_fallback(
    character: sqlite3.Row,
    recent_messages: list[dict[str, str]],
    memory_summary: str,
    related_assets: list[sqlite3.Row] | None = None,
    user_name: str = "",
    conn: sqlite3.Connection | None = None,
    user_id: int | None = None,
    ai_config: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any] | None, bool]:
    """
    组装 Prompt → 调用 AI → 解析状态增量 → 返回 (cleaned_reply, new_state)。
    
    参数：
        conn, user_id — 可选，用于读取/写入关系状态
    
    返回：
        (reply_text, new_state, used_fallback)
        reply_text — 去掉 [STATE_UPDATE] 标签后的纯净回复
        new_state  — 更新后的关系状态字典，若未处理则为 None
        used_fallback — 是否走了 mock 降级
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
        used_fallback = False
    except Exception:
        user_message = recent_messages[-1]["content"] if recent_messages else ""
        return build_mock_reply(character, user_message), None, True

    # 解析状态增量
    cleaned_reply, delta = parse_state_update_tag(raw_reply)

    # 应用增量到 DB
    new_state: dict[str, Any] | None = None
    if delta and conn is not None and user_id is not None:
        try:
            new_state = apply_state_delta(conn, user_id, character["id"], delta)
        except Exception:
            pass  # 状态更新失败不影响正常回复

    return cleaned_reply, new_state, used_fallback


def build_mock_reply(character: sqlite3.Row, user_message: str) -> str:
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
