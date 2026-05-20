"""chat_query 服务层测试 — 使用 FakeSequenceConn 模拟 DB 交互。

覆盖：消息校验、消息统计、Regenerate/Continue 目标查询等纯逻辑 + Mock DB 函数。
"""

import pytest
from unittest.mock import patch

from conftest import FakeSequenceConn, FakeQueryResult, FakeRow


# ============================================================
# _normalize_non_empty_message
# ============================================================
class TestNormalizeNonEmptyMessage:
    def test_clean_text_returned(self):
        from services.chat_query import _normalize_non_empty_message
        assert _normalize_non_empty_message("hello") == "hello"

    def test_whitespace_stripped(self):
        from services.chat_query import _normalize_non_empty_message
        assert _normalize_non_empty_message("  hello  ") == "hello"

    def test_empty_raises_400(self):
        from services.chat_query import _normalize_non_empty_message
        from core.exceptions import BadRequestError
        with pytest.raises(BadRequestError) as exc:
            _normalize_non_empty_message("   ")
        assert "消息不能为空" in exc.value.detail

    def test_empty_string_raises_400(self):
        from services.chat_query import _normalize_non_empty_message
        from core.exceptions import BadRequestError
        with pytest.raises(BadRequestError):
            _normalize_non_empty_message("")


# ============================================================
# count_chat_messages
# ============================================================
class TestCountChatMessages:
    def test_returns_total_count(self):
        from services.chat_query import count_chat_messages
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"total": 5}))])
        result = count_chat_messages(conn, user_id=1, character_id="c1")
        assert result == 5

    def test_no_messages_returns_zero(self):
        from services.chat_query import count_chat_messages
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"total": 0}))])
        result = count_chat_messages(conn, user_id=1, character_id="c1")
        assert result == 0


# ============================================================
# get_last_chat_time
# ============================================================
class TestGetLastChatTime:
    def test_returns_timestamp(self):
        from services.chat_query import get_last_chat_time
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"created_at": "2026-05-19T10:00:00Z"}))])
        result = get_last_chat_time(conn, user_id=1, character_id="c1")
        assert result == "2026-05-19T10:00:00Z"

    def test_no_messages_returns_none(self):
        from services.chat_query import get_last_chat_time
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        result = get_last_chat_time(conn, user_id=1, character_id="c1")
        assert result is None


# ============================================================
# get_message_for_regenerate_or_continue
# ============================================================
class TestGetMessageForRegenerateOrContinue:
    def test_found_message_returned(self):
        from services.chat_query import get_message_for_regenerate_or_continue
        row_data = {
            "id": 100, "user_id": 1, "character_id": "c1",
            "role": "assistant", "content": "Previous reply",
        }
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow(row_data))])
        msg, char_id = get_message_for_regenerate_or_continue(
            conn, user_id=1, message_id="100", operation="regenerate",
        )
        assert msg["id"] == 100
        assert msg["content"] == "Previous reply"
        assert char_id == "c1"

    def test_not_found_raises_404(self):
        from services.chat_query import get_message_for_regenerate_or_continue
        from core.exceptions import NotFoundError
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        with pytest.raises(NotFoundError) as exc:
            get_message_for_regenerate_or_continue(
                conn, user_id=1, message_id="999", operation="regenerate",
            )
        assert "不存在" in exc.value.detail


# ============================================================
# get_linked_assets
# ============================================================
class TestGetLinkedAssets:
    def test_returns_empty_list(self):
        from services.chat_query import get_linked_assets
        conn = FakeSequenceConn([])
        result = get_linked_assets(conn, "c1")
        assert result == []


# ============================================================
# get_character_or_404 — 角色缓存与查询
# ============================================================
class TestGetCharacterOr404:
    def test_cached_character_returned_without_db(self):
        from services.chat_query import get_character_or_404
        cache_data = FakeRow({"id": "c1", "name": "CachedChar", "is_visible": 1, "required_plan": "guest"})
        with patch("services.chat_query.get_character", return_value=cache_data):
            conn = FakeSequenceConn([])  # 不应该执行任何 SQL
            result = get_character_or_404(conn, "c1")
            assert result["name"] == "CachedChar"

    def test_not_found_raises_404(self):
        from services.chat_query import get_character_or_404
        from core.exceptions import NotFoundError
        with patch("services.chat_query.get_character", return_value=None):
            conn = FakeSequenceConn([FakeQueryResult(one=None)])
            with pytest.raises(NotFoundError):
                get_character_or_404(conn, "nonexistent")

    def test_db_fallback_when_cache_miss(self):
        from services.chat_query import get_character_or_404
        char_row = FakeRow({"id": "c2", "name": "DBChar", "is_visible": 1, "required_plan": "guest"})
        with patch("services.chat_query.get_character", return_value=None), \
             patch("services.chat_query.set_character") as mock_set:
            conn = FakeSequenceConn([FakeQueryResult(one=char_row)])
            result = get_character_or_404(conn, "c2")
            assert result["name"] == "DBChar"
            mock_set.assert_called_once()

    def test_vip_character_blocked_for_free_user(self):
        from services.chat_query import get_character_or_404
        from core.exceptions import ForbiddenError
        char_row = FakeRow({"id": "c3", "name": "VIPChar", "is_visible": 1, "required_plan": "vip"})
        with patch("services.chat_query.get_character", return_value=None):
            conn = FakeSequenceConn([FakeQueryResult(one=char_row)])
            with pytest.raises(ForbiddenError):
                get_character_or_404(conn, "c3", viewer_plan="free")
