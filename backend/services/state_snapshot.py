"""
状态快照注入 — 构建关系/剧情状态快照、时间感知、情感锚点，注入到 runtime_bundle。

从 prompt_assembler.py 拆分出来（阶段5），消除该文件行数逼近红线的问题。
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Any

from constants.mood import MOOD_LABELS, SCENARIO_MOOD_LABELS
from constants.story_phase import STORY_PHASE_LABELS, SCENARIO_PHASE_LABELS
from constants.prompt_templates import STATE_UPDATE_INSTRUCTION, SCENARIO_STATE_UPDATE_INSTRUCTION
from core.config import TIMEZONE_OFFSET
from core.database import ConnType
from repositories import story_repository as story_repo
from services.character_affection import is_affection_enabled as _check_affection
from services.prompt_builder import _get_behavior_tendency
from services.runtime_bundle import _get_field
from utils.json_utils import parse_json_object

logger = logging.getLogger(__name__)


# ── 子步骤 ──────────────────────────────────────────────

def _build_state_lines(
    card_type: str,
    affection: int,
    phase: str,
    mood: str,
    phase_behaviors: dict[str, Any],
    *,
    archetype: str | None = None,
) -> tuple[list[str], list[str]]:
    """构建核心状态文本行，返回 (state_lines, update_instruction)。"""
    if card_type == "scenario":
        phase_label = SCENARIO_PHASE_LABELS.get(phase, phase)
        mood_label = SCENARIO_MOOD_LABELS.get(mood, mood)
        update_instruction = SCENARIO_STATE_UPDATE_INSTRUCTION
        tendency = _get_behavior_tendency(phase, mood, card_type="scenario", phase_behaviors=phase_behaviors)
        state_lines = [
            "【当前剧情状态（每轮自动更新）】",
            f"- 剧情沉浸度：{affection}/100",
            f"- 剧情阶段：{phase_label}（{phase}）",
            f"- 当前氛围：{mood_label}（{mood}）",
        ]
    else:
        phase_label = STORY_PHASE_LABELS.get(phase, phase)
        mood_label = MOOD_LABELS.get(mood, mood)
        update_instruction = STATE_UPDATE_INSTRUCTION
        tendency = _get_behavior_tendency(phase, mood, phase_behaviors=phase_behaviors, archetype=archetype)
        state_lines = [
            "【当前关系状态（每轮自动更新）】",
            f"- 好感度：{affection}/100",
            f"- 关系阶段：{phase_label}（{phase}）",
            f"- 当前心情：{mood_label}（{mood}）",
        ]

    if tendency:
        state_lines.append(f"- 行为倾向：{tendency}")

    return state_lines, update_instruction


def _enrich_state_with_context(
    state_lines: list[str],
    conn: ConnType | None,
    storyline_id: int | None,
    card_type: str,
    user_id: int | str | None,
    char_id: str,
    custom_vars: dict[str, Any],
) -> None:
    """追加剧情线信息、最近剧情事件、时间感知、自定义变量、待处理事件。"""
    _append_storyline_info(state_lines, conn, storyline_id, card_type, user_id, char_id)
    _append_time_context(state_lines)
    _append_custom_var_context(state_lines, custom_vars)
    _append_pending_context(state_lines, custom_vars)


def _append_storyline_info(
    state_lines: list[str],
    conn: ConnType | None,
    storyline_id: int | None,
    card_type: str,
    user_id: int | str | None,
    char_id: str,
) -> None:
    """追加当前剧情线名称和最近剧情事件标题。"""
    if not storyline_id or conn is None:
        return

    try:
        name = story_repo.get_storyline_name(conn, storyline_id)
        if name:
            state_lines.append(f"- 当前剧情线：{name}")

        if card_type == "scenario" and user_id:
            try:
                triggered_ids = story_repo.get_triggered_event_ids(conn, user_id, char_id)
                if triggered_ids:
                    recent_ids = sorted(triggered_ids)[-3:]
                    titles = story_repo.get_recent_event_titles(conn, recent_ids)
                    if titles:
                        state_lines.append(f"- 最近剧情：{' → '.join(titles)}")
            except Exception:
                logger.warning(
                    "查询最近剧情事件失败 char_id=%s user_id=%s", char_id, user_id, exc_info=True,
                )
    except Exception:
        logger.warning("查询 story_progress 失败 char_id=%s", char_id, exc_info=True)


def _append_time_context(state_lines: list[str]) -> None:
    """追加时间感知（日期类型 + 时段）。"""
    _tz_offset = TIMEZONE_OFFSET
    _now = datetime.now(timezone(timedelta(hours=_tz_offset)))
    _h = _now.hour
    if _h < 5:
        _time_desc = "深夜"
    elif _h < 8:
        _time_desc = "清晨"
    elif _h < 12:
        _time_desc = "上午"
    elif _h < 14:
        _time_desc = "中午"
    elif _h < 18:
        _time_desc = "下午"
    elif _h < 20:
        _time_desc = "傍晚"
    else:
        _time_desc = "晚上"
    _date_desc = "周末" if _now.weekday() >= 5 else "工作日"
    state_lines.append(
        f"- 当前时间：{_date_desc}{_time_desc}（背景信息，不要主动提及时间，除非用户话题涉及）"
    )


def _append_custom_var_context(state_lines: list[str], custom_vars: dict[str, Any]) -> None:
    """追加自定义变量展示（过滤内部变量，最多 5 个）。"""
    if not custom_vars:
        return
    count = 0
    for k, v in custom_vars.items():
        if k.startswith("_"):
            continue
        state_lines.append(f"- {k}：{v}")
        count += 1
        if count >= 5:
            break


def _append_pending_context(state_lines: list[str], custom_vars: dict[str, Any]) -> None:
    """追加待处理剧情事件和沉默轮数提醒。"""
    pending_events = custom_vars.get("_pending_events") or []
    for pe in pending_events[:2]:
        title = pe.get("title", "剧情事件")
        content = pe.get("event_content", "")
        if content:
            state_lines.append(f"- 【触发剧情事件：{title}】{content[:100]}")

    silent_rounds = int(custom_vars.get("_silent_rounds") or 0)
    if silent_rounds >= 6:
        state_lines.append(
            f"- 💡 提示：已连续{silent_rounds}轮未记录互动，如本轮有值得记录的内容可补充上报"
        )


def _finalize_state_snapshot(
    state_lines: list[str],
    update_instruction: list[str],
    budget: Any,
) -> str:
    """将状态行组装为最终文本，必要时截断。"""
    state_lines.extend(update_instruction)
    state_snapshot = "\n".join(state_lines)
    _state_max = max(1000, int(budget.wi_max_chars() * 0.15))
    if len(state_snapshot) <= _state_max:
        return state_snapshot

    # 内容过长：保留前 6 行 + update_instruction
    truncated_lines = state_lines[:6]
    truncated_lines.append("…（自定义变量已省略）")
    truncated_lines.extend(update_instruction)
    return "\n".join(truncated_lines)


def _inject_affection_anchor(
    runtime_bundle: dict[str, Any],
    shared_moments: list[str],
    last_chat_time: str | None,
    card_type: str,
    custom_vars: dict[str, Any] | None = None,
) -> None:
    """注入情感锚点和主动回忆到 runtime_bundle 的 world_info_after。"""
    if not shared_moments:
        return

    proactive_cared = False
    candidates = shared_moments[-5:]

    # 轮换选取锚点，避免连续多轮重复同一段回忆
    last_idx = int(custom_vars.get("_last_anchor_index") or -1) if custom_vars else -1
    next_idx = (last_idx + 1) % len(candidates)
    anchor = candidates[next_idx]
    if custom_vars is not None:
        custom_vars["_last_anchor_index"] = next_idx

    # 长时间未互动时注入主动回忆
    if last_chat_time:
        try:
            last_dt = datetime.fromisoformat(str(last_chat_time))
            hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if hours_since >= 24:
                if card_type == "scenario":
                    proactive_text = (
                        f"【剧情回响】距离上一次互动已过去较长时间（{int(hours_since)}小时）。回忆起「{anchor}」，"
                        f"如果用户的问题与此相关，可以自然地引入这段经历。"
                    )
                else:
                    proactive_text = (
                        f"【背景提示】你已经很久没和用户聊天了（{int(hours_since)}小时）。想起「{anchor}」，你有点想念对方。"
                        f"但不要生硬地打断用户的问题——如果用户问了具体问题，先认真回答；"
                        f"如果用户只是打招呼或闲聊，可以自然地表达想念，如\"好久不见，最近怎么样？\"或\"想起{anchor}，就想和你聊聊\"。"
                    )
                existing = runtime_bundle.get("world_info_after") or ""
                runtime_bundle["world_info_after"] = (proactive_text + "\n\n" + existing).strip()
                proactive_cared = True
        except (ValueError, TypeError):
            pass

    # 默认注入共同回忆锚点
    if not proactive_cared:
        if card_type == "scenario":
            anchor_text = (
                f"【共同回忆】{anchor}"
                f"（这段经历是你和用户之间的纽带，不需要刻意提及，但会影响你此刻的态度和情感色彩）"
            )
        else:
            anchor_text = (
                f"【共同回忆】{anchor}"
                f"（这是你和用户的共同回忆，会影响你此刻的情感基调。只有当话题自然关联时才提起，不要为了提起而提起）"
            )
        existing = runtime_bundle.get("world_info_after") or ""
        runtime_bundle["world_info_after"] = (anchor_text + "\n\n" + existing).strip()


# ── 主入口 ──────────────────────────────────────────────

def inject_state_snapshot(
    conn: ConnType | None,
    character: Any,
    runtime_bundle: dict[str, Any],
    character_state: dict | None,
    budget: Any,
    card_type: str,
    last_chat_time: str | None,
    user_id: int | str | None,
    char_id: str,
) -> None:
    """构建关系状态快照、时间感知、情感锚点，注入到 world_info_after。"""
    # 1. 检查好感度系统是否启用
    _affection_enabled = True
    if conn is not None and character_state:
        _affection_enabled = _check_affection(conn, char_id)

    if not (character_state and _affection_enabled):
        return

    # 2. 提取状态值
    affection = character_state.get("affection", 0)
    phase = character_state.get("story_phase", "stranger")
    mood = character_state.get("mood", "neutral")
    custom_vars = character_state.get("custom_vars") or {}
    phase_behaviors = parse_json_object(
        _get_field(character, "phase_behaviors_json", ""), fallback={},
    )
    storyline_id = character_state.get("storyline_id") if character_state else None
    archetype = runtime_bundle.get("archetype") or None

    # 3. 构建核心状态行
    state_lines, update_instruction = _build_state_lines(
        card_type, affection, phase, mood, phase_behaviors, archetype=archetype,
    )

    # 4. 丰富上下文
    _enrich_state_with_context(
        state_lines, conn, storyline_id, card_type, user_id, char_id, custom_vars,
    )

    # 5. 组装并截断
    state_snapshot = _finalize_state_snapshot(state_lines, update_instruction, budget)

    # 6. 注入情感锚点
    shared_moments = list(custom_vars.get("_shared_moments") or [])
    _inject_affection_anchor(runtime_bundle, shared_moments, last_chat_time, card_type, custom_vars)

    # 7. 状态快照放到 world_info_after 最前面
    existing_after = runtime_bundle.get("world_info_after") or ""
    if existing_after:
        runtime_bundle["world_info_after"] = state_snapshot + "\n\n" + existing_after
    else:
        runtime_bundle["world_info_after"] = state_snapshot
