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
from services.character_state import is_affection_enabled as _check_affection
from services.prompt_builder import _get_behavior_tendency
from services.runtime_bundle import _get_field
from utils.json_utils import parse_json_object

logger = logging.getLogger(__name__)


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
    _affection_enabled = True
    if conn is not None and character_state:
        _affection_enabled = _check_affection(conn, char_id)

    if not (character_state and _affection_enabled):
        return

    affection = character_state.get("affection", 0)
    phase = character_state.get("story_phase", "stranger")
    mood = character_state.get("mood", "neutral")
    custom_vars = character_state.get("custom_vars") or {}

    phase_behaviors = parse_json_object(_get_field(character, "phase_behaviors_json", ""), fallback={})

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
        tendency = _get_behavior_tendency(phase, mood, phase_behaviors=phase_behaviors)
        state_lines = [
            "【当前关系状态（每轮自动更新）】",
            f"- 好感度：{affection}/100",
            f"- 关系阶段：{phase_label}（{phase}）",
            f"- 当前心情：{mood_label}（{mood}）",
        ]
    if tendency:
        state_lines.append(f"- 行为倾向：{tendency}")

    # 当前剧情线名称显示
    storyline_id = character_state.get("storyline_id") if character_state else None
    if storyline_id and conn is not None:
        try:
            sl_row = conn.execute(
                "SELECT name FROM character_storylines WHERE id = %s",
                (storyline_id,),
            ).fetchone()
            if sl_row and sl_row["name"]:
                state_lines.append(f"- 当前剧情线：{sl_row['name']}")

            if card_type == "scenario" and user_id:
                try:
                    progress_row = conn.execute(
                        "SELECT triggered_event_ids FROM user_story_progress WHERE user_id = %s AND character_id = %s",
                        (user_id, char_id)
                    ).fetchone()
                    if progress_row and progress_row["triggered_event_ids"]:
                        event_ids = [int(x.strip()) for x in str(progress_row["triggered_event_ids"]).split(",") if x.strip().isdigit()]
                        if event_ids:
                            recent_ids = event_ids[-3:]
                            placeholders = ",".join(["%s"] * len(recent_ids))
                            recent_events = conn.execute(
                                f"SELECT title FROM story_events WHERE id IN ({placeholders}) ORDER BY id DESC",
                                tuple(recent_ids)
                            ).fetchall()
                            if recent_events:
                                titles = [e["title"] for e in recent_events if e["title"]]
                                if titles:
                                    state_lines.append(f"- 最近剧情：{' → '.join(titles)}")
                except Exception:
                    logger.warning("查询最近剧情事件失败 char_id=%s user_id=%s", char_id, user_id, exc_info=True)
        except Exception:
            logger.warning("查询 story_progress 失败 char_id=%s", char_id, exc_info=True)

    # 时间感知
    _tz_offset = TIMEZONE_OFFSET
    _now = datetime.now(timezone(timedelta(hours=_tz_offset)))
    _h = _now.hour
    if _h < 5: _time_desc = "深夜"
    elif _h < 8: _time_desc = "清晨"
    elif _h < 12: _time_desc = "上午"
    elif _h < 14: _time_desc = "中午"
    elif _h < 18: _time_desc = "下午"
    elif _h < 20: _time_desc = "傍晚"
    else: _time_desc = "晚上"
    _date_desc = "周末" if _now.weekday() >= 5 else "工作日"
    state_lines.append(f"- 当前时间：{_date_desc}{_time_desc}（背景信息，不要主动提及时间，除非用户话题涉及）")

    # 自定义变量展示（过滤内部变量）
    if custom_vars:
        for k, v in list(custom_vars.items())[:5]:
            if k.startswith("_"):
                continue
            state_lines.append(f"- {k}：{v}")

    # 注入待处理剧情事件
    pending_events = custom_vars.get("_pending_events") or []
    if pending_events:
        for pe in pending_events[:2]:
            title = pe.get("title", "剧情事件")
            content = pe.get("event_content", "")
            if content:
                state_lines.append(f"- 【触发剧情事件：{title}】{content[:100]}")

    # 沉默轮数提醒
    silent_rounds = int(custom_vars.get("_silent_rounds") or 0)
    if silent_rounds >= 3:
        state_lines.append(f"- 💡 提示：已连续{silent_rounds}轮未记录互动，如本轮有值得记录的内容可补充上报")

    state_lines.extend(update_instruction)

    state_snapshot = "\n".join(state_lines)
    _state_max = max(1000, int(budget.wi_max_chars() * 0.15))
    if len(state_snapshot) > _state_max:
        truncated_lines = state_lines[:6]
        truncated_lines.append("…（自定义变量已省略）")
        truncated_lines.extend(update_instruction)
        state_snapshot = "\n".join(truncated_lines)

    # ── 情感锚点 & 主动回忆注入 ──
    shared_moments = list(custom_vars.get("_shared_moments") or [])
    proactive_cared = False

    if shared_moments and last_chat_time:
        try:
            last_dt = datetime.fromisoformat(str(last_chat_time))
            hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if hours_since >= 24:
                anchor = random.choice(shared_moments[-5:])
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
                existing_after = runtime_bundle.get("world_info_after") or ""
                runtime_bundle["world_info_after"] = (proactive_text + "\n\n" + existing_after).strip()
                proactive_cared = True
        except (ValueError, TypeError):
            pass

    if shared_moments and not proactive_cared:
        candidates = shared_moments[-5:]
        anchor = random.choice(candidates)
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
        existing_after = runtime_bundle.get("world_info_after") or ""
        runtime_bundle["world_info_after"] = (anchor_text + "\n\n" + existing_after).strip()

    # 状态快照优先级最高：放在 world_info_after 最前面
    existing_after = runtime_bundle.get("world_info_after") or ""
    if existing_after:
        runtime_bundle["world_info_after"] = (state_snapshot + "\n\n" + existing_after).strip()
    else:
        runtime_bundle["world_info_after"] = state_snapshot
