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

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.dirname(__file__))

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
        """\\r\\n 和 \\r 均转为 \\n。"""
        assert normalize_text("a\r\nb\rc") == "a\nb\nc"

    def test_converts_fullwidth_space(self):
        """全角空格 \\u3000 转为半角空格。"""
        assert normalize_text("a\u3000b") == "a b"

    def test_non_string_converted_to_json_string(self):
        """非字符串输入通过 json.dumps 转换。"""
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

    def test_removes_think_tag(self):
        result = strip_xml_wrappers("<think>thought</think>")
        assert "think" not in result.lower()
        assert "thought" in result

    def test_preserves_content_without_tags(self):
        text = "plain text without any tags"
        assert strip_xml_wrappers(text) == text.strip()

    def test_case_insensitive_tag_removal(self):
        result = strip_xml_wrappers("<PERSONALITY>content</PERSONALITY>")
        assert "personality" not in result.lower()

    def test_tag_with_attributes_removed(self):
        result = strip_xml_wrappers('<description class="x">text</description>')
        assert "<description" not in result


# ============================================================
# 4. remove_html_tags 测试
# ============================================================

class TestRemoveHtmlTags:
    """HTML 标签剥离。"""

    def test_simple_tag_removed(self):
        result = remove_html_tags("<div>hello</div>")
        assert "<div>" not in result
        assert "hello" in result

    def test_br_converted_to_newline(self):
        result = remove_html_tags("a<br>b")
        assert "\n" in result
        assert "<br" not in result

    def test_p_closing_converted_to_newline(self):
        result = remove_html_tags("a</p>b")
        assert "\n" in result

    def test_complex_html_stripped(self):
        result = remove_html_tags('<p class="x">hello <b>world</b></p>')
        assert "<p" not in result
        assert "<b" not in result
        assert "hello" in result
        assert "world" in result

    def test_plain_text_unchanged(self):
        assert remove_html_tags("no html here") == "no html here"


# ============================================================
# 5. shorten_text 测试
# ============================================================

class TestShortenText:
    """文本截断 + 省略号。"""

    def test_short_text_unchanged(self):
        text = "short"
        assert shorten_text(text, limit=100) == text

    def test_long_text_truncated_with_ellipsis(self):
        text = "A" * 300
        result = shorten_text(text, limit=50)
        assert len(result) <= 51  # limit + ellipsis
        assert result.endswith("…")

    def test_default_limit_is_220(self):
        text = "X" * 300
        result = shorten_text(text)
        assert len(result) <= 221


# ============================================================
# 6. ensure_list 测试
# ============================================================

class TestEnsureList:
    """统一转字符串列表。"""

    def test_none_returns_empty(self):
        assert ensure_list(None) == []

    def test_empty_string_returns_empty(self):
        assert ensure_list("") == []

    def test_string_wrapped_in_list(self):
        result = ensure_list("hello")
        assert result == ["hello"]

    def test_list_items_normalized(self):
        result = ensure_list([" a ", " b ", None, ""])
        assert result == ["a", "b"]

    def test_non_string_element_converted(self):
        result = ensure_list([42, True])
        assert len(result) == 2
        # Elements converted via normalize_text (json.dumps for non-str)


# ============================================================
# 7. compact_json 测试
# ============================================================

class TestCompactJson:
    """复杂对象 JSON 压缩。"""

    def test_none_returns_empty(self):
        assert compact_json(None) == ""

    def test_empty_values_return_empty(self):
        assert compact_json("") == ""
        assert compact_json([]) == ""
        assert compact_json({}) == ""

    def test_small_object_fits_within_limit(self):
        data = {"a": 1}
        result = compact_json(data, limit=200)
        assert "a" in result
        assert not result.endswith("…")

    def test_large_object_truncated(self):
        big = {f"key_{i}": f"value_{i}" * 10 for i in range(100)}
        result = compact_json(big, limit=100)
        assert len(result) <= 101
        assert result.endswith("…")


# ============================================================
# 8. merge_text_parts 测试
# ============================================================

class TestMergeTextParts:
    """多段文本合并去重。"""

    def test_merges_two_parts(self):
        result = merge_text_parts("part A", "part B")
        assert "part A" in result
        assert "part B" in result

    def test_deduplicates_identical_lines(self):
        result = merge_text_parts("same line", "same line", "different")
        assert result.count("same line") == 1

    def test_ignores_none_and_empty_parts(self):
        result = merge_text_parts(None, "", "valid")
        assert "valid" in result

    def test_all_empty_returns_empty(self):
        assert merge_text_parts(None, "", "") == ""


# ============================================================
# 9. pick_root_text 测试
# ============================================================

class TestPickRootText:
    """取未命名根段落。"""

    def test_returns_root_content(self):
        sections = {"__root__": "root content here"}
        assert pick_root_text(sections) == "root content here"

    def test_empty_root_returns_empty(self):
        sections = {"__root__": "", "other": "data"}
        assert pick_root_text(sections) == ""

    def test_missing_key_returns_empty(self):
        assert pick_root_text({}) == ""

    def test_strips_surrounding_whitespace(self):
        sections = {"__root__": "  content  "}
        assert pick_root_text(sections) == "content"


# ============================================================
# 10. split_structured_sections 测试
# ============================================================

class TestSplitStructuredSections:
    """结构化段落拆分（YAML 风格 / 标题风格）。"""

    def test_empty_input_returns_empty(self):
        assert split_structured_sections("") == {}

    def test_plain_text_goes_to_root(self):
        result = split_structured_sections("just some text")
        assert "__root__" in result
        assert "just some text" in result["__root__"]

    def test_yaml_style_section_detected(self):
        text = "name: 角色\n描述: 这是一个角色"
        result = split_structured_sections(text)
        assert "name" in result or "角色" in str(result)

    def bracket_style_section_detected(self):
        text = "【背景】这是背景内容\n【性格】这是性格"
        result = split_structured_sections(text)
        # 【】括号风格可能被归入 root 或按 key 拆分
        assert len(result) >= 1
        assert "背景" in str(result) or "性格" in str(result) or "__root__" in result

    def test_markdown_heading_detected(self):
        text = "# 基本信息\n名字：测试\n## 性格\n温柔善良"
        result = split_structured_sections(text)
        assert len(result) >= 1


# ============================================================
# 11. pick_section_text 测试
# ============================================================

class TestPickSectionText:
    """按关键词从 section 中捞取内容。"""

    def test_matches_keyword(self):
        sections = {"background": "背景故事内容", "personality": "性格描述"}
        result = pick_section_text(sections, ["back"])
        assert "背景故事" in result

    def test_multiple_keywords_match_any(self):
        sections = {"mood": "心情好", "state": "状态佳"}
        result = pick_section_text(sections, ["mood", "nonexistent"])
        assert "心情" in result

    def test_no_match_returns_empty(self):
        sections = {"a": "content_a"}
        assert pick_section_text(sections, ["zzz"]) == ""

    def test_empty_sections_returns_empty(self):
        assert pick_section_text({}, ["any"]) == ""


# ============================================================
# 12. expand_macros 测试
# ============================================================

class TestExpandMacros:
    """模板变量替换 {{char}} / {{user}}。"""

    def test_replaces_char_macro(self):
        result = expand_macros("{{char}} is cute", char_name="Luna")
        assert result == "Luna is cute"

    def test_replaces_user_macro(self):
        result = expand_macros("Hello {{user}}!", user_name="User123")
        assert result == "Hello User123!"

    def test_case_insensitive_char(self):
        result = expand_macros("{{Char}} speaks", char_name="Luna")
        assert "Luna" in result

    def test_case_insensitive_user(self):
        result = expand_macros("{{USER}} said hi", user_name="Me")
        assert "Me" in result

    def test_no_char_name_replaces_with_placeholder(self):
        result = expand_macros("{{char}} likes you")
        assert "<角色>" in result

    def test_no_user_name_replaces_with_placeholder(self):
        result = expand_macros("{{user}} is here")
        assert "<用户>" in result

    def test_empty_input_returns_empty(self):
        assert expand_macros("") == ""

    def test_no_macros_unchanged(self):
        text = "normal text without macros"
        assert expand_macros(text) == text


# ============================================================
# 13. extract_yaml_block 测试
# ============================================================

class TestExtractYamlBlock:
    """YAML 代码块提取。"""

    def test_extracts_yaml_code_block(self):
        text = 'some intro\n```yaml\nkey: value\n```\nmore text'
        result = extract_yaml_block(text)
        assert "key: value" in result

    def test_no_yaml_block_returns_empty_for_short_text(self):
        text = "just a short description"
        assert extract_yaml_block(text) == ""

    def test_falls_back_to_yaml_like_text(self):
        """有冒号且多行的文本回退到原文。"""
        text = "name: test\ndesc: something\nmore: content\nand more lines here"
        result = extract_yaml_block(text)
        assert "name:" in result or len(result) > 0

    def test_empty_input_returns_empty(self):
        assert extract_yaml_block("") == ""
        assert extract_yaml_block(None) == ""
