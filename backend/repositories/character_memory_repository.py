"""
角色记忆与后置规则的数据查询层。

从 memory_service.py 拆分出来，职责：
    - 查询角色的记忆条目（关键词匹配 + constant/sticky/cooldown）
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
    current_turn: int = 0,
    sticky_state: dict[int, int] | None = None,
    cooldown_state: dict[int, int] | None = None,
    current_storyline_id: int | None = None,
) -> tuple[list[str], list[str], dict[int, int], dict[int, int]]:
    """
    从数据库查询角色的记忆条目，并根据上下文文本匹配关键词。

    参数：
        conn: 数据库连接
        character_id: 角色 ID
        context_text: 用于匹配的上下文文本
        max_triggered: 最多触发条目数
        max_per_entry: 单条最大字符数
        wi_max: WI 总字符上限
        current_turn: 当前对话轮数（用于 sticky/cooldown 计算）
        sticky_state: 上一轮的 sticky 状态 {memory_id: remaining_turns}
        cooldown_state: 上一轮的 cooldown 状态 {memory_id: remaining_cooldown}

    返回：
        (before_list, after_list, new_sticky_state, new_cooldown_state)
        — 分别对应 position='before' 和 'after' 的匹配内容列表
        — 新的 sticky 和 cooldown 状态，需由调用方持久化
    """
    rows = conn.execute(
        """
        SELECT id, keywords, trigger_logic, content, position, priority,
               selective, constant, sticky, cooldown
        FROM character_memories
        WHERE character_id = %s AND is_active = 1
        ORDER BY priority ASC, id ASC
        """,
        (character_id,),
    ).fetchall()

    if not rows:
        return [], [], {}, {}

    sticky_state = dict(sticky_state or {})
    cooldown_state = dict(cooldown_state or {})
    ctx_lower = context_text.lower()
    triggered = []

    for row in rows:
        mid = row["id"]
        is_constant = bool(row.get("constant", 0))
        is_selective = bool(row.get("selective", 1))
        sticky_turns = row.get("sticky", 0) or 0
        cooldown_turns = row.get("cooldown", 0) or 0

        # 1. cooldown 检查：如果该条目仍在冷却期内，跳过
        remaining_cooldown = cooldown_state.get(mid, 0)
        if remaining_cooldown > 0:
            continue

        # 2. constant 或 selective=0：始终注入，不需要关键词匹配
        if is_constant or not is_selective:
            triggered.append({
                "id": mid,
                "content": row["content"],
                "position": row["position"] or "before",
                "priority": row["priority"] or 100,
            })
            if not is_constant:
                if sticky_turns > 0:
                    sticky_state[mid] = sticky_turns
                if cooldown_turns > 0:
                    cooldown_state[mid] = cooldown_turns
            continue

        # 3. sticky 延续：上一轮触发了且 sticky 未耗尽
        remaining_sticky = sticky_state.get(mid, 0)
        if remaining_sticky > 0:
            triggered.append({
                "id": mid,
                "content": row["content"],
                "position": row["position"] or "before",
                "priority": row["priority"] or 100,
            })
            continue

        # 5. 常规关键词匹配
        keywords_raw = row["keywords"].split(",")
        keywords = []
        storyline_filter = None

        # 解析 @storyline: 前缀（剧情线过滤）
        for kw in keywords_raw:
            kw = kw.strip()
            if kw.startswith("@storyline:"):
                try:
                    storyline_filter = int(kw.split(":")[1])
                except (ValueError, IndexError):
                    pass
            elif kw:
                keywords.append(kw.lower())

        # 如果设置了剧情线过滤且不匹配当前剧情线，跳过
        if storyline_filter is not None and current_storyline_id != storyline_filter:
            continue

        if not keywords:
            continue

        trigger_logic = row["trigger_logic"] or "any"

        if trigger_logic == "all":
            matched = all(kw in ctx_lower for kw in keywords)
        else:
            matched = any(kw in ctx_lower for kw in keywords)

        if matched:
            triggered.append({
                "id": mid,
                "content": row["content"],
                "position": row["position"] or "before",
                "priority": row["priority"] or 100,
            })
            # 触发后设置 sticky 和 cooldown
            if sticky_turns > 0:
                sticky_state[mid] = sticky_turns
            if cooldown_turns > 0:
                cooldown_state[mid] = cooldown_turns

    # 按 priority 排序并截断
    triggered.sort(key=lambda e: e["priority"])
    triggered = triggered[:max_triggered]

    before_list = []
    after_list = []
    wi_used = 0
    triggered_ids = set()

    for entry in triggered:
        content = entry["content"].strip()
        if not content:
            continue

        if len(content) > max_per_entry:
            content = content[:max_per_entry].rstrip() + "\n…（内容已截断）"

        if wi_used + len(content) > wi_max:
            break

        wi_used += len(content)
        triggered_ids.add(entry["id"])

        if entry["position"] == "after":
            after_list.append(content)
        else:
            before_list.append(content)

    # 更新 sticky 和 cooldown 状态
    new_sticky = {}
    new_cooldown = {}

    for mid, remaining in sticky_state.items():
        if mid in triggered_ids:
            # 本轮被触发（含 sticky 延续），消耗 1 轮
            new_remaining = remaining - 1
            if new_remaining > 0:
                new_sticky[mid] = new_remaining
            # else: sticky 耗尽，自然移除
        else:
            # 本轮未被触发但仍有 sticky 计数（不应出现，因为 sticky 延续会触发）
            # 保守处理：仍然消耗 1 轮
            new_remaining = remaining - 1
            if new_remaining > 0:
                new_sticky[mid] = new_remaining

    for mid, remaining in cooldown_state.items():
        # 消耗 1 轮冷却
        new_remaining = remaining - 1
        if new_remaining > 0:
            new_cooldown[mid] = new_remaining
        # else: 冷却结束，自然移除

    return before_list, after_list, new_sticky, new_cooldown


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
