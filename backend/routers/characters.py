from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from core.auth import CurrentUser, get_current_user, get_optional_user
from core.database import ConnType, get_db_dep
from core.schemas import CharacterProfileUpdatePayload, ClearChatPayload
from repositories import character_repository as char_repo
from repositories import chat_repository as chat_repo
from services.character_session_service import (
    clear_chat_history_with_greeting,
    reset_character_chat_state,
)
from services.character_state import get_character_state
from services.chat_query import ensure_opening_message, get_character_or_404
from utils.json_utils import parse_json_list, parse_json_object
from services.cache_service import cache_get, cache_set
from core.plan_constants import (
    GUEST_PLAN,
    can_access_required_plan,
    normalize_required_plan,
    plan_display_name,
)
from core.config import logger

router = APIRouter()


def _serialize_character_for_client(
    conn: ConnType,
    row: Any,
    user_id: int | str | None = None,
    overrides_map: dict[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """把角色数据库行转换成前端直接可用的结构。"""
    char_id = row["id"]
    if overrides_map is not None:
        remark, custom_signature = overrides_map.get(char_id, ("", ""))
    else:
        remark, custom_signature = char_repo.get_user_overrides(conn, user_id, char_id)

    avatar_value = (row["avatar_url"] or "").strip()
    cover_value = (row["cover_url"] or "").strip() or avatar_value

    # 图片 URL 版本号：基于路径内容生成，路径不变则版本不变，变更后浏览器自动拉新
    import hashlib
    _img_version = hashlib.md5((avatar_value + "|" + cover_value).encode()).hexdigest()[:8]

    avatar_img = f"/api/avatar/{char_id}?v={_img_version}" if avatar_value else ""
    cover_img = f"/api/cover/{char_id}?v={_img_version}" if cover_value else ""
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


def _get_accessible_character(conn: ConnType, character_id: str, viewer_plan: str):
    """读取单个可访问角色，不满足时抛出 404/403。"""
    return get_character_or_404(conn, character_id, viewer_plan=viewer_plan)


@router.get("/characters")
def list_characters(user: CurrentUser | None = Depends(get_optional_user), conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    """获取可见角色列表（按 home_priority 排序）。优先从缓存读取。"""
    viewer_plan = _get_viewer_plan(user)
    cache_key = "character_list_all"
    cached_rows = cache_get(cache_key)

    if cached_rows is None:
        cached_rows = char_repo.list_visible_characters(conn)
        cache_set(cache_key, cached_rows, ttl=3600)

    visible_rows = [
        row for row in cached_rows if can_access_required_plan(viewer_plan, row.get("required_plan", "guest"))
    ]
    overrides_map = char_repo.get_user_overrides_map(conn, user.id if user else None)
    return [
        _serialize_character_for_client(
            conn,
            row,
            user.id if user else None,
            overrides_map=overrides_map,
        )
        for row in visible_rows
    ]


@router.get("/character/profile")
def get_character_profile(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """获取用户对某角色的个性化配置（备注、签名）。"""
    char_row = _get_accessible_character(conn, character_id, user.effective_plan)
    character = _serialize_character_for_client(conn, char_row, user.id)
    return {
        "character": character,
        "remark": character["remark"],
        "custom_signature": character["custom_signature"],
    }


@router.post("/character/profile")
def update_character_profile(
    payload: CharacterProfileUpdatePayload,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """更新用户对某角色的个性化配置。"""
    _get_accessible_character(conn, payload.character_id, user.effective_plan)
    char_repo.upsert_user_profile(
        conn,
        user_id=user.id,
        character_id=payload.character_id,
        remark=payload.remark,
        custom_signature=payload.custom_signature,
    )
    conn.commit()

    char_row = char_repo.get_character_by_id(conn, payload.character_id)

    return {
        "ok": True,
        "character": _serialize_character_for_client(conn, char_row, user.id),
    }


@router.get("/character/greetings")
def get_character_greetings(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    获取角色的开场白列表。

    返回：
        - first_mes: 默认开场白
        - alternate_greetings: 备选开场白列表
        - total: 总数
    """
    row = _get_accessible_character(conn, character_id, user.effective_plan)

    first_mes = (row["opening_message"] or "").strip()
    structured = parse_json_object(row["structured_asset_json"], fallback={})
    greetings: list[dict[str, Any]] = []
    seen_contents: set[str] = set()

    if first_mes:
        greetings.append(
            {
                "index": 0,
                "label": "默认开场",
                "preview": first_mes[:100],
                "content": first_mes,
            }
        )
        seen_contents.add(first_mes)

    db_rows = char_repo.get_active_greetings(conn, character_id)

    for g in db_rows:
        content = (g["content"] or "").strip()
        if not content or content in seen_contents:
            continue
        label = g["storyline_name"] or f"{g['story_phase']} / {g['mood'] or '默认'}"
        greetings.append(
            {
                "index": g["id"],
                "label": label,
                "preview": content[:100],
                "content": content,
            }
        )
        seen_contents.add(content)

    if not db_rows:
        alts = structured.get("alternate_greetings", []) if structured else []
        if isinstance(alts, list):
            for idx, item in enumerate(alts, start=1):
                content = str(item).strip()
                if not content or content in seen_contents:
                    continue
                greetings.append(
                    {
                        "index": idx,
                        "label": f"备选开场 {idx}",
                        "preview": content[:100],
                        "content": content,
                    }
                )
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


@router.get("/character/state")
def get_character_state_api(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """获取用户与某角色的关系状态（好感度、剧情阶段、心情）。"""
    _get_accessible_character(conn, character_id, user.effective_plan)
    state = get_character_state(conn, user.id, character_id)
    clean_state = {k: v for k, v in state.items() if not k.startswith("_")}
    # 从角色卡配置中提取 show_bar 偏好，供前端控制状态栏显隐
    show_bar = True
    try:
        row = conn.execute(
            "SELECT affection_rules_json FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if row and row["affection_rules_json"]:
            rules = parse_json_object(row["affection_rules_json"], fallback={})
            if "show_bar" in rules:
                show_bar = bool(rules["show_bar"])
    except Exception:
        pass
    return {"state": clean_state, "show_bar": show_bar}


@router.post("/character/state/reset")
def reset_character_state(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """重置用户与某角色的关系状态（清空聊天记录、重置状态）。"""
    _get_accessible_character(conn, character_id, user.effective_plan)
    result = reset_character_chat_state(
        conn,
        user_id=user.id,
        character_id=character_id,
        clear_state=True,
    )
    return {"message": "关系状态已重置", "state": result["state"]}


@router.post("/chat/clear")
def clear_chat_history(
    payload: ClearChatPayload,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    清空聊天记录并重新选择开场白。

    greeting_index:
        - -1/0: 使用默认开场白
        - 1,2,...: 使用 alternate_greetings 中的对应开场白
    """
    _get_accessible_character(conn, payload.character_id, user.effective_plan)
    greeting = clear_chat_history_with_greeting(
        conn,
        user_id=user.id,
        character_id=payload.character_id,
        greeting_index=payload.greeting_index,
    )
    return {"ok": True, "greeting": greeting}


@router.get("/chat/history")
def chat_history(
    character_id: str,
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数，最大 200"),
) -> dict[str, Any]:
    """获取聊天历史记录（分页）。"""
    char_row = _get_accessible_character(conn, character_id, user.effective_plan)
    ensure_opening_message(conn, user.id, character_id)

    total = chat_repo.count_chat_history(conn, user.id, character_id)
    offset = (page - 1) * page_size
    messages = chat_repo.get_chat_history(conn, user.id, character_id, limit=page_size, offset=offset)

    return {
        "character": _serialize_character_for_client(conn, char_row, user.id),
        "character_id": character_id,
        "messages": messages,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": offset + page_size < total,
    }
