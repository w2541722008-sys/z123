"""story_event_service 子函数单元测试。"""
from __future__ import annotations

import pytest

from conftest import FakeRow, FakeSequenceConn


class TestFetchActiveStoryEvents:
    def test_returns_events(self):
        from services.story_event_service import _fetch_active_story_events
        rows = [
            FakeRow({"id": 1, "title": "初遇", "trigger_score": 10}),
            FakeRow({"id": 2, "title": "重逢", "trigger_score": 50}),
        ]
        conn = FakeSequenceConn([rows])
        result = _fetch_active_story_events(conn, "char1")
        assert len(result) == 2
        assert result[0]["title"] == "初遇"

    def test_empty_result(self):
        from services.story_event_service import _fetch_active_story_events
        conn = FakeSequenceConn([[]])
        result = _fetch_active_story_events(conn, "char1")
        assert result == []


class TestLoadTriggeredEventIds:
    def test_returns_ids(self):
        from services.story_event_service import _load_triggered_event_ids
        conn = FakeSequenceConn([
            FakeRow({"triggered_event_ids": "1,3,5"})
        ])
        result = _load_triggered_event_ids(conn, 1, "char1")
        assert result == {1, 3, 5}

    def test_empty_for_none_row(self):
        from services.story_event_service import _load_triggered_event_ids
        conn = FakeSequenceConn([None])
        result = _load_triggered_event_ids(conn, 1, "char1")
        assert result == set()

    def test_empty_for_null_field(self):
        from services.story_event_service import _load_triggered_event_ids
        conn = FakeSequenceConn([
            FakeRow({"triggered_event_ids": None})
        ])
        result = _load_triggered_event_ids(conn, 1, "char1")
        assert result == set()


class TestShouldTriggerEvent:
    def test_already_triggered_returns_false(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 1, "trigger_score": 10, "trigger_custom_key": ""}
        assert _should_trigger_event(event, {1, 2}, 50, {}) is False

    def test_score_too_low_returns_false(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 3, "trigger_score": 60, "trigger_custom_key": ""}
        assert _should_trigger_event(event, {1, 2}, 50, {}) is False

    def test_custom_key_missing_returns_false(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 3, "trigger_score": 10, "trigger_custom_key": "has_sword"}
        assert _should_trigger_event(event, set(), 50, {}) is False

    def test_custom_key_empty_value_returns_false(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 3, "trigger_score": 10, "trigger_custom_key": "has_sword"}
        assert _should_trigger_event(event, set(), 50, {"has_sword": 0}) is False

    def test_all_conditions_met_returns_true(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 3, "trigger_score": 10, "trigger_custom_key": "has_sword"}
        assert _should_trigger_event(event, set(), 50, {"has_sword": True}) is True

    def test_no_custom_key_returns_true_when_score_met(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 3, "trigger_score": 10, "trigger_custom_key": ""}
        assert _should_trigger_event(event, set(), 50, {}) is True

    def test_multiple_custom_keys_all_present(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 3, "trigger_score": 10, "trigger_custom_key": "key_a, key_b"}
        assert _should_trigger_event(event, set(), 50, {"key_a": 1, "key_b": "yes"}) is True

    def test_multiple_custom_keys_one_missing(self):
        from services.story_event_service import _should_trigger_event
        event = {"id": 3, "trigger_score": 10, "trigger_custom_key": "key_a, key_b"}
        assert _should_trigger_event(event, set(), 50, {"key_a": 1}) is False


class TestUnlockEventAssets:
    def test_unlocks_memories(self):
        from services.story_event_service import _unlock_event_assets
        conn = FakeSequenceConn([None])
        event = {
            "unlocked_memory_ids": "1,2,3",
            "unlocked_greeting_ids": None,
            "unlocked_storyline_id": None,
        }
        result = _unlock_event_assets(conn, event, "char1")
        assert result == {"memories": [1, 2, 3]}
        assert len(conn.executed) == 1

    def test_unlocks_greetings(self):
        from services.story_event_service import _unlock_event_assets
        conn = FakeSequenceConn([None])
        event = {
            "unlocked_memory_ids": None,
            "unlocked_greeting_ids": "5,6",
            "unlocked_storyline_id": None,
        }
        result = _unlock_event_assets(conn, event, "char1")
        assert result == {"greetings": [5, 6]}

    def test_unlocks_storyline(self):
        from services.story_event_service import _unlock_event_assets
        conn = FakeSequenceConn([None])
        event = {
            "unlocked_memory_ids": None,
            "unlocked_greeting_ids": None,
            "unlocked_storyline_id": "7",
        }
        result = _unlock_event_assets(conn, event, "char1")
        assert result == {"storyline_id": 7}

    def test_unlocks_all_three(self):
        from services.story_event_service import _unlock_event_assets
        conn = FakeSequenceConn([None, None, None])
        event = {
            "unlocked_memory_ids": "1",
            "unlocked_greeting_ids": "2",
            "unlocked_storyline_id": "3",
        }
        result = _unlock_event_assets(conn, event, "char1")
        assert "memories" in result
        assert "greetings" in result
        assert "storyline_id" in result
        assert len(conn.executed) == 3

    def test_empty_event_returns_empty_dict(self):
        from services.story_event_service import _unlock_event_assets
        conn = FakeSequenceConn([])
        event = {
            "unlocked_memory_ids": None,
            "unlocked_greeting_ids": None,
            "unlocked_storyline_id": None,
        }
        result = _unlock_event_assets(conn, event, "char1")
        assert result == {}


class TestPersistStoryProgress:
    def test_executes_upsert(self):
        from services.story_event_service import _persist_story_progress
        conn = FakeSequenceConn([None])
        _persist_story_progress(conn, 1, "char1", {1, 2}, ["3", "4"], commit=False)
        assert len(conn.executed) == 1
        assert "INSERT INTO user_story_progress" in conn.executed[0][0]

    def test_commits_when_flag_set(self):
        from services.story_event_service import _persist_story_progress
        conn = FakeSequenceConn([None])
        _persist_story_progress(conn, 1, "char1", set(), ["5"], commit=True)
        assert conn.committed
