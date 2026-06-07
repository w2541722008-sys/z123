"""character_state_repository 单元测试"""

from conftest import FakeRow, FakeQueryResult, FakeSequenceConn
from repositories.character_state_repository import get_character_state, upsert_character_state


class TestGetCharacterState:
    def test_basic_select(self):
        result = FakeQueryResult(
            one=FakeRow({
                "affection": 50, "story_phase": "intro", "mood": "happy",
                "custom_vars": "{}", "daily_event_counts": "{}",
                "daily_affection_gained": 0, "last_event_timestamps": "{}",
                "daily_reset_date": "2026-01-01",
            })
        )
        conn = FakeSequenceConn([result])
        row = get_character_state(conn, user_id=1, character_id="char-1")
        assert row["affection"] == 50
        assert row["story_phase"] == "intro"

    def test_for_update_adds_lock_clause(self):
        result = FakeQueryResult(one=FakeRow({"affection": 0}))
        conn = FakeSequenceConn([result])
        get_character_state(conn, user_id=1, character_id="char-1", for_update=True)
        assert "FOR UPDATE" in conn.executed[0][0]

    def test_for_update_false_omits_lock(self):
        result = FakeQueryResult(one=FakeRow({"affection": 0}))
        conn = FakeSequenceConn([result])
        get_character_state(conn, user_id=1, character_id="char-1", for_update=False)
        assert "FOR UPDATE" not in conn.executed[0][0]

    def test_not_found_returns_none(self):
        conn = FakeSequenceConn([FakeQueryResult(one=None)])
        row = get_character_state(conn, user_id=999, character_id="nonexistent")
        assert row is None


class TestUpsertCharacterState:
    def test_upsert_basic(self):
        conn = FakeSequenceConn([FakeRow({})])
        upsert_character_state(
            conn,
            user_id=1, character_id="char-1",
            affection=50, story_phase="intro", mood="happy",
            custom_vars_json="{}", daily_event_counts_json="{}",
            daily_affection_gained=10, last_event_timestamps_json="{}",
            daily_reset_date="2026-01-01",
        )
        sql = conn.executed[0][0]
        assert "INSERT INTO character_states" in sql
        assert "ON CONFLICT" in sql
