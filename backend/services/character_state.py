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
def get_character_state(conn: ConnType, user_id: int | str, character_id: str) -> dict[str, Any]:
    """读取用户对某角色的当前关系状态，不存在时返回默认值。"""
    # 查询角色状态
    row = conn.execute(
        """
        SELECT affection, story_phase, mood, custom_vars,
               daily_event_counts, daily_affection_gained, last_event_timestamps, daily_reset_date
        FROM character_states
        WHERE user_id = %s AND character_id = %s
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
            "affection": 30,
            "story_phase": "stranger",
            "mood": "neutral",
            "custom_vars": {},
            "storyline_id": storyline_id,
        }
    
    return {
        "affection": int(row["affection"] or 30),
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


def apply_state_delta(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    delta: dict[str, Any],
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """
    把 AI 输出的状态增量应用到现有状态，返回更新后的状态。
    
    安全说明：
        - 所有增量字段都会经过白名单验证
        - 非法字段会被自动过滤，不会报错但会被记录
        - 数值字段有范围限制，防止极端值
    """
    # 首先验证和清理增量
    delta = _sanitize_state_delta(delta)
    
    affection_enabled = is_affection_enabled(conn, character_id)

    current = get_character_state(conn, user_id, character_id)
    current = _reset_daily_fields_if_needed(current)

    affection = current["affection"]
    story_phase = current["story_phase"]
    mood = current["mood"]
    custom_vars = dict(current["custom_vars"])

    # 好感度变化量计算
    affection_change = 0

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

    # 剧情阶段
    if "story_phase" in delta:
        val = str(delta["story_phase"]).strip().lower()
        if val in _VALID_STORY_PHASES:
            story_phase = val
    else:
        # 检查是否允许阶段回退（从角色卡的 affection_rules_json 中读取）
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
            pass
        story_phase = _auto_advance_story_phase(affection, story_phase, allow_regression=allow_regression)

    # 心情
    if "mood" in delta:
        val = str(delta["mood"]).strip().lower()
        if val in _VALID_MOODS:
            mood = val

    # 情感锚点：moment → 追加到 custom_vars._shared_moments（FIFO）
    if "moment" in delta and delta["moment"]:
        moments = list(custom_vars.get("_shared_moments") or [])
        moments.append(str(delta["moment"]))
        if len(moments) > _SHARED_MOMENTS_MAX:
            moments = moments[-_SHARED_MOMENTS_MAX:]
        custom_vars["_shared_moments"] = moments

    # 自定义变量
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

    # 沉默轮数检测：AI 有上报事件则归零，无上报则 +1
    has_state_update = "event" in delta or "affection" in delta
    silent_rounds = int(custom_vars.get("_silent_rounds") or 0)
    if has_state_update:
        custom_vars["_silent_rounds"] = 0
    else:
        custom_vars["_silent_rounds"] = silent_rounds + 1

    # 剧情线 AI 驱动切换：当 AI 通过 custom.current_storyline_id 切换剧情线时，
    # 同步更新 user_story_progress 表，确保后置规则等逻辑感知到切换
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
            # 校验剧情线ID是否属于当前角色且已激活，防止AI幻觉写入无效ID
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

    # 检查并触发剧情事件（在写库之前，基于新的好感度）
    triggered_events = check_and_trigger_story_events(
        conn, user_id, character_id, affection, story_phase,
        custom_vars=custom_vars, commit=False,
    )

    # 检测剧情线切换并通知用户
    old_storyline_id = current.get("storyline_id")
    if new_storyline_id and new_storyline_id != old_storyline_id:
        try:
            sl_row = conn.execute(
                "SELECT name FROM character_storylines WHERE id = %s",
                (new_storyline_id,)
            ).fetchone()
            if sl_row and sl_row["name"]:
                if not triggered_events:
                    triggered_events = []
                triggered_events.append({
                    "type": "storyline_changed",
                    "title": f"进入【{sl_row['name']}】",
                    "description": ""
                })
                # 标记需要刷新开场白
                custom_vars["_force_refresh_greeting"] = True
        except Exception:
            pass

    # 将触发的剧情事件内容存入 custom_vars._pending_events（下一轮注入到 prompt）
    if triggered_events:
        pending = [
            {"title": e.get("title", ""), "event_content": e.get("event_content", "")}
            for e in triggered_events
            if e.get("event_content")
        ]
        if pending:
            custom_vars["_pending_events"] = pending
    else:
        # AI 已成功回复，清空上一轮已消费的待处理事件
        # （如果本轮触发了新事件，上面的 pending 已设置；否则清除旧事件）
        custom_vars.pop("_pending_events", None)

    # 写库
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

    # 将触发的事件信息添加到返回结果中
    if triggered_events:
        result["_triggered_events"] = triggered_events

    return result



