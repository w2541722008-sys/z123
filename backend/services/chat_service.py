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
    row = None
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
) -> int:
    """保存 AI 助手的回复到数据库。返回新消息的 ID。"""
    row = conn.execute(
        "INSERT INTO chat_messages(user_id, character_id, role, content, created_at) VALUES (%s, %s, 'assistant', %s, %s) RETURNING id",
        (user_id, character_id, reply, utc_now_iso()),
    ).fetchone()
    if commit:
        conn.commit()
    return row["id"] if row else None


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


# ============================================================
# Regenerate / Continue 功能 - 核心业务逻辑
# ============================================================

def get_message_for_regenerate_or_continue(
    conn: Any,
    user_id: int,
    message_id: int,
    operation: str = "regenerate",
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    """
    获取要 regenerate/continue 的消息及其上下文。
    
    参数：
        conn: 数据库连接
        user_id: 当前用户 ID
        message_id: 目标 AI 消息 ID
        operation: 操作类型 'regenerate' 或 'continue'
    
    返回：
        (message_row, recent_messages, character_id)
        message_row: 目标 AI 消息的数据库行
        recent_messages: 该消息之前的所有历史消息（用于构建上下文）
        character_id: 角色 ID
    
    异常：
        HTTPException 404: 消息不存在或不属于当前用户
        HTTPException 400: 消息不是 assistant 类型
    """
    from fastapi import HTTPException
    
    # 1. 查询目标消息
    row = conn.execute(
        """SELECT * FROM chat_messages 
           WHERE id = %s AND user_id = %s AND role = 'assistant'""",
        (message_id, user_id),
    ).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="消息不存在或无权操作")
    
    character_id = row["character_id"]
    
    # 2. 获取该消息之前的所有历史消息（不包括目标消息本身）
    #    这样可以保证 regenerate 时上下文完全一致
    history_rows = conn.execute(
        """SELECT role, content, created_at 
           FROM chat_messages 
           WHERE user_id = %s AND character_id = %s AND id < %s
           ORDER BY id ASC""",
        (user_id, character_id, message_id),
    ).fetchall()
    
    recent_messages = [
        {"role": r["role"], "content": r["content"]}
        for r in history_rows
    ]
    
    return dict(row), recent_messages, character_id


def save_regenerated_version(
    conn: Any,
    message_id: str,
    new_content: str,
    *,
    is_append: bool = False,
    commit: bool = True,
) -> None:
    """
    保存新生成的内容，仅保留最终版本到数据库。

    策略：不累积历史版本。每次 regenerate/continue 只保存最终结果。

    参数：
        conn: 数据库连接
        message_id: 目标消息 ID (UUID)
        new_content: 新生成的内容（regenerate=完整替换, continue=追加部分）
        is_append: True 表示 continue（追加），False 表示 regenerate（替换）
        commit: 是否立即提交事务
    """
    from config import utc_now_iso

    try:
        current_row = conn.execute(
            "SELECT content FROM chat_messages WHERE id = %s",
            (message_id,),
        ).fetchone()

        if not current_row:
            raise ValueError(f"消息 {message_id} 不存在")

        import json as _json
        now = utc_now_iso()

        if is_append:
            base_content = current_row["content"] or ""
            final_content = base_content + new_content
        else:
            final_content = new_content

        versions = [{
            "content": final_content,
            "created_at": now,
            "operation": "continue" if is_append else "regenerate",
        }]

        conn.execute(
            """UPDATE chat_messages
               SET content = %s,
                   versions = %s::jsonb,
                   current_version_index = 0,
                   updated_at = %s
               WHERE id = %s""",
            (final_content, _json.dumps(versions, ensure_ascii=False), now, message_id),
        )
    except Exception as e:
        import logging
        logging.warning(f"版本保存失败，降级为仅更新内容: {e}")
        now = utc_now_iso()

        if is_append:
            row = conn.execute(
                "SELECT content FROM chat_messages WHERE id = %s", (message_id,)
            ).fetchone()
            final_content = (row["content"] or "") + new_content if row else new_content
        else:
            final_content = new_content

        conn.execute(
            """UPDATE chat_messages
               SET content = %s, updated_at = %s
               WHERE id = %s""",
            (final_content, now, message_id),
        )

    if commit:
        conn.commit()

    if commit:
        conn.commit()


def prepare_regenerate_context(
    conn: Any,
    user_id: int,
    character_id: str,
    recent_messages: list[dict[str, str]],
    viewer_plan: str | None = None,
) -> tuple[Any, str, list[dict[str, str]], str]:
    """
    为 regenerate 准备完整的聊天上下文（复用 prepare_chat_context 逻辑）。
    
    返回：
        (character, memory_summary, recent_messages_with_memory, related_assets)
    """
    character = get_character_or_404(conn, character_id, viewer_plan=viewer_plan)
    
    # 读取记忆摘要
    memory_summary = get_summary_for_prompt(conn, user_id, character_id)
    
    # 获取关联资产
    related_assets = get_linked_assets(conn, character_id)
    
    return character, memory_summary, recent_messages, related_assets


def prepare_continue_context(
    conn: Any,
    user_id: int,
    character_id: str,
    message_id: int,
    current_content: str,
    recent_messages: list[dict[str, str]],
    viewer_plan: str | None = None,
) -> tuple[Any, str, list[dict[str, str]], str]:
    """
    为 continue 准备上下文：在历史消息中追加一条"继续"指令。
    
    Continue 的特殊之处：
    - 需要把当前 AI 回复作为上下文的一部分
    - 在末尾追加一个 system/user 提示让 AI 继续生成
    """
    character = get_character_or_404(conn, character_id, viewer_plan=viewer_plan)
    memory_summary = get_summary_for_prompt(conn, user_id, character_id)
    related_assets = get_linked_assets(conn, character_id)
    
    # 构建用于 continue 的消息列表：
    # 历史消息 + 当前的 assistant 回复 + 继续指令
    continue_messages = list(recent_messages)
    continue_messages.append({
        "role": "assistant",
        "content": current_content,
    })
    # 添加继续生成指令（以 user 角色注入，避免多条 system）
    continue_messages.append({
        "role": "user",
        "content": "【请继续】请接着上面的话继续说下去，保持角色设定和语气，不要重复已说过的内容。直接继续输出即可。",
    })
    
    return character, memory_summary, continue_messages, related_assets
