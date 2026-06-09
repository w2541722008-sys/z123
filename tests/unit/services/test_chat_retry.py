"""chat_retry 纯函数单元测试。

覆盖：消息投影、历史截取、上下文构建等纯逻辑函数。
"""
from services.chat_retry import (
    message_projection,
    _message_with_id_projection,
    _fallback_recent_messages,
    _find_target_message_index,
    _messages_before_target,
    _trim_recent_messages_tail,
    _project_message_rows,
    _resolve_recent_messages_before_target,
    _build_continue_prompt_messages,
)


# ============================================================
# message_projection
# ============================================================
class TestMessageProjection:
    def test_basic(self):
        result = message_projection("user", "hello")
        assert result == {"role": "user", "content": "hello"}

    def test_assistant(self):
        result = message_projection("assistant", "hi there")
        assert result == {"role": "assistant", "content": "hi there"}

    def test_empty_content(self):
        result = message_projection("user", "")
        assert result == {"role": "user", "content": ""}

    def test_none_values(self):
        result = message_projection(None, None)
        assert result == {"role": None, "content": None}


# ============================================================
# _message_with_id_projection
# ============================================================
class TestMessageWithIdProjection:
    def test_basic(self):
        result = _message_with_id_projection(42, "user", "hello")
        assert result == {"id": "42", "role": "user", "content": "hello"}

    def test_uuid(self):
        result = _message_with_id_projection("abc-123", "assistant", "hi")
        assert result == {"id": "abc-123", "role": "assistant", "content": "hi"}

    def test_int_converted_to_str(self):
        result = _message_with_id_projection(100, "user", "test")
        assert result["id"] == "100"
        assert isinstance(result["id"], str)


# ============================================================
# _fallback_recent_messages
# ============================================================
class TestFallbackRecentMessages:
    def test_non_empty(self):
        msgs = [{"role": "assistant", "content": "hi"}]
        result = _fallback_recent_messages(msgs)
        assert result == [msgs[0]]

    def test_empty(self):
        assert _fallback_recent_messages([]) == []

    def test_multiple_takes_first(self):
        msgs = [
            {"role": "assistant", "content": "first"},
            {"role": "user", "content": "second"},
        ]
        result = _fallback_recent_messages(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "first"


# ============================================================
# _find_target_message_index
# ============================================================
class TestFindTargetMessageIndex:
    def test_found(self):
        msgs = [
            {"id": "1", "role": "user", "content": "a"},
            {"id": "2", "role": "assistant", "content": "b"},
            {"id": "3", "role": "user", "content": "c"},
        ]
        assert _find_target_message_index(msgs, "2") == 1

    def test_not_found(self):
        msgs = [{"id": "1", "role": "user", "content": "a"}]
        assert _find_target_message_index(msgs, "999") is None

    def test_empty_list(self):
        assert _find_target_message_index([], "1") is None

    def test_first_element(self):
        msgs = [{"id": "10", "role": "user", "content": "a"}]
        assert _find_target_message_index(msgs, "10") == 0

    def test_id_as_string_comparison(self):
        """_find_target_message_index 用 str(target_message_id) 比较，id 字段也需为 str。"""
        msgs = [{"id": "5", "role": "user", "content": "a"}]
        assert _find_target_message_index(msgs, 5) == 0


# ============================================================
# _messages_before_target
# ============================================================
class TestMessagesBeforeTarget:
    def test_found(self):
        msgs = [
            {"id": "1", "role": "user", "content": "a"},
            {"id": "2", "role": "assistant", "content": "b"},
            {"id": "3", "role": "user", "content": "c"},
        ]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _messages_before_target(msgs, "3", fallback)
        assert len(result) == 2
        assert result[0]["id"] == "1"

    def test_not_found_returns_chronological(self):
        """目标消息不在列表中（已通过 created_at 过滤排除），直接使用整个 chronological 列表。"""
        msgs = [{"id": "1", "role": "user", "content": "a"}]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _messages_before_target(msgs, "999", fallback)
        assert result == msgs

    def test_not_found_empty_chronological_uses_fallback(self):
        """chronological 为空且找不到目标消息时，使用 fallback。"""
        msgs = []
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _messages_before_target(msgs, "999", fallback)
        assert result == fallback

    def test_target_at_start(self):
        msgs = [{"id": "1", "role": "user", "content": "a"}]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _messages_before_target(msgs, "1", fallback)
        assert result == []


# ============================================================
# _trim_recent_messages_tail
# ============================================================
class TestTrimRecentMessagesTail:
    def test_trims_trailing_assistant(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "assistant", "content": "there"},
        ]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _trim_recent_messages_tail(msgs, fallback)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_no_trailing_assistant(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "how are you"},
        ]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _trim_recent_messages_tail(msgs, fallback)
        assert len(result) == 3

    def test_all_assistant_returns_fallback(self):
        msgs = [
            {"role": "assistant", "content": "hi"},
            {"role": "assistant", "content": "there"},
        ]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _trim_recent_messages_tail(msgs, fallback)
        assert result == fallback

    def test_empty_returns_fallback(self):
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _trim_recent_messages_tail([], fallback)
        assert result == fallback

    def test_does_not_mutate_original(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        fallback = []
        _trim_recent_messages_tail(msgs, fallback)
        assert len(msgs) == 2


# ============================================================
# _project_message_rows
# ============================================================
class TestProjectMessageRows:
    def test_basic(self):
        rows = [
            {"id": 1, "role": "user", "content": "hello"},
            {"id": 2, "role": "assistant", "content": "hi"},
        ]
        result = _project_message_rows(rows)
        assert len(result) == 2
        assert result[0] == {"id": "1", "role": "user", "content": "hello"}
        assert result[1] == {"id": "2", "role": "assistant", "content": "hi"}

    def test_empty(self):
        assert _project_message_rows([]) == []


# ============================================================
# _resolve_recent_messages_before_target
# ============================================================
class TestResolveRecentMessagesBeforeTarget:
    def test_trims_trailing_assistant(self):
        chronological = [
            {"id": "1", "role": "user", "content": "hello"},
            {"id": "2", "role": "assistant", "content": "hi"},
            {"id": "3", "role": "assistant", "content": "there"},
        ]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _resolve_recent_messages_before_target(
            chronological, target_message_id="3", fallback_recent=fallback
        )
        assert all(m["role"] != "assistant" for m in result) or not result

    def test_not_found_returns_chronological_after_trim(self):
        """目标消息不在列表中时，使用 chronological 并移除末尾 assistant。"""
        chronological = [{"id": "1", "role": "user", "content": "a"}]
        fallback = [{"role": "assistant", "content": "fallback"}]
        result = _resolve_recent_messages_before_target(
            chronological, target_message_id="999", fallback_recent=fallback
        )
        # chronological 非空且末尾是 user，直接返回
        assert result == chronological


# ============================================================
# _build_continue_prompt_messages
# ============================================================
class TestBuildContinuePromptMessages:
    def test_appends_assistant_and_user(self):
        recent = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _build_continue_prompt_messages(recent, "hi")
        assert len(result) == 4  # 2 original + assistant current + user continue
        assert result[2]["role"] == "assistant"
        assert result[2]["content"] == "hi"
        assert result[3]["role"] == "user"
        assert "继续" in result[3]["content"]

    def test_does_not_mutate_original(self):
        recent = [{"role": "user", "content": "hello"}]
        original_len = len(recent)
        _build_continue_prompt_messages(recent, "hi")
        assert len(recent) == original_len

    def test_empty_recent(self):
        result = _build_continue_prompt_messages([], "current text")
        assert len(result) == 2
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "user"
