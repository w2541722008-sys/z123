"""character_admin_memory_repository 单元测试"""

from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn
from repositories.character_admin_memory_repository import (
    admin_list_memories,
    admin_create_memory,
    admin_get_memory,
    admin_update_memory,
    admin_delete_memory,
    admin_list_memory_categories,
    admin_create_memory_category,
    admin_get_memory_category,
    admin_delete_memory_category,
    admin_count_memories_in_category,
    admin_get_memory_category_for_impact,
    admin_list_memories_in_category,
)


class TestMemoryCRUD:
    def test_admin_list_memories(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        admin_list_memories(conn, character_id="char-1")
        sql = conn.executed[0][0]
        assert "FROM character_memories" in sql
        assert "ORDER BY priority ASC" in sql

    def test_admin_create_memory(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 99}))])
        mem_id = admin_create_memory(
            conn, character_id="char-1",
            keywords="hello", trigger_logic="any", content="test",
            category_id=None, position="mid", priority=5,
            is_active=True, comment=None,
            selective=False, constant=True, sticky=0, cooldown=60,
        )
        assert mem_id == 99
        sql = conn.executed[0][0]
        assert "INSERT INTO character_memories" in sql

    def test_admin_get_memory(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": "1"}))])
        row = admin_get_memory(conn, memory_id="1", character_id="char-1")
        assert row is not None

    def test_admin_update_memory(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_update_memory(
            conn, memory_id="1",
            keywords="hi", trigger_logic="all", content="updated",
            category_id=None, position="top", priority=1,
            is_active=False, comment=None,
            selective=True, constant=False, sticky=10, cooldown=30,
        )
        assert "UPDATE character_memories" in conn.executed[0][0]

    def test_admin_delete_memory(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_delete_memory(conn, memory_id="1")
        assert "DELETE FROM character_memories" in conn.executed[0][0]


class TestMemoryCategoryCRUD:
    def test_admin_list_memory_categories(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        admin_list_memory_categories(conn, character_id="char-1")
        assert "FROM memory_categories" in conn.executed[0][0]

    def test_admin_create_memory_category(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 42}))])
        cat_id = admin_create_memory_category(
            conn, character_id="char-1",
            name="分类A", description="描述", color="#FF0000", sort_order=1,
        )
        assert cat_id == 42

    def test_admin_get_memory_category(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": "1"}))])
        row = admin_get_memory_category(conn, category_id="1", character_id="char-1")
        assert row is not None

    def test_admin_delete_memory_category(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_delete_memory_category(conn, category_id="1")
        assert "DELETE FROM memory_categories" in conn.executed[0][0]

    def test_admin_count_memories_in_category(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"count": 5}))])
        count = admin_count_memories_in_category(conn, category_id="1")
        assert count == 5

    def test_admin_count_memories_in_category_returns_zero_when_missing(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        count = admin_count_memories_in_category(conn, category_id="1")
        assert count == 0

    def test_admin_get_memory_category_for_impact_returns_category_name(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 1, "name": "重要"}))])
        row = admin_get_memory_category_for_impact(conn, category_id="1", character_id="char-1")
        assert row["name"] == "重要"

    def test_admin_get_memory_category_for_impact_returns_none_when_missing(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        row = admin_get_memory_category_for_impact(conn, category_id="missing", character_id="char-1")
        assert row is None

    def test_admin_list_memories_in_category_returns_rows_for_impact_preview(self):
        rows = [FakeRow({"id": 1, "keywords": "k", "comment": "c"})]
        conn = FakeSequenceConn([FakeQueryResult(many=rows)])
        result = admin_list_memories_in_category(conn, character_id="char-1", category_id="cat-1")
        assert result == rows
