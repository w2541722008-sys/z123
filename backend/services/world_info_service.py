"""
World Info 动态触发服务 — 从数据库记忆和后置规则中匹配并截断内容。

从 repositories/character_memory_repository.py 提取而来。
将原始 SQL 查询留在 repository，所有关键词匹配、粘性/冷却状态机、
优先级排序、预算控制、内容截断逻辑移至本模块。

职责：
    - 关键词匹配（any/all 触发逻辑、@storyline: 前缀解析）
    - 粘性（sticky）和冷却（cooldown）回合制状态机
    - WI 预算控制（按字符数截断）
    - 后置规则条件过滤与截断
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType
from repositories.character_memory_repository import (
    fetch_active_memory_rows,
    fetch_active_post_rule_rows,
)


def resolve_triggered_memories(
    conn: ConnType,
    character_id: str,
    context_text: str,
    *,
    max_triggered: int = 12,
    max_per_entry: int = 500,
    wi_max: int = 8000,
    sticky_state: dict[int, int] | None = None,
    cooldown_state: dict[int, int] | None = None,
    current_storyline_id: int | None = None,
) -> tuple[list[str], list[str], dict[int, int], dict[int, int]]:
    """从数据库查询记忆条目，按上下文关键词匹配并触发。

    返回 (before_list, after_list, new_sticky, new_cooldown)。
    before_list — position 不为 "after" 的触发内容
    after_list  — position 为 "after" 的触发内容
    new_sticky / new_cooldown — 下一轮使用的状态，由调用方持久化
    """
    rows = fetch_active_memory_rows(conn, character_id)
    if not rows:
        return [], [], {}, {}

    sticky_state = _normalize_turn_state(sticky_state)
    cooldown_state = _normalize_turn_state(cooldown_state)
    ctx_lower = context_text.lower()
    triggered: list[dict[str, Any]] = []

    for row in rows:
        mid = row["id"]
        is_constant = bool(row.get("constant", 0))
        is_selective = bool(row.get("selective", 1))
        sticky_turns = row.get("sticky", 0) or 0
        cooldown_turns = row.get("cooldown", 0) or 0

        # 1. cooldown 检查
        remaining_cooldown = cooldown_state.get(mid, 0)
        if remaining_cooldown > 0:
            continue

        # 2. constant 或 selective=0：始终注入
        if is_constant or not is_selective:
            triggered.append(_make_entry(row))
            if not is_constant:
                if sticky_turns > 0:
                    sticky_state[mid] = sticky_turns
                if cooldown_turns > 0:
                    cooldown_state[mid] = cooldown_turns
            continue

        # 3. sticky 延续
        remaining_sticky = sticky_state.get(mid, 0)
        if remaining_sticky > 0:
            triggered.append(_make_entry(row))
            continue

        # 4. 常规关键词匹配
        keywords_raw = str(row["keywords"]).split(",")
        keywords: list[str] = []
        storyline_filter: int | None = None

        for kw in keywords_raw:
            kw = kw.strip()
            if kw.startswith("@storyline:"):
                try:
                    storyline_filter = int(kw.split(":")[1])
                except (ValueError, IndexError):
                    pass
            elif kw:
                keywords.append(kw.lower())

        if storyline_filter is not None and current_storyline_id != storyline_filter:
            continue

        if not keywords:
            continue

        trigger_logic = row.get("trigger_logic") or "any"

        if trigger_logic == "all":
            matched = all(kw in ctx_lower for kw in keywords)
        else:
            matched = any(kw in ctx_lower for kw in keywords)

        if matched:
            triggered.append(_make_entry(row))
            if sticky_turns > 0:
                sticky_state[mid] = sticky_turns
            if cooldown_turns > 0:
                cooldown_state[mid] = cooldown_turns

    # 按 priority 排序并截断
    triggered.sort(key=lambda e: e["priority"])
    triggered = triggered[:max_triggered]

    before_list, after_list, triggered_ids = _build_position_lists(
        triggered, max_per_entry, wi_max
    )

    new_sticky, new_cooldown = _advance_states(
        sticky_state, cooldown_state, triggered_ids
    )

    return before_list, after_list, new_sticky, new_cooldown


def resolve_post_rules(
    conn: ConnType,
    character_id: str,
    *,
    storyline_id: int | None = None,
    story_phase: str | None = None,
    max_chars: int = 16000,
) -> list[str]:
    """从数据库查询后置规则，按条件过滤并截断。

    返回匹配的规则内容列表（已按优先级排序，总字符数不超过 max_chars）。
    """
    rows = fetch_active_post_rule_rows(
        conn, character_id,
        storyline_id=storyline_id,
        story_phase=story_phase,
    )
    if not rows:
        return []

    rules: list[str] = []
    total_chars = 0

    for row in rows:
        content = str(row["content"]).strip()
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


# ── 内部辅助 ──────────────────────────────────────────────


def _normalize_turn_state(state: dict[Any, Any] | None) -> dict[int, int]:
    """把 JSON 读回的回合状态归一成 int -> positive int，忽略脏值。"""
    normalized: dict[int, int] = {}
    for raw_key, raw_value in (state or {}).items():
        if isinstance(raw_key, bool) or isinstance(raw_value, bool):
            continue
        try:
            memory_id = int(raw_key)
            remaining_turns = int(raw_value)
        except (TypeError, ValueError):
            continue
        if memory_id <= 0 or remaining_turns <= 0:
            continue
        normalized[memory_id] = remaining_turns
    return normalized


def _make_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "content": str(row["content"]),
        "position": row.get("position") or "before",
        "priority": row.get("priority") or 100,
    }


def _build_position_lists(
    triggered: list[dict[str, Any]],
    max_per_entry: int,
    wi_max: int,
) -> tuple[list[str], list[str], set[int]]:
    """将触发的条目按 position 分流，并应用预算截断。"""
    before_list: list[str] = []
    after_list: list[str] = []
    wi_used = 0
    triggered_ids: set[int] = set()

    for entry in triggered:
        content = str(entry["content"]).strip()
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

    return before_list, after_list, triggered_ids


def _advance_states(
    sticky_state: dict[int, int],
    cooldown_state: dict[int, int],
    triggered_ids: set[int],
) -> tuple[dict[int, int], dict[int, int]]:
    """回合推进：所有 sticky/cooldown 计数各减 1，归零则移除。"""
    new_sticky: dict[int, int] = {}
    new_cooldown: dict[int, int] = {}

    for mid, remaining in sticky_state.items():
        new_remaining = remaining - 1
        if new_remaining > 0:
            new_sticky[mid] = new_remaining

    for mid, remaining in cooldown_state.items():
        new_remaining = remaining - 1
        if new_remaining > 0:
            new_cooldown[mid] = new_remaining

    return new_sticky, new_cooldown
