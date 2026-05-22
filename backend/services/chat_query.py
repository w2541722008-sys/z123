"""
聊天查询服务 - 角色查询、消息加载、上下文准备

职责：
- 角色查询（带缓存）
- 开场白获取
- 消息加载与统计
- Regenerate/Continue 目标消息查询
"""

from __future__ import annotations

from typing import Any

from core.exceptions import BadRequestError, NotFoundError
from core.config import logger
from core.database import ConnType
from repositories import chat_repository as chat_repo
from services.cache_service import get_character, set_character
from core.plan_constants import plan_display_name
from services.plan_service import ensure_plan_access
from services.character_state import get_character_state, get_greeting_for_phase
from services.memory_service import get_recent_messages, get_summary_for_prompt


# ============================================================
# 消息投影工具（供 chat_send / chat_retry 共用）
# ============================================================
def message_projection(role: Any, content: Any) -> dict[str, Any]:
    """将 role/content 组装为消息字典。"""
    return {
        "role": role,
        "content": content,
    }


def _message_with_id_projection(message_id: Any, role: Any, content: Any) -> dict[str, Any]:
    return {
        "id": str(message_id),
        "role": role,
        "content": content,
    }


# ============================================================
# 角色查询
# ============================================================
def get_character_or_404(
    conn: ConnType,
    character_id: str,
    viewer_plan: str | None = None,
) -> Any:
    """获取角色，不存在时抛出 404。优先从缓存读取。"""
    
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
            raise NotFoundError(detail="角色不存在")
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


def ensure_opening_message(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    *,
    commit: bool = True,
) -> None:
    """
    确保用户首次和角色对话时，数据库里有一条角色的开场白。
    
    同时处理关系阶段升级的触发语：如果有暂存的升级消息，
    在用户已有聊天记录的情况下，以角色主动消息的形式插入。
    """
    # 优先处理关系阶段升级的触发语（即使已有聊天记录也要插入）
    state = get_character_state(conn, user_id, character_id)
    if state and state.get("custom_vars"):
        pending_upgrade = state["custom_vars"].get("_pending_phase_upgrade")
        if pending_upgrade and pending_upgrade.get("greeting"):
            upgrade_greeting = pending_upgrade["greeting"]
            # 插入升级触发语作为角色的主动消息
            conn.execute(
                """
                INSERT INTO chat_messages(user_id, character_id, role, content, is_summarized)
                VALUES (%s, %s, 'assistant', %s, 1)
                """,
                (user_id, character_id, upgrade_greeting),
            )
            # 清除已消费的升级标记（直接 SQL，避免循环导入 character_state.upsert）
            import json
            state["custom_vars"].pop("_pending_phase_upgrade", None)
            conn.execute(
                """
                UPDATE character_states
                SET custom_vars = %s, updated_at = now()
                WHERE user_id = %s AND character_id = %s
                """,
                (json.dumps(state["custom_vars"], ensure_ascii=False), user_id, character_id),
            )
            if commit:
                conn.commit()
            return

    if chat_repo.message_exists(conn, user_id, character_id):
        return  # 已有消息，不需要开场白
    
    # 获取当前关系阶段和剧情线
    story_phase = state.get("story_phase", "stranger") if state else "stranger"
    storyline_id = state.get("storyline_id") if state else None
    
    # 获取对应阶段和剧情线的开场白
    greeting_id, greeting = get_greeting_for_phase(conn, character_id, story_phase, storyline_id)
    
    if not greeting:
        return
    
    # 插入开场白与更新 use_count 保持同一事务
    conn.execute(
        """
        INSERT INTO chat_messages(user_id, character_id, role, content, is_summarized)
        VALUES (%s, %s, 'assistant', %s, 1)
        """,
        (user_id, character_id, greeting),
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


# ============================================================
# 消息校验与加载
# ============================================================
def _normalize_non_empty_message(user_message: str) -> str:
    clean_text = user_message.strip()
    if not clean_text:
        raise BadRequestError(detail="消息不能为空")
    return clean_text


def _load_recent_messages_and_summary(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    clean_text: str,
    persist_user_message: bool,
) -> tuple[list[dict[str, str]], str]:
    recent_messages = get_recent_messages(conn, user_id, character_id)
    if not persist_user_message and clean_text:
        recent_messages.append({"role": "user", "content": clean_text})
    memory_summary = get_summary_for_prompt(conn, user_id, character_id)
    return recent_messages, memory_summary


# ============================================================
# 消息统计
# ============================================================
def search_chat_messages(
    conn: ConnType,
    user_id: int | str,
    query: str,
    *,
    character_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """全文搜索聊天消息（委托 repository 层执行 tsquery 查询）。"""
    from repositories.chat_repository import search_messages
    return search_messages(conn, user_id, query, character_id=character_id, limit=limit, offset=offset)


def count_chat_search_results(
    conn: ConnType,
    user_id: int | str,
    query: str,
    *,
    character_id: str | None = None,
) -> int:
    """统计搜索结果总数（委托 repository 层）。"""
    from repositories.chat_repository import count_search_results
    return count_search_results(conn, user_id, query, character_id=character_id)


def count_chat_messages(conn: ConnType, user_id: int | str, character_id: str) -> int:
    """统计用户和某角色的聊天消息总数。"""
    return chat_repo.count_chat_history(conn, user_id, character_id)


def get_last_chat_time(conn: ConnType, user_id: int | str, character_id: str) -> str | None:
    """获取用户与角色最近一条 assistant 消息的 created_at 时间戳，用于判断久未聊天。"""
    return chat_repo.get_last_assistant_message_time(conn, user_id, character_id)


def get_linked_assets(conn: ConnType, character_id: str) -> list[Any]:
    """
    获取角色关联的资产列表（世界卡/剧情卡等）。
    
    当前 MVP 阶段暂未建立关联表，默认返回空列表。
    """
    return []


# ============================================================
# Regenerate/Continue 目标消息查询
# ============================================================
def get_message_for_regenerate_or_continue(
    conn: ConnType,
    user_id: int | str,
    message_id: str,
    operation: str = "regenerate",
) -> tuple[dict[str, Any], str]:
    """
    获取要 regenerate/continue 的目标 assistant 消息及角色信息。
    
    返回：
        (message_row, character_id)
    
    异常：
        HTTPException 404: 消息不存在或不属于当前用户
        HTTPException 400: 消息不是 assistant 类型
    """
    _ = operation

    row = chat_repo.get_assistant_message_by_id(conn, message_id, user_id)

    if not row:
        raise NotFoundError(detail="消息不存在或无权操作")

    return dict(row), row["character_id"]
