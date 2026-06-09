"""character_memory_repository 单元测试"""

from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn
from repositories.character_memory_repository import (
    fetch_active_memory_rows,
    fetch_active_post_rule_rows,
    get_active_keyword_memories,
)


class TestFetchActiveMemoryRows:
    def test_returns_active_memory_rows_for_character(self):
        result = FakeQueryResult(many=[
            FakeRow({"id": 1, "keywords": "你好", "content": "记忆内容", "priority": 1}),
        ])
        conn = FakeSequenceConn([result])
        rows = fetch_active_memory_rows(conn, character_id="char-1")
        assert len(rows) == 1
        assert rows[0]["keywords"] == "你好"

    def test_only_active_rows(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        rows = fetch_active_memory_rows(conn, character_id="char-1")
        sql = conn.executed[0][0]
        assert "is_active = 1" in sql
        assert "ORDER BY priority ASC" in sql


class TestFetchActivePostRuleRows:
    def test_returns_active_post_rule_rows_for_character(self):
        result = FakeQueryResult(many=[
            FakeRow({"content": "规则内容", "priority": 5}),
        ])
        conn = FakeSequenceConn([result])
        rows = fetch_active_post_rule_rows(conn, character_id="char-1")
        assert len(rows) == 1
        assert rows[0]["content"] == "规则内容"

    def test_with_storyline_filter(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        fetch_active_post_rule_rows(conn, character_id="char-1", storyline_id=42)
        sql = conn.executed[0][0]
        assert "storyline_id" in sql

    def test_with_story_phase_filter(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        fetch_active_post_rule_rows(conn, character_id="char-1", story_phase="climax")
        sql = conn.executed[0][0]
        assert "story_phase" in sql


class TestGetActiveKeywordMemories:
    def test_queries_active_keyword_memories_for_character(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        get_active_keyword_memories(conn, character_id="char-1")
        sql = conn.executed[0][0]
        assert "character_memories" in sql
        assert "is_active = 1" in sql
