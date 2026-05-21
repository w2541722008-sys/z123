"""character_admin_repository 单元测试 — 验证 SQL 参数传递与返回值。"""
from __future__ import annotations

import pytest

from conftest import FakeRow, FakeSequenceConn


# ============================================================
# 记忆条目
# ============================================================

class TestAdminListMemories:
    def test_returns_rows(self):
        from repositories.character_admin_repository import admin_list_memories
        rows = [
            FakeRow({"id": 1, "keywords": "hello", "trigger_logic": "any", "content": "hi"}),
            FakeRow({"id": 2, "keywords": "world", "trigger_logic": "all", "content": "hey"}),
        ]
        conn = FakeSequenceConn([rows])
        result = admin_list_memories(conn, "char1")
        assert len(result) == 2
        assert result[0]["keywords"] == "hello"

    def test_empty_result(self):
        from repositories.character_admin_repository import admin_list_memories
        conn = FakeSequenceConn([[]])
        result = admin_list_memories(conn, "char1")
        assert result == []


class TestAdminCreateMemory:
    def test_returns_new_id(self):
        from repositories.character_admin_repository import admin_create_memory
        conn = FakeSequenceConn([FakeRow({"id": 42})])
        new_id = admin_create_memory(
            conn, "char1",
            keywords="k", trigger_logic="any", content="c", category_id=None,
            position="system", priority=1, is_active=True, comment=None,
            selective=False, constant=False, sticky=0, cooldown=0,
        )
        assert new_id == 42


class TestAdminGetMemory:
    def test_found(self):
        from repositories.character_admin_repository import admin_get_memory
        conn = FakeSequenceConn([FakeRow({"id": 1})])
        result = admin_get_memory(conn, "1", "char1")
        assert result is not None

    def test_not_found(self):
        from repositories.character_admin_repository import admin_get_memory
        conn = FakeSequenceConn([None])
        result = admin_get_memory(conn, "999", "char1")
        assert result is None


class TestAdminDeleteMemory:
    def test_executes_delete(self):
        from repositories.character_admin_repository import admin_delete_memory
        conn = FakeSequenceConn([None])
        admin_delete_memory(conn, "1")
        assert len(conn.executed) == 1
        assert "DELETE FROM character_memories" in conn.executed[0][0]


# ============================================================
# 记忆分类
# ============================================================

class TestAdminListMemoryCategories:
    def test_returns_rows(self):
        from repositories.character_admin_repository import admin_list_memory_categories
        rows = [FakeRow({"id": 1, "name": "cat1", "color": "red"})]
        conn = FakeSequenceConn([rows])
        result = admin_list_memory_categories(conn, "char1")
        assert len(result) == 1


class TestAdminCreateMemoryCategory:
    def test_returns_new_id(self):
        from repositories.character_admin_repository import admin_create_memory_category
        conn = FakeSequenceConn([FakeRow({"id": 7})])
        new_id = admin_create_memory_category(
            conn, "char1", name="n", description="d", color="#fff", sort_order=1,
        )
        assert new_id == 7


class TestAdminCountMemoriesInCategory:
    def test_returns_count(self):
        from repositories.character_admin_repository import admin_count_memories_in_category
        conn = FakeSequenceConn([FakeRow({"count": 3})])
        result = admin_count_memories_in_category(conn, "cat1")
        assert result == 3

    def test_returns_zero_for_none(self):
        from repositories.character_admin_repository import admin_count_memories_in_category
        conn = FakeSequenceConn([None])
        result = admin_count_memories_in_category(conn, "cat1")
        assert result == 0


class TestAdminGetMemoryCategoryForImpact:
    def test_returns_category(self):
        from repositories.character_admin_repository import admin_get_memory_category_for_impact
        conn = FakeSequenceConn([FakeRow({"id": 1, "name": "重要"})])
        result = admin_get_memory_category_for_impact(conn, "1", "char1")
        assert result["name"] == "重要"

    def test_not_found(self):
        from repositories.character_admin_repository import admin_get_memory_category_for_impact
        conn = FakeSequenceConn([None])
        result = admin_get_memory_category_for_impact(conn, "999", "char1")
        assert result is None


class TestAdminListMemoriesInCategory:
    def test_returns_memories(self):
        from repositories.character_admin_repository import admin_list_memories_in_category
        rows = [FakeRow({"id": 1, "keywords": "k", "comment": "c"})]
        conn = FakeSequenceConn([rows])
        result = admin_list_memories_in_category(conn, "char1", "cat1")
        assert len(result) == 1


# ============================================================
# 开场白
# ============================================================

class TestAdminListGreetings:
    def test_returns_rows(self):
        from repositories.character_admin_repository import admin_list_greetings
        rows = [FakeRow({"id": 1, "story_phase": "stranger", "content": "hello"})]
        conn = FakeSequenceConn([rows])
        result = admin_list_greetings(conn, "char1")
        assert len(result) == 1


class TestAdminCreateGreeting:
    def test_returns_new_id(self):
        from repositories.character_admin_repository import admin_create_greeting
        conn = FakeSequenceConn([FakeRow({"id": 10})])
        new_id = admin_create_greeting(
            conn, "char1",
            story_phase="stranger", mood="neutral", content="hi",
            storyline_id=None, priority=1, is_active=True, comment=None,
        )
        assert new_id == 10


class TestAdminGetGreeting:
    def test_found(self):
        from repositories.character_admin_repository import admin_get_greeting
        conn = FakeSequenceConn([FakeRow({"id": 1})])
        assert admin_get_greeting(conn, "1", "char1") is not None

    def test_not_found(self):
        from repositories.character_admin_repository import admin_get_greeting
        conn = FakeSequenceConn([None])
        assert admin_get_greeting(conn, "999", "char1") is None


# ============================================================
# 剧情线
# ============================================================

class TestAdminListStorylines:
    def test_returns_rows(self):
        from repositories.character_admin_repository import admin_list_storylines
        rows = [FakeRow({"id": 1, "name": "主线", "is_default": True})]
        conn = FakeSequenceConn([rows])
        result = admin_list_storylines(conn, "char1")
        assert len(result) == 1


class TestAdminClearDefaultStoryline:
    def test_clears_all(self):
        from repositories.character_admin_repository import admin_clear_default_storyline
        conn = FakeSequenceConn([None])
        admin_clear_default_storyline(conn, "char1")
        assert "UPDATE character_storylines" in conn.executed[0][0]

    def test_excludes_id(self):
        from repositories.character_admin_repository import admin_clear_default_storyline
        conn = FakeSequenceConn([None])
        admin_clear_default_storyline(conn, "char1", exclude_id="5")
        assert "AND id !=" in conn.executed[0][0]


class TestAdminCreateStoryline:
    def test_returns_new_id(self):
        from repositories.character_admin_repository import admin_create_storyline
        conn = FakeSequenceConn([FakeRow({"id": 3})])
        new_id = admin_create_storyline(
            conn, "char1",
            storyline_id=None, title="t", name="n", description="d",
            unlock_score=10, unlock_condition=None, stages_json="[]",
            is_default=False, is_active=True, sort_order=1,
        )
        assert new_id == 3


class TestAdminGetStoryline:
    def test_found(self):
        from repositories.character_admin_repository import admin_get_storyline
        conn = FakeSequenceConn([FakeRow({"id": 1, "name": "主线"})])
        result = admin_get_storyline(conn, "1", "char1")
        assert result["name"] == "主线"

    def test_not_found(self):
        from repositories.character_admin_repository import admin_get_storyline
        conn = FakeSequenceConn([None])
        assert admin_get_storyline(conn, "999", "char1") is None


class TestAdminDetachStorylineRefs:
    def test_executes_three_updates(self):
        from repositories.character_admin_repository import admin_detach_storyline_refs
        conn = FakeSequenceConn([None, None, None])
        admin_detach_storyline_refs(conn, "1")
        assert len(conn.executed) == 3


class TestAdminGetStorylineForImpact:
    def test_returns_storyline(self):
        from repositories.character_admin_repository import admin_get_storyline_for_impact
        conn = FakeSequenceConn([FakeRow({"id": 1, "name": "主线", "is_default": 0})])
        result = admin_get_storyline_for_impact(conn, "1", "char1")
        assert result["name"] == "主线"


class TestAdminListGreetingsForStoryline:
    def test_returns_greetings(self):
        from repositories.character_admin_repository import admin_list_greetings_for_storyline
        rows = [FakeRow({"id": 1, "story_phase": "friend", "content": "hi"})]
        conn = FakeSequenceConn([rows])
        result = admin_list_greetings_for_storyline(conn, "char1", "sl1")
        assert len(result) == 1


# ============================================================
# 后置规则
# ============================================================

class TestAdminListPostRules:
    def test_returns_rows(self):
        from repositories.character_admin_repository import admin_list_post_rules
        rows = [FakeRow({"id": 1, "name": "rule1", "content": "c"})]
        conn = FakeSequenceConn([rows])
        result = admin_list_post_rules(conn, "char1")
        assert len(result) == 1


class TestAdminCreatePostRule:
    def test_returns_new_id(self):
        from repositories.character_admin_repository import admin_create_post_rule
        conn = FakeSequenceConn([FakeRow({"id": 5})])
        new_id = admin_create_post_rule(
            conn, "char1",
            name="r", content="c", storyline_id=None,
            story_phase="", priority=1, is_active=True,
        )
        assert new_id == 5


class TestAdminGetPostRule:
    def test_found(self):
        from repositories.character_admin_repository import admin_get_post_rule
        conn = FakeSequenceConn([FakeRow({"id": 1})])
        assert admin_get_post_rule(conn, "1", "char1") is not None

    def test_not_found(self):
        from repositories.character_admin_repository import admin_get_post_rule
        conn = FakeSequenceConn([None])
        assert admin_get_post_rule(conn, "999", "char1") is None


# ============================================================
# 剧情事件
# ============================================================

class TestAdminListStoryEvents:
    def test_returns_rows(self):
        from repositories.character_admin_repository import admin_list_story_events
        rows = [FakeRow({"id": 1, "title": "event1"})]
        conn = FakeSequenceConn([rows])
        result = admin_list_story_events(conn, "char1")
        assert len(result) == 1


class TestAdminCreateStoryEvent:
    def test_returns_new_id(self):
        from repositories.character_admin_repository import admin_create_story_event
        conn = FakeSequenceConn([FakeRow({"id": 8})])
        new_id = admin_create_story_event(
            conn, "char1",
            event_id="evt-001", title="t", description="d",
            trigger_score=50, trigger_custom_key="",
            unlocked_memory_ids="", unlocked_greeting_ids="",
            unlocked_storyline_id=None, event_content="",
            sort_order=1, is_active=True,
        )
        assert new_id == 8


class TestAdminGetStoryEvent:
    def test_found(self):
        from repositories.character_admin_repository import admin_get_story_event
        conn = FakeSequenceConn([FakeRow({"id": 1})])
        assert admin_get_story_event(conn, "1", "char1") is not None

    def test_not_found(self):
        from repositories.character_admin_repository import admin_get_story_event
        conn = FakeSequenceConn([None])
        assert admin_get_story_event(conn, "999", "char1") is None


class TestAdminDeleteStoryEvent:
    def test_executes_delete(self):
        from repositories.character_admin_repository import admin_delete_story_event
        conn = FakeSequenceConn([None])
        admin_delete_story_event(conn, "1")
        assert "DELETE FROM story_events" in conn.executed[0][0]
