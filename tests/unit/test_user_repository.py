"""user_repository 单元测试 — 验证参数传递、SQL 结构与返回值逻辑。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conftest import FakeRow, FakeSequenceConn


# ── find_user_by_email ────────────────────────────────

class TestFindUserByEmail:
    def test_found(self):
        from repositories.user_repository import find_user_by_email
        row = FakeRow({"id": 1, "email": "a@b.com", "nickname": "test"})
        conn = FakeSequenceConn([row])
        result = find_user_by_email(conn, "a@b.com")
        assert result is row
        sql, params = conn.executed[0]
        assert "LOWER(email) = %s" in sql
        assert params == ("a@b.com",)

    def test_not_found(self):
        from repositories.user_repository import find_user_by_email
        conn = FakeSequenceConn([None])
        result = find_user_by_email(conn, "nobody@b.com")
        assert result is None


# ── check_email_exists ────────────────────────────────

class TestCheckEmailExists:
    def test_exists(self):
        from repositories.user_repository import check_email_exists
        conn = FakeSequenceConn([FakeRow({"?column?": 1})])
        assert check_email_exists(conn, "a@b.com") is True

    def test_not_exists(self):
        from repositories.user_repository import check_email_exists
        conn = FakeSequenceConn([None])
        assert check_email_exists(conn, "nobody@b.com") is False


# ── insert_user ───────────────────────────────────────

class TestInsertUser:
    def test_returns_id_on_success(self):
        from repositories.user_repository import insert_user
        row = FakeRow({"id": 42})
        conn = FakeSequenceConn([row])
        result = insert_user(conn, email="a@b.com", password_hash="h", password_algo="bcrypt", nickname="n")
        assert result == 42
        sql, params = conn.executed[0]
        assert "RETURNING id" in sql
        assert params == ("a@b.com", "h", "bcrypt", "n")
        assert sql.count("%s") == len(params)

    def test_returns_none_on_failure(self):
        from repositories.user_repository import insert_user
        conn = FakeSequenceConn([None])
        result = insert_user(conn, email="a@b.com", password_hash="h", password_algo="bcrypt", nickname="n")
        assert result is None


# ── update_password ──────────────────────────────────

class TestUpdatePassword:
    def test_sets_bcrypt_algo(self):
        from repositories.user_repository import update_password
        conn = FakeSequenceConn([FakeRow()])
        update_password(conn, user_id=1, password_hash="new_hash")
        sql, params = conn.executed[0]
        assert "password_algo = 'bcrypt'" in sql
        assert params == ("new_hash", 1)


# ── get_user_avatar_url / update_user_avatar ────────

class TestAvatarOperations:
    def test_get_avatar_found(self):
        from repositories.user_repository import get_user_avatar_url
        conn = FakeSequenceConn([FakeRow({"avatar_url": "https://img.test/a.jpg"})])
        assert get_user_avatar_url(conn, 1) == "https://img.test/a.jpg"

    def test_get_avatar_not_found(self):
        from repositories.user_repository import get_user_avatar_url
        conn = FakeSequenceConn([None])
        assert get_user_avatar_url(conn, 999) is None

    def test_update_avatar_params(self):
        from repositories.user_repository import update_user_avatar
        conn = FakeSequenceConn([FakeRow()])
        update_user_avatar(conn, user_id=1, avatar_url="https://new.img/a.jpg")
        sql, params = conn.executed[0]
        assert params == ("https://new.img/a.jpg", 1)


# ── admin: get_user_by_id / get_user_id_email ───────

class TestAdminGetUser:
    def test_get_user_by_id_found(self):
        from repositories.user_repository import get_user_by_id
        row = FakeRow({"id": 1, "email": "a@b.com"})
        conn = FakeSequenceConn([row])
        result = get_user_by_id(conn, 1)
        assert result is row

    def test_get_user_id_email_not_found(self):
        from repositories.user_repository import get_user_id_email
        conn = FakeSequenceConn([None])
        result = get_user_id_email(conn, 999)
        assert result is None


# ── admin: update_user_fields ───────────────────────

class TestUpdateUserFields:
    def test_dynamic_set_clause(self):
        from repositories.user_repository import update_user_fields
        conn = FakeSequenceConn([FakeRow()])
        update_user_fields(conn, user_id=1, updates={"nickname": "new", "email": "vip@test.com"})
        sql, params = conn.executed[0]
        assert "nickname = %s" in sql
        assert "email = %s" in sql
        assert "updated_at = now()" in sql
        # 源码使用 list(updates.values()) + [user_id]，参数为 list
        assert list(params) == ["new", "vip@test.com", 1]


# ── admin: update_user_plan ─────────────────────────

class TestUpdateUserPlan:
    def test_params_alignment(self):
        from repositories.user_repository import update_user_plan
        conn = FakeSequenceConn([FakeRow()])
        expires = datetime(2026, 6, 1, tzinfo=timezone.utc)
        update_user_plan(conn, user_id=1, plan_type="vip", plan_expires_at=expires)
        sql, params = conn.executed[0]
        assert params == ("vip", expires, 1)
        assert sql.count("%s") == len(params)


# ── admin: delete_user_cascade ─────────────────────

class TestDeleteUserCascade:
    def test_deletes_in_order(self):
        from repositories.user_repository import delete_user_cascade
        conn = FakeSequenceConn([FakeRow()] * 10)
        delete_user_cascade(conn, user_id=1)
        sqls = [sql for sql, _ in conn.executed]
        # 验证删除顺序：先子表后主表
        table_order = []
        for sql in sqls:
            for table in ["ai_request_logs", "chat_messages", "chat_summaries",
                          "user_character_profiles", "character_states", "user_story_progress",
                          "membership_orders", "auth_tokens", "password_reset_codes", "users"]:
                if f"DELETE FROM {table}" in sql:
                    table_order.append(table)
        assert table_order.index("users") > table_order.index("chat_messages")
        assert len(conn.executed) == 10
