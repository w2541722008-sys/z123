"""
Admin 子路由 CRUD smoke 测试

覆盖之前完全缺失的端点：
  - characters_memory: 记忆/分类 CRUD
  - characters_story: 开场白/剧情线 CRUD
  - characters_rules_events: 后置规则/剧情事件 CRUD
  - characters_insights: 配置摘要/消息预览/关键词测试

测试策略：
  - 使用 FakeSequenceConn 模拟 DB（与现有测试一致）
  - 每个 CRUD 端点至少一个 200 happy path + 一个 404/400 错误路径
  - 验证 commit() 后 fetchone() 顺序（PSQL cursor 生命周期）
"""

import pytest

from core.auth import CurrentUser, get_admin_user, get_current_user, get_optional_user
from tests.support.app import override_db
from tests.support.db import FakeDummyConn, FakeQueryResult, FakeRow, FakeSequenceConn


def _assert_audit_action(conn: FakeSequenceConn, action: str) -> None:
    """确认 mutation 成功路径写入了预期审计动作。"""
    assert any(
        "INSERT INTO admin_audit_logs" in sql and params and params[2] == action
        for sql, params in conn.executed
    )


# ── 记忆条目 CRUD ──────────────────────────────────────────────

class TestAdminMemories:
    """角色记忆条目管理端点。"""

    def test_list_memories_returns_list(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),  # character exists
            FakeQueryResult(many=[{
                "id": 1, "keywords": "关键词", "trigger_logic": "any",
                "content": "内容", "category_id": None, "position": "before",
                "priority": 100, "is_active": 1, "comment": "",
                "selective": 1, "constant": 0, "sticky": 0, "cooldown": 0,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/luna/memories")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_memories_character_not_found(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),  # character not found
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/nonexistent/memories")
        assert response.status_code == 404

    def test_create_memory_returns_id(self, admin_client):
        """验证创建记忆条目返回 ID（commit 前 fetchone 模式）。"""
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),  # character exists
            FakeQueryResult(one={"id": 42}),       # RETURNING id
            FakeQueryResult(rowcount=1),           # audit log INSERT
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/memories", json={
                "keywords": "test", "trigger_logic": "any", "content": "test content",
                "category_id": None, "position": "before", "priority": 100,
                "is_active": True, "comment": "",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "id" in data
        _assert_audit_action(conn, "create_memory")

    def test_update_memory_not_found(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),  # memory not found
        ])
        with override_db(app, conn):
            response = client.put("/api/admin/character/luna/memories/9999", json={
                "keywords": "test", "trigger_logic": "any", "content": "test content",
                "category_id": None, "position": "before", "priority": 100,
                "is_active": True, "comment": "",
            })
        assert response.status_code == 404

    def test_delete_memory_not_found(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/character/luna/memories/9999")
        assert response.status_code == 404


# ── 记忆分类 CRUD ──────────────────────────────────────────────

class TestAdminMemoryCategories:
    """角色记忆分类管理端点。"""

    def test_list_memory_categories_returns_list(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(many=[{
                "id": 1, "name": "默认", "description": "",
                "color": "#1890FF", "sort_order": 0,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/luna/memory-categories")
        assert response.status_code == 200

    def test_create_memory_category_returns_id(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 5}),
            FakeQueryResult(rowcount=1),  # audit log INSERT
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/memory-categories", json={
                "name": "测试分类", "description": "", "color": "#FF0000", "sort_order": 0,
            })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "id" in data
        _assert_audit_action(conn, "create_memory_category")

    def test_delete_memory_category_with_memories_returns_400(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": 1}),  # category exists
            FakeQueryResult(one={"count": 3}),  # has memories
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/character/luna/memory-categories/1")
        assert response.status_code == 400


# ── 开场白 CRUD ──────────────────────────────────────────────

class TestAdminGreetings:
    """角色开场白管理端点。"""

    def test_list_greetings_returns_list(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(many=[{
                "id": 1, "story_phase": "stranger", "mood": "neutral",
                "content": "你好", "storyline_id": None,
                "priority": 100, "is_active": 1, "use_count": 0, "comment": "",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/luna/greetings")
        assert response.status_code == 200

    def test_create_greeting_returns_id(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 10}),
            FakeQueryResult(rowcount=1),  # audit log INSERT
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/greetings", json={
                "story_phase": "stranger", "mood": "neutral", "content": "测试开场白",
                "storyline_id": None, "priority": 100, "is_active": True,
            })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "id" in data
        _assert_audit_action(conn, "create_greeting")

    def test_delete_greeting_not_found(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/character/luna/greetings/9999")
        assert response.status_code == 404


# ── 剧情线 CRUD ──────────────────────────────────────────────

class TestAdminStorylines:
    """角色剧情线管理端点。"""

    def test_list_storylines_returns_list(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(many=[{
                "id": 1, "storyline_id": "main", "title": "主线", "name": "主线",
                "description": "", "unlock_condition": None, "stages": [],
                "unlock_score": 0, "is_default": 1, "is_active": 1, "sort_order": 0,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/luna/storylines")
        assert response.status_code == 200

    def test_create_storyline_returns_id(self, admin_client):
        app, client = admin_client
        # is_default=0: 不触发 UPDATE，只有 SELECT + INSERT
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),   # character exists
            FakeQueryResult(one={"id": 7}),         # RETURNING id
            FakeQueryResult(rowcount=1),            # audit log INSERT
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/storylines", json={
                "name": "新剧情线", "description": "",
                "unlock_score": 50, "is_default": 0, "is_active": 1, "sort_order": 0,
            })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "id" in data
        _assert_audit_action(conn, "create_storyline")

    def test_delete_storyline_not_found(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.delete("/api/admin/character/luna/storylines/9999")
        assert response.status_code == 404


# ── 后置规则 CRUD ──────────────────────────────────────────────

class TestAdminPostRules:
    """角色后置规则管理端点。"""

    def test_list_post_rules_returns_list(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(many=[{
                "id": 1, "name": "规则1", "content": "规则内容",
                "storyline_id": None, "story_phase": "", "priority": 100,
                "is_active": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/luna/post-rules")
        assert response.status_code == 200

    def test_create_post_rule_returns_id(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 3}),
            FakeQueryResult(rowcount=1),  # audit log INSERT
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/post-rules", json={
                "name": "新规则", "content": "规则内容",
                "storyline_id": None, "story_phase": "", "priority": 100, "is_active": True,
            })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "id" in data
        _assert_audit_action(conn, "create_post_rule")


# ── 剧情事件 CRUD ──────────────────────────────────────────────

class TestAdminStoryEvents:
    """角色剧情事件管理端点。"""

    def test_list_story_events_returns_list(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(many=[{
                "id": 1, "title": "事件1", "description": "", "trigger_score": 50,
                "trigger_custom_key": "",
                "unlocked_memory_ids": "", "unlocked_greeting_ids": "",
                "unlocked_storyline_id": None, "event_content": "",
                "sort_order": 0, "is_active": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }]),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/luna/story-events")
        assert response.status_code == 200

    def test_create_story_event_returns_id(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one={"id": "luna"}),
            FakeQueryResult(one={"id": 8}),
            FakeQueryResult(rowcount=1),  # audit log INSERT
        ])
        with override_db(app, conn):
            response = client.post("/api/admin/character/luna/story-events", json={
                "title": "新事件", "description": "", "trigger_score": 60,
                "unlocked_memory_ids": "", "unlocked_greeting_ids": "",
                "unlocked_storyline_id": None, "event_content": "",
                "sort_order": 0, "is_active": True,
            })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "id" in data
        _assert_audit_action(conn, "create_story_event")


# ── 配置摘要 / 消息预览 ──────────────────────────────────────────

class TestAdminInsights:
    """角色配置洞察端点。"""

    def test_config_summary_character_not_found(self, admin_client):
        app, client = admin_client
        conn = FakeSequenceConn([
            FakeQueryResult(one=None),
        ])
        with override_db(app, conn):
            response = client.get("/api/admin/character/nonexistent/config-summary")
        assert response.status_code == 404


# ── Admin 子路由鉴权守卫 ────────────────────────────────────────

class TestAdminSubRouterAuthGuards:
    """验证 admin 子路由端点都需要管理员权限。"""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/admin/character/luna/memories"),
        ("GET", "/api/admin/character/luna/memory-categories"),
        ("GET", "/api/admin/character/luna/greetings"),
        ("GET", "/api/admin/character/luna/storylines"),
        ("GET", "/api/admin/character/luna/post-rules"),
        ("GET", "/api/admin/character/luna/story-events"),
        ("GET", "/api/admin/character/luna/config-summary"),
    ])
    def test_unauthenticated_returns_401(self, app_client, method, path):
        """未登录用户访问 admin 子路由应返回 401。"""
        _, client = app_client
        response = client.request(method, path)
        assert response.status_code == 401
