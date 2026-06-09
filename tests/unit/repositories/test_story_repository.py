"""story_repository 单元测试"""

import pytest
from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn
from repositories.story_repository import (
    fetch_active_story_events,
    get_triggered_event_ids,
    unlock_memories,
    unlock_greetings,
    unlock_storyline,
    get_storyline_name,
    get_recent_event_titles,
    get_current_storyline_id,
    is_storyline_valid,
    set_current_storyline_id,
    upsert_story_progress,
)


class TestFetchActiveStoryEvents:
    def test_queries_active_story_events_in_trigger_order(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        fetch_active_story_events(conn, character_id="char-1")
        sql = conn.executed[0][0]
        assert "is_active = 1" in sql
        assert "ORDER BY trigger_score ASC" in sql


class TestGetTriggeredEventIds:
    def test_returns_set(self):
        result = FakeQueryResult(
            one=FakeRow({"triggered_event_ids": "1,2,3"})
        )
        conn = FakeSequenceConn([result])
        ids = get_triggered_event_ids(conn, user_id=1, character_id="char-1")
        assert ids == {1, 2, 3}

    def test_empty_string_returns_empty_set(self):
        result = FakeQueryResult(one=FakeRow({"triggered_event_ids": ""}))
        conn = FakeSequenceConn([result])
        ids = get_triggered_event_ids(conn, user_id=1, character_id="char-1")
        assert ids == set()

    def test_no_progress_returns_empty_set(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        ids = get_triggered_event_ids(conn, user_id=1, character_id="char-1")
        assert ids == set()

    def test_mixed_ids_filter_nondigits(self):
        result = FakeQueryResult(
            one=FakeRow({"triggered_event_ids": "1,abc,3,"})
        )
        conn = FakeSequenceConn([result])
        ids = get_triggered_event_ids(conn, user_id=1, character_id="char-1")
        assert ids == {1, 3}


class TestUnlockOperations:
    def test_unlock_memories_empty_list(self):
        conn = FakeSequenceConn([])
        unlock_memories(conn, character_id="char-1", memory_ids=[])
        assert len(conn.executed) == 0

    def test_unlock_memories_with_ids(self):
        conn = FakeSequenceConn([FakeRow({})])
        unlock_memories(conn, character_id="char-1", memory_ids=[1, 2])
        sql = conn.executed[0][0]
        assert "UPDATE character_memories" in sql
        assert "is_active = 1" in sql

    def test_unlock_greetings_empty_list(self):
        conn = FakeSequenceConn([])
        unlock_greetings(conn, character_id="char-1", greeting_ids=[])
        assert len(conn.executed) == 0

    def test_unlock_storyline(self):
        conn = FakeSequenceConn([FakeRow({})])
        unlock_storyline(conn, character_id="char-1", storyline_id=42)
        sql = conn.executed[0][0]
        assert "UPDATE character_storylines" in sql


class TestQueryFunctions:
    def test_get_storyline_name_found(self):
        result = FakeQueryResult(one=FakeRow({"name": "主线剧情"}))
        conn = FakeSequenceConn([result])
        name = get_storyline_name(conn, storyline_id=1)
        assert name == "主线剧情"

    def test_get_storyline_name_not_found(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        name = get_storyline_name(conn, storyline_id=999)
        assert name is None

    def test_get_recent_event_titles_empty(self):
        titles = get_recent_event_titles(FakeSequenceConn([]), event_ids=[])
        assert titles == []

    def test_get_recent_event_titles_with_ids(self):
        result = FakeQueryResult(many=[
            FakeRow({"title": "事件A"}), FakeRow({"title": "事件B"})
        ])
        conn = FakeSequenceConn([result])
        titles = get_recent_event_titles(conn, event_ids=[1, 2])
        assert "事件A" in titles

    def test_is_storyline_valid_true(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"count": 1}))])
        assert is_storyline_valid(conn, storyline_id=1, character_id="char-1")

    def test_is_storyline_valid_false(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        assert not is_storyline_valid(conn, storyline_id=999, character_id="char-1")


class TestUpsertStoryProgress:
    def test_upsert(self):
        conn = FakeSequenceConn([FakeRow({})])
        upsert_story_progress(
            conn, user_id=1, character_id="char-1",
            triggered_ids_str="1,2", storyline_id=3,
        )
        sql = conn.executed[0][0]
        assert "INSERT INTO user_story_progress" in sql
        assert "ON CONFLICT" in sql


class TestSetCurrentStorylineId:
    def test_set_storyline(self):
        conn = FakeSequenceConn([FakeRow({})])
        set_current_storyline_id(conn, user_id=1, character_id="char-1", storyline_id=5)
        sql = conn.executed[0][0]
        assert "current_storyline_id" in sql


class TestGetCurrentStorylineId:
    def test_returns_int(self):
        result = FakeQueryResult(one=FakeRow({"current_storyline_id": 42}))
        conn = FakeSequenceConn([result])
        sid = get_current_storyline_id(conn, user_id=1, character_id="char-1")
        assert sid == 42

    def test_none_returns_none(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        sid = get_current_storyline_id(conn, user_id=1, character_id="char-1")
        assert sid is None
