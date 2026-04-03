"""
utils/json_utils 模块单元测试

覆盖范围：
  - parse_json_list: 安全解析 JSON 数组（兼容 None/list/str）
  - parse_json_object: 安全解析 JSON 对象（兼容 None/dict/str）
  - to_json_string: 任意数据 → JSON 字符串
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.dirname(__file__))

from utils.json_utils import (
    parse_json_list,
    parse_json_object,
    to_json_string,
)


# ============================================================
# 1. parse_json_list 测试
# ============================================================

class TestParseJsonList:
    """安全 JSON 数组解析 — 兼容 psycopg2 自动解析结果。"""

    def test_none_returns_empty_list(self):
        assert parse_json_list(None) == []

    def test_empty_string_returns_empty_list(self):
        assert parse_json_list("") == []

    def test_whitespace_string_returns_empty_list(self):
        assert parse_json_list("   ") == []

    def test_valid_list_passthrough(self):
        """psycopg2 已解析的 list 直接返回。"""
        result = parse_json_list([1, 2, 3])
        assert result == [1, 2, 3]

    def test_dict_input_returns_fallback(self):
        """dict 输入不是 list，返回 fallback。"""
        assert parse_json_list({"a": 1}) == []
        assert parse_json_list({"a": 1}, fallback=["x"]) == ["x"]

    def test_valid_json_string_parsed(self):
        """合法 JSON 字符串被正确解析。"""
        assert parse_json_list('[1,2,3]') == [1, 2, 3]
        assert parse_json_list('["a","b"]') == ["a", "b"]

    def test_invalid_json_returns_fallback(self):
        """非法 JSON 返回 fallback。"""
        assert parse_json_list("not json") == []
        assert parse_json_list("invalid", fallback=["default"]) == ["default"]

    def test_non_dict_json_string_returns_fallback(self):
        """JSON 是对象而非数组时返回 fallback。"""
        assert parse_json_list('{"a":1}') == []
        assert parse_json_list('"just a string"') == []

    def custom_fallback_used(self):
        """自定义 fallback 值被使用（值相等即可，不要求同一引用）。"""
        fallback = ["custom_default"]
        result = parse_json_list(None, fallback=fallback)
        assert result == fallback  # 值相等
        assert result == ["custom_default"]
        assert parse_json_list("bad", fallback=fallback) == fallback

    def test_integer_input_returns_fallback(self):
        """非字符串非列表的输入返回 fallback。"""
        assert parse_json_list(42) == []
        assert parse_json_list(True, fallback=["x"]) == ["x"]


# ============================================================
# 2. parse_json_object 测试
# ============================================================

class TestParseJsonObject:
    """安全 JSON 对象解析 — 兼容 psycopg2 自动解析结果。"""

    def test_none_returns_empty_dict(self):
        assert parse_json_object(None) == {}

    def test_empty_string_returns_empty_dict(self):
        assert parse_json_object("") == {}

    def test_valid_dict_passthrough(self):
        """psycopg2 已解析的 dict 直接返回。"""
        result = parse_json_object({"a": 1, "b": "x"})
        assert result == {"a": 1, "b": "x"}

    def test_list_input_returns_fallback(self):
        """list 输入不是 dict，返回 fallback。"""
        assert parse_json_object([1, 2]) == {}
        assert parse_json_object([1], fallback={"x": 1}) == {"x": 1}

    def test_valid_json_string_parsed(self):
        """合法 JSON 字符串被正确解析。"""
        assert parse_json_object('{"a":1,"b":"x"}') == {"a": 1, "b": "x"}

    def test_invalid_json_returns_fallback(self):
        """非法 JSON 返回 fallback。"""
        assert parse_json_object("not json") == {}
        assert parse_json_object("bad", fallback={"d": True}) == {"d": True}

    def test_non_object_json_returns_fallback(self):
        """JSON 是数组或标量时返回 fallback。"""
        assert parse_json_object('[1,2]') == {}
        assert parse_json_object('"string"') == {}
        assert parse_json_object('42', fallback={"num": True}) == {"num": True}

    def test_whitespace_input_returns_fallback(self):
        assert parse_json_object("   ") == {}

    def custom_fallback_used(self):
        """自定义 fallback 值被使用（值相等即可，不要求同一引用）。"""
        fallback = {"custom": True}
        result = parse_json_object(None, fallback=fallback)
        assert result == fallback  # 值相等
        assert result["custom"] is True


# ============================================================
# 3. to_json_string 测试
# ============================================================

class TestToJsonString:
    """任意数据 → JSON 字符串转换。"""

    def test_dict_to_json(self):
        result = to_json_string({"a": 1})
        assert '"a"' in result
        assert "1" in result

    def test_list_to_json(self):
        result = to_json_string([1, 2, 3])
        assert result.startswith("[")
        assert result.endswith("]")

    def test_string_to_json(self):
        result = to_json_string("hello")
        assert '"hello"' in result

    def test_none_to_json(self):
        result = to_json_string(None)
        assert "null" in result

    def test_unicode_preserved(self):
        """中文等 Unicode 字符应保留（ensure_ascii=False）。"""
        result = to_json_string({"name": "你好"})
        assert "你好" in result

    def test_unserializable_returns_default(self):
        """不可序列化的对象返回默认值。"""
        class Unserializable:
            pass
        result = to_json_string(Unserializable())
        assert result == "{}"

    def test_custom_error_default(self):
        """自定义错误默认值。"""
        result = to_json_string(object(), default_on_error='{"error": true}')
        assert result == '{"error": true}'
