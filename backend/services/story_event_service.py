"""
剧情事件服务 - 好感度触发的剧情事件系统

从 character_state.py 拆分出来，职责：
    - 检查好感度阈值触发剧情事件
    - 解锁记忆条目、开场白、剧情线
    - 更新用户剧情进度
"""
from __future__ import annotations

import logging
from typing import Any

from core.database import ConnType
from repositories import story_repository as story_repo

logger = logging.getLogger(__name__)


# ── 子步骤 ──────────────────────────────────────────────

def _fetch_active_story_events(
    conn: ConnType, character_id: str
) -> list[dict[str, Any]]:
    """获取角色所有启用的剧情事件，按触发分数升序。"""
    return story_repo.fetch_active_story_events(conn, character_id)


def _load_triggered_event_ids(
    conn: ConnType, user_id: int | str, character_id: str
) -> set[int]:
    """读取用户已触发的剧情事件 ID 集合。"""
    return story_repo.get_triggered_event_ids(conn, user_id, character_id)


def _should_trigger_event(
    event: dict[str, Any],
    triggered_ids: set[int],
    current_affection: int,
    custom_vars: dict[str, Any],
) -> bool:
    """判断一个剧情事件是否应该触发（纯函数，不访问 DB）。"""
    if event["id"] in triggered_ids:
        return False

    if current_affection < event["trigger_score"]:
        return False

    trigger_keys_str = (event.get("trigger_custom_key") or "").strip()
    if trigger_keys_str:
        required_keys = [k.strip() for k in trigger_keys_str.split(",") if k.strip()]
        if required_keys and not all(
            k in custom_vars and custom_vars[k] not in (None, "", 0, False)
            for k in required_keys
        ):
            return False

    return True


def _unlock_event_assets(
    conn: ConnType,
    event: dict[str, Any],
    character_id: str,
) -> dict[str, Any]:
    """解锁事件关联的记忆、开场白、剧情线。返回解锁内容摘要。"""
    unlocked: dict[str, Any] = {}

    if event["unlocked_memory_ids"]:
        memory_ids = [
            int(x.strip())
            for x in str(event["unlocked_memory_ids"]).split(",")
            if x.strip().isdigit()
        ]
        if memory_ids:
            story_repo.unlock_memories(conn, character_id, memory_ids)
            unlocked["memories"] = memory_ids

    if event["unlocked_greeting_ids"]:
        greeting_ids = [
            int(x.strip())
            for x in str(event["unlocked_greeting_ids"]).split(",")
            if x.strip().isdigit()
        ]
        if greeting_ids:
            story_repo.unlock_greetings(conn, character_id, greeting_ids)
            unlocked["greetings"] = greeting_ids

    if event["unlocked_storyline_id"]:
        storyline_id = int(event["unlocked_storyline_id"])
        story_repo.unlock_storyline(conn, character_id, storyline_id)
        unlocked["storyline_id"] = storyline_id

    return unlocked


def _persist_story_progress(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    triggered_ids: set[int],
    new_triggered_ids: list[str],
    *,
    commit: bool = True,
) -> None:
    """将新触发的事件 ID 合并写入 user_story_progress。"""
    all_triggered = triggered_ids | set(int(x) for x in new_triggered_ids)
    all_triggered_str = ",".join(sorted(str(x) for x in all_triggered))

    story_repo.upsert_story_progress(conn, user_id, character_id, all_triggered_str)
    if commit:
        conn.commit()


# ── 主入口 ──────────────────────────────────────────────

def check_and_trigger_story_events(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    current_affection: int,
    current_phase: str,
    *,
    custom_vars: dict[str, Any] | None = None,
    commit: bool = True,
) -> list[dict[str, Any]]:
    """
    检查并触发剧情事件。

    当用户好感度达到事件触发阈值且自定义变量条件满足时，自动触发对应的剧情事件，
    解锁相关的记忆、开场白、剧情线等内容。
    """
    triggered: list[dict[str, Any]] = []
    _custom_vars = custom_vars or {}

    try:
        events = _fetch_active_story_events(conn, character_id)
        if not events:
            return triggered

        triggered_ids = _load_triggered_event_ids(conn, user_id, character_id)
        new_ids: list[str] = []

        for event in events:
            if not _should_trigger_event(event, triggered_ids, current_affection, _custom_vars):
                continue

            new_ids.append(str(event["id"]))
            event_data = {
                "id": event["id"],
                "title": event["title"],
                "description": event["description"] or "",
                "trigger_score": event["trigger_score"],
                "event_content": event["event_content"] or "",
                "unlocked": _unlock_event_assets(conn, event, character_id),
            }
            triggered.append(event_data)

        if new_ids:
            _persist_story_progress(
                conn, user_id, character_id, triggered_ids, new_ids, commit=commit,
            )

    except Exception as e:
        logger.error("剧情事件触发失败: %s", e, exc_info=True)

    return triggered
