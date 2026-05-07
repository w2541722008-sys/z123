"""
记忆服务 - 聊天摘要生成、结构化存储、后台刷新

职责：
- 获取和解析结构化摘要（用户画像、偏好、事件、关系、待跟进）
- 生成和合并摘要文本
- 后台异步刷新摘要
- 管理摘要任务并发控制
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any

from core.config import RECENT_MESSAGE_WINDOW, SUMMARY_MAX_TOKENS, SUMMARY_TRIGGER_COUNT, logger, utc_now
from core.database import ConnType, get_conn
from core.model_adapter import get_ai_config, request_chat_completion
from utils.stream_filter import normalize_reply_text


# ============================================================
# 常量定义
# ============================================================

_SUMMARY_SECTION_TITLES: list[tuple[str, str]] = [
    ("profile", "用户画像"),
    ("preferences", "用户偏好"),
    ("events", "近期事件"),
    ("relationship", "关系状态"),
    ("pending", "待跟进事项"),
]

_SUMMARY_SECTION_LIMITS: dict[str, int] = {
    "profile": 8,
    "preferences": 5,
    "events": 8,
    "relationship": 8,
    "pending": 5,
}

_PERSISTENT_KEYS = {"profile", "relationship"}
_PERSISTENT_PRESERVE_SLOTS = 3

_SUMMARY_SECTION_ALIASES: dict[str, str] = {
    "用户画像": "profile",
    "用户偏好": "preferences",
    "近期事件": "events",
    "关系状态": "relationship",
    "待跟进事项": "pending",
    "待跟进": "pending",
    "未完成话题": "pending",
}

# 并发控制
_SUMMARY_JOB_LOCK = threading.Lock()
_SUMMARY_RUNNING_KEYS: set[tuple[int, str]] = set()
_MAX_SUMMARY_THREADS = threading.Semaphore(5)


# ============================================================
# 数据库查询
# ============================================================

def get_recent_messages(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    limit: int = RECENT_MESSAGE_WINDOW,
) -> list[dict[str, str]]:
    """获取最近 N 条消息（按时间正序）。"""
    rows = conn.execute(
        """
        SELECT role, content FROM (
            SELECT id, role, content
            FROM chat_messages
            WHERE user_id = %s AND character_id = %s
            ORDER BY id DESC
            LIMIT %s
        ) sub
        ORDER BY id ASC
        """,
        (user_id, character_id, limit),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def get_unsummarized_messages(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> list[dict[str, Any]]:
    """获取所有未摘要的消息。"""
    rows: list[dict[str, Any]] = conn.execute(
        """
        SELECT id, role, content, created_at
        FROM chat_messages
        WHERE user_id = %s AND character_id = %s AND is_summarized = FALSE
        ORDER BY id ASC
        """,
        (user_id, character_id),
    ).fetchall()
    return rows


def get_summary_record(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> Any | None:
    """获取摘要记录（完整行）。"""
    return conn.execute(
        "SELECT * FROM chat_summaries WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    ).fetchone()


def get_summary_text(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> str:
    """获取摘要文本（纯文本）。"""
    row = get_summary_record(conn, user_id, character_id)
    if not row:
        return ""
    return (row["summary"] or "").strip()


def save_summary(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    summary_text: str,
    last_message_id: int | None,
) -> None:
    """保存或更新摘要记录。"""
    now = utc_now()
    existing = get_summary_record(conn, user_id, character_id)
    if existing:
        conn.execute(
            """
            UPDATE chat_summaries
            SET summary = %s,
                memory_version = memory_version + 1,
                last_message_id = %s,
                last_summarized_at = %s,
                updated_at = now()
            WHERE user_id = %s AND character_id = %s
            """,
            (summary_text, last_message_id, now, user_id, character_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO chat_summaries(
                user_id, character_id, summary, memory_version,
                last_message_id, last_summarized_at
            ) VALUES (%s, %s, %s, 1, %s, %s)
            """,
            (user_id, character_id, summary_text, last_message_id, now),
        )


def mark_messages_summarized(conn: ConnType, message_ids: list[int]) -> None:
    """标记消息为已摘要。"""
    if not message_ids:
        return
    placeholders = ",".join("%s" for _ in message_ids)
    conn.execute(
        f"UPDATE chat_messages SET is_summarized = 1 WHERE id IN ({placeholders})",
        message_ids,
    )


def should_refresh_summary(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> bool:
    """判断是否需要刷新摘要（未摘要消息数 >= 阈值）。"""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM chat_messages WHERE user_id = %s AND character_id = %s AND is_summarized = FALSE",
        (user_id, character_id),
    ).fetchone()
    return int(row["cnt"]) >= SUMMARY_TRIGGER_COUNT


# ============================================================
# 结构化摘要解析与格式化
# ============================================================

def _empty_structured_summary() -> dict[str, Any]:
    """返回空的结构化摘要。"""
    return {
        "profile": [],
        "preferences": [],
        "events": [],
        "relationship": [],
        "pending": [],
        "raw_summary": "",
    }


def _parse_structured_summary_text(summary_text: str) -> dict[str, list[str]]:
    """解析摘要文本为结构化字典。"""
    result: dict[str, list[str]] = {key: [] for key, _ in _SUMMARY_SECTION_TITLES}
    current_key: str | None = None
    for raw_line in (summary_text or "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        matched_key = None
        if line.startswith("[") and "]" in line:
            title = line[1:line.find("]")].strip()
            matched_key = _SUMMARY_SECTION_ALIASES.get(title)
        if matched_key:
            current_key = matched_key
            continue
        if current_key is None:
            continue
        if line.startswith(("- ", "• ", "* ")):
            item = line[2:].strip()
        else:
            item = line.strip()
        if item:
            result[current_key].append(item)
    return result


def _dedupe_summary_items(items: list[str], limit: int) -> list[str]:
    """去重并限制条目数量。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if not text:
            continue
        norm = text.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _render_structured_summary(summary: dict[str, list[str]]) -> str:
    """将结构化摘要渲染为文本。"""
    blocks: list[str] = []
    for key, title in _SUMMARY_SECTION_TITLES:
        items = _dedupe_summary_items(summary.get(key, []), _SUMMARY_SECTION_LIMITS[key])
        if not items:
            items = ["暂无稳定信息"]
        block = [f"[{title}]"]
        block.extend(f"- {item}" for item in items)
        blocks.append("\n".join(block))
    return "\n\n".join(blocks).strip()


def get_structured_summary(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> dict[str, Any]:
    """获取结构化摘要（包含原始文本）。"""
    row = get_summary_record(conn, user_id, character_id)
    if not row:
        return _empty_structured_summary()
    summary_text = (row["summary"] or "").strip()
    parsed = _parse_structured_summary_text(summary_text)
    return {
        "profile": parsed.get("profile", []),
        "preferences": parsed.get("preferences", []),
        "events": parsed.get("events", []),
        "relationship": parsed.get("relationship", []),
        "pending": parsed.get("pending", []),
        "raw_summary": summary_text,
    }


def format_structured_summary(summary: dict[str, Any]) -> str:
    """格式化结构化摘要为 Prompt 可用文本。"""
    blocks: list[str] = []
    mapping = [
        ("用户画像", summary.get("profile", [])),
        ("用户偏好", summary.get("preferences", [])),
        ("近期事件", summary.get("events", [])),
        ("关系状态", summary.get("relationship", [])),
        ("待跟进事项", summary.get("pending", [])),
    ]
    for title, items in mapping:
        if not items:
            continue
        rows = []
        for item in items:
            text = str(item or "").strip()
            if not text:
                continue
            rows.append(text if text.startswith("- ") else f"- {text}")
        if rows:
            blocks.append(f"【{title}】\n" + "\n".join(rows))
    return "\n\n".join(blocks).strip()


def get_summary_for_prompt(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
) -> str:
    """获取用于 Prompt 的摘要文本（优先使用结构化格式）。"""
    structured = get_structured_summary(conn, user_id, character_id)
    formatted = format_structured_summary(structured)
    if formatted:
        return formatted
    return get_summary_text(conn, user_id, character_id)


# ============================================================
# 摘要生成与合并
# ============================================================

def build_structured_memory_summary_fallback(
    existing_summary: str,
    unsummarized_messages: list[Any],
) -> str:
    """降级方案：从消息中提取简单摘要。"""
    user_lines = [row["content"].strip() for row in unsummarized_messages if row["role"] == "user" and row["content"].strip()]
    assistant_lines = [row["content"].strip() for row in unsummarized_messages if row["role"] == "assistant" and row["content"].strip()]

    def pick(items: list[str], limit: int = 3) -> list[str]:
        return [f"- {item[:60]}" for item in items[-limit:]] or ["- 暂无稳定信息"]

    structured = [
        "[用户画像]",
        *pick(user_lines[:2], limit=2),
        "[用户偏好]",
        *(["- 从近期对话中暂未提炼出稳定偏好"] if not user_lines else [f"- 用户最近反复提到：{user_lines[-1][:60]}"]),
        "[近期事件]",
        *pick(user_lines, limit=3),
        "[待跟进事项]",
        *(["- 暂无明确待跟进事项"] if not user_lines else [f"- 可在后续对话跟进：{user_lines[-1][:60]}"]),
        "[关系状态]",
        *(["- 角色持续与用户保持对话，关系在稳定推进"] if assistant_lines else ["- 暂无稳定信息"]),
    ]

    if existing_summary.strip():
        return existing_summary.strip() + "\n" + "\n".join(structured)
    return "\n".join(structured)


def merge_summary_text(existing_summary: str, new_summary_text: str) -> str:
    """合并新旧摘要（保留持久化字段的旧条目）。"""
    new_text = normalize_reply_text(new_summary_text)
    old_text = normalize_reply_text(existing_summary)

    if not new_text:
        return old_text
    if not old_text:
        return new_text

    old_structured = _parse_structured_summary_text(old_text)
    new_structured = _parse_structured_summary_text(new_text)

    has_old_sections = any(old_structured.get(key) for key, _ in _SUMMARY_SECTION_TITLES)
    has_new_sections = any(new_structured.get(key) for key, _ in _SUMMARY_SECTION_TITLES)
    if not has_old_sections or not has_new_sections:
        return new_text or old_text

    merged: dict[str, list[str]] = {}
    for key, _ in _SUMMARY_SECTION_TITLES:
        new_items = list(new_structured.get(key, []))
        old_items = list(old_structured.get(key, []))
        limit = _SUMMARY_SECTION_LIMITS[key]

        if key in _PERSISTENT_KEYS and old_items:
            new_norms = {re.sub(r"\s+", " ", it.lower().strip()) for it in new_items if it}
            preserved_old = [
                it for it in old_items
                if re.sub(r"\s+", " ", str(it).lower().strip()) not in new_norms
            ][:_PERSISTENT_PRESERVE_SLOTS]
            merged[key] = _dedupe_summary_items(new_items + preserved_old, limit)
        else:
            merged[key] = _dedupe_summary_items(new_items + old_items, limit)

    return _render_structured_summary(merged)


# ============================================================
# 后台摘要刷新
# ============================================================

def _claim_summary_job(user_id: int | str, character_id: str) -> bool:
    """尝试占用摘要任务（防止重复执行）。"""
    key = (user_id, character_id)
    with _SUMMARY_JOB_LOCK:
        if key in _SUMMARY_RUNNING_KEYS:
            return False
        _SUMMARY_RUNNING_KEYS.add(key)
        return True


def _release_summary_job(user_id: int | str, character_id: str) -> None:
    """释放摘要任务占用。"""
    key = (user_id, character_id)
    with _SUMMARY_JOB_LOCK:
        _SUMMARY_RUNNING_KEYS.discard(key)


def refresh_memory_summary(
    conn: ConnType,
    user_id: int | str,
    character_id: str,
    character: Any,
) -> None:
    """同步刷新摘要（调用 AI 生成或降级方案）。"""
    unsummarized_rows = get_unsummarized_messages(conn, user_id, character_id)
    if len(unsummarized_rows) < SUMMARY_TRIGGER_COUNT:
        return

    summary_target_rows = unsummarized_rows[:-RECENT_MESSAGE_WINDOW]
    if len(summary_target_rows) < RECENT_MESSAGE_WINDOW:
        return

    from services.prompt_assembler import build_memory_summary_messages
    existing_summary = get_summary_text(conn, user_id, character_id)
    prompt_messages = build_memory_summary_messages(character, existing_summary, summary_target_rows)

    try:
        summary_text = request_chat_completion(
            prompt_messages,
            get_ai_config(os.environ),
            normalize_reply_text,
            max_tokens=SUMMARY_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning(
            "记忆摘要 AI 生成失败，改走降级方案 user_id=%s character_id=%s error=%s",
            user_id, character_id, exc,
        )
        summary_text = build_structured_memory_summary_fallback(existing_summary, summary_target_rows)

    summary_text = merge_summary_text(existing_summary, summary_text)
    last_message_id = summary_target_rows[-1]["id"] if summary_target_rows else None
    save_summary(conn, user_id, character_id, summary_text, last_message_id)
    mark_messages_summarized(conn, [row["id"] for row in summary_target_rows])
    conn.commit()


def run_memory_summary_background(
    user_id: int | str,
    character_id: str,
    character_row_data: dict,
) -> None:
    """后台异步刷新摘要（线程池控制并发）。"""
    if not _claim_summary_job(user_id, character_id):
        logger.info("跳过重复记忆摘要任务 user_id=%s character_id=%s", user_id, character_id)
        return

    should_spawn = False
    precheck_conn = None
    try:
        precheck_conn = get_conn()
        should_spawn = should_refresh_summary(precheck_conn, user_id, character_id)
    finally:
        if precheck_conn is not None:
            precheck_conn.close()

    if not should_spawn:
        _release_summary_job(user_id, character_id)
        return

    def target():
        acquired = _MAX_SUMMARY_THREADS.acquire(blocking=False)
        if not acquired:
            logger.warning("摘要线程已满(%d)，跳过 user_id=%s character_id=%s", 5, user_id, character_id)
            _release_summary_job(user_id, character_id)
            return
        conn = None
        try:
            conn = get_conn()
            if not should_refresh_summary(conn, user_id, character_id):
                return
            refresh_memory_summary(conn, user_id, character_id, character_row_data)
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.exception("后台记忆摘要失败 user_id=%s character_id=%s error=%s", user_id, character_id, e)
        finally:
            if conn is not None:
                conn.close()
            _MAX_SUMMARY_THREADS.release()
            _release_summary_job(user_id, character_id)

    threading.Thread(target=target, daemon=True).start()
