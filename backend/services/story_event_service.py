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

logger = logging.getLogger(__name__)


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

    Args:
        conn: 数据库连接
        user_id: 用户ID
        character_id: 角色ID
        current_affection: 当前好感度
        current_phase: 当前关系阶段
        custom_vars: 当前自定义变量（用于 trigger_custom_key 条件检查）

    Returns:
        触发的事件列表，每个事件包含标题、描述、解锁内容等
    """
    triggered: list[dict[str, Any]] = []
    _custom_vars = custom_vars or {}

    try:
        # 1. 获取该角色所有启用的剧情事件
        events = conn.execute(
            """
            SELECT id, title, description, trigger_score, trigger_custom_key,
                   unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
                   event_content, is_active
            FROM story_events
            WHERE character_id = %s AND is_active = 1
            ORDER BY trigger_score ASC
            """,
            (character_id,),
        ).fetchall()

        if not events:
            return triggered

        # 2. 获取用户已触发的事件ID列表
        progress_row = conn.execute(
            """
            SELECT triggered_event_ids FROM user_story_progress
            WHERE user_id = %s AND character_id = %s
            """,
            (user_id, character_id),
        ).fetchone()

        triggered_ids = set()
        if progress_row and progress_row["triggered_event_ids"]:
            triggered_ids = set(
                int(x.strip())
                for x in str(progress_row["triggered_event_ids"]).split(",")
                if x.strip().isdigit()
            )

        # 3. 检查每个事件是否应该触发
        new_triggered_ids = []
        for event in events:
            event_id = event["id"]

            # 已触发过，跳过
            if event_id in triggered_ids:
                continue

            # 好感度未达到触发阈值，跳过
            if current_affection < event["trigger_score"]:
                continue

            # 自定义变量条件检查：trigger_custom_key 中的所有键必须存在于 custom_vars 且非空
            trigger_keys_str = (event.get("trigger_custom_key") or "").strip()
            if trigger_keys_str:
                required_keys = [k.strip() for k in trigger_keys_str.split(",") if k.strip()]
                if required_keys:
                    all_keys_present = all(
                        k in _custom_vars and _custom_vars[k] not in (None, "", 0, False)
                        for k in required_keys
                    )
                    if not all_keys_present:
                        continue

            # 触发事件
            new_triggered_ids.append(str(event_id))

            event_data = {
                "id": event_id,
                "title": event["title"],
                "description": event["description"] or "",
                "trigger_score": event["trigger_score"],
                "event_content": event["event_content"] or "",
                "unlocked": {},
            }

            # 4. 解锁相关内容
            # 解锁记忆条目
            if event["unlocked_memory_ids"]:
                memory_ids = [
                    int(x.strip())
                    for x in str(event["unlocked_memory_ids"]).split(",")
                    if x.strip().isdigit()
                ]
                if memory_ids:
                    # 激活这些记忆条目
                    placeholders = ",".join(["%s"] * len(memory_ids))
                    conn.execute(
                        f"""
                        UPDATE character_memories
                        SET is_active = 1
                        WHERE character_id = %s AND id IN ({placeholders})
                        """,
                        (character_id,) + tuple(memory_ids),
                    )
                    event_data["unlocked"]["memories"] = memory_ids

            # 解锁开场白
            if event["unlocked_greeting_ids"]:
                greeting_ids = [
                    int(x.strip())
                    for x in str(event["unlocked_greeting_ids"]).split(",")
                    if x.strip().isdigit()
                ]
                if greeting_ids:
                    # 激活这些开场白
                    placeholders = ",".join(["%s"] * len(greeting_ids))
                    conn.execute(
                        f"""
                        UPDATE character_greetings
                        SET is_active = 1
                        WHERE character_id = %s AND id IN ({placeholders})
                        """,
                        (character_id,) + tuple(greeting_ids),
                    )
                    event_data["unlocked"]["greetings"] = greeting_ids

            # 解锁剧情线
            if event["unlocked_storyline_id"]:
                storyline_id = int(event["unlocked_storyline_id"])
                conn.execute(
                    """
                    UPDATE character_storylines
                    SET is_active = 1
                    WHERE character_id = %s AND id = %s
                    """,
                    (character_id, storyline_id),
                )
                event_data["unlocked"]["storyline_id"] = storyline_id

            triggered.append(event_data)

        # 5. 更新用户剧情进度
        if new_triggered_ids:
            all_triggered = triggered_ids | set(int(x) for x in new_triggered_ids)
            all_triggered_str = ",".join(sorted(str(x) for x in all_triggered))

            conn.execute(
                """
                INSERT INTO user_story_progress
                (user_id, character_id, triggered_event_ids, current_storyline_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(user_id, character_id) DO UPDATE SET
                    triggered_event_ids = excluded.triggered_event_ids,
                    last_updated = now()
                """,
                (
                    user_id,
                    character_id,
                    all_triggered_str,
                    None,  # current_storyline_id 保持不变
                ),
            )
            if commit:
                conn.commit()

    except Exception as e:
        # 剧情事件触发失败不应影响主流程，记录完整错误信息
        logger.error("剧情事件触发失败: %s", e, exc_info=True)

    return triggered
