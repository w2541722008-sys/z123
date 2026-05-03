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
       - 每日好感度涨幅上限 15 点
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

# 标准库导入
import json
import logging
from datetime import date, datetime, timezone
from typing import Any

# 本地模块导入
from core.config import utc_now
from constants import Mood, StoryPhase
from core.database import ConnType
from services.cache_service import cache_get, cache_set
from services.story_event_service import check_and_trigger_story_events
from utils.json_utils import parse_json_object

logger = logging.getLogger(__name__)

# ============================================================
# 全局配置常量
# ============================================================

# 全局底座事件规则（角色卡可覆盖）
# 正向事件：增加好感度，负向事件：减少好感度
_AFFECTION_BASE_RULES: dict[str, int] = {
    # === 正向事件 ===
    "deep_conversation": 4,   # 深度交流
    "light_chat": 1,          # 闲聊
    "compliment": 2,          # 赞美
    "gift": 6,                # 送礼物
    "help": 3,                # 帮助
    "shared_secret": 5,       # 分享秘密
    "first_meeting": 3,       # 初次见面
    "comfort": 3,             # 安慰
    "flirt": 2,               # 调情
    "date": 5,                # 约会
    "first_hug": 7,           # 第一次拥抱
    "kiss": 8,                # 亲吻
    "confession": 10,         # 表白
    # === 负向事件 ===
    "argument": -5,           # 争吵
    "rude": -3,               # 粗鲁
    "ignore": -2,             # 忽视
    "lie": -4,                # 撒谎
    "betray": -8,             # 背叛
    "insult": -6,             # 侮辱
}

# 事件冷却时间（秒）
# 防止短时间内重复刷同一事件
_AFFECTION_COOLDOWN_SECONDS: dict[str, int] = {
    "deep_conversation": 3600,     # 1小时
    "light_chat": 300,             # 5分钟
    "compliment": 1800,            # 30分钟
    "gift": 86400,                 # 24小时
    "help": 3600,                  # 1小时
    "shared_secret": 7200,         # 2小时
    "first_meeting": 604800,       # 7天（一次性事件）
    "comfort": 1800,               # 30分钟
    "flirt": 1200,                 # 20分钟
    "date": 43200,                 # 12小时
    "first_hug": 604800,           # 7天（一次性事件）
    "kiss": 604800,                # 7天（一次性事件）
    "confession": 604800,          # 7天（一次性事件）
}

# 边际递减系数
# 第1次 100%，第2次 60%，第3次 30%，第4次+ 0%
_AFFECTION_DIMINISHING_RETURNS: list[float] = [1.0, 0.6, 0.3, 0.0]

# 单日好感度上限
_DAILY_AFFECTION_CAP = 15

# 剧情阶段阈值（好感度达到阈值自动推进）
_PHASE_THRESHOLDS: dict[str, int] = {
    "acquaintance": 20,   # 熟人
    "friend": 50,         # 朋友
    "lover": 80,          # 恋人
}

# 阶段涨幅系数（越后期越难涨）
# 陌生人 100%，熟人 80%，朋友 60%，恋人 40%
_PHASE_GAIN_MULTIPLIER: dict[str, float] = {
    "stranger": 1.0,
    "acquaintance": 0.8,
    "friend": 0.6,
    "lover": 0.4,
}

# 有效阶段列表（从 StoryPhase 枚举派生）
_VALID_STORY_PHASES = tuple(phase.value for phase in StoryPhase)

# 有效心情列表（从 Mood 枚举派生）
_VALID_MOODS = tuple(mood.value for mood in Mood)

# 单次好感度变化上限（防止极端情况）
_AFFECTION_DELTA_MAX = 10


# ============================================================
# 工具函数
# ============================================================
def _get_today_date() -> str:
    """返回 UTC 日期字符串 YYYY-MM-DD（与数据库字段保持一致）。"""
    return datetime.now(timezone.utc).date().isoformat()


def _get_affection_rules(conn: ConnType, character_id: str) -> dict[str, int]:
    """读取角色卡自定义规则，与全局底座合并（角色卡覆盖同名 key）。结果缓存 300s。"""
    cache_key = f"affection_rules:{character_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return dict(cached)

    row = conn.execute(
        "SELECT affection_rules_json, affection_enabled FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    if not row:
        result = dict(_AFFECTION_BASE_RULES)
        cache_set(cache_key, result, ttl=300)
        return result

    merged = dict(_AFFECTION_BASE_RULES)
    card_rules = parse_json_object(row["affection_rules_json"] or "{}", fallback={})
    
    for k, v in card_rules.items():
        if k == "enabled":
            continue
        try:
            raw_val = int(v)
        except (ValueError, TypeError):
            continue

        if k in _AFFECTION_BASE_RULES:
            base_original = _AFFECTION_BASE_RULES[k]
            if base_original >= 0:
                max_allowed = min(base_original * 2, 15)
                raw_val = max(0, min(raw_val, max_allowed))
            else:
                min_allowed = max(base_original * 2, -15)
                raw_val = min(0, max(raw_val, min_allowed))
        else:
            raw_val = max(-10, min(raw_val, 10))

        merged[k] = raw_val

    cache_set(cache_key, merged, ttl=300)
    return merged


def is_affection_enabled(conn: ConnType, character_id: str) -> bool:
    """判断该角色卡是否启用好感度系统。"""
    row = conn.execute(
        "SELECT affection_enabled, affection_rules_json, card_type FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    if not row:
        return True

    card_type = (row["card_type"] or "intimate").strip()
    if card_type == "world":
        return False

    if int(row["affection_enabled"] or 1) == 0:
        return False

    card_rules = parse_json_object(row["affection_rules_json"] or "{}", fallback={})
    if "enabled" in card_rules:
        return bool(card_rules["enabled"])

    return True


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
# 好感度计算（三防机制）
# ============================================================
def _calculate_affection_change(
    event: str,
    rules: dict[str, int],
    current_state: dict[str, Any],
) -> tuple[int, str]:
    """
    计算单个事件对好感度的实际影响，应用三防机制。

    三防机制详解：
        1. 冷却检测：同类事件在冷却期内触发，加分归零
        2. 日上限检测：今日涨幅已达上限，正向加分归零
        3. 边际递减：同类事件多次触发，按衰减系数折减

    负向事件特殊处理：
        - 负向事件不受三防限制（防止恶意刷分）
        - 但受阶段系数影响（关系越好，负向影响越大）
        - 陌生人 80%，熟人 100%，朋友 120%，恋人 150%

    Args:
        event: 事件名称
        rules: 好感度规则字典
        current_state: 当前状态字典

    Returns:
        tuple: (实际变化量, 计算原因说明)

    计算步骤：
        1. 获取基础变化量
        2. 如果是负向事件，应用阶段系数，返回结果
        3. 如果是正向事件，依次应用三防机制
        4. 计算最终变化量
    """
    # 步骤 1：获取基础变化量
    base_change = rules.get(event, 0)
    if base_change == 0:
        return 0, f"event={event} not in rules or base_change=0"

    # 步骤 2：负向事件处理（不受三防限制）
    if base_change < 0:
        phase = current_state.get("story_phase", "stranger")
        # 负向事件阶段系数：关系越好，伤害越大
        negative_multiplier = {
            "stranger": 0.8,
            "acquaintance": 1.0,
            "friend": 1.2,
            "lover": 1.5,
        }.get(phase, 1.0)
        actual = int(base_change * negative_multiplier)
        actual = max(actual, -_AFFECTION_DELTA_MAX)  # 限制单次最大跌幅
        return actual, f"negative event, phase={phase}, multiplier={negative_multiplier}"

    # 步骤 3：正向事件 - 三防机制

    # ① 冷却检测
    cooldown_secs = _AFFECTION_COOLDOWN_SECONDS.get(event, 600)
    last_ts_map = current_state.get("_last_event_timestamps", {})
    last_ts = last_ts_map.get(event)
    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed < cooldown_secs:
                remaining = int(cooldown_secs - elapsed)
                return 0, f"cooldown: event={event}, remaining={remaining}s"
        except (ValueError, TypeError):
            pass  # 时间格式错误，忽略冷却检测

    # ② 今日上限检测
    daily_gained = current_state.get("_daily_affection_gained", 0)
    if daily_gained >= _DAILY_AFFECTION_CAP:
        return 0, f"daily_cap: already gained {daily_gained}/{_DAILY_AFFECTION_CAP} today"

    # ③ 边际递减
    daily_counts = current_state.get("_daily_event_counts", {})
    trigger_count = int(daily_counts.get(event, 0))
    if trigger_count < len(_AFFECTION_DIMINISHING_RETURNS):
        diminish_rate = _AFFECTION_DIMINISHING_RETURNS[trigger_count]
    else:
        diminish_rate = 0.0

    # ④ 阶段系数
    phase = current_state.get("story_phase", "stranger")
    phase_multiplier = _PHASE_GAIN_MULTIPLIER.get(phase, 1.0)

    # ⑤ 计算最终变化量
    raw = base_change * diminish_rate * phase_multiplier
    actual = max(0, min(int(round(raw)), base_change))

    # ⑥ 日上限兜底（确保不超过今日剩余额度）
    remaining_cap = max(0, _DAILY_AFFECTION_CAP - daily_gained)
    actual = min(actual, remaining_cap)

    reason = (
        f"event={event}, base={base_change}, diminish={diminish_rate:.1f}, "
        f"phase={phase}×{phase_multiplier}, actual={actual}"
    )
    return actual, reason


def _update_anti_abuse_counters(
    current_state: dict[str, Any],
    event: str,
    actual_change: int,
) -> dict[str, Any]:
    """更新三防计数器。"""
    last_ts_map = dict(current_state.get("_last_event_timestamps", {}))
    last_ts_map[event] = utc_now().isoformat()

    daily_counts = dict(current_state.get("_daily_event_counts", {}))
    daily_gained = current_state.get("_daily_affection_gained", 0)

    if actual_change > 0:
        daily_counts[event] = int(daily_counts.get(event, 0)) + 1
        daily_gained = daily_gained + actual_change

    updated = dict(current_state)
    updated["_last_event_timestamps"] = last_ts_map
    updated["_daily_event_counts"] = daily_counts
    updated["_daily_affection_gained"] = daily_gained
    return updated


def _auto_advance_story_phase(affection: int, current_phase: str) -> str:
    """
    根据好感度阈值自动推进剧情阶段（单向，只升不降）。

    阶段推进规则：
        - stranger（陌生人）→ acquaintance（熟人）：好感度 >= 20
        - acquaintance（熟人）→ friend（朋友）：好感度 >= 50
        - friend（朋友）→ lover（恋人）：好感度 >= 80

    重要特性：
        - 单向推进：阶段只升不降，即使好感度下降也不会回退
        - 自动触发：好感度达到阈值时自动推进，无需手动操作

    Args:
        affection: 当前好感度值（0-100）
        current_phase: 当前阶段

    Returns:
        新的阶段名称

    示例：
        >>> _auto_advance_story_phase(30, "stranger")
        'acquaintance'
        >>> _auto_advance_story_phase(45, "acquaintance")
        'acquaintance'  # 未达到 50，保持原阶段
    """
    phases_order = list(_VALID_STORY_PHASES)
    current_idx = phases_order.index(current_phase) if current_phase in phases_order else 0

    # 找出当前好感度能达到的最高阶段
    best_idx = current_idx
    for phase_name, threshold in _PHASE_THRESHOLDS.items():
        if affection >= threshold:
            candidate_idx = phases_order.index(phase_name) if phase_name in phases_order else 0
            if candidate_idx > best_idx:
                best_idx = candidate_idx

    return phases_order[best_idx]


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
    "custom",         # 自定义变量字典
}

# 自定义变量的黑名单 - 这些键不允许被AI修改
_CUSTOM_VARS_BLACKLIST = {
    "_triggered_events",  # 内部事件标记
    "_daily_event_counts",  # 日事件计数（内部使用）
    "_daily_affection_gained",  # 日好感度获得（内部使用）
    "_last_event_timestamps",  # 事件时间戳（内部使用）
    "_daily_reset_date",  # 日重置日期（内部使用）
}


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
            affection_change, _ = _calculate_affection_change(event_name, rules, current)
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
        story_phase = _auto_advance_story_phase(affection, story_phase)

    # 心情
    if "mood" in delta:
        val = str(delta["mood"]).strip().lower()
        if val in _VALID_MOODS:
            mood = val

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

    # 检查并触发剧情事件（在写库之前，基于新的好感度）
    triggered_events = check_and_trigger_story_events(
        conn, user_id, character_id, affection, story_phase, commit=False
    )

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



