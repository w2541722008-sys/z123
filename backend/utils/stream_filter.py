"""
流式响应过滤和文本清理工具。

从 memory_service.py 拆分出来，职责：
    - AI 回复文本清理（去除思考标签、统一换行）
    - 流式 chunk 过滤（状态机处理跨 chunk 的标签截断）
    - 状态增量标签解析（提取 [STATE_UPDATE] 内容）
"""
from __future__ import annotations

import json
import re
from typing import Any


def normalize_reply_text(text: str) -> str:
    """
    清理 AI 回复文本。

    清理规则：
        1. 统一换行符（\\r\\n、\\r → \\n）
        2. 移除 <think-/-think> 思考过程标签
        3. 去除空行，每行去除首尾空格

    Args:
        text: 原始 AI 回复文本

    Returns:
        清理后的文本
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    # 移除 <think-/-think> 思考过程
    while "\u003cthink\u003e" in text and "\u003c/think\u003e" in text:
        start = text.find("\u003cthink\u003e")
        end = text.find("\u003c/think\u003e", start)
        if end == -1:
            break
        text = text[:start] + text[end + len("\u003c/think\u003e"):]

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines).strip()


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
