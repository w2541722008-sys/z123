"""
角色状态服务 - 管理好感度、剧情阶段、心情等角色关系状态

核心功能：
    - 读取/写入用户对某角色的关系状态
    - 好感度计算（含三防机制：冷却、日上限、边际递减）
    - 剧情阶段自动推进
    - 自定义变量管理

三防机制详解：
    1. Cooldown（冷却机制）：
       - 同类事件触发后进入冷却期
       - 冷却期内再次触发，加分归零
       - 不同事件冷却时间不同（如 gift 24小时，flirt 20分钟）

    2. Daily Cap（日上限机制）：
       - 每日好感度涨幅上限默认 15 点
       - 可通过角色卡 affection_rules_json 的 daily_cap 字段自定义（0=不限制）
       - 达到上限后，正向加分归零
       - 负向扣分不受影响（防止恶意刷分）

    3. Diminishing Returns（边际递减）：
       - 同类事件多次触发，按衰减系数折减
       - 衰减系数：[1.0, 0.6, 0.3, 0.0]
       - 第1次 100%，第2次 60%，第3次 30%，第4次+ 0%

主要导出：
    - get_character_state: 获取角色状态
    - upsert_character_state: 更新角色状态
    - apply_state_delta: 应用状态增量
    - is_affection_enabled: 检查好感度系统是否启用
    - _calculate_affection_change: 计算好感度变化（含三防）
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from core.config import utc_now
from constants import Mood, StoryPhase
from core.database import ConnType
from services.cache_service import cache_get, cache_set
from services.story_event_service import check_and_trigger_story_events
from utils.json_utils import parse_json_object
from services.character_affection import (
    _AFFECTION_BASE_RULES,
    _AFFECTION_COOLDOWN_SECONDS,
    _AFFECTION_DIMINISHING_RETURNS,
    _DAILY_AFFECTION_CAP_DEFAULT,
    _PHASE_THRESHOLDS,
    _PHASE_GAIN_MULTIPLIER,
    _AFFECTION_DELTA_MAX,
    _EVENT_NAME_MIGRATION,
    _get_affection_rules,
    _get_daily_cap,
    is_affection_enabled,
    _calculate_affection_change,
    _update_anti_abuse_counters,
    _auto_advance_story_phase,
)

logger = logging.getLogger(__name__)

_VALID_STORY_PHASES = tuple(phase.value for phase in StoryPhase)
_VALID_MOODS = tuple(mood.value for mood in Mood)


def _get_today_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ============================================================
# 状态读写
# ============================================================
def get_character_state(conn: ConnType, user_id: int | str, character_id: str, *, for_update: bool = False) -> dict[str, Any]:
    """读取用户对某角色的当前关系状态，不存在时返回默认值。

    Args:
        for_update: 若为 True，对 character_states 行加 SELECT ... FOR UPDATE 行级锁，
                    防止并发请求之间的丢失更新。仅在事务中使用。
    """
    # 查询角色状态
    lock_clause = "\nFOR UPDATE" if for_update else ""
    row = conn.execute(
        f"""
        SELECT affection, story_phase, mood, custom_vars,
               daily_event_counts, daily_affection_gained, last_event_timestamps, daily_reset_date
        FROM character_states
        WHERE user_id = %s AND character_id = %s{lock_clause}
        """,
        (user_id, character_id),
    ).fetchone()
    
    # 查询当前剧情线（从用户剧情进度表）
    progress_row = conn.execute(
        """
        SELECT current_storyline_id FROM user_story_progress
        WHERE user_id = %s AND character_id = %s
        """,
        (user_id, character_id),
    ).fetchone()
    
    storyline_id = None
    if progress_row and progress_row["current_storyline_id"]:
        try:
            storyline_id = int(progress_row["current_storyline_id"])
        except (ValueError, TypeError):
            storyline_id = None
    
    if not row:
        return {
            "affection": 0,
            "story_phase": "stranger",
            "mood": "neutral",
            "custom_vars": {},
            "storyline_id": storyline_id,
        }
    
    return {
        "affection": int(row["affection"] or 0),
        "story_phase": row["story_phase"] or "stranger",
        "mood": row["mood"] or "neutral",
        "custom_vars": parse_json_object(row["custom_vars"], fallback={}),
        "storyline_id": storyline_id,
        "_daily_event_counts": parse_json_object(row["daily_event_counts"] or "{}", fallback={}),
        "_daily_affection_gained": int(row["daily_affection_gained"] or 0),
        "_last_event_timestamps": parse_json_object(row["last_event_timestamps"] or "{}", fallback={}),
        "_daily_reset_date": row["daily_reset_date"] or "",
    }


def _reset_daily_fields_if_needed(state: dict[str, Any]) -> dict[str, Any]:
    """惰性日重置：如果不是今天，归零当天统计。"""
    today = _get_today_date()
    if state.get("_daily_reset_date") != today:
        state["_daily_event_counts"] = {}
        state["_daily_affection_gained"] = 0
        state["_daily_reset_date"] = today
    return state


def upsert_character_state(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    affection: int,
    story_phase: str,
    mood: str,
    custom_vars: dict[str, Any],
    daily_event_counts: dict[str, Any] | None = None,
    daily_affection_gained: int = 0,
    last_event_timestamps: dict[str, Any] | None = None,
    daily_reset_date: str = "",
    *,
    commit: bool = True,
) -> None:
    """写入（插入或更新）一条关系状态记录。"""
    affection = max(0, min(100, int(affection)))
    if story_phase not in _VALID_STORY_PHASES:
        story_phase = "stranger"
    if mood not in _VALID_MOODS:
        mood = "neutral"
    if daily_event_counts is None:
        daily_event_counts = {}
    if last_event_timestamps is None:
        last_event_timestamps = {}
    if not daily_reset_date:
        daily_reset_date = _get_today_date()

    conn.execute(
        """
        INSERT INTO character_states(
            user_id, character_id, affection, story_phase, mood, custom_vars,
            daily_event_counts, daily_affection_gained, last_event_timestamps,
            daily_reset_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(user_id, character_id) DO UPDATE SET
            affection = excluded.affection,
            story_phase = excluded.story_phase,
            mood = excluded.mood,
            custom_vars = excluded.custom_vars,
            daily_event_counts = excluded.daily_event_counts,
            daily_affection_gained = excluded.daily_affection_gained,
            last_event_timestamps = excluded.last_event_timestamps,
            daily_reset_date = excluded.daily_reset_date,
            updated_at = now()
        """,
        (
            user_id, character_id, affection, story_phase, mood,
            json.dumps(custom_vars, ensure_ascii=False),
            json.dumps(daily_event_counts, ensure_ascii=False),
            daily_affection_gained,
            json.dumps(last_event_timestamps, ensure_ascii=False),
            daily_reset_date,
        ),
    )
    if commit:
        conn.commit()


# ============================================================
# 状态增量应用
# ============================================================

# STATE_UPDATE 白名单字段 - 只允许这些字段被AI更新
# 这是安全防线，防止AI输出意外字段导致数据污染
_STATE_UPDATE_ALLOWED_FIELDS = {
    "affection",      # 好感度变化或直接设置
    "event",          # 触发的好感度事件名称
    "story_phase",    # 剧情阶段
    "mood",           # 心情状态
    "moment",         # 本轮共同时刻（情感锚点），简短文字描述
    "custom",         # 自定义变量字典
}

# 自定义变量的黑名单 - 这些键不允许被AI修改
_CUSTOM_VARS_BLACKLIST = {
    "_triggered_events",  # 内部事件标记
    "_daily_event_counts",  # 日事件计数（内部使用）
    "_daily_affection_gained",  # 日好感度获得（内部使用）
    "_last_event_timestamps",  # 事件时间戳（内部使用）
    "_daily_reset_date",  # 日重置日期（内部使用）
    "_shared_moments",  # 情感锚点列表（系统管理，不允许AI直接修改）
    "_pending_events",  # 待处理剧情事件（系统管理，注入后自动清空）
    "_pending_phase_upgrade",  # 关系阶段升级触发语（系统管理，用户下次打开时消费）
    "_silent_rounds",  # 沉默轮数计数（系统管理，AI上报后自动归零）
}

# 情感锚点 FIFO 上限
_SHARED_MOMENTS_MAX = 15


def _sanitize_state_delta(delta: dict[str, Any]) -> dict[str, Any]:
    """
    清理和验证 STATE_UPDATE 增量，只允许白名单字段通过。
    
    安全处理规则：
        1. 只保留白名单中的字段
        2. custom 字典中的黑名单键会被过滤
        3. 数值字段进行范围限制
        4. 字符串字段进行长度限制
    
    Args:
        delta: AI 输出的原始增量字典
        
    Returns:
        清理后的安全增量字典
    """
    if not isinstance(delta, dict):
        return {}
    
    sanitized: dict[str, str | int | dict[str, str | int | float]] = {}
    
    for key, value in delta.items():
        # 只处理白名单字段
        if key not in _STATE_UPDATE_ALLOWED_FIELDS:
            continue
        
        if key == "affection":
            # 好感度：可以是数字或 +/- 前缀的字符串
            if isinstance(value, (int, float)):
                sanitized[key] = max(-_AFFECTION_DELTA_MAX, min(_AFFECTION_DELTA_MAX, int(value)))
            elif isinstance(value, str):
                sanitized[key] = value[:20]  # 限制长度，如 "+5" "-3"
        
        elif key == "event":
            # 事件名称：字符串，限制长度
            if isinstance(value, str):
                sanitized[key] = value.strip().lower()[:50]
        
        elif key == "story_phase":
            # 剧情阶段：必须是有效值
            if isinstance(value, str) and value.strip().lower() in _VALID_STORY_PHASES:
                sanitized[key] = value.strip().lower()
        
        elif key == "mood":
            # 心情：必须是有效值
            if isinstance(value, str) and value.strip().lower() in _VALID_MOODS:
                sanitized[key] = value.strip().lower()
        
        elif key == "moment":
            # 情感锚点：简短文字，限制长度
            if isinstance(value, str) and value.strip():
                sanitized[key] = value.strip()[:30]
        
        elif key == "custom":
            # 自定义变量：必须是字典，且过滤黑名单键
            if isinstance(value, dict):
                safe_custom = {}
                for k, v in value.items():
                    # 跳过黑名单键
                    if k in _CUSTOM_VARS_BLACKLIST:
                        continue
                    # 键名安全检查
                    if not isinstance(k, str) or not k:
                        continue
                    safe_key = k[:50]  # 限制键名长度
                    # 值类型安全检查
                    if isinstance(v, (str, int, float, bool)):
                        safe_custom[safe_key] = v
                    elif isinstance(v, dict):
                        safe_custom[safe_key] = str(v)[:200]  # 嵌套字典转字符串
                    else:
                        safe_custom[safe_key] = str(v)[:200]
                sanitized[key] = safe_custom
    
    return sanitized


# ============================================================
# apply_state_delta 处理器
# 将原来的 253 行巨函数拆分为 6 个处理器 + 1 个编排函数
# ============================================================

def _resolve_affection_delta(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    delta: dict[str, Any],
) -> tuple[dict[str, Any], int, str, str, dict[str, Any]]:
    """处理器1：好感度变化计算。

    读取当前状态、重置每日字段、计算好感度变化量、更新反滥用计数器。
    返回 (current_state, affection, story_phase, mood, custom_vars)。
    """
    current = get_character_state(conn, user_id, character_id, for_update=True)
    current = _reset_daily_fields_if_needed(current)

    affection = current["affection"]
    story_phase = current["story_phase"]
    mood = current["mood"]
    custom_vars = dict(current["custom_vars"])

    affection_change = 0
    affection_enabled = is_affection_enabled(conn, character_id)

    if affection_enabled:
        if "event" in delta:
            event_name = str(delta["event"]).strip().lower()
            rules = _get_affection_rules(conn, character_id)
            daily_cap = _get_daily_cap(conn, character_id)
            affection_change, _ = _calculate_affection_change(event_name, rules, current, daily_cap=daily_cap)
            current = _update_anti_abuse_counters(current, event_name, affection_change)
        elif "affection" in delta:
            raw = str(delta["affection"]).strip()
            if raw.startswith("+"):
                raw_change = min(int(raw[1:]), _AFFECTION_DELTA_MAX)
                affection_change = raw_change
            elif raw.startswith("-"):
                raw_change = min(int(raw[1:]), _AFFECTION_DELTA_MAX)
                affection_change = -raw_change
            else:
                try:
                    affection = max(0, min(100, int(raw)))
                except ValueError:
                    pass

    affection = max(0, min(100, affection + affection_change))
    return current, affection, story_phase, mood, custom_vars


def _resolve_story_phase(
    conn: ConnType,
    character_id: str,
    affection: int,
    current_phase: str,
    delta: dict[str, Any],
) -> tuple[str, str]:
    """处理器2：剧情阶段推进。

    如果 AI 指定了阶段则使用指定值，否则按好感度自动推进。
    返回 (new_phase, old_phase)。
    """
    old_phase = current_phase
    if "story_phase" in delta:
        val = str(delta["story_phase"]).strip().lower()
        if val in _VALID_STORY_PHASES:
            return val, old_phase

    # AI 未指定阶段时，按好感度自动推进
    allow_regression = False
    try:
        rules_row = conn.execute(
            "SELECT affection_rules_json FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if rules_row and rules_row["affection_rules_json"]:
            rules_json = parse_json_object(rules_row["affection_rules_json"], fallback={})
            allow_regression = bool(rules_json.get("allow_regression", False))
    except Exception:
        logger.warning("解析 affection_rules_json 失败 character_id=%s", character_id, exc_info=True)
    new_phase = _auto_advance_story_phase(affection, current_phase, allow_regression=allow_regression)
    return new_phase, old_phase


def _resolve_mood_and_moments(
    current_mood: str,
    custom_vars: dict[str, Any],
    delta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """处理器3：心情更新 + 情感锚点追加（FIFO）。"""
    mood = current_mood
    if "mood" in delta:
        val = str(delta["mood"]).strip().lower()
        if val in _VALID_MOODS:
            mood = val

    if "moment" in delta and delta["moment"]:
        moments = list(custom_vars.get("_shared_moments") or [])
        moments.append(str(delta["moment"]))
        if len(moments) > _SHARED_MOMENTS_MAX:
            moments = moments[-_SHARED_MOMENTS_MAX:]
        custom_vars["_shared_moments"] = moments

    return mood, custom_vars


def _resolve_custom_vars_and_silence(
    custom_vars: dict[str, Any],
    delta: dict[str, Any],
) -> dict[str, Any]:
    """处理器4：自定义变量更新（含 +/- 增量语义）+ 沉默轮数计数。"""
    if "custom" in delta and isinstance(delta["custom"], dict):
        for k, v in delta["custom"].items():
            raw = str(v).strip()
            existing = custom_vars.get(k)
            if raw.startswith("+") and isinstance(existing, (int, float)):
                try:
                    custom_vars[k] = existing + int(raw[1:])
                except ValueError:
                    custom_vars[k] = raw
            elif raw.startswith("-") and isinstance(existing, (int, float)):
                try:
                    custom_vars[k] = existing - int(raw[1:])
                except ValueError:
                    custom_vars[k] = raw
            else:
                custom_vars[k] = v

    has_state_update = "event" in delta or "affection" in delta
    silent_rounds = int(custom_vars.get("_silent_rounds") or 0)
    if has_state_update:
        custom_vars["_silent_rounds"] = 0
    else:
        custom_vars["_silent_rounds"] = silent_rounds + 1

    return custom_vars


def _handle_storyline_and_events(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    affection: int,
    old_phase: str,
    new_phase: str,
    custom_vars: dict[str, Any],
    current: dict[str, Any],
    delta: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """处理器5：剧情线切换 + 剧情事件触发 + 阶段升级通知 + 待处理事件管理。

    返回 (updated_custom_vars, triggered_events)。
    """
    triggered_events: list[dict[str, Any]] = []

    # ── 剧情线 AI 驱动切换 ──
    new_storyline_id = None
    if "custom" in delta and isinstance(delta["custom"], dict):
        raw_sid = delta["custom"].get("current_storyline_id")
        if raw_sid is not None:
            try:
                new_storyline_id = int(raw_sid)
            except (ValueError, TypeError):
                pass

    if new_storyline_id is not None:
        try:
            valid_row = conn.execute(
                "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s AND is_active = TRUE",
                (new_storyline_id, character_id),
            ).fetchone()
            if valid_row:
                conn.execute(
                    """
                    INSERT INTO user_story_progress (user_id, character_id, triggered_event_ids, current_storyline_id)
                    VALUES (%s, %s, '', %s)
                    ON CONFLICT(user_id, character_id) DO UPDATE SET
                        current_storyline_id = excluded.current_storyline_id,
                        last_updated = now()
                    """,
                    (user_id, character_id, new_storyline_id),
                )
            else:
                logger.warning("剧情线ID无效或不属于当前角色: storyline_id=%s, character_id=%s", new_storyline_id, character_id)
        except Exception as e:
            logger.warning("剧情线切换失败: %s", e)

    # ── 检查并触发剧情事件 ──
    triggered_events = check_and_trigger_story_events(
        conn, user_id, character_id, affection, new_phase,
        custom_vars=custom_vars, commit=False,
    )

    # ── 剧情线切换通知 ──
    old_storyline_id = current.get("storyline_id")
    if new_storyline_id and new_storyline_id != old_storyline_id:
        try:
            sl_row = conn.execute(
                "SELECT name FROM character_storylines WHERE id = %s",
                (new_storyline_id,)
            ).fetchone()
            if sl_row and sl_row["name"]:
                triggered_events.append({
                    "type": "storyline_changed",
                    "title": f"进入【{sl_row['name']}】",
                    "description": ""
                })
                custom_vars["_force_refresh_greeting"] = True
        except Exception:
            pass

    # ── 关系阶段升级通知 ──
    if new_phase != old_phase:
        try:
            from services.chat_query import get_greeting_for_phase
            storyline_id_for_greeting = None
            progress_row = conn.execute(
                "SELECT current_storyline_id FROM user_story_progress WHERE user_id = %s AND character_id = %s",
                (user_id, character_id),
            ).fetchone()
            if progress_row and progress_row["current_storyline_id"]:
                try:
                    storyline_id_for_greeting = int(progress_row["current_storyline_id"])
                except (ValueError, TypeError):
                    pass
            _, upgrade_greeting = get_greeting_for_phase(
                conn, character_id, new_phase, storyline_id_for_greeting,
            )
            if upgrade_greeting:
                custom_vars["_pending_phase_upgrade"] = {
                    "from_phase": old_phase,
                    "to_phase": new_phase,
                    "greeting": upgrade_greeting,
                }
                from constants.story_phase import STORY_PHASE_LABELS
                phase_label = STORY_PHASE_LABELS.get(new_phase, new_phase)
                triggered_events.append({
                    "type": "phase_upgrade",
                    "title": f"关系升级为「{phase_label}」",
                    "description": "下次打开对话时，角色会主动和你打招呼",
                })
                logger.info(
                    "关系阶段升级: user=%s char=%s %s→%s, 触发语已暂存",
                    user_id, character_id, old_phase, new_phase,
                )
        except Exception as e:
            logger.warning("阶段升级触发语处理异常: %s", e)

    # ── 待处理剧情事件管理 ──
    if triggered_events:
        pending = [
            {"title": e.get("title", ""), "event_content": e.get("event_content", "")}
            for e in triggered_events
            if e.get("event_content")
        ]
        if pending:
            custom_vars["_pending_events"] = pending
    else:
        custom_vars.pop("_pending_events", None)

    return custom_vars, triggered_events


def _persist_and_finalize(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    affection: int,
    story_phase: str,
    mood: str,
    custom_vars: dict[str, Any],
    current: dict[str, Any],
    triggered_events: list[dict[str, Any]],
    *,
    commit: bool,
) -> dict[str, Any]:
    """处理器6：持久化到数据库并返回最终状态。"""
    upsert_character_state(
        conn, user_id, character_id,
        affection=affection,
        story_phase=story_phase,
        mood=mood,
        custom_vars=custom_vars,
        daily_event_counts=current.get("_daily_event_counts", {}),
        daily_affection_gained=current.get("_daily_affection_gained", 0),
        last_event_timestamps=current.get("_last_event_timestamps", {}),
        daily_reset_date=current.get("_daily_reset_date", _get_today_date()),
        commit=False,
    )

    if commit:
        conn.commit()

    result = get_character_state(conn, user_id, character_id)
    if triggered_events:
        result["_triggered_events"] = triggered_events

    return result


def apply_state_delta(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    delta: dict[str, Any],
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """把 AI 输出的状态增量应用到现有状态，返回更新后的状态。

    安全说明：
        - 所有增量字段都会经过白名单验证
        - 非法字段会被自动过滤，不会报错但会被记录
        - 数值字段有范围限制，防止极端值
    """
    # 安全验证
    delta = _sanitize_state_delta(delta)

    # 处理器1：好感度变化计算
    current, affection, story_phase, mood, custom_vars = _resolve_affection_delta(
        conn, user_id, character_id, delta,
    )

    # 处理器2：剧情阶段推进
    story_phase, old_phase = _resolve_story_phase(
        conn, character_id, affection, story_phase, delta,
    )

    # 处理器3：心情 + 情感锚点
    mood, custom_vars = _resolve_mood_and_moments(mood, custom_vars, delta)

    # 处理器4：自定义变量 + 沉默轮数
    custom_vars = _resolve_custom_vars_and_silence(custom_vars, delta)

    # 处理器5：剧情线切换 + 剧情事件 + 阶段升级
    custom_vars, triggered_events = _handle_storyline_and_events(
        conn, user_id, character_id, affection, old_phase, story_phase,
        custom_vars, current, delta,
    )

    # 处理器6：持久化 + 返回
    return _persist_and_finalize(
        conn, user_id, character_id, affection, story_phase, mood,
        custom_vars, current, triggered_events, commit=commit,
    )



