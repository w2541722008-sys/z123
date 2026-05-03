"""runtime_bundle 纯函数单元测试。

覆盖：_get_field / get_runtime_layers / _merge_text /
_merge_alternate_greetings / build_runtime_bundle / expand_bundle_macros。
"""
from services.runtime_bundle import (
    _get_field,
    get_runtime_layers,
    _merge_text,
    _merge_alternate_greetings,
    build_runtime_bundle,
    expand_bundle_macros,
)


# ============================================================
# _get_field
# ============================================================
class TestGetField:
    def test_dict_access(self):
        obj = {"name": "Alice"}
        assert _get_field(obj, "name") == "Alice"

    def test_dict_default(self):
        obj = {"name": "Alice"}
        assert _get_field(obj, "age", 0) == 0

    def test_dict_none_returns_default(self):
        obj = {"name": None}
        assert _get_field(obj, "name", "default") == "default"

    def test_object_access(self):
        class Obj:
            name = "Bob"
        assert _get_field(Obj(), "name") == "Bob"

    def test_object_default(self):
        class Obj:
            pass
        assert _get_field(Obj(), "missing", "default") == "default"

    def test_object_none_returns_default(self):
        class Obj:
            name = None
        assert _get_field(Obj(), "name", "default") == "default"


# ============================================================
# get_runtime_layers
# ============================================================
class TestGetRuntimeLayers:
    def test_from_runtime_cache_json(self):
        char = {
            "runtime_cache_json": '{"asset_type": "character", "base_profile": "cached profile"}',
            "system_prompt": "should not use",
        }
        result = get_runtime_layers(char)
        assert result["asset_type"] == "character"
        assert result["base_profile"] == "cached profile"

    def test_fallback_to_fields(self):
        char = {
            "runtime_cache_json": "",
            "asset_type": "hybrid",
            "system_prompt": "sys prompt",
            "description": "desc",
            "opening_message": "hello",
        }
        result = get_runtime_layers(char)
        assert result["asset_type"] == "hybrid"
        assert result["primary_system_prompt"] == "sys prompt"
        assert result["base_profile"] == "desc"
        assert result["opening_message"] == "hello"

    def test_invalid_json_fallback(self):
        char = {
            "runtime_cache_json": "not valid json",
            "asset_type": "character",
            "description": "desc",
        }
        result = get_runtime_layers(char)
        assert result["asset_type"] == "character"

    def test_default_empty_layers(self):
        char = {"runtime_cache_json": "", "asset_type": "character"}
        result = get_runtime_layers(char)
        assert result["personality"] == ""
        assert result["scenario"] == ""
        assert result["world_rules"] == ""
        assert isinstance(result["alternate_greetings"], list)


# ============================================================
# _merge_text
# ============================================================
class TestMergeText:
    def test_basic_merge(self):
        result = _merge_text("hello", "world")
        assert result == "hello\n\nworld"

    def test_dedup(self):
        result = _merge_text("hello", "hello")
        assert result == "hello"

    def test_skip_empty(self):
        result = _merge_text("hello", "", "world")
        assert result == "hello\n\nworld"

    def test_skip_none(self):
        result = _merge_text("hello", None, "world")
        assert result == "hello\n\nworld"

    def test_all_empty(self):
        result = _merge_text("", None, "")
        assert result == ""

    def test_whitespace_stripped(self):
        result = _merge_text("  hello  ")
        assert result == "hello"


# ============================================================
# _merge_alternate_greetings
# ============================================================
class TestMergeAlternateGreetings:
    def test_basic_merge(self):
        result = _merge_alternate_greetings(["a", "b"], ["c"])
        assert result == ["a", "b", "c"]

    def test_dedup(self):
        result = _merge_alternate_greetings(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_max_six(self):
        groups = [[f"g{i}" for i in range(5)], [f"g{i+5}" for i in range(5)]]
        result = _merge_alternate_greetings(*groups)
        assert len(result) == 6

    def test_skip_empty(self):
        result = _merge_alternate_greetings(["a", "", "b"], ["c"])
        assert result == ["a", "b", "c"]

    def test_non_list_ignored(self):
        result = _merge_alternate_greetings("not a list", ["a"])
        assert result == ["a"]

    def test_empty_groups(self):
        result = _merge_alternate_greetings([], [])
        assert result == []


# ============================================================
# build_runtime_bundle
# ============================================================
class TestBuildRuntimeBundle:
    def test_basic_character(self):
        char = {
            "id": "c1",
            "name": "Alice",
            "asset_type": "character",
            "system_prompt": "sys",
            "description": "desc",
            "runtime_cache_json": "",
        }
        bundle = build_runtime_bundle(char)
        assert bundle["asset_type"] == "character"
        assert bundle["primary_system_prompt"] == "sys"
        assert bundle["base_profile"] == "desc"
        assert bundle["related_assets"] == []

    def test_with_world_asset(self):
        char = {
            "id": "c1",
            "name": "Main",
            "asset_type": "character",
            "runtime_cache_json": "",
        }
        world_asset = {
            "id": "w1",
            "name": "World",
            "asset_type": "world",
            "runtime_cache_json": '{"asset_type":"world","base_profile":"world desc","world_rules":"rules"}',
        }
        bundle = build_runtime_bundle(char, related_assets=[world_asset])
        assert len(bundle["related_assets"]) == 1
        assert bundle["related_assets"][0]["asset_type"] == "world"
        assert "world desc" in bundle["world_rules"]

    def test_with_scenario_asset(self):
        char = {
            "id": "c1",
            "name": "Main",
            "asset_type": "character",
            "runtime_cache_json": "",
        }
        scenario_asset = {
            "id": "s1",
            "name": "Quest",
            "asset_type": "scenario",
            "runtime_cache_json": '{"asset_type":"scenario","base_profile":"quest desc","scenario":"scene"}',
        }
        bundle = build_runtime_bundle(char, related_assets=[scenario_asset])
        assert "quest desc" in bundle["scenario"]

    def test_with_character_asset(self):
        char = {
            "id": "c1",
            "name": "Main",
            "asset_type": "character",
            "description": "main desc",
            "runtime_cache_json": "",
        }
        extra_char = {
            "id": "c2",
            "name": "Extra",
            "asset_type": "character",
            "runtime_cache_json": '{"asset_type":"character","base_profile":"extra desc","personality":"p1"}',
        }
        bundle = build_runtime_bundle(char, related_assets=[extra_char])
        assert "extra desc" in bundle["base_profile"]

    def test_depth_prompt_from_extension_hints(self):
        char = {
            "id": "c1",
            "name": "Test",
            "asset_type": "character",
            "runtime_cache_json": '{"asset_type":"character","extension_hints":{"depth_prompt":{"prompt":"inject","depth":4,"role":"user"}}}',
        }
        bundle = build_runtime_bundle(char)
        assert bundle["depth_prompt"]["prompt"] == "inject"
        assert bundle["depth_prompt"]["depth"] == 4


# ============================================================
# expand_bundle_macros
# ============================================================
class TestExpandBundleMacros:
    def test_basic_expansion(self):
        bundle = {
            "primary_system_prompt": "{{char}} says hello to {{user}}",
            "base_profile": "{{char}} is a character",
            "personality": "",
            "scenario": "{{user}} meets {{char}}",
            "world_rules": "",
            "examples": "",
            "post_history_rules": "",
            "world_info_before": "",
            "world_info_after": "",
            "alternate_greetings": ["{{char}} greets {{user}}"],
        }
        result = expand_bundle_macros(bundle, char_name="Alice", user_name="Bob")
        assert result["primary_system_prompt"] == "Alice says hello to Bob"
        assert result["base_profile"] == "Alice is a character"
        assert result["scenario"] == "Bob meets Alice"
        assert result["alternate_greetings"] == ["Alice greets Bob"]

    def test_no_macros(self):
        bundle = {
            "primary_system_prompt": "plain text",
            "base_profile": "no macros",
            "personality": "",
            "scenario": "",
            "world_rules": "",
            "examples": "",
            "post_history_rules": "",
            "world_info_before": "",
            "world_info_after": "",
            "alternate_greetings": [],
        }
        result = expand_bundle_macros(bundle, char_name="Alice", user_name="Bob")
        assert result["primary_system_prompt"] == "plain text"

    def test_empty_values_preserved(self):
        bundle = {
            "primary_system_prompt": "",
            "base_profile": "",
            "personality": "",
            "scenario": "",
            "world_rules": "",
            "examples": "",
            "post_history_rules": "",
            "world_info_before": "",
            "world_info_after": "",
            "alternate_greetings": [],
        }
        result = expand_bundle_macros(bundle, char_name="Alice", user_name="Bob")
        assert result["primary_system_prompt"] == ""
