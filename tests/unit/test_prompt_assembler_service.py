"""prompt_assembler 服务层纯函数单元测试。

覆盖已有 test_prompt_assembler.py 未充分覆盖的函数：
_clip / _build_single_system_prompt / _related_assets_text /
_alternate_samples_text / _split_last_user_message /
_append_runtime_text_layers / _append_world_info_after /
_mode_sections / _append_post_history_then_user / _select_mode_builder。
"""
from services.prompt_assembler import (
    _clip,
    _build_single_system_prompt,
    _related_assets_text,
    _alternate_samples_text,
    _split_last_user_message,
    _append_runtime_text_layers,
    _append_world_info_after,
    _mode_sections,
    _append_post_history_then_user,
    _select_mode_builder,
    _build_character_mode_messages,
    _build_scenario_mode_messages,
    _build_hybrid_mode_messages,
)


# ============================================================
# _clip
# ============================================================
class TestClip:
    def test_short_text_unchanged(self):
        assert _clip("hello", 100) == "hello"

    def test_long_text_truncated(self):
        text = "a" * 200
        result = _clip(text, 100)
        assert len(result) < 200
        assert "截断" in result

    def test_whitespace_stripped(self):
        assert _clip("  hello  ", 100) == "hello"

    def test_exact_length(self):
        text = "a" * 100
        result = _clip(text, 100)
        assert "截断" not in result

    def test_custom_label(self):
        text = "a" * 200
        result = _clip(text, 100, label="test")
        assert "截断" in result


# ============================================================
# _build_single_system_prompt
# ============================================================
class TestBuildSingleSystemPrompt:
    def test_primary_only(self):
        result = _build_single_system_prompt("main prompt", [])
        assert result == "main prompt"

    def test_with_layers(self):
        layers = [("Title A", "content A"), ("Title B", "content B")]
        result = _build_single_system_prompt("main", layers)
        assert "main" in result
        assert "Title A" in result
        assert "content A" in result
        assert "Title B" in result

    def test_empty_primary_with_layers(self):
        layers = [("Title A", "content A")]
        result = _build_single_system_prompt("", layers)
        assert "Title A" in result

    def test_empty_content_layer_skipped(self):
        layers = [("Title A", "content A"), ("Title B", "")]
        result = _build_single_system_prompt("main", layers)
        assert "Title A" in result
        assert "Title B" not in result

    def test_layer_without_title(self):
        layers = [("", "just content")]
        result = _build_single_system_prompt("main", layers)
        assert "just content" in result

    def test_truncation(self):
        primary = "p" * 50000
        result = _build_single_system_prompt(primary, [], total_max=100)
        assert "截断" in result

    def test_with_budget(self):
        from services.token_budget import TokenBudget
        budget = TokenBudget(context_tokens=4096, output_reserve=512)
        result = _build_single_system_prompt("main prompt", [], budget=budget)
        assert "main prompt" in result


# ============================================================
# _related_assets_text
# ============================================================
class TestRelatedAssetsText:
    def test_no_assets(self):
        assert _related_assets_text({}) == ""
        assert _related_assets_text({"related_assets": []}) == ""

    def test_with_assets(self):
        bundle = {
            "related_assets": [
                {"asset_type": "scenario", "name": "Quest"},
                {"asset_type": "character", "name": "Alice"},
            ]
        }
        result = _related_assets_text(bundle)
        assert "Quest" in result
        assert "Alice" in result
        assert "关联资产" in result

    def test_asset_without_name_skipped(self):
        bundle = {
            "related_assets": [
                {"asset_type": "scenario"},
                {"asset_type": "character", "name": "Alice"},
            ]
        }
        result = _related_assets_text(bundle)
        assert "Alice" in result


# ============================================================
# _alternate_samples_text
# ============================================================
class TestAlternateSamplesText:
    def test_empty(self):
        assert _alternate_samples_text([]) == ""
        assert _alternate_samples_text(None) == ""

    def test_non_list(self):
        assert _alternate_samples_text("not a list") == ""

    def test_with_samples(self):
        result = _alternate_samples_text(["hello", "world"])
        assert "hello" in result
        assert "world" in result
        assert "开场" in result

    def test_max_two_samples(self):
        result = _alternate_samples_text(["a", "b", "c"])
        assert "c" not in result


# ============================================================
# _split_last_user_message
# ============================================================
class TestSplitLastUserMessage:
    def test_last_is_user(self):
        msgs = [
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "hello"},
        ]
        history, last = _split_last_user_message(msgs)
        assert len(history) == 1
        assert last == {"role": "user", "content": "hello"}

    def test_last_is_not_user(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        history, last = _split_last_user_message(msgs)
        assert len(history) == 2
        assert last is None

    def test_empty(self):
        history, last = _split_last_user_message([])
        assert history == []
        assert last is None

    def test_does_not_mutate(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
        ]
        _split_last_user_message(msgs)
        assert len(msgs) == 3


# ============================================================
# _append_runtime_text_layers
# ============================================================
class TestAppendRuntimeTextLayers:
    def test_basic(self):
        pairs = [("A", "a")]
        sections = [("B", "b"), ("C", "c")]
        result = _append_runtime_text_layers(pairs, sections)
        assert len(result) == 3

    def test_title_only_no_content(self):
        pairs = []
        sections = [("Title Only", "")]
        result = _append_runtime_text_layers(pairs, sections)
        # title without content: append with empty content
        assert len(result) == 1

    def test_empty_content_skipped(self):
        pairs = []
        sections = [("", "")]
        result = _append_runtime_text_layers(pairs, sections)
        assert len(result) == 0


# ============================================================
# _append_world_info_after
# ============================================================
class TestAppendWorldInfoAfter:
    def test_with_content(self):
        pairs = [("A", "a")]
        result = _append_world_info_after(pairs, "wi after text")
        assert len(result) == 2
        assert result[1][0] == "【世界信息-后置】"

    def test_empty_content(self):
        pairs = [("A", "a")]
        result = _append_world_info_after(pairs, "")
        assert len(result) == 1


# ============================================================
# _mode_sections
# ============================================================
class TestModeSections:
    def test_character_mode(self):
        bundle = {
            "base_profile": "desc",
            "examples": "ex",
            "world_rules": "rules",
            "scenario": "scene",
            "personality": "pers",
            "alternate_greetings": [],
            "related_assets": [],
        }
        sections = _mode_sections(bundle, {}, "character")
        titles = [s[0] for s in sections if s[0]]
        assert "【角色底稿】" in titles
        assert "【性格与表达风格】" in titles

    def test_scenario_mode(self):
        bundle = {
            "base_profile": "desc",
            "examples": "",
            "world_rules": "",
            "scenario": "scene",
            "personality": "",
            "alternate_greetings": [],
            "related_assets": [],
        }
        sections = _mode_sections(bundle, {}, "scenario")
        titles = [s[0] for s in sections if s[0]]
        assert "【剧情入口/背景】" in titles

    def test_hybrid_mode(self):
        bundle = {
            "base_profile": "desc",
            "examples": "",
            "world_rules": "",
            "scenario": "",
            "personality": "pers",
            "alternate_greetings": [],
            "related_assets": [],
        }
        sections = _mode_sections(bundle, {}, "hybrid")
        titles = [s[0] for s in sections if s[0]]
        assert "【角色底稿】" in titles
        assert "【性格与表达风格】" in titles


# ============================================================
# _append_post_history_then_user
# ============================================================
class TestAppendPostHistoryThenUser:
    def test_with_user_msg(self):
        messages = []
        _append_post_history_then_user(
            messages,
            last_user_message={"role": "user", "content": "hello"},
        )
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "hello" in messages[0]["content"]

    def test_no_user_msg(self):
        messages = []
        _append_post_history_then_user(
            messages,
            last_user_message=None,
        )
        assert len(messages) == 0

    def test_user_msg_merges_with_previous_user(self):
        messages = [{"role": "user", "content": "previous"}]
        _append_post_history_then_user(
            messages,
            last_user_message={"role": "user", "content": "hello"},
        )
        assert len(messages) == 1
        assert "previous" in messages[0]["content"]
        assert "hello" in messages[0]["content"]

    def test_user_msg_after_assistant(self):
        messages = [{"role": "assistant", "content": "hi"}]
        _append_post_history_then_user(
            messages,
            last_user_message={"role": "user", "content": "hello"},
        )
        assert len(messages) == 2
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "hello"


# ============================================================
# _select_mode_builder
# ============================================================
class TestSelectModeBuilder:
    def test_scenario_card_type(self):
        builder = _select_mode_builder("scenario", "character")
        assert builder is _build_scenario_mode_messages

    def test_character_asset_type(self):
        builder = _select_mode_builder("intimate", "character")
        assert builder is _build_character_mode_messages

    def test_scenario_asset_type(self):
        builder = _select_mode_builder("intimate", "scenario")
        assert builder is _build_scenario_mode_messages

    def test_hybrid_default(self):
        builder = _select_mode_builder("intimate", "hybrid")
        assert builder is _build_hybrid_mode_messages
