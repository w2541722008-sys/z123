"""
card_text_utils 模块单元测试

覆盖范围：
  - normalize_text: 文本清洗（None/非字符串/换行符/全角空格）
  - collapse_blank_lines: 多余空行压缩
  - strip_xml_wrappers: XML 容器标签清除
  - remove_html_tags: HTML 标签剥离
  - shorten_text: 文本截断（带省略号）
  - ensure_list: 统一转字符串列表
  - compact_json: 复杂对象 JSON 压缩
  - merge_text_parts: 多段文本合并去重
  - pick_root_text: 取未命名根段落
  - split_structured_sections: 结构化段落拆分
  - pick_section_text: 按关键词捞取段落
  - expand_macros: 模板变量替换（{{char}}/{{user}}）
  - extract_yaml_block: YAML 代码块提取
"""

from card_text_utils import (
    collapse_blank_lines,
    compact_json,
    ensure_list,
    expand_macros,
    extract_yaml_block,
    merge_text_parts,
    normalize_text,
    pick_root_text,
    pick_section_text,
    remove_html_tags,
    shorten_text,
    split_structured_sections,
    strip_xml_wrappers,
)


# ============================================================
# 1. normalize_text 测试
# ============================================================

class TestNormalizeText:
    """文本清洗 — 任意输入 → 干净字符串。"""

    def test_none_returns_empty(self):
        assert normalize_text(None) == ""

    def test_empty_string_unchanged(self):
        assert normalize_text("") == ""

    def test_normal_string_unchanged(self):
        assert normalize_text("hello") == "hello"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_converts_windows_line_endings(self):
        assert normalize_text("a\r\nb\rc") == "a\nb\nc"

    def test_converts_fullwidth_space(self):
        assert normalize_text("a\u3000b") == "a b"

    def test_non_string_converted_to_json_string(self):
        result = normalize_text({"key": "val"})
        assert "key" in result
        assert "val" in result


# ============================================================
# 2. collapse_blank_lines 测试
# ============================================================

class TestCollapseBlankLines:
    """多余空行压缩。"""

    def test_single_blank_line_preserved(self):
        text = "line1\n\nline2"
        assert "\n\n" in collapse_blank_lines(text)

    def test_triple_or_more_collapsed_to_double(self):
        text = "line1\n\n\n\nline2"
        result = collapse_blank_lines(text)
        assert "\n\n\n" not in result
        assert result.count("\n\n") >= 1

    def test_no_blanks_unchanged(self):
        text = "line1\nline2"
        assert collapse_blank_lines(text) == "line1\nline2"


# ============================================================
# 3. strip_xml_wrappers 测试
# ============================================================

class TestStripXmlWrappers:
    """XML 容器标签清除，保留内容。"""

    def test_removes_personality_tag(self):
        result = strip_xml_wrappers("<personality>content</personality>")
        assert "personality" not in result.lower()
        assert "content" in result

    def test_removes_description_tag(self):
        result = strip_xml_wrappers("<description>desc</description>")
        assert "<description" not in result
        assert "desc" in result

    def test_removes_scenario_tag(self):
        result = strip_xml_wrappers("<scenario>scene</scenario>")
        assert "scenario" not in result.lower()
        assert "scene" in result
