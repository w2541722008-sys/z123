"""
memory_service 模块单元测试

覆盖范围：
  - parse_state_update_tag: AI 状态更新标签解析
  - structured summary helpers: 结构化摘要解析、格式化与合并
"""

from services.memory_service import (
    _empty_structured_summary,
    format_structured_summary,
    merge_summary_text,
    refresh_memory_summary,
)
from utils.stream_filter import parse_state_update_tag


# ============================================================
# parse_state_update_tag 测试
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

    def test_extracts_xml_style_state_tag(self):
        """兼容旧版 XML 风格状态标签。"""
        text = '你好<STATE_UPDATE>{"mood": "warm"}</STATE_UPDATE>世界'
        cleaned, delta = parse_state_update_tag(text)
        assert cleaned == "你好世界"
        assert delta == {"mood": "warm"}


# ============================================================
# 3. structured summary helpers 测试
# ============================================================

class TestStructuredSummaryHelpers:
    def test_empty_structured_summary_returns_stable_shape(self):
        result = _empty_structured_summary()
        assert result == {
            "profile": [],
            "preferences": [],
            "events": [],
            "relationship": [],
            "pending": [],
            "raw_summary": "",
        }

    def test_format_structured_summary_skips_empty_sections(self):
        result = format_structured_summary({
            "profile": ["喜欢夜聊"],
            "preferences": [],
            "events": ["刚刚一起看完电影"],
            "relationship": [],
            "pending": [],
        })

        assert "【用户画像】" in result
        assert "- 喜欢夜聊" in result
        assert "【近期事件】" in result
        assert "- 刚刚一起看完电影" in result
        assert "【用户偏好】" not in result

    def test_merge_summary_text_prefers_new_items_and_deduplicates(self):
        existing = """[用户画像]\n- 喜欢夜聊\n\n[近期事件]\n- 昨天聊到工作压力\n\n[关系状态]\n- 关系稳定推进"""
        new_text = """[用户画像]\n- 喜欢夜聊\n- 说话直接\n\n[近期事件]\n- 今天计划一起散步\n\n[关系状态]\n- 关系稳定推进"""

        merged = merge_summary_text(existing, new_text)

        assert merged.index("- 喜欢夜聊") < merged.index("- 说话直接")
        assert merged.count("- 喜欢夜聊") == 1
        assert "- 今天计划一起散步" in merged
        assert "- 昨天聊到工作压力" in merged

    def test_merge_summary_text_returns_new_text_when_old_not_structured(self):
        merged = merge_summary_text("旧版自由文本摘要", "[用户画像]\n- 喜欢旅行")
        assert merged == "[用户画像]\n- 喜欢旅行"


# ============================================================
# refresh_memory_summary 测试
# ============================================================

class TestRefreshMemorySummary:
    def _rows(self, count: int):
        return [
            {
                "id": idx,
                "role": "user" if idx % 2 else "assistant",
                "content": f"message {idx}",
            }
            for idx in range(1, count + 1)
        ]

    def _conn(self):
        class FakeConn:
            def __init__(self):
                self.committed = False

            def commit(self):
                self.committed = True

        return FakeConn()

    def test_first_summary_at_trigger_summarizes_rows_before_recent_window(self, monkeypatch):
        rows = self._rows(16)
        conn = self._conn()
        events = {}

        monkeypatch.setattr("services.memory_service.get_unsummarized_messages", lambda *args: rows)
        monkeypatch.setattr("services.memory_service.get_summary_record", lambda *args: None)

        def build_messages(character, existing_summary, summary_target_rows):
            events["target_ids"] = [row["id"] for row in summary_target_rows]
            events["existing_summary"] = existing_summary
            return [{"role": "user", "content": "summarize"}]

        monkeypatch.setattr("services.memory_service.build_memory_summary_messages", build_messages)
        monkeypatch.setattr("services.memory_service.request_chat_completion", lambda *args, **kwargs: "[用户画像]\n- 已认识")
        monkeypatch.setattr("services.memory_service.get_ai_config", lambda env: {})
        monkeypatch.setattr("services.memory_service.merge_summary_text", lambda existing, new: new)
        monkeypatch.setattr(
            "services.memory_service.save_summary",
            lambda conn, user_id, character_id, summary_text, last_message_id: events.update(
                saved=(summary_text, last_message_id)
            ),
        )
        monkeypatch.setattr(
            "services.memory_service.mark_messages_summarized",
            lambda conn, ids: events.update(marked=ids),
        )

        refresh_memory_summary(conn, 1, "c1", {"name": "Test"})

        assert events["existing_summary"] == ""
        assert events["target_ids"] == [1, 2, 3, 4]
        assert events["saved"] == ("[用户画像]\n- 已认识", 4)
        assert events["marked"] == [1, 2, 3, 4]
        assert conn.committed is True

    def test_existing_summary_keeps_original_batch_threshold(self, monkeypatch):
        rows = self._rows(16)
        conn = self._conn()
        events = []

        monkeypatch.setattr("services.memory_service.get_unsummarized_messages", lambda *args: rows)
        monkeypatch.setattr(
            "services.memory_service.get_summary_record",
            lambda *args: {"summary": "[用户画像]\n- 旧记忆"},
        )
        monkeypatch.setattr(
            "services.memory_service.request_chat_completion",
            lambda *args, **kwargs: events.append("request"),
        )

        refresh_memory_summary(conn, 1, "c1", {"name": "Test"})

        assert events == []
        assert conn.committed is False

    def test_existing_summary_refreshes_when_full_batch_available(self, monkeypatch):
        rows = self._rows(24)
        conn = self._conn()
        events = {}

        monkeypatch.setattr("services.memory_service.get_unsummarized_messages", lambda *args: rows)
        monkeypatch.setattr(
            "services.memory_service.get_summary_record",
            lambda *args: {"summary": "[用户画像]\n- 旧记忆"},
        )

        def build_messages(character, existing_summary, summary_target_rows):
            events["target_ids"] = [row["id"] for row in summary_target_rows]
            events["existing_summary"] = existing_summary
            return [{"role": "user", "content": "summarize"}]

        monkeypatch.setattr("services.memory_service.build_memory_summary_messages", build_messages)
        monkeypatch.setattr("services.memory_service.request_chat_completion", lambda *args, **kwargs: "[用户画像]\n- 新记忆")
        monkeypatch.setattr("services.memory_service.get_ai_config", lambda env: {})
        monkeypatch.setattr("services.memory_service.merge_summary_text", lambda existing, new: new)
        monkeypatch.setattr(
            "services.memory_service.save_summary",
            lambda conn, user_id, character_id, summary_text, last_message_id: events.update(
                saved=(summary_text, last_message_id)
            ),
        )
        monkeypatch.setattr(
            "services.memory_service.mark_messages_summarized",
            lambda conn, ids: events.update(marked=ids),
        )

        refresh_memory_summary(conn, 1, "c1", {"name": "Test"})

        assert events["existing_summary"] == "[用户画像]\n- 旧记忆"
        assert events["target_ids"] == list(range(1, 13))
        assert events["saved"] == ("[用户画像]\n- 新记忆", 12)
        assert events["marked"] == list(range(1, 13))
        assert conn.committed is True
