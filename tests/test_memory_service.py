"""
memory_service 模块单元测试

覆盖范围：
  - sanitize_stream_chunk: SSE 流式响应 </think> 标签过滤（核心状态机逻辑）
  - parse_state_update_tag: AI 状态更新标签解析
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.dirname(__file__))

from services.memory_service import (
    parse_state_update_tag,
    sanitize_stream_chunk,
)


# ============================================================
# 1. sanitize_stream_chunk 测试（SSE 流式 </think> 标签过滤）
# ============================================================

class TestSanitizeStreamChunk:
    """
    sanitize_stream_chunk 状态机测试。

    状态机规则：
      - 默认状态：正常输出文本
      - 遇到  → 退出 think 模式
      - 跨 chunk 的标签碎片需要 buffer 处理

    输入：chunk 文本 + state 字典（被修改）
    输出：过滤后的可见文本
    """

    def _fresh_state(self):
        return {"buffer": "", "in_think": False}

    # ── 基本功能 ─────────────────────────────────────────

    def test_plain_text_passthrough(self):
        """纯文本应原样通过。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("你好世界", state)
        assert result == "你好世界"
        assert state["buffer"] == ""

    def test_empty_chunk_returns_empty(self):
        """空 chunk 返回空字符串。"""
        state = self._fresh_state()
        assert sanitize_stream_chunk("", state) == ""

    def test_none_chunk_returns_empty(self):
        """None chunk 应安全处理。"""
        state = self._fresh_state()
        assert sanitize_stream_chunk(None, state) == ""

    # ── 完整 <think> 块过滤 ─────────────────────────────────────

    def test_full_think_block_in_single_chunk(self):
        """单个 chunk 内的完整 <think>...</think> 块应被完全移除。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("你好<think>思考过程</think>世界", state)
        assert result == "你好世界"
        assert state["in_think"] is False

    def test_only_think_block(self):
        """只有 <think> 块的 chunk 应返回空。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("<think>内部思考</think>", state)
        assert result == ""
        assert state["in_think"] is False

    # ── 跨 chunk <think> 处理 ────────────────────────────────────

    def test_think_opens_in_one_chunk(self):
        """<think> 在一个 chunk 中打开，没有关闭。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("你好<think>开始思考", state)
        assert result == "你好"
        assert state["in_think"] is True
        # 开始标签后的内容保留在 buffer 中（下次 chunk 可能包含 </think>）

    def test_think_continues_to_next_chunk(self):
        """think 状态持续到下一个 chunk。"""
        state = {"buffer": "", "in_think": True}
        result = sanitize_stream_chunk("继续思考中...", state)
        assert result == ""
        assert state["in_think"] is True

    def test_think_closes_in_later_chunk(self):
        """</think> 在后续 chunk 中出现。"""
        state = {"buffer": "", "in_think": True}
        result = sanitize_stream_chunk("结束思考</think>后面内容", state)
        assert result == "后面内容"
        assert state["in_think"] is False

    def test_multi_chunk_think_scenario(self):
        """完整的多 chunk 场景模拟。"""
        state = self._fresh_state()

        r1 = sanitize_stream_chunk("前缀<think>", state)
        assert r1 == "前缀"
        assert state["in_think"] is True

        r2 = sanitize_stream_chunk("思考第一部分", state)
        assert r2 == ""

        r3 = sanitize_stream_chunk("思考第二部分", state)
        assert r3 == ""

        r4 = sanitize_stream_chunk("</think>后缀文本", state)
        assert r4 == "后缀文本"
        assert state["in_think"] is False

    # ── 边界情况：跨 chunk 的标签碎片 ───────────────────────────

    def test_partial_open_tag_at_chunk_end(self):
        """chunk 以 "<" 或 "<t" 结尾时可能是不完整的标签。"""
        state = self._fresh_state()

        result = sanitize_stream_chunk("text<t", state)
        assert result == "text"
        assert state["buffer"] == "<t"  # 保留到下次处理

        result2 = sanitize_stream_chunk("hink>内容", state)
        assert result2 == ""
        assert state["in_think"] is True

    def test_partial_close_tag_at_chunk_end(self):
        """chunk 以 "</" 或 "</t" 结尾时可能是不完整的关闭标签。"""
        state = {"buffer": "", "in_think": True}
        result = sanitize_stream_chunk("</t", state)
        assert result == ""
        assert state["in_think"] is True  # 仍在 think 中
        assert "</t" in state.get("buffer", "")

    # ── 连续多个 <think> 块 ─────────────────────────────────────

    def test_consecutive_think_blocks(self):
        """连续两个 <think> 块都应被正确过滤。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("A<think>x</think>B<think>y</think>C", state)
        assert result == "ABC"
        assert state["in_think"] is False

    # ── 嵌套/异常格式 ──────────────────────────────────────

    def test_unclosed_think_tag(self):
        """未关闭的 <think> 标签不应崩溃。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("text<think>永远不关闭", state)
        assert result == "text"
        assert state["in_think"] is True

    def test_stray_close_tag_without_open(self):
        """没有对应开启标签的 </think> 不应影响输出（原样保留）。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("前</think>后", state)
        assert "前" in result
        assert "后" in result

    def test_empty_think_content(self):
        """空的 <think></think> 块。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("A<think></think>B", state)
        assert result == "AB"

    # ── 特殊字符和 Unicode ──────────────────────────────────

    def test_unicode_content_preserved(self):
        """Unicode 内容在非 think 区域应保留。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("你好🌙世界🎵", state)
        assert "你好" in result
        assert "世界" in result

    def test_newlines_in_output(self):
        """换行符应保留在输出中。"""
        state = self._fresh_state()
        result = sanitize_stream_chunk("line1\nline2\nline3", state)
        assert "\n" in result


# ============================================================
# 2. parse_state_update_tag 测试
# ============================================================

class TestParseStateUpdateTag:
    """
    从 AI 回复中提取 [STATE_UPDATE]...[/STATE_UPDATE] 标签。

    格式：
      [STATE_UPDATE]
      {"event": "deep_conversation", "mood": "warm"}
      [/STATE_UPDATE]

    返回：(cleaned_text, delta_dict | None)
    """

    def test_extracts_valid_state_tag(self):
        """标准格式的状态标签应被正确提取。"""
        text = '你好呀！[STATE_UPDATE]{"event": "deep_conversation", "mood": "warm"}[/STATE_UPDATE]'
        cleaned, delta = parse_state_update_tag(text)

        assert cleaned == "你好呀！"
        assert delta is not None
        assert delta["event"] == "deep_conversation"
        assert delta["mood"] == "warm"

    def test_returns_none_when_no_tag(self):
        """没有状态标签时返回 (原文, None)。"""
        text = "普通回复，没有任何标签"
        cleaned, delta = parse_state_update_tag(text)
        assert cleaned == text
        assert delta is None

    def test_removes_tag_from_cleaned_text(self):
        """清理后的文本不应包含标签内容。"""
        text = '前面[STATE_UPDATE]{"a":1}[/STATE_UPDATE]后面'
        cleaned, _ = parse_state_update_tag(text)
        assert "[STATE_UPDATE]" not in cleaned
        assert "[/STATE_UPDATE]" not in cleaned
        assert "前面" in cleaned
        assert "后面" in cleaned

    def test_handles_multiline_tag_content(self):
        """多行 JSON 内容也能正确解析。"""
        text = '回复\n[STATE_UPDATE]\n{"event": "test",\n"mood": "happy"}\n[/STATE_UPDATE]\n结尾'
        cleaned, delta = parse_state_update_tag(text)
        assert delta is not None
        assert delta["event"] == "test"

    def test_handles_invalid_json_gracefully(self):
        """标签内 JSON 格式错误时返回 None。"""
        text = "回复[STATE_UPDATE]这不是JSON[/STATE_UPDATE]"
        cleaned, delta = parse_state_update_tag(text)
        assert delta is None
        assert "[STATE_UPDATE]" not in cleaned

    def test_handles_non_dict_json(self):
        """JSON 不是 dict 类型时返回 None。"""
        text = "回复[STATE_UPDATE][1,2,3][/STATE_UPDATE]"
        cleaned, delta = parse_state_update_tag(text)
        assert delta is None

    def test_handles_empty_tag_body(self):
        """空标签体。"""
        text = "回复[STATE_UPDATE][/STATE_UPDATE]"
        cleaned, delta = parse_state_update_tag(text)
        assert delta is None

    def test_handles_multiple_tags_takes_first(self):
        """多个标签时取第一个。"""
        text = 'A[STATE_UPDATE]{"e":"first"}[/STATE_UPDATE]B[STATE_UPDATE]{"e":"second"}[/STATE_UPDATE]C'
        cleaned, delta = parse_state_update_tag(text)
        assert delta["e"] == "first"

    def test_case_insensitive_tag_match(self):
        """标签名大小写不敏感。"""
        text = 'text[state_update]{"e":"test"}[/state_update]'
        cleaned, delta = parse_state_update_tag(text)
        assert delta is not None
        assert delta["e"] == "test"

    def test_preserves_whitespace_around_tag(self):
        """标签周围的空白应保留在清理文本中。"""
        text = '前   [STATE_UPDATE]{"e":"x"}[/STATE_UPDATE]   后'
        cleaned, _ = parse_state_update_tag(text)
        assert "前" in cleaned
        assert "后" in cleaned

    def test_complex_delta_fields(self):
        """复杂的状态增量字段。"""
        text = '回复[STATE_UPDATE]{"event":"confession","mood":"melting","story_phase":"lover","affection_delta":10}[/STATE_UPDATE]'
        cleaned, delta = parse_state_update_tag(text)
        assert delta["event"] == "confession"
        assert delta["story_phase"] == "lover"
        assert delta["affection_delta"] == 10
