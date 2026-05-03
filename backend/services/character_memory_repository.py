"""
角色记忆与后置规则的数据查询层。

从 memory_service.py 拆分出来，职责：
    - 查询角色的记忆条目（关键词匹配）
    - 查询角色的后置规则（按条件过滤）
"""
from __future__ import annotations

from typing import Any

from core.database import ConnType


def fetch_character_memories(
    conn: ConnType,
    character_id: str,
    context_text: str,
    *,
    max_triggered: int = 12,
    max_per_entry: int = 500,
    wi_max: int = 8000,
) -> tuple[list[str], list[str]]:
    """
    从数据库查询角色的记忆条目，并根据上下文文本匹配关键词。

    参数：
        conn: 数据库连接
        character_id: 角色 ID
        context_text: 用于匹配的上下文文本
        max_triggered: 最多触发条目数
        max_per_entry: 单条最大字符数
        wi_max: WI 总字符上限

    返回：
        (before_list, after_list) — 分别对应 position='before' 和 'after' 的匹配内容列表
    """
    rows = conn.execute(
        """
        SELECT keywords, trigger_logic, content, position, priority
        FROM character_memories
        WHERE character_id = %s AND is_active = 1
        ORDER BY priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()

    if not rows or not context_text:
        return [], []

    ctx_lower = context_text.lower()
    triggered = []

    for row in rows:
        keywords = [k.strip().lower() for k in row["keywords"].split(",") if k.strip()]
        if not keywords:
            continue

        trigger_logic = row["trigger_logic"] or "any"

        if trigger_logic == "all":
            if all(kw in ctx_lower for kw in keywords):
                matched = keywords
            else:
                matched = []
        else:
            matched = [kw for kw in keywords if kw in ctx_lower]

        if matched:
            triggered.append({
                "content": row["content"],
                "position": row["position"] or "before",
                "priority": row["priority"] or 100,
            })

    triggered.sort(key=lambda e: e["priority"])
    triggered = triggered[:max_triggered]

    before_list = []
    after_list = []
    wi_used = 0

    for entry in triggered:
        content = entry["content"].strip()
        if not content:
            continue

        if len(content) > max_per_entry:
            content = content[:max_per_entry].rstrip() + "\n…（内容已截断）"

        if wi_used + len(content) > wi_max:
            break

        wi_used += len(content)

        if entry["position"] == "after":
            after_list.append(content)
        else:
            before_list.append(content)

    return before_list, after_list


def fetch_character_post_rules(
    conn: ConnType,
    character_id: str,
    *,
    storyline_id: int | None = None,
    story_phase: str | None = None,
    max_chars: int = 16000,
) -> list[str]:
    """
    从数据库查询角色的后置规则。

    参数：
        conn: 数据库连接
        character_id: 角色 ID
        storyline_id: 当前剧情线 ID（可选）
        story_phase: 当前关系阶段（可选）
        max_chars: 返回规则的总字符上限

    返回：
        匹配的后置规则内容列表（已按优先级排序）
    """
    conditions = ["character_id = %s", "is_active = 1"]
    params: list[Any] = [character_id]

    if storyline_id is not None:
        conditions.append("(storyline_id IS NULL OR storyline_id = %s)")
        params.append(storyline_id)

    if story_phase:
        conditions.append("(story_phase IS NULL OR story_phase = '' OR story_phase = %s)")
        params.append(story_phase)

    where_clause = " AND ".join(conditions)

    rows = conn.execute(
        f"""
        SELECT content, priority
        FROM character_post_rules
        WHERE {where_clause}
        ORDER BY priority ASC, id ASC
        """,
        tuple(params),
    ).fetchall()

    if not rows:
        return []

    rules = []
    total_chars = 0

    for row in rows:
        content = row["content"].strip()
        if not content:
            continue

        if total_chars + len(content) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 100:
                rules.append(content[:remaining].rstrip() + "\n…（内容已截断）")
            break

        total_chars += len(content)
        rules.append(content)

    return rules
