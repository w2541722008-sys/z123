"""
管理后台 - 共享常量和工具函数
"""

from __future__ import annotations

import logging

from core.database import ConnType
from core.exceptions import BadRequestError
from repositories import character_admin_memory_repository as memory_repo
from repositories import character_admin_story_repository as story_repo

logger = logging.getLogger(__name__)

# 管理后台可编辑的字段白名单
_ADMIN_EDITABLE_FIELDS = {
    "name",
    "abbr",
    "subtitle",
    "description",
    "tags",
    "opening_message",
    "system_prompt",
    "sort_order",
    "is_visible",
    "home_priority",
    "card_type",
    "required_plan",
    "affection_enabled",
    "affection_rules_json",
    "import_locked",
    "avatar_url",
    "cover_url",
    "phase_behaviors_json",
    "life_profile_json",
}


def _transaction(conn, func):
    """
    在事务中执行函数，出错时自动回滚。
    """
    try:
        result = func()
        conn.commit()
        return result
    except Exception:
        logger.exception("管理后台事务执行失败")
        conn.rollback()
        raise


def _normalize_pagination(page: int, limit: int, *, max_limit: int) -> tuple[int, int]:
    safe_limit = min(limit, max_limit)
    offset = (max(1, page) - 1) * safe_limit
    return offset, safe_limit


def _validate_pagination_params(page: int, limit: int, *, max_limit: int) -> None:
    if page < 1:
        raise BadRequestError(detail="page参数必须大于等于1")
    if limit < 1 or limit > max_limit:
        raise BadRequestError(detail=f"limit参数必须在1-{max_limit}之间")


def _build_where_clause(conditions: list[str]) -> str:
    return "WHERE " + " AND ".join(conditions) if conditions else ""


def _split_csv_ids(raw: str | None) -> list[str]:
    out: list[str] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(part)
    return out


def _assert_memory_category_owned(
    conn: ConnType,
    character_id: str,
    category_id: str | None,
) -> None:
    if category_id is None:
        return
    if not memory_repo.admin_get_memory_category(conn, category_id, character_id):
        raise BadRequestError(detail="分类不存在或不属于该角色")


def _assert_storyline_owned(
    conn: ConnType,
    character_id: str,
    storyline_id: str | None,
) -> None:
    if storyline_id is None:
        return
    if not story_repo.admin_get_storyline(conn, storyline_id, character_id):
        raise BadRequestError(detail="剧情线不存在或不属于该角色")


def _assert_story_event_unlock_refs_owned(
    conn: ConnType,
    character_id: str,
    unlocked_memory_ids: str | None,
    unlocked_greeting_ids: str | None,
    unlocked_storyline_id: str | None,
) -> None:
    memory_ids = _split_csv_ids(unlocked_memory_ids)
    greeting_ids = _split_csv_ids(unlocked_greeting_ids)

    # 解锁目标只需存在且属于该角色，不要求 is_active=1
    # 因为解锁类对象（记忆、开场白、剧情线）通常 is_active=0，
    # 正是由故事事件触发后才激活
    if memory_ids:
        valid_memory_ids = memory_repo.admin_list_memory_ids(conn, character_id)
        bad_ids = [x for x in memory_ids if x not in valid_memory_ids]
        if bad_ids:
            raise BadRequestError(detail=f"存在无效的记忆解锁对象：{bad_ids}")

    if greeting_ids:
        valid_greeting_ids = story_repo.admin_list_greeting_ids(conn, character_id)
        bad_ids = [x for x in greeting_ids if x not in valid_greeting_ids]
        if bad_ids:
            raise BadRequestError(detail=f"存在无效的开场白解锁对象：{bad_ids}")

    if unlocked_storyline_id:
        if not story_repo.admin_get_storyline(
            conn, unlocked_storyline_id, character_id
        ):
            raise BadRequestError(detail="解锁的剧情线不存在或不属于该角色")
