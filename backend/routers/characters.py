"""
角色路由 - 处理角色列表、详情、状态、配置

端点：
    GET  /api/characters                    - 角色列表
    GET  /api/character/profile             - 获取用户对某角色的配置
    POST /api/character/profile             - 更新用户对某角色的配置
    GET  /api/character/greetings           - 获取角色开场白列表
    GET  /api/character/state               - 获取角色关系状态
    POST /api/character/state/reset         - 重置角色关系状态
    POST /api/chat/clear                    - 清空聊天记录
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import CurrentUser, get_current_user, get_optional_user
from config import utc_now_iso
from database import get_conn
from models import CharacterProfileUpdatePayload, ClearChatPayload
from services.character_state import get_character_state
from services.chat_service import ensure_opening_message, get_character_or_404
from services.memory_service import parse_json_list, parse_json_object
from services.plan_service import (
    GUEST_PLAN,
    can_access_required_plan,
    ensure_plan_access,
    normalize_required_plan,
    plan_display_name,
)

router = APIRouter()


def _get_user_character_overrides(
    conn: Any,
    user_id: int | None,
    character_id: str,
) -> tuple[str, str]:
    """读取用户对角色的私有备注和签名。"""
    if not user_id:
        return "", ""

    row = conn.execute(
        """
        SELECT remark, custom_signature
        FROM user_character_profiles
        WHERE user_id = ? AND character_id = ?
        """,
        (user_id, character_id),
    ).fetchone()
    if not row:
        return "", ""
    return (row["remark"] or "", row["custom_signature"] or "")


def _serialize_character_for_client(
    conn: Any,
    row: Any,
    user_id: int | None = None,
) -> dict[str, Any]:
    """把角色数据库行转换成前端直接可用的结构。"""
    char_id = row["id"]
    remark, custom_signature = _get_user_character_overrides(conn, user_id, char_id)

    avatar_value = (row["avatar_url"] or "").strip()
    cover_value = (row["cover_url"] or "").strip() or avatar_value
    avatar_img = f"/api/avatar/{char_id}" if avatar_value else ""
    cover_img = f"/api/cover/{char_id}" if cover_value else ""
    opening_message = row["opening_message"] or ""
    required_plan = normalize_required_plan(row["required_plan"] if "required_plan" in row.keys() else "guest")

    return {
        "id": char_id,
        "name": row["name"],
        "abbr": row["abbr"],
        "subtitle": row["subtitle"] or "",
        "avatar_url": avatar_img,
        "cover_url": cover_img,
        "avatarImg": avatar_img,
        "coverImg": cover_img,
        "description": row["description"] or "",
        "opening_message": opening_message,
        "first_message": opening_message,
        "tags": parse_json_list(row["tags"]),
        "card_type": row["card_type"] or "intimate",
        "required_plan": required_plan,
        "required_plan_label": plan_display_name(required_plan),
        "home_priority": row["home_priority"],
        "remark": remark,
        "custom_signature": custom_signature,
        "display_name": remark or row["name"],
        "sign": custom_signature or (row["subtitle"] or ""),
    }


def _get_viewer_plan(user: CurrentUser | None) -> str:
    """获取前台访问角色时的用户档位。"""
    return user.effective_plan if user else GUEST_PLAN


def _get_accessible_character(conn: Any, character_id: str, viewer_plan: str):
    """读取单个可访问角色，不满足时抛出 404/403。"""
    return get_character_or_404(conn, character_id, viewer_plan=viewer_plan)


@router.get("/characters")
def list_characters(user: CurrentUser | None = Depends(get_optional_user)) -> list[dict[str, Any]]:
    """获取可见角色列表（按 home_priority 排序）。"""
    conn = get_conn()
    try:
        viewer_plan = _get_viewer_plan(user)
        rows = conn.execute(
            """
            SELECT id, name, abbr, subtitle, avatar_url, cover_url, description, opening_message, tags,
                   card_type, home_priority, is_visible, required_plan
            FROM characters
            WHERE is_visible = 1
            ORDER BY home_priority ASC, sort_order ASC
            """
        ).fetchall()

        visible_rows = [
            row for row in rows
            if can_access_required_plan(viewer_plan, row["required_plan"] if "required_plan" in row.keys() else "guest")
        ]
        return [_serialize_character_for_client(conn, row, user.id if user else None) for row in visible_rows]
    finally:
        conn.close()


@router.get("/character/profile")
def get_character_profile(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """获取用户对某角色的个性化配置（备注、签名）。"""
    conn = get_conn()
    try:
        char_row = _get_accessible_character(conn, character_id, user.effective_plan)

        character = _serialize_character_for_client(conn, char_row, user.id)
        return {
            "character": character,
            "remark": character["remark"],
            "custom_signature": character["custom_signature"],
        }
    finally:
        conn.close()


@router.post("/character/profile")
def update_character_profile(
    payload: CharacterProfileUpdatePayload,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """更新用户对某角色的个性化配置。"""
    conn = get_conn()
    try:
        _get_accessible_character(conn, payload.character_id, user.effective_plan)
        now = utc_now_iso()
        conn.execute(
            """
            INSERT INTO user_character_profiles(user_id, character_id, remark, custom_signature, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, character_id) DO UPDATE SET
                remark = excluded.remark,
                custom_signature = excluded.custom_signature,
                updated_at = excluded.updated_at
            """,
            (user.id, payload.character_id, payload.remark, payload.custom_signature, now, now),
        )
        conn.commit()

        char_row = conn.execute(
            """
            SELECT id, name, abbr, subtitle, avatar_url, cover_url, description,
                   opening_message, tags, card_type, home_priority, required_plan
            FROM characters
            WHERE id = ?
            """,
            (payload.character_id,),
        ).fetchone()
        if not char_row:
            raise HTTPException(status_code=404, detail="角色不存在")

        return {
            "ok": True,
            "character": _serialize_character_for_client(conn, char_row, user.id),
        }
    finally:
        conn.close()


@router.get("/character/greetings")
def get_character_greetings(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    获取角色的开场白列表。
    
    返回：
        - first_mes: 默认开场白
        - alternate_greetings: 备选开场白列表
        - total: 总数
    """
    conn = get_conn()
    try:
        row = _get_accessible_character(conn, character_id, user.effective_plan)

        first_mes = (row["opening_message"] or "").strip()
        structured = parse_json_object(row["structured_asset_json"], fallback={})
        greetings: list[dict[str, Any]] = []
        seen_contents: set[str] = set()

        if first_mes:
            greetings.append({
                "index": 0,
                "label": "默认开场",
                "preview": first_mes[:100],
                "content": first_mes,
            })
            seen_contents.add(first_mes)

        db_rows = conn.execute(
            """
            SELECT g.id, g.content, g.story_phase, g.mood, g.storyline_id,
                   COALESCE(s.name, '') AS storyline_name
            FROM character_greetings g
            LEFT JOIN character_storylines s ON s.id = g.storyline_id
            WHERE g.character_id = ? AND g.is_active = 1 AND g.story_phase = 'stranger'
            ORDER BY g.priority ASC, g.id ASC
            """,
            (character_id,),
        ).fetchall()

        for g in db_rows:
            content = (g["content"] or "").strip()
            if not content or content in seen_contents:
                continue
            label = g["storyline_name"] or f"{g['story_phase']} / {g['mood'] or '默认'}"
            greetings.append({
                "index": g["id"],
                "label": label,
                "preview": content[:100],
                "content": content,
            })
            seen_contents.add(content)

        if not db_rows:
            alts = structured.get("alternate_greetings", []) if structured else []
            if isinstance(alts, list):
                for idx, item in enumerate(alts, start=1):
                    content = str(item).strip()
                    if not content or content in seen_contents:
                        continue
                    greetings.append({
                        "index": idx,
                        "label": f"备选开场 {idx}",
                        "preview": content[:100],
                        "content": content,
                    })
                    seen_contents.add(content)

        if not greetings:
            fallback = "你好，很高兴认识你。"
            greetings.append({"index": 0, "label": "默认开场", "preview": fallback, "content": fallback})
            first_mes = fallback

        return {
            "first_mes": greetings[0]["content"],
            "alternate_greetings": [item["content"] for item in greetings[1:]],
            "greetings": greetings,
            "total": len(greetings),
        }
    finally:
        conn.close()


@router.get("/character/state")
def get_character_state_api(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """获取用户与某角色的关系状态（好感度、剧情阶段、心情）。"""
    conn = get_conn()
    try:
        _get_accessible_character(conn, character_id, user.effective_plan)
        state = get_character_state(conn, user.id, character_id)
        # 过滤内部字段
        clean_state = {k: v for k, v in state.items() if not k.startswith("_")}
        return {"state": clean_state}
    finally:
        conn.close()


@router.post("/character/state/reset")
def reset_character_state(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """重置用户与某角色的关系状态（清空聊天记录、重置状态）。"""
    conn = get_conn()
    try:
        _get_accessible_character(conn, character_id, user.effective_plan)
        # 删除聊天记录
        conn.execute(
            "DELETE FROM chat_messages WHERE user_id = ? AND character_id = ?",
            (user.id, character_id),
        )
        # 删除摘要
        conn.execute(
            "DELETE FROM chat_summaries WHERE user_id = ? AND character_id = ?",
            (user.id, character_id),
        )
        # 删除状态
        conn.execute(
            "DELETE FROM character_states WHERE user_id = ? AND character_id = ?",
            (user.id, character_id),
        )
        conn.commit()

        # 重新插入开场白
        ensure_opening_message(conn, user.id, character_id)
        
        # 获取默认状态
        state = get_character_state(conn, user.id, character_id)
        return {"message": "关系状态已重置", "state": {k: v for k, v in state.items() if not k.startswith("_")}}
    finally:
        conn.close()


@router.post("/chat/clear")
def clear_chat_history(
    payload: ClearChatPayload,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    清空聊天记录并重新选择开场白。
    
    greeting_index:
        - -1/0: 使用默认开场白
        - 1,2,...: 使用 alternate_greetings 中的对应开场白
    """
    conn = get_conn()
    try:
        _get_accessible_character(conn, payload.character_id, user.effective_plan)
        # 删除聊天记录
        conn.execute(
            "DELETE FROM chat_messages WHERE user_id = ? AND character_id = ?",
            (user.id, payload.character_id),
        )
        # 删除摘要
        conn.execute(
            "DELETE FROM chat_summaries WHERE user_id = ? AND character_id = ?",
            (user.id, payload.character_id),
        )
        conn.commit()

        # 根据 greeting_index 选择开场白
        char_row = conn.execute(
            "SELECT opening_message, structured_asset_json FROM characters WHERE id = ?",
            (payload.character_id,),
        ).fetchone()

        greeting = "你好，很高兴认识你。"
        if char_row:
            if payload.greeting_index > 0:
                greeting_row = conn.execute(
                    """
                    SELECT content FROM character_greetings
                    WHERE id = ? AND character_id = ? AND is_active = 1
                    LIMIT 1
                    """,
                    (payload.greeting_index, payload.character_id),
                ).fetchone()
                if greeting_row and (greeting_row["content"] or "").strip():
                    greeting = greeting_row["content"].strip()

            structured = parse_json_object(char_row["structured_asset_json"], fallback={})
            alts = structured.get("alternate_greetings", [])
            
            idx = payload.greeting_index
            if idx <= 0:
                greeting = char_row["opening_message"] or (alts[0] if alts else greeting)
            elif greeting == "你好，很高兴认识你。" and isinstance(alts, list) and 1 <= idx <= len(alts):
                greeting = alts[idx - 1]

        # 插入新的开场白
        conn.execute(
            """
            INSERT INTO chat_messages(user_id, character_id, role, content, created_at, is_summarized)
            VALUES (?, ?, 'assistant', ?, ?, 1)
            """,
            (user.id, payload.character_id, greeting, utc_now_iso()),
        )
        conn.commit()

        return {"ok": True, "greeting": greeting}
    finally:
        conn.close()


@router.get("/chat/history")
def chat_history(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """获取聊天历史记录。"""
    conn = get_conn()
    try:
        char_row = _get_accessible_character(conn, character_id, user.effective_plan)
        ensure_opening_message(conn, user.id, character_id)

        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE user_id = ? AND character_id = ?
            ORDER BY id ASC
            """,
            (user.id, character_id),
        ).fetchall()

        messages = [
            {"role": row["role"], "content": row["content"], "created_at": row["created_at"]}
            for row in rows
        ]

        return {
            "character": _serialize_character_for_client(conn, char_row, user.id),
            "character_id": character_id,
            "messages": messages,
            "count": len(messages),
        }
    finally:
        conn.close()
