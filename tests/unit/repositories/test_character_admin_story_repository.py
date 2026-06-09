"""character_admin_story_repository 单元测试"""

from tests.support.db import FakeQueryResult, FakeRow, FakeSequenceConn
from repositories.character_admin_story_repository import (
    admin_list_greetings,
    admin_create_greeting,
    admin_get_greeting,
    admin_update_greeting,
    admin_delete_greeting,
    admin_list_storylines,
    admin_create_storyline,
    admin_get_storyline,
    admin_get_storyline_for_impact,
    admin_update_storyline,
    admin_delete_storyline,
    admin_detach_storyline_refs,
    admin_clear_default_storyline,
    admin_list_greetings_for_storyline,
    admin_list_post_rules,
    admin_create_post_rule,
    admin_get_post_rule,
    admin_update_post_rule,
    admin_delete_post_rule,
    admin_list_story_events,
    admin_create_story_event,
    admin_get_story_event,
    admin_update_story_event,
    admin_delete_story_event,
)


class TestGreetingCRUD:
    def test_admin_list_greetings(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        admin_list_greetings(conn, character_id="char-1")
        sql = conn.executed[0][0]
        assert "FROM character_greetings" in sql

    def test_admin_create_greeting(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 10}))])
        gid = admin_create_greeting(
            conn, character_id="char-1",
            story_phase="intro", mood="happy", content="你好!",
            storyline_id=None, priority=1, is_active=True, comment=None,
        )
        assert gid == 10

    def test_admin_get_greeting(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": "1"}))])
        row = admin_get_greeting(conn, greeting_id="1", character_id="char-1")
        assert row is not None

    def test_admin_update_greeting(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_update_greeting(
            conn, greeting_id="1",
            story_phase="climax", mood="sad", content="updated",
            storyline_id=None, priority=2, is_active=False, comment=None,
        )
        assert "UPDATE character_greetings" in conn.executed[0][0]

    def test_admin_delete_greeting(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_delete_greeting(conn, greeting_id="1")
        assert "DELETE FROM character_greetings" in conn.executed[0][0]


class TestStorylineCRUD:
    def test_admin_list_storylines(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        admin_list_storylines(conn, character_id="char-1")
        assert "FROM character_storylines" in conn.executed[0][0]

    def test_admin_create_storyline(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 7}))])
        sid = admin_create_storyline(
            conn, character_id="char-1",
            storyline_id="SL-1", title="主线", name="main",
            description=None, unlock_score=10, unlock_condition=None,
            stages_json="[]", is_default=True, is_active=True, sort_order=1,
        )
        assert sid == 7

    def test_admin_get_storyline(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": "1", "name": "test"}))])
        row = admin_get_storyline(conn, storyline_id="1", character_id="char-1")
        assert row is not None

    def test_admin_update_storyline(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_update_storyline(
            conn, storyline_id="1",
            storyline_id_field="SL-1", title="主线", name="main",
            description=None, unlock_score=10, unlock_condition=None,
            stages_json="[]", is_default=True, is_active=True, sort_order=1,
        )
        assert "UPDATE character_storylines" in conn.executed[0][0]

    def test_admin_delete_storyline(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_delete_storyline(conn, storyline_id="1")
        assert "DELETE FROM character_storylines" in conn.executed[0][0]

    def test_admin_detach_storyline_refs(self):
        conn = FakeSequenceConn([FakeRow({}), FakeRow({}), FakeRow({})])
        admin_detach_storyline_refs(conn, storyline_id="1")
        assert len(conn.executed) == 3

    def test_admin_clear_default_storyline_with_exclude(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_clear_default_storyline(conn, character_id="char-1", exclude_id="5")
        sql = conn.executed[0][0]
        assert "is_default = 0" in sql
        assert "id != %s" in sql

    def test_admin_get_storyline_for_impact_returns_storyline_name(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 1, "name": "主线", "is_default": 0}))])
        row = admin_get_storyline_for_impact(conn, storyline_id="1", character_id="char-1")
        assert row["name"] == "主线"

    def test_admin_list_greetings_for_storyline_returns_impacted_greetings(self):
        rows = [FakeRow({"id": 1, "story_phase": "friend", "content": "hi"})]
        conn = FakeSequenceConn([FakeQueryResult(many=rows)])
        result = admin_list_greetings_for_storyline(conn, character_id="char-1", storyline_id="1")
        assert result == rows


class TestPostRuleCRUD:
    def test_admin_list_post_rules(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        admin_list_post_rules(conn, character_id="char-1")
        assert "FROM character_post_rules" in conn.executed[0][0]

    def test_admin_create_post_rule(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 3}))])
        rid = admin_create_post_rule(
            conn, character_id="char-1",
            name="规则A", content="回复时应...", storyline_id=None,
            story_phase="intro", priority=1, is_active=True,
        )
        assert rid == 3

    def test_admin_get_post_rule(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": "1"}))])
        row = admin_get_post_rule(conn, rule_id="1", character_id="char-1")
        assert row is not None

    def test_admin_update_post_rule(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_update_post_rule(
            conn, rule_id="1",
            name="更新规则", content="新内容", storyline_id=None,
            story_phase="climax", priority=2, is_active=False,
        )
        assert "UPDATE character_post_rules" in conn.executed[0][0]

    def test_admin_delete_post_rule(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_delete_post_rule(conn, rule_id="1")
        assert "DELETE FROM character_post_rules" in conn.executed[0][0]


class TestStoryEventCRUD:
    def test_admin_list_story_events(self):
        conn = FakeSequenceConn([FakeQueryResult(many=[])])
        admin_list_story_events(conn, character_id="char-1")
        assert "FROM story_events" in conn.executed[0][0]

    def test_admin_create_story_event(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": 11}))])
        eid = admin_create_story_event(
            conn, character_id="char-1",
            event_id="EV-1", title="事件", description=None,
            trigger_score=50, trigger_custom_key="",
            unlocked_memory_ids="", unlocked_greeting_ids="",
            unlocked_storyline_id=None, event_content="内容",
            sort_order=1, is_active=True,
        )
        assert eid == 11

    def test_admin_get_story_event(self):
        conn = FakeSequenceConn([FakeQueryResult(one=FakeRow({"id": "1"}))])
        row = admin_get_story_event(conn, event_id="1", character_id="char-1")
        assert row is not None

    def test_admin_update_story_event(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_update_story_event(
            conn, event_id="1",
            title="更新事件", description=None, trigger_score=60,
            trigger_custom_key="key1", unlocked_memory_ids="1,2",
            unlocked_greeting_ids="3", unlocked_storyline_id=None,
            event_content="新内容", sort_order=2, is_active=True,
        )
        assert "UPDATE story_events" in conn.executed[0][0]

    def test_admin_delete_story_event(self):
        conn = FakeSequenceConn([FakeRow({})])
        admin_delete_story_event(conn, event_id="1")
        assert "DELETE FROM story_events" in conn.executed[0][0]
