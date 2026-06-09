"""
Cursor 生命周期集成测试

验证 psycopg2 中 commit() 关闭 cursor 的行为不会被违反。
这是 commit-before-fetchone bug 的回归测试。

核心规则：
  - conn.commit() 后 cursor 被关闭，不能再 fetchone()
  - 必须先 fetchone() 获取数据，再 commit()
"""

import pytest

from core.auth import CurrentUser, get_admin_user
from tests.support.app import override_db
from tests.support.db import FakeQueryResult, FakeSequenceConn


class TestCursorLifecycle:
    """验证所有使用 RETURNING id 的 INSERT 端点
    都在 commit() 之前调用 fetchone()。"""

    def test_create_memory_fetchone_before_commit(self, admin_client):
        """create_memory 端点：fetchone() 必须在 commit() 之前。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 42}),
            FakeQueryResult(rowcount=1),
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/memories", json={
                "keywords": "test", "trigger_logic": "any", "content": "c",
                "category_id": None, "position": "before", "priority": 100,
                "is_active": True, "comment": "",
            })
        assert response.status_code == 200
        assert response.json()["id"] == 42
        # 验证 execute 次数正确（character check + INSERT + audit log）
        assert len(conn.executed) == 3

    def test_create_memory_category_fetchone_before_commit(self, admin_client):
        """create_memory_category 端点。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 5}),
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/memory-categories", json={
                "name": "分类", "description": "", "color": "#FF0000", "sort_order": 0,
            })
        assert response.status_code == 200
        assert response.json()["id"] == 5

    def test_create_greeting_fetchone_before_commit(self, admin_client):
        """create_greeting 端点。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 10}),
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/greetings", json={
                "story_phase": "stranger", "mood": "neutral", "content": "你好",
                "storyline_id": None, "priority": 100, "is_active": True,
            })
        assert response.status_code == 200
        assert response.json()["id"] == 10

    def test_create_storyline_fetchone_before_commit(self, admin_client):
        """create_storyline 端点。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 7}),
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/storylines", json={
                "name": "主线", "description": "", "unlock_score": 0,
                "is_default": 0, "is_active": 1, "sort_order": 0,
            })
        assert response.status_code == 200
        assert response.json()["id"] == 7

    def test_create_post_rule_fetchone_before_commit(self, admin_client):
        """create_post_rule 端点。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 3}),
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/post-rules", json={
                "name": "规则", "content": "内容",
                "storyline_id": None, "story_phase": "", "priority": 100, "is_active": True,
            })
        assert response.status_code == 200
        assert response.json()["id"] == 3

    def test_create_story_event_fetchone_before_commit(self, admin_client):
        """create_story_event 端点。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 8}),
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/story-events", json={
                "title": "事件", "description": "", "trigger_score": 50,
                "unlocked_memory_ids": "", "unlocked_greeting_ids": "",
                "unlocked_storyline_id": None, "event_content": "",
                "sort_order": 0, "is_active": True,
            })
        assert response.status_code == 200
        assert response.json()["id"] == 8


class TestCommitRollbackOrder:
    """验证 FakeSequenceConn 的 commit/rollback 顺序记录正确。"""

    def test_update_memory_commits_after_execute(self, admin_client):
        """update 端点：commit 应在所有 execute 之后。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": 1}),  # SELECT existing
            FakeQueryResult(rowcount=1),      # UPDATE
        ])
        with override_db(app, conn):
            response = client.put("/api/admin/character/luna/memories/1", json={
                "keywords": "test", "trigger_logic": "any", "content": "updated",
                "category_id": None, "position": "before", "priority": 100,
                "is_active": True, "comment": "",
            })
        assert response.status_code == 200
        assert conn.committed is True

    def test_delete_memory_commits_after_execute(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": 1}),  # SELECT existing
            FakeQueryResult(rowcount=1),      # DELETE
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/character/luna/memories/1")
        assert response.status_code == 200
        assert conn.committed is True
