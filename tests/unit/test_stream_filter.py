"""stream_filter 单元测试 — 流式响应过滤与状态解析。"""
from __future__ import annotations

import json

import pytest

from services.stream_filter import normalize_reply_text, parse_state_update_tag, sanitize_stream_chunk


# ── normalize_reply_text ─────────────────────────────

class TestNormalizeReplyText:
    def test_empty_string(self):
        assert normalize_reply_text("") == ""

    def test_none_input(self):
        assert normalize_reply_text(None) == ""

    def test_removes_think_tags(self):
        # 源码使用 \u003c 和 \u003e 转义，即 < 和 >
        text = "你好\u003cthink\u003e我在思考\u003c/think\u003e再见"
        result = normalize_reply_text(text)
        assert "\u003cthink" not in result
        assert "你好" in result
        assert "再见" in result

    def test_removes_multiple_think_blocks(self):
        text = "\u003cthink\u003eblock1\u003c/think\u003ehello\u003cthink\u003eblock2\u003c/think\u003eworld"
        result = normalize_reply_text(text)
        assert "block1" not in result
        assert "block2" not in result
        assert "hello" in result
        assert "world" in result

    def test_unclosed_think_tag_preserved(self):
        text = "你好\u003cthink\u003e未关闭"
        result = normalize_reply_text(text)
        # 未关闭的标签不会被移除（没有匹配的 </think）
        assert "你好" in result

    def test_normalizes_line_endings(self):
        text = "hello\r\nworld\rtest"
        result = normalize_reply_text(text)
        assert "\r" not in result

    def test_strips_blank_lines(self):
        text = "hello\n\n\nworld\n\n\ntest"
        result = normalize_reply_text(text)
        assert "\n\n" not in result


# ── parse_state_update_tag ───────────────────────────

class TestParseStateUpdateTag:
    def test_bracket_format(self):
        reply = "你好[STATE_UPDATE]\n{\"affection_delta\": 5}\n[/STATE_UPDATE]再见"
        cleaned, delta = parse_state_update_tag(reply)
        assert "你好" in cleaned
        assert "再见" in cleaned
        assert delta == {"affection_delta": 5}

    def test_xml_format(self):
        reply = "hello<STATE_UPDATE>{\"mood_delta\": 3}</STATE_UPDATE>world"
        cleaned, delta = parse_state_update_tag(reply)
        assert delta == {"mood_delta": 3}

    def test_no_tag(self):
        reply = "普通回复，没有状态标签"
        cleaned, delta = parse_state_update_tag(reply)
        assert cleaned == reply
        assert delta is None

    def test_invalid_json_in_tag(self):
        reply = "[STATE_UPDATE]not json[/STATE_UPDATE]"
        cleaned, delta = parse_state_update_tag(reply)
        assert delta is None

    def test_non_dict_json_in_tag(self):
        reply = "[STATE_UPDATE][1, 2, 3][/STATE_UPDATE]"
        cleaned, delta = parse_state_update_tag(reply)
        assert delta is None

    def test_empty_tag(self):
        reply = "[STATE_UPDATE][/STATE_UPDATE]"
        cleaned, delta = parse_state_update_tag(reply)
        assert delta is None


# ── sanitize_stream_chunk ────────────────────────────

class TestSanitizeStreamChunk:
    def test_empty_chunk(self):
        state = {}
        assert sanitize_stream_chunk("", state) == ""

    def test_plain_text_passthrough(self):
        state = {}
        result = sanitize_stream_chunk("你好世界", state)
        assert result == "你好世界"

    def test_filters_think_tag_single_chunk(self):
        state = {}
        result = sanitize_stream_chunk("\u003cthink\u003e思考内容\u003c/think\u003e你好", state)
        assert "思考" not in result
        assert "你好" in result

    def test_filters_state_update_tag(self):
        state = {}
        result = sanitize_stream_chunk("[STATE_UPDATE]{\"a\":1}[/STATE_UPDATE]你好", state)
        assert "STATE_UPDATE" not in result
        assert "你好" in result

    def test_cross_chunk_think_tag(self):
        """思考标签跨越两个 chunk 的场景。"""
        state = {}
        # 第一个 chunk 包含开始标签和部分内容
        r1 = sanitize_stream_chunk("hello\u003cthink\u003e思考", state)
        assert r1 == "hello"
        # 第二个 chunk 包含结束标签和剩余内容
        r2 = sanitize_stream_chunk("结束\u003c/think\u003eworld", state)
        assert "world" in r2

    def test_cross_chunk_state_update(self):
        """STATE_UPDATE 标签跨 chunk。"""
        state = {}
        r1 = sanitize_stream_chunk("hi[STATE_UPDATE]{", state)
        assert r1 == "hi"
        r2 = sanitize_stream_chunk("\"a\":1}[/STATE_UPDATE]bye", state)
        assert "bye" in r2

    def test_partial_tag_at_chunk_end(self):
        """chunk 以标签前缀结尾，应暂存到 buffer。"""
        state = {}
        r1 = sanitize_stream_chunk("hello\u003cthi", state)
        assert r1 == "hello"
        assert state.get("buffer", "") != ""

    def test_state_persistence_across_chunks(self):
        state = {"in_think": False, "in_state_update": False, "buffer": ""}
        sanitize_stream_chunk("\u003cthink\u003e", state)
        assert state["in_think"] is True
