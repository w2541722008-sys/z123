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

from utils.card_text import (
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


# ============================================================
# 4. remove_html_tags 测试
# ============================================================

class TestRemoveHtmlTags:
    def test_br_to_newline(self):
        assert "hello\nworld" in remove_html_tags("hello<br>world")

    def test_strips_all_tags(self):
        result = remove_html_tags("<b>bold</b> <i>italic</i>")
        assert "<b>" not in result
        assert "bold" in result
        assert "italic" in result

    def test_empty_input(self):
        assert remove_html_tags("") == ""


# ============================================================
# 5. shorten_text 测试
# ============================================================

class TestShortenText:
    def test_short_text_unchanged(self):
        assert shorten_text("hello", limit=100) == "hello"

    def test_long_text_truncated(self):
        long_text = "a" * 300
        result = shorten_text(long_text, limit=100)
        assert len(result) <= 100
        assert result.endswith("…")

    def test_default_limit(self):
        long_text = "b" * 300
        result = shorten_text(long_text)
        assert len(result) <= 220


# ============================================================
# 6. ensure_list 测试
# ============================================================

class TestEnsureList:
    def test_none_returns_empty(self):
        assert ensure_list(None) == []

    def test_list_passthrough(self):
        assert ensure_list(["a", "b"]) == ["a", "b"]

    def test_string_wrapped(self):
        assert ensure_list("hello") == ["hello"]

    def test_empty_string_returns_empty(self):
        assert ensure_list("") == []

    def test_filters_empty_items(self):
        assert ensure_list(["a", "", "b"]) == ["a", "b"]


# ============================================================
# 7. compact_json 测试
# ============================================================

class TestCompactJson:
    def test_none_returns_empty(self):
        assert compact_json(None) == ""

    def test_empty_dict_returns_empty(self):
        assert compact_json({}) == ""

    def test_empty_list_returns_empty(self):
        assert compact_json([]) == ""

    def test_dict_output(self):
        result = compact_json({"key": "value"})
        assert "key" in result
        assert "value" in result

    def test_large_object_truncated(self):
        big = {"k": "v" * 5000}
        result = compact_json(big, limit=100)
        assert result.endswith("…")


# ============================================================
# 8. merge_text_parts 测试
# ============================================================

class TestMergeTextParts:
    def test_merges_and_dedupes(self):
        result = merge_text_parts("hello", "hello", "world")
        assert result.count("hello") == 1
        assert "world" in result

    def test_empty_parts_ignored(self):
        assert merge_text_parts("", None) == ""

    def test_single_part(self):
        assert merge_text_parts("text") == "text"


# ============================================================
# 9. pick_root_text 测试
# ============================================================

class TestPickRootText:
    def test_root_section(self):
        sections = {"__root__": "main content", "other": "other"}
        assert pick_root_text(sections) == "main content"

    def test_missing_root(self):
        sections = {"other": "other"}
        assert pick_root_text(sections) == ""


# ============================================================
# 10. split_structured_sections 测试
# ============================================================

class TestSplitStructuredSections:
    def test_bracket_sections(self):
        text = "【性格】\n温柔\n善良\n\n【外貌】\n美丽"
        result = split_structured_sections(text)
        assert any("温柔" in v for v in result.values())

    def test_yaml_style_sections(self):
        text = "personality:\nkind\n\ndescription:\ntall"
        result = split_structured_sections(text)
        assert "personality" in result
        assert "description" in result

    def test_empty_input(self):
        assert split_structured_sections("") == {}


# ============================================================
# 11. pick_section_text 测试
# ============================================================

class TestPickSectionText:
    def test_matches_keywords(self):
        sections = {"性格": "温柔", "外貌": "美丽", "背景": "神秘"}
        result = pick_section_text(sections, ["性格", "外貌"])
        assert "温柔" in result
        assert "美丽" in result

    def test_no_match_returns_empty(self):
        sections = {"性格": "温柔"}
        result = pick_section_text(sections, ["不存在"])
        assert result == ""


# ============================================================
# 12. expand_macros 测试
# ============================================================

class TestExpandMacros:
    def test_replaces_char(self):
        result = expand_macros("{{char}}是个好人", char_name="小明")
        assert result == "小明是个好人"

    def test_replaces_user(self):
        result = expand_macros("你好{{user}}", user_name="小红")
        assert result == "你好小红"

    def test_case_insensitive(self):
        result = expand_macros("{{CHAR}}和{{User}}", char_name="A", user_name="B")
        assert "A" in result
        assert "B" in result

    def test_unknown_char_macro(self):
        result = expand_macros("{{char}}", char_name="")
        assert "<角色>" in result

    def test_unknown_user_macro(self):
        result = expand_macros("{{user}}", user_name="")
        assert "<用户>" in result

    def test_empty_text(self):
        assert expand_macros("") == ""
        assert expand_macros(None) is None


# ============================================================
# 13. extract_yaml_block 测试
# ============================================================

class TestExtractYamlBlock:
    def test_fenced_yaml(self):
        text = "```yaml\nkey: value\n```"
        result = extract_yaml_block(text)
        assert "key" in result

    def test_plain_yaml_like(self):
        text = "name: test\nage: 20\ndesc: hello\nextra: world"
        result = extract_yaml_block(text)
        assert "name" in result

    def test_empty_input(self):
        assert extract_yaml_block("") == ""

    def test_no_yaml_structure(self):
        assert extract_yaml_block("just plain text") == ""
