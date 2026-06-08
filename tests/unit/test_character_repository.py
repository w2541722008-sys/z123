"""character_repository 单元测试 — 验证参数传递与返回值逻辑。"""
from __future__ import annotations

import pytest

from conftest import FakeRow, FakeSequenceConn


# ── get_user_overrides_map ───────────────────────────────

class TestGetUserOverridesMap:
    def test_no_user_id_returns_empty(self):
        from repositories.character_repository import get_user_overrides_map
        conn = FakeSequenceConn([])
        result = get_user_overrides_map(conn, user_id=None)
        assert result == {}
        assert len(conn.executed) == 0

    def test_zero_user_id_returns_empty(self):
        from repositories.character_repository import get_user_overrides_map
        conn = FakeSequenceConn([])
        result = get_user_overrides_map(conn, user_id=0)
        assert result == {}

    def test_found_builds_map(self):
        from repositories.character_repository import get_user_overrides_map
        rows = [
            FakeRow({"character_id": "char1", "remark": "r1", "custom_signature": "s1"}),
            FakeRow({"character_id": "char2", "remark": None, "custom_signature": None}),
        ]
        conn = FakeSequenceConn([rows])
        result = get_user_overrides_map(conn, user_id=1)
        assert result == {"char1": ("r1", "s1"), "char2": ("", "")}


# ── get_user_overrides ──────────────────────────────────

class TestGetUserOverrides:
    def test_no_user_id_returns_empty_tuple(self):
        from repositories.character_repository import get_user_overrides
        conn = FakeSequenceConn([])
        result = get_user_overrides(conn, user_id=None, character_id="c1")
        assert result == ("", "")

    def test_not_found_returns_empty_tuple(self):
        from repositories.character_repository import get_user_overrides
        conn = FakeSequenceConn([None])
        result = get_user_overrides(conn, user_id=1, character_id="c1")
        assert result == ("", "")

    def test_found_returns_values(self):
        from repositories.character_repository import get_user_overrides
        row = FakeRow({"remark": "hello", "custom_signature": "sig"})
        conn = FakeSequenceConn([row])
        result = get_user_overrides(conn, user_id=1, character_id="c1")
        assert result == ("hello", "sig")


# ── list_visible_characters ────────────────────────────

class TestListVisibleCharacters:
    def test_returns_dict_list(self):
        from repositories.character_repository import list_visible_characters
        rows = [FakeRow({"id": "c1", "name": "Test"})]
        conn = FakeSequenceConn([rows])
        result = list_visible_characters(conn)
        assert len(result) == 1
        assert result[0]["id"] == "c1"
        sql = conn.executed[0][0]
        assert "is_visible = 1" in sql


# ── get_character_by_id ────────────────────────────────

class TestGetCharacterById:
    def test_found(self):
        from repositories.character_repository import get_character_by_id
        row = FakeRow({"id": "c1", "name": "Test"})
        conn = FakeSequenceConn([row])
        result = get_character_by_id(conn, "c1")
        assert result is row

    def test_not_found(self):
        from repositories.character_repository import get_character_by_id
        conn = FakeSequenceConn([None])
        result = get_character_by_id(conn, "nonexistent")
        assert result is None


# ── upsert_user_profile ────────────────────────────────

class TestUpsertUserProfile:
    def test_params_alignment(self):
        from repositories.character_repository import upsert_user_profile
        conn = FakeSequenceConn([FakeRow()])
        upsert_user_profile(conn, user_id=1, character_id="c1", remark="r", custom_signature="s")
        sql, params = conn.executed[0]
        assert "ON CONFLICT" in sql
        assert params == (1, "c1", "r", "s")
        assert sql.count("%s") == len(params)


# ── get_avatar_url / get_cover_urls ────────────────────

class TestAvatarAndCover:
    def test_get_avatar_found(self):
        from repositories.character_repository import get_avatar_url
        row = FakeRow({"avatar_url": "https://img.test/a.jpg"})
        conn = FakeSequenceConn([row])
        assert get_avatar_url(conn, "c1") == "https://img.test/a.jpg"

    def test_get_avatar_not_found(self):
        from repositories.character_repository import get_avatar_url
        conn = FakeSequenceConn([None])
        assert get_avatar_url(conn, "c1") is None

    def test_get_cover_urls_found(self):
        from repositories.character_repository import get_cover_urls
        row = FakeRow({"avatar_url": "av", "cover_url": "cv"})
        conn = FakeSequenceConn([row])
        assert get_cover_urls(conn, "c1") == ("av", "cv")

    def test_get_cover_urls_not_found(self):
        from repositories.character_repository import get_cover_urls
        conn = FakeSequenceConn([None])
        assert get_cover_urls(conn, "c1") == (None, None)


# ── delete_character_cascade ───────────────────────────

class TestDeleteCharacterCascade:
    def test_found_deletes_all_and_returns_name(self):
        from repositories.character_repository import delete_character_cascade
        row = FakeRow({"id": "c1", "name": "TestChar"})
        # 12 个 DELETE + 1 个 SELECT = 13 个结果
        conn = FakeSequenceConn([row] + [FakeRow()] * 12)
        result = delete_character_cascade(conn, "c1")
        assert result == {"id": "c1", "name": "TestChar"}
        # 验证 DELETE 顺序
        delete_sqls = [sql for sql, _ in conn.executed[1:]]
        assert any("user_character_profiles" in s for s in delete_sqls)
        assert any("character_states" in s for s in delete_sqls)
        assert any("characters" in s for s in delete_sqls)

    def test_not_found_returns_none(self):
        from repositories.character_repository import delete_character_cascade
        conn = FakeSequenceConn([None])
        result = delete_character_cascade(conn, "nonexistent")
        assert result is None
        # 不应执行任何 DELETE
        assert len(conn.executed) == 1


class TestUpdateCharacterFields:
    def test_allows_life_profile_json(self):
        from repositories.character_repository import update_character_fields
        conn = FakeSequenceConn([FakeRow()])

        update_character_fields(conn, "luna", {"life_profile_json": '{"basic_info":"林深"}'})

        sql, params = conn.executed[0]
        assert "life_profile_json = %s" in sql
        assert params == ['{"basic_info":"林深"}', "luna"]

    def test_rejects_unknown_field(self):
        from repositories.character_repository import update_character_fields
        conn = FakeSequenceConn([])

        with pytest.raises(ValueError):
            update_character_fields(conn, "luna", {"drop table users": "x"})
