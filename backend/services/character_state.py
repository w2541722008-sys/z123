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

内部流水线使用 CharacterStateSnapshot 数据对象，替代了原有的 12 参数传递。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from constants import Mood, StoryPhase
from core.database import ConnType
from core.character_state_snapshot import CharacterStateSnapshot
from repositories import character_repository as char_repo
from repositories import character_state_repository as state_repo
from repositories import story_repository as story_repo
from services.story_event_service import check_and_trigger_story_events
from utils.json_utils import parse_json_object
from constants.affection import (
    AFFECTION_BASE_RULES,
    AFFECTION_DELTA_MAX,
    DAILY_AFFECTION_CAP_DEFAULT,
)
from services.character_affection import (
    auto_advance_story_phase,
    calculate_affection_change,
    get_affection_rules,
    get_daily_cap,
    is_affection_enabled,
    update_anti_abuse_counters,
)

# 向后兼容别名（旧测试代码可能通过 from services.character_state import _xxx 引用）
_AFFECTION_BASE_RULES = AFFECTION_BASE_RULES
_AFFECTION_DELTA_MAX = AFFECTION_DELTA_MAX
_DAILY_AFFECTION_CAP_DEFAULT = DAILY_AFFECTION_CAP_DEFAULT
_calculate_affection_change = calculate_affection_change
_auto_advance_story_phase = auto_advance_story_phase
_update_anti_abuse_counters = update_anti_abuse_counters

logger = logging.getLogger(__name__)

_VALID_STORY_PHASES = tuple(phase.value for phase in StoryPhase)
_VALID_MOODS = tuple(mood.value for mood in Mood)


def get_greeting_for_phase(
    conn: ConnType,
    character_id: str,
    story_phase: str = "stranger",
    storyline_id: int | None = None,
) -> tuple[int | None, str | None]:
    """
    根据关系阶段获取对应的开场白。

    优先级：
    1. 从 character_greetings 表中查询匹配当前阶段和剧情线的开场白
    2. 如果没有匹配，返回 characters.opening_message

    返回：
        (greeting_id, 开场白内容)
        - 命中 character_greetings 时返回真实 greeting_id
        - 回退到 characters.opening_message 时返回 (None, content)
    """
    # 1. 尝试从多阶段开场白表中获取（含剧情线匹配优先级）
    row = None
    if storyline_id:
        row = char_repo.get_best_greeting_for_storyline(
            conn, character_id, story_phase, storyline_id
        )
        if not row:
            logger.info(
                "未找到剧情线 %s 的开场白，将尝试通用开场白",
                storyline_id,
            )

    # 2. 如果没有指定剧情线，或指定剧情线未匹配到，尝试通用开场白
    if not row:
        row = char_repo.get_generic_greeting(conn, character_id, story_phase)

    if row and row["content"]:
        return row["id"], row["content"]

    # 3. 回退到角色的默认开场白
    msg = char_repo.get_opening_message(conn, character_id)
    return None, msg


def _get_today_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ============================================================
# 状态读写
# ============================================================
def get_character_state(
    conn: ConnType, user_id: int | str, character_id: str, *, for_update: bool = False
) -> dict[str, Any]:
    """读取用户对某角色的当前关系状态，不存在时返回默认值。

    Args:
        for_update: 若为 True，对 character_states 行加 SELECT ... FOR UPDATE 行级锁，
                    防止并发请求之间的丢失更新。仅在事务中使用。
    """
    row = state_repo.get_character_state(
        conn, user_id, character_id, for_update=for_update
    )
    storyline_id = story_repo.get_current_storyline_id(conn, user_id, character_id)

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
        "_daily_event_counts": parse_json_object(
            row["daily_event_counts"] or "{}", fallback={}
        ),
        "_daily_affection_gained": int(row["daily_affection_gained"] or 0),
        "_last_event_timestamps": parse_json_object(
            row["last_event_timestamps"] or "{}", fallback={}
        ),
        "_daily_reset_date": row["daily_reset_date"] or "",
    }


def _reset_daily_fields_if_needed(
    snapshot: CharacterStateSnapshot | dict,
) -> CharacterStateSnapshot | dict:
    """惰性日重置：如果不是今天，归零当天统计。

    兼容 dict 和 CharacterStateSnapshot 两种输入，游客路径传入的是普通 dict。
    """
    today = _get_today_date()
    if isinstance(snapshot, dict):
        if snapshot.get("daily_reset_date", "") != today:
            snapshot["daily_event_counts"] = {}
            snapshot["daily_affection_gained"] = 0
            snapshot["daily_reset_date"] = today
    else:
        if snapshot.daily_reset_date != today:
            snapshot.daily_event_counts = {}
            snapshot.daily_affection_gained = 0
            snapshot.daily_reset_date = today
    return snapshot


def upsert_character_state(
    conn: ConnType,
    snapshot: CharacterStateSnapshot,
    *,
    commit: bool = True,
) -> None:
    """写入（插入或更新）一条关系状态记录。"""
    affection = max(0, min(100, int(snapshot.affection)))
    story_phase = (
        snapshot.story_phase
        if snapshot.story_phase in _VALID_STORY_PHASES
        else "stranger"
    )
    mood = snapshot.mood if snapshot.mood in _VALID_MOODS else "neutral"
    daily_reset_date = snapshot.daily_reset_date or _get_today_date()

    state_repo.upsert_character_state(
        conn,
        user_id=snapshot.user_id,
        character_id=snapshot.character_id,
        affection=affection,
        story_phase=story_phase,
        mood=mood,
        custom_vars_json=json.dumps(snapshot.custom_vars, ensure_ascii=False),
        daily_event_counts_json=json.dumps(
            snapshot.daily_event_counts, ensure_ascii=False
        ),
        daily_affection_gained=snapshot.daily_affection_gained,
        last_event_timestamps_json=json.dumps(
            snapshot.last_event_timestamps, ensure_ascii=False
        ),
        daily_reset_date=daily_reset_date,
    )
    if commit:
        conn.commit()


# ============================================================
# 状态增量应用
# ============================================================

_STATE_UPDATE_ALLOWED_FIELDS = {
    "affection",
    "event",
    "story_phase",
    "mood",
    "moment",
    "custom",
}

_CUSTOM_VARS_BLACKLIST = {
    "_triggered_events",
    "_daily_event_counts",
    "_daily_affection_gained",
    "_last_event_timestamps",
    "_daily_reset_date",
    "_shared_moments",
    "_pending_events",
    "_pending_phase_upgrade",
    "_silent_rounds",
}

_SHARED_MOMENTS_MAX = 15


def _sanitize_state_delta(delta: dict[str, Any]) -> dict[str, Any]:
    """清理和验证 STATE_UPDATE 增量，只允许白名单字段通过。"""
    if not isinstance(delta, dict):
        return {}

    sanitized: dict[str, str | int | dict[str, str | int | float]] = {}

    for key, value in delta.items():
        if key not in _STATE_UPDATE_ALLOWED_FIELDS:
            continue

        if key == "affection":
            if isinstance(value, (int, float)):
                sanitized[key] = max(
                    -AFFECTION_DELTA_MAX, min(AFFECTION_DELTA_MAX, int(value))
                )
            elif isinstance(value, str):
                sanitized[key] = value[:20]

        elif key == "event":
            if isinstance(value, str):
                sanitized[key] = value.strip().lower()[:50]

        elif key == "story_phase":
            if isinstance(value, str) and value.strip().lower() in _VALID_STORY_PHASES:
                sanitized[key] = value.strip().lower()

        elif key == "mood":
            if isinstance(value, str) and value.strip().lower() in _VALID_MOODS:
                sanitized[key] = value.strip().lower()

        elif key == "moment":
            if isinstance(value, str) and value.strip():
                sanitized[key] = value.strip()[:30]

        elif key == "custom":
            if isinstance(value, dict):
                safe_custom = {}
                for k, v in value.items():
                    if k in _CUSTOM_VARS_BLACKLIST:
                        continue
                    if not isinstance(k, str) or not k:
                        continue
                    safe_key = k[:50]
                    if isinstance(v, (str, int, float, bool)):
                        safe_custom[safe_key] = v
                    elif isinstance(v, dict):
                        safe_custom[safe_key] = str(v)[:200]
                    else:
                        safe_custom[safe_key] = str(v)[:200]
                sanitized[key] = safe_custom

    return sanitized


# ============================================================
# apply_state_delta 处理器（使用 CharacterStateSnapshot 流水线）
# ============================================================


def _resolve_affection_delta(
    conn: ConnType,
    snapshot: CharacterStateSnapshot,
    delta: dict[str, Any],
) -> CharacterStateSnapshot:
    """处理器1：好感度变化计算。在 snapshot 上原地修改 affection 等字段。"""
    affection_enabled = is_affection_enabled(conn, snapshot.character_id)

    if affection_enabled:
        if "event" in delta:
            event_name = str(delta["event"]).strip().lower()
            rules = get_affection_rules(conn, snapshot.character_id)
            daily_cap = get_daily_cap(conn, snapshot.character_id)
            # 将 snapshot 转为旧 dict 传给现有函数（渐进迁移，后续可改造这些函数）
            current_dict = snapshot.to_dict()
            affection_change, _ = calculate_affection_change(
                event_name, rules, current_dict, daily_cap=daily_cap
            )
            # 同步反滥用计数器回 snapshot
            anti_abuse = update_anti_abuse_counters(
                current_dict, event_name, affection_change
            )
            snapshot.daily_event_counts = anti_abuse.get(
                "_daily_event_counts", snapshot.daily_event_counts
            )
            snapshot.daily_affection_gained = anti_abuse.get(
                "_daily_affection_gained", snapshot.daily_affection_gained
            )
            snapshot.last_event_timestamps = anti_abuse.get(
                "_last_event_timestamps", snapshot.last_event_timestamps
            )
            snapshot.affection = max(0, min(100, snapshot.affection + affection_change))
        elif "affection" in delta:
            raw = str(delta["affection"]).strip()
            if raw.startswith("+"):
                raw_change = min(int(raw[1:]), AFFECTION_DELTA_MAX)
                snapshot.affection = max(0, min(100, snapshot.affection + raw_change))
            elif raw.startswith("-"):
                raw_change = min(int(raw[1:]), AFFECTION_DELTA_MAX)
                snapshot.affection = max(0, min(100, snapshot.affection - raw_change))
            else:
                try:
                    snapshot.affection = max(0, min(100, int(raw)))
                except ValueError:
                    pass

    return snapshot


def _resolve_story_phase(
    conn: ConnType,
    snapshot: CharacterStateSnapshot,
    delta: dict[str, Any],
) -> CharacterStateSnapshot:
    """处理器2：剧情阶段推进。设置 snapshot.old_phase（瞬态）。"""
    snapshot.old_phase = snapshot.story_phase

    if "story_phase" in delta:
        val = str(delta["story_phase"]).strip().lower()
        if val in _VALID_STORY_PHASES:
            snapshot.story_phase = val
            return snapshot

    # AI 未指定阶段时，按好感度自动推进
    allow_regression = False
    try:
        rules_row = char_repo.get_affection_config(conn, snapshot.character_id)
        if rules_row and rules_row["affection_rules_json"]:
            rules_json = parse_json_object(
                rules_row["affection_rules_json"], fallback={}
            )
            allow_regression = bool(rules_json.get("allow_regression", False))
    except Exception:
        logger.warning(
            "解析 affection_rules_json 失败 character_id=%s",
            snapshot.character_id,
            exc_info=True,
        )

    snapshot.story_phase = auto_advance_story_phase(
        snapshot.affection, snapshot.story_phase, allow_regression=allow_regression
    )
    return snapshot


def _resolve_mood_and_moments(
    snapshot: CharacterStateSnapshot,
    delta: dict[str, Any],
) -> CharacterStateSnapshot:
    """处理器3：心情更新 + 情感锚点追加（FIFO）。"""
    if "mood" in delta:
        val = str(delta["mood"]).strip().lower()
        if val in _VALID_MOODS:
            snapshot.mood = val

    if "moment" in delta and delta["moment"]:
        moments = list(snapshot.custom_vars.get("_shared_moments") or [])
        moments.append(str(delta["moment"]))
        if len(moments) > _SHARED_MOMENTS_MAX:
            moments = moments[-_SHARED_MOMENTS_MAX:]
        snapshot.custom_vars["_shared_moments"] = moments

    return snapshot


def _resolve_custom_vars_and_silence(
    snapshot: CharacterStateSnapshot,
    delta: dict[str, Any],
) -> CharacterStateSnapshot:
    """处理器4：自定义变量更新（含 +/- 增量语义）+ 沉默轮数计数。"""
    if "custom" in delta and isinstance(delta["custom"], dict):
        for k, v in delta["custom"].items():
            raw = str(v).strip()
            existing = snapshot.custom_vars.get(k)
            if raw.startswith("+") and isinstance(existing, (int, float)):
                try:
                    snapshot.custom_vars[k] = existing + int(raw[1:])
                except ValueError:
                    snapshot.custom_vars[k] = raw
            elif raw.startswith("-") and isinstance(existing, (int, float)):
                try:
                    snapshot.custom_vars[k] = existing - int(raw[1:])
                except ValueError:
                    snapshot.custom_vars[k] = raw
            else:
                snapshot.custom_vars[k] = v

    has_state_update = "event" in delta or "affection" in delta
    silent_rounds = int(snapshot.custom_vars.get("_silent_rounds") or 0)
    if has_state_update:
        snapshot.custom_vars["_silent_rounds"] = 0
    else:
        snapshot.custom_vars["_silent_rounds"] = silent_rounds + 1

    return snapshot


def _handle_storyline_and_events(
    conn: ConnType,
    snapshot: CharacterStateSnapshot,
    delta: dict[str, Any],
) -> CharacterStateSnapshot:
    """处理器5：剧情线切换 + 剧情事件触发 + 阶段升级通知 + 待处理事件管理。"""
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
            if story_repo.is_storyline_valid(
                conn, new_storyline_id, snapshot.character_id
            ):
                story_repo.set_current_storyline_id(
                    conn,
                    snapshot.user_id,
                    snapshot.character_id,
                    new_storyline_id,
                )
                # 内存传播，消除 SQL#11 防御性重读
                snapshot.storyline_id = new_storyline_id
            else:
                logger.warning(
                    "剧情线ID无效或不属于当前角色: storyline_id=%s, character_id=%s",
                    new_storyline_id,
                    snapshot.character_id,
                )
        except Exception as e:
            logger.warning(
                "剧情线切换失败 storyline_id=%s: %s", new_storyline_id, e, exc_info=True
            )

    # ── 检查并触发剧情事件 ──
    triggered_events = check_and_trigger_story_events(
        conn,
        snapshot.user_id,
        snapshot.character_id,
        snapshot.affection,
        snapshot.story_phase,
        custom_vars=snapshot.custom_vars,
        commit=False,
    )

    # ── 剧情线切换通知 ──
    old_storyline_id = snapshot.storyline_id
    if new_storyline_id and new_storyline_id != old_storyline_id:
        try:
            sl_name = story_repo.get_storyline_name(conn, new_storyline_id)
            if sl_name:
                triggered_events.append(
                    {
                        "type": "storyline_changed",
                        "title": f"进入【{sl_name}】",
                        "description": "",
                    }
                )
                snapshot.custom_vars["_force_refresh_greeting"] = True
        except Exception:
            logger.warning(
                "剧情线切换查询失败 storyline_id=%s", new_storyline_id, exc_info=True
            )

    # ── 关系阶段升级通知 ──
    old_phase = snapshot.old_phase or snapshot.story_phase
    if snapshot.story_phase != old_phase:
        try:
            _, upgrade_greeting = get_greeting_for_phase(
                conn,
                snapshot.character_id,
                snapshot.story_phase,
                snapshot.storyline_id,
            )
            if upgrade_greeting:
                snapshot.custom_vars["_pending_phase_upgrade"] = {
                    "from_phase": old_phase,
                    "to_phase": snapshot.story_phase,
                    "greeting": upgrade_greeting,
                }
                from constants.story_phase import STORY_PHASE_LABELS

                phase_label = STORY_PHASE_LABELS.get(
                    snapshot.story_phase, snapshot.story_phase
                )
                triggered_events.append(
                    {
                        "type": "phase_upgrade",
                        "title": f"关系升级为「{phase_label}」",
                        "description": "下次打开对话时，角色会主动和你打招呼",
                    }
                )
                logger.info(
                    "关系阶段升级: user=%s char=%s %s→%s, 触发语已暂存",
                    snapshot.user_id,
                    snapshot.character_id,
                    old_phase,
                    snapshot.story_phase,
                )
        except Exception as e:
            logger.warning("阶段升级触发语处理异常: %s", e, exc_info=True)

    # ── 待处理剧情事件管理 ──
    if triggered_events:
        pending = [
            {"title": e.get("title", ""), "event_content": e.get("event_content", "")}
            for e in triggered_events
            if e.get("event_content")
        ]
        if pending:
            snapshot.custom_vars["_pending_events"] = pending
    else:
        snapshot.custom_vars.pop("_pending_events", None)

    snapshot.triggered_events = triggered_events
    return snapshot


def _persist_and_finalize(
    conn: ConnType,
    snapshot: CharacterStateSnapshot,
    *,
    commit: bool,
) -> dict[str, Any]:
    """处理器6：持久化到数据库并返回最终状态。"""
    upsert_character_state(conn, snapshot, commit=False)

    if commit:
        conn.commit()

    # 数据已在 snapshot 中，无需重新查询数据库
    result = snapshot.to_dict()
    if snapshot.triggered_events:
        result["_triggered_events"] = snapshot.triggered_events

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

    内部使用 CharacterStateSnapshot 流水线，替代原有的 12 参数传递。
    """
    # 安全验证
    delta = _sanitize_state_delta(delta)

    # 读取当前状态，构建快照
    state_dict = get_character_state(conn, user_id, character_id, for_update=True)
    snapshot = CharacterStateSnapshot.from_legacy_dict(
        state_dict, user_id, character_id
    )
    snapshot = _reset_daily_fields_if_needed(snapshot)

    # 流水线处理
    snapshot = _resolve_affection_delta(conn, snapshot, delta)
    snapshot = _resolve_story_phase(conn, snapshot, delta)
    snapshot = _resolve_mood_and_moments(snapshot, delta)
    snapshot = _resolve_custom_vars_and_silence(snapshot, delta)
    snapshot = _handle_storyline_and_events(conn, snapshot, delta)

    # 持久化
    return _persist_and_finalize(conn, snapshot, commit=commit)


def _resolve_show_bar_preference(conn: ConnType, character_id: str) -> bool:
    """从角色配置读取状态栏显隐偏好，解析失败时保持显示。"""
    try:
        rules_row = char_repo.get_affection_config(conn, character_id)
        if rules_row and rules_row["affection_rules_json"]:
            rules = parse_json_object(rules_row["affection_rules_json"], fallback={})
            if "show_bar" in rules:
                return bool(rules["show_bar"])
    except Exception:
        logger.warning(
            "解析好感度规则失败 character_id=%s", character_id, exc_info=True
        )
    return True


def _serialize_public_character_state(
    conn: ConnType,
    raw_state: dict[str, Any],
    character_id: str,
) -> dict[str, Any]:
    """把内部状态转换为前端可见状态。"""
    if not raw_state:
        return {}

    result = {k: v for k, v in raw_state.items() if not str(k).startswith("_")}

    # 暴露剧情事件给前端，去掉内部下划线前缀。
    if "_triggered_events" in raw_state:
        result["triggered_events"] = raw_state["_triggered_events"]

    result["show_bar"] = _resolve_show_bar_preference(conn, character_id)

    storyline_id = raw_state.get("storyline_id")
    if storyline_id:
        try:
            storyline_name = story_repo.get_storyline_name(conn, storyline_id)
            if storyline_name:
                result["storyline_name"] = storyline_name
        except Exception:
            logger.warning(
                "查询剧情线名称失败 storyline_id=%s", storyline_id, exc_info=True
            )

    return result


def get_public_character_state(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """读取或更新后返回前端可见的角色状态。"""
    if delta:
        raw_state = apply_state_delta(conn, user_id, character_id, delta, commit=False)
    else:
        raw_state = get_character_state(conn, user_id, character_id)
    return _serialize_public_character_state(conn, raw_state, character_id)
