"""
记忆服务 - 管理聊天历史摘要和长期记忆

核心功能：
    - 读取最近消息（用于 AI 上下文窗口）
    - 读取/更新记忆摘要
    - 触发摘要生成（当未摘要消息达到阈值）
    - 文本清理和格式化
    - 流式响应内容过滤

摘要触发机制：
    - 当未摘要消息达到 SUMMARY_TRIGGER_COUNT（默认 24 条）时触发
    - 后台异步生成摘要，不阻塞用户对话
    - 降级策略：AI 失败时使用简单提取方案

主要导出：
    - get_recent_messages: 获取最近消息
    - get_unsummarized_messages: 获取未摘要消息
    - get_summary_text: 获取摘要文本
    - get_structured_summary: 获取结构化摘要
    - refresh_memory_summary: 刷新摘要（后台调用）
    - run_memory_summary_background: 后台线程启动摘要生成
    - parse_state_update_tag: 解析 AI 状态更新标签
    - sanitize_stream_chunk: 流式响应内容过滤
"""

from __future__ import annotations

# 标准库导入
import json
import os
import re
import threading
from typing import Any

# 本地模块导入
from config import SUMMARY_MAX_TOKENS, SUMMARY_TRIGGER_COUNT, logger, utc_now_iso
from database import get_conn, get_db
from model_adapter import get_ai_config, request_chat_completion
from prompt_assembler import RECENT_MESSAGE_WINDOW, build_memory_summary_messages
from utils.json_utils import parse_json_list, parse_json_object


_SUMMARY_SECTION_TITLES: list[tuple[str, str]] = [
    ("profile", "用户画像"),
    ("preferences", "用户偏好"),
    ("events", "近期事件"),
    ("relationship", "关系状态"),
    ("pending", "待跟进事项"),
]

# 各分区最多保留的条目数量
_SUMMARY_SECTION_LIMITS: dict[str, int] = {
    "profile": 5,
    "preferences": 5,
    "events": 8,
    "relationship": 5,
    "pending": 5,
}

_SUMMARY_SECTION_ALIASES: dict[str, str] = {
    "用户画像": "profile",
    "用户偏好": "preferences",
    "近期事件": "events",
    "关系状态": "relationship",
    "待跟进事项": "pending",
    "待跟进": "pending",
    "未完成话题": "pending",
}

_SUMMARY_JOB_LOCK = threading.Lock()
_SUMMARY_RUNNING_KEYS: set[tuple[int, str]] = set()


def _empty_structured_summary() -> dict[str, Any]:
    return {
        "profile": [],
        "preferences": [],
        "events": [],
        "relationship": [],
        "pending": [],
        "raw_summary": "",
    }


def _claim_summary_job(user_id: int, character_id: str) -> bool:
    """尝试占用一份摘要任务，避免同一用户-角色对被重复并发处理。"""
    key = (user_id, character_id)
    with _SUMMARY_JOB_LOCK:
        if key in _SUMMARY_RUNNING_KEYS:
            return False
        _SUMMARY_RUNNING_KEYS.add(key)
        return True


def _release_summary_job(user_id: int, character_id: str) -> None:
    """释放摘要任务占用标记。"""
    key = (user_id, character_id)
    with _SUMMARY_JOB_LOCK:
        _SUMMARY_RUNNING_KEYS.discard(key)


# ============================================================
# 消息查询
# ============================================================
def get_recent_messages(
    conn: Any,
    user_id: int,
    character_id: str,
    limit: int = RECENT_MESSAGE_WINDOW,
) -> list[dict[str, str]]:
    """
    获取最近的聊天消息。

    查询策略：
        - 按 id 倒序取 limit 条（最新消息）
        - 返回时反转，保持时间正序（旧 → 新）

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID
        limit: 返回消息数量，默认 RECENT_MESSAGE_WINDOW

    Returns:
        消息列表，每条包含 role 和 content
    """
    rows = conn.execute(
        """
        SELECT role, content
        FROM chat_messages
        WHERE user_id = %s AND character_id = %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (user_id, character_id, limit),
    ).fetchall()
    # 反转列表，保持时间正序（旧消息在前，新消息在后）
    return [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
    ]


def get_unsummarized_messages(
    conn: Any,
    user_id: int,
    character_id: str,
) -> list[Any]:
    """
    获取所有未摘要的消息。

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID

    Returns:
        未摘要消息列表（按时间正序）
    """
    return conn.execute(
        """
        SELECT id, role, content, created_at
        FROM chat_messages
        WHERE user_id = %s AND character_id = %s AND is_summarized = 0
        ORDER BY id ASC
        """,
        (user_id, character_id),
    ).fetchall()


# ============================================================
# 摘要管理
# ============================================================
def get_summary_record(
    conn: Any,
    user_id: int,
    character_id: str,
) -> Any | None:
    """
    获取摘要记录。

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID

    Returns:
        摘要记录行，如果不存在则返回 None
    """
    return conn.execute(
        "SELECT * FROM chat_summaries WHERE user_id = %s AND character_id = %s",
        (user_id, character_id),
    ).fetchone()


def get_summary_text(
    conn: Any,
    user_id: int,
    character_id: str,
) -> str:
    """
    获取摘要文本内容。

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID

    Returns:
        摘要文本，如果不存在则返回空字符串
    """
    row = get_summary_record(conn, user_id, character_id)
    if not row:
        return ""
    return (row["summary"] or "").strip()


def _parse_structured_summary_text(summary_text: str) -> dict[str, list[str]]:
    """把摘要文本拆成结构化分区，兼容旧格式和轻微标题变体。"""
    result = {key: [] for key, _ in _SUMMARY_SECTION_TITLES}
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
    """按文本归一化去重，同时保留原始表述顺序。"""
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
    """把结构化摘要渲染回统一文本格式，便于存库与复用。"""
    blocks: list[str] = []
    for key, title in _SUMMARY_SECTION_TITLES:
        items = _dedupe_summary_items(summary.get(key, []), _SUMMARY_SECTION_LIMITS[key])
        if not items:
            items = ["暂无稳定信息"]
        block = [f"[{title}]"]
        block.extend(f"- {item}" for item in items)
        blocks.append("\n".join(block))
    return "\n\n".join(blocks).strip()


def get_summary_for_prompt(
    conn: Any,
    user_id: int,
    character_id: str,
) -> str:
    """返回给 Prompt 使用的长期记忆文本，优先走结构化整理后的格式。"""
    structured = get_structured_summary(conn, user_id, character_id)
    formatted = format_structured_summary(structured)
    if formatted:
        return formatted
    return get_summary_text(conn, user_id, character_id)


def should_refresh_summary(
    conn: Any,
    user_id: int,
    character_id: str,
) -> bool:
    """
    判断是否需要刷新摘要。

    触发条件：未摘要消息数量 >= SUMMARY_TRIGGER_COUNT（默认 24 条）

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID

    Returns:
        True 表示需要刷新摘要
    """
    rows = get_unsummarized_messages(conn, user_id, character_id)
    return len(rows) >= SUMMARY_TRIGGER_COUNT


def get_structured_summary(
    conn: Any,
    user_id: int,
    character_id: str,
) -> dict[str, Any]:
    """
    解析结构化的摘要内容。

    解析格式：
        [用户画像]
        - 用户特征描述
        [用户偏好]
        - 用户喜好描述
        [近期事件]
        - 最近发生的事情
        [关系状态]
        - 角色关系描述
        [待跟进事项]
        - 后续值得回收的话题/承诺

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID

    Returns:
        结构化摘要字典，包含：
        - profile: 用户画像列表
        - preferences: 用户偏好列表
        - events: 近期事件列表
        - relationship: 关系状态列表
        - pending: 待跟进事项列表
        - raw_summary: 原始摘要文本
    """
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
    """
    将结构化摘要格式化为可读文本。

    用于将解析后的结构化摘要重新格式化为带标题的文本，
    方便在提示词中使用。

    Args:
        summary: 结构化摘要字典（来自 get_structured_summary）

    Returns:
        格式化后的文本，每个段落带【标题】前缀
    """
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


# ============================================================
# 摘要生成
# ============================================================
def normalize_reply_text(text: str) -> str:
    """
    清理 AI 回复文本。

    清理规则：
        1. 统一换行符（\r\n、\r → \n）
        2. 移除 <think>...</think> 思考过程标签
        3. 去除空行，每行去除首尾空格

    Args:
        text: 原始 AI 回复文本

    Returns:
        清理后的文本
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    # 移除 <think> 思考过程
    while "<think>" in text and "</think>" in text:
        start = text.find("<think>")
        end = text.find("</think>", start)
        if end == -1:
            break
        text = text[:start] + text[end + len("</think>"):]

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines).strip()


def build_structured_memory_summary_fallback(
    existing_summary: str,
    unsummarized_messages: list[Any],
) -> str:
    """
    AI 摘要失败时的降级方案：简单提取关键信息。

    当调用 AI 生成摘要失败（网络错误、超时等）时，使用此函数
    简单提取用户消息作为摘要，保证功能不中断。

    提取策略：
        - 用户画像：取前 2 条用户消息
        - 用户偏好：取最后 1 条用户消息
        - 近期事件：取最后 3 条用户消息
        - 关系状态：根据是否有 AI 回复判断

    Args:
        existing_summary: 已有摘要文本
        unsummarized_messages: 未摘要的消息列表

    Returns:
        格式化的摘要文本
    """
    user_lines = [row["content"].strip() for row in unsummarized_messages if row["role"] == "user" and row["content"].strip()]
    assistant_lines = [row["content"].strip() for row in unsummarized_messages if row["role"] == "assistant" and row["content"].strip()]

    def pick(items: list[str], limit: int = 3) -> list[str]:
        """从列表中选取最后 limit 项，格式化为列表项。"""
        return [f"- {item[:60]}" for item in items[-limit:]] or ["- 暂无稳定信息"]

    # 构建结构化摘要
    structured = [
        "[用户画像]",
        *pick(user_lines[:2], limit=2),
        "[用户偏好]",
        *(["- 从近期对话中暂未提炼出稳定偏好"] if not user_lines else [f"- 用户最近反复提到：{user_lines[-1][:60]}"]),
        "[近期事件]",
        *pick(user_lines, limit=3),
        "[待跟进事项]",
        *( ["- 暂无明确待跟进事项"] if not user_lines else [f"- 可在后续对话跟进：{user_lines[-1][:60]}"] ),
        "[关系状态]",
        *(["- 角色持续与用户保持对话，关系在稳定推进"] if assistant_lines else ["- 暂无稳定信息"]),
    ]

    # 合并已有摘要和新摘要
    if existing_summary.strip():
        return existing_summary.strip() + "\n" + "\n".join(structured)
    return "\n".join(structured)


def merge_summary_text(existing_summary: str, new_summary_text: str) -> str:
    """
    合并新旧摘要（优先使用新摘要）。

    合并策略：
        - 如果新摘要非空，使用新摘要
        - 否则保留旧摘要

    Args:
        existing_summary: 已有摘要文本
        new_summary_text: 新生成的摘要文本

    Returns:
        合并后的摘要文本
    """
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
        merged[key] = _dedupe_summary_items(
            list(new_structured.get(key, [])) + list(old_structured.get(key, [])),
            _SUMMARY_SECTION_LIMITS[key],
        )

    return _render_structured_summary(merged)


def save_summary(
    conn: Any,
    user_id: int,
    character_id: str,
    summary_text: str,
    last_message_id: int | None,
) -> None:
    """
    保存或更新摘要记录。

    如果该用户-角色组合已有摘要记录，则更新；
    否则插入新记录。

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID
        summary_text: 摘要文本内容
        last_message_id: 最后摘要的消息 ID
    """
    now = utc_now_iso()
    existing = get_summary_record(conn, user_id, character_id)
    if existing:
        # 更新已有记录：版本号 +1，更新时间戳
        conn.execute(
            """
            UPDATE chat_summaries
            SET summary = %s,
                memory_version = memory_version + 1,
                last_message_id = %s,
                last_summarized_at = %s,
                updated_at = %s
            WHERE user_id = %s AND character_id = %s
            """,
            (summary_text, last_message_id, now, now, user_id, character_id),
        )
    else:
        # 插入新记录：版本号从 1 开始
        conn.execute(
            """
            INSERT INTO chat_summaries(
                user_id, character_id, summary, memory_version,
                last_message_id, last_summarized_at, created_at, updated_at
            ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s)
            """,
            (user_id, character_id, summary_text, last_message_id, now, now, now),
        )


def mark_messages_summarized(conn: Any, message_ids: list[int]) -> None:
    """
    将指定消息标记为已摘要。

    Args:
        conn: 数据库连接
        message_ids: 要标记的消息 ID 列表
    """
    if not message_ids:
        return
    placeholders = ",".join("%s" for _ in message_ids)
    conn.execute(
        f"UPDATE chat_messages SET is_summarized = 1 WHERE id IN ({placeholders})",
        message_ids,
    )


def refresh_memory_summary(
    conn: Any,
    user_id: int,
    character_id: str,
    character: Any,
) -> None:
    """
    刷新记忆摘要。

    当未摘要消息达到阈值时，调用 AI 生成新的摘要。
    这个函数应该在后台线程中调用，避免阻塞主线程。

    摘要策略：
        1. 获取所有未摘要消息
        2. 保留最近 RECENT_MESSAGE_WINDOW 条不摘要（保持上下文完整）
        3. 调用 AI 生成摘要（失败时使用降级方案）
        4. 保存摘要并标记消息为已摘要

    Args:
        conn: 数据库连接
        user_id: 用户 ID
        character_id: 角色 ID
        character: 角色数据字典
    """
    # 步骤 1：获取未摘要消息
    unsummarized_rows = get_unsummarized_messages(conn, user_id, character_id)
    if len(unsummarized_rows) < SUMMARY_TRIGGER_COUNT:
        return

    # 步骤 2：保留最近消息不摘要（RECENT_MESSAGE_WINDOW 条）
    summary_target_rows = unsummarized_rows[:-RECENT_MESSAGE_WINDOW]
    if len(summary_target_rows) < RECENT_MESSAGE_WINDOW:
        return

    # 步骤 3：获取已有摘要，构建提示词
    existing_summary = get_summary_text(conn, user_id, character_id)
    prompt_messages = build_memory_summary_messages(character, existing_summary, summary_target_rows)

    # 步骤 4：调用 AI 生成摘要（带异常降级）
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
            user_id,
            character_id,
            exc,
        )
        # AI 失败时使用降级方案
        summary_text = build_structured_memory_summary_fallback(existing_summary, summary_target_rows)

    # 步骤 5：合并新旧摘要
    summary_text = merge_summary_text(existing_summary, summary_text)

    # 步骤 6：保存摘要并标记消息
    last_message_id = summary_target_rows[-1]["id"] if summary_target_rows else None
    save_summary(conn, user_id, character_id, summary_text, last_message_id)
    mark_messages_summarized(conn, [row["id"] for row in summary_target_rows])
    conn.commit()


def run_memory_summary_background(
    user_id: int,
    character_id: str,
    character_row_data: dict,
) -> None:
    """
    在后台线程中运行记忆摘要生成。

    使用方式：
        >>> threading.Thread(
        ...     target=run_memory_summary_background,
        ...     args=(user_id, character_id, dict(character_row)),
        ...     daemon=True
        ... ).start()

    设计说明：
        - 使用守护线程（daemon=True），主进程退出时自动终止
        - 捕获所有异常，防止后台线程崩溃影响主服务
        - 每个连接独立获取和关闭，避免连接泄漏

    Args:
        user_id: 用户 ID
        character_id: 角色 ID
        character_row_data: 角色数据字典
    """
    if not _claim_summary_job(user_id, character_id):
        logger.info(
            "跳过重复记忆摘要任务 user_id=%s character_id=%s",
            user_id,
            character_id,
        )
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
            logger.exception(
                "后台记忆摘要失败 user_id=%s character_id=%s error=%s",
                user_id,
                character_id,
                e,
            )
        finally:
            if conn is not None:
                conn.close()
            _release_summary_job(user_id, character_id)

    threading.Thread(target=target, daemon=True).start()


# ============================================================
# 状态更新标签解析
# ============================================================
def parse_state_update_tag(reply: str) -> tuple[str, dict[str, Any] | None]:
    """
    从 AI 回复里提取状态增量标签，兼容方括号与 XML 两种历史格式。

    当前规范格式：
        [STATE_UPDATE]
        {"affection_delta": 5, "mood_delta": 3}
        [/STATE_UPDATE]
    """
    patterns = [
        re.compile(r'\[STATE_UPDATE\](.*?)\[/STATE_UPDATE\]', re.DOTALL | re.IGNORECASE),
        re.compile(r'<STATE_UPDATE>(.*?)</STATE_UPDATE>', re.DOTALL | re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(reply)
        if not match:
            continue

        raw_json = match.group(1).strip()
        cleaned = pattern.sub("", reply).strip()

        try:
            delta = json.loads(raw_json)
        except json.JSONDecodeError:
            return cleaned, None

        if not isinstance(delta, dict):
            return cleaned, None

        return cleaned, delta

    return reply, None


# ============================================================
# 流式响应工具
# ============================================================
def sanitize_stream_chunk(chunk: str, state: dict[str, Any]) -> str:
    """
    按增量片段过滤思考内容和 [STATE_UPDATE] 标签，处理跨 chunk 截断。

    AI 模型可能在回复中包含：
    1. 思考标签（如 DeepSeek 的思考过程）
    2. [STATE_UPDATE]...[/STATE_UPDATE] 状态更新标签
    流式响应时，这些标签可能跨多个 chunk，需要状态机正确处理。

    state 用于保存跨 chunk 的状态：
        - buffer: 未处理的残留文本（可能是标签的一部分）
        - in_think: 是否处于思考标签内
        - in_state_update: 是否处于 [STATE_UPDATE] 标签内
    """
    if not chunk:
        return ""

    # 合并残留 buffer 和新 chunk
    buf = state.get("buffer", "") + chunk
    state["buffer"] = ""
    in_think = state.get("in_think", False)
    in_state_update = state.get("in_state_update", False)
    output = ""

    # 标签定义
    think_open = "\u003cthink\u003e"
    think_close = "\u003c/think\u003e"
    state_open = "[STATE_UPDATE]"
    state_close = "[/STATE_UPDATE]"

    # 状态机处理 buffer
    while buf:
        if in_think:
            # 在思考标签内，寻找结束标签
            end_idx = buf.find(think_close)
            if end_idx == -1:
                state["buffer"] = buf
                buf = ""
            else:
                in_think = False
                buf = buf[end_idx + len(think_close):]

        elif in_state_update:
            # 在 [STATE_UPDATE] 标签内，寻找结束标签
            end_idx = buf.find(state_close)
            if end_idx == -1:
                state["buffer"] = buf
                buf = ""
            else:
                in_state_update = False
                buf = buf[end_idx + len(state_close):]

        else:
            # 不在任何标签内，寻找最近的开始标签
            think_start = buf.find(think_open)
            state_start = buf.find(state_open)

            # 找到最先出现的标签
            next_tag = None
            next_pos = len(buf)

            if think_start != -1 and think_start < next_pos:
                next_tag = "think"
                next_pos = think_start
            if state_start != -1 and state_start < next_pos:
                next_tag = "state_update"
                next_pos = state_start

            if next_tag is None:
                # 没有开始标签，检查是否以标签的一部分结尾
                safe_end = len(buf)
                for tag in (think_open, state_open):
                    for i in range(1, len(tag)):
                        if buf.endswith(tag[:i]):
                            safe_end = min(safe_end, len(buf) - i)
                            break
                output += buf[:safe_end]
                state["buffer"] = buf[safe_end:]
                buf = ""
            else:
                # 找到开始标签，输出之前的内容
                output += buf[:next_pos]
                if next_tag == "think":
                    in_think = True
                    buf = buf[next_pos + len(think_open):]
                else:
                    in_state_update = True
                    buf = buf[next_pos + len(state_open):]

    state["in_think"] = in_think
    state["in_state_update"] = in_state_update
    return output


# ============================================================
# 角色记忆与后置规则查询（从 prompt_assembler 迁移）
# 说明：
#   - 原来在 prompt_assembler 中包含 DB 查询，违反"SQL 只在 services 层"原则
#   - 移至此处后，budget 相关参数由调用方传入，不依赖 prompt_assembler 内部常量
# ============================================================

def fetch_character_memories(
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
        character_id: 角色 ID
        context_text: 用于匹配的上下文文本
        max_triggered: 最多触发条目数
        max_per_entry: 单条最大字符数
        wi_max: WI 总字符上限

    返回：
        (before_list, after_list) — 分别对应 position='before' 和 'after' 的匹配内容列表
    """
    with get_db() as conn:
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
    character_id: str,
    *,
    storyline_id: int | None = None,
    story_phase: str | None = None,
    max_chars: int = 16000,
) -> list[str]:
    """
    从数据库查询角色的后置规则。

    参数：
        character_id: 角色 ID
        storyline_id: 当前剧情线 ID（可选）
        story_phase: 当前关系阶段（可选）
        max_chars: 返回规则的总字符上限

    返回：
        匹配的后置规则内容列表（已按优先级排序）
    """
    with get_db() as conn:
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
