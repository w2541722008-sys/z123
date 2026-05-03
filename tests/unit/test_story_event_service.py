"""story_event_service 单元测试。

覆盖：check_and_trigger_story_events 的各种场景。
使用 FakeSequenceConn 模拟数据库。
"""
from conftest import FakeSequenceConn, FakeRow, FakeQueryResult


# ============================================================
# check_and_trigger_story_events
# ============================================================
class TestCheckAndTriggerStoryEvents:
    def _make_conn(self, events, progress_row=None, extra_results=None):
        """构建 FakeSequenceConn，预设 events 和 progress 查询结果。"""
        results = [events]
        if progress_row is not None:
            results.append(progress_row)
        else:
            results.append(FakeRow({"triggered_event_ids": ""}))
        if extra_results:
            results.extend(extra_results)
        return FakeSequenceConn(results)

    def test_no_events(self):
        from services.story_event_service import check_and_trigger_story_events
        conn = self._make_conn([])
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert result == []

    def test_affection_below_threshold(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "First Meet", "description": "desc",
                "trigger_score": 100, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events)
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert result == []

    def test_affection_meets_threshold(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "First Meet", "description": "desc",
                "trigger_score": 30, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "event content", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=1),  # INSERT INTO user_story_progress
        ])
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert len(result) == 1
        assert result[0]["title"] == "First Meet"
        assert result[0]["trigger_score"] == 30

    def test_already_triggered_event_skipped(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "First Meet", "description": "desc",
                "trigger_score": 30, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
        ]
        progress = FakeRow({"triggered_event_ids": "1"})
        conn = self._make_conn(events, progress_row=progress)
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert result == []

    def test_unlock_memory_ids(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "Unlock Memory", "description": "desc",
                "trigger_score": 30, "unlocked_memory_ids": "10,20",
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=2),  # UPDATE character_memories
            FakeQueryResult(rowcount=1),  # INSERT INTO user_story_progress
        ])
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert len(result) == 1
        assert result[0]["unlocked"]["memories"] == [10, 20]

    def test_unlock_greeting_ids(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 2, "title": "Unlock Greeting", "description": "desc",
                "trigger_score": 40, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": "5,6", "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=2),  # UPDATE character_greetings
            FakeQueryResult(rowcount=1),  # INSERT INTO user_story_progress
        ])
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert result[0]["unlocked"]["greetings"] == [5, 6]

    def test_unlock_storyline(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 3, "title": "Unlock Storyline", "description": "desc",
                "trigger_score": 50, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": 7,
                "event_content": "", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=1),  # UPDATE character_storylines
            FakeQueryResult(rowcount=1),  # INSERT INTO user_story_progress
        ])
        result = check_and_trigger_story_events(conn, 1, "c1", 60, "stranger", commit=False)
        assert result[0]["unlocked"]["storyline_id"] == 7

    def test_multiple_events_triggered(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "Event A", "description": "desc A",
                "trigger_score": 20, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
            FakeRow({
                "id": 2, "title": "Event B", "description": "desc B",
                "trigger_score": 40, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=1),  # INSERT INTO user_story_progress
        ])
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert len(result) == 2
        assert result[0]["title"] == "Event A"
        assert result[1]["title"] == "Event B"

    def test_commit_true(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "Event", "description": "",
                "trigger_score": 10, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=1),  # INSERT
        ])
        check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=True)
        assert conn.committed is True

    def test_commit_false(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "Event", "description": "",
                "trigger_score": 10, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=1),  # INSERT
        ])
        check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert conn.committed is False

    def test_exception_returns_empty(self):
        from services.story_event_service import check_and_trigger_story_events
        conn = FakeSequenceConn([])  # no results → will raise
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger")
        # Exception caught internally, returns empty list
        assert result == []

    def test_progress_row_with_existing_ids(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "Already Done", "description": "",
                "trigger_score": 10, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "", "is_active": 1,
            }),
            FakeRow({
                "id": 2, "title": "New Event", "description": "desc",
                "trigger_score": 20, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "content", "is_active": 1,
            }),
        ]
        progress = FakeRow({"triggered_event_ids": "1"})
        conn = self._make_conn(events, progress_row=progress, extra_results=[
            FakeQueryResult(rowcount=1),  # INSERT
        ])
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert len(result) == 1
        assert result[0]["title"] == "New Event"

    def test_event_content_included(self):
        from services.story_event_service import check_and_trigger_story_events
        events = [
            FakeRow({
                "id": 1, "title": "Event", "description": "desc text",
                "trigger_score": 10, "unlocked_memory_ids": None,
                "unlocked_greeting_ids": None, "unlocked_storyline_id": None,
                "event_content": "event content here", "is_active": 1,
            }),
        ]
        conn = self._make_conn(events, extra_results=[
            FakeQueryResult(rowcount=1),
        ])
        result = check_and_trigger_story_events(conn, 1, "c1", 50, "stranger", commit=False)
        assert result[0]["event_content"] == "event content here"
        assert result[0]["description"] == "desc text"
