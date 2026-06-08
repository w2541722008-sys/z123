"""character_repository 集成测试 — 真实 SQL 执行验证。

运行条件：需要 TEST_DATABASE_URL + 测试数据库中已有角色数据。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestListVisibleCharacters:
    def test_returns_only_visible(self, db_conn):
        from repositories.character_repository import list_visible_characters
        result = list_visible_characters(db_conn)
        assert isinstance(result, list)
        # 所有返回的角色都应该是 is_visible=1
        for char in result:
            assert char.get("is_visible") == 1 or char.get("is_visible") is True

    def test_ordered_by_priority(self, db_conn):
        from repositories.character_repository import list_visible_characters
        result = list_visible_characters(db_conn)
        if len(result) > 1:
            priorities = [c.get("home_priority", 0) for c in result]
            assert priorities == sorted(priorities)


class TestGetCharacterById:
    def test_found(self, db_conn):
        """如果测试数据库有角色，能正确查询。"""
        from repositories.character_repository import list_visible_characters, get_character_by_id
        chars = list_visible_characters(db_conn)
        if not chars:
            pytest.skip("No characters in test DB")
        char_id = chars[0]["id"]
        result = get_character_by_id(db_conn, char_id)
        assert result is not None
        assert result["id"] == char_id

    def test_not_found(self, db_conn):
        from repositories.character_repository import get_character_by_id
        result = get_character_by_id(db_conn, "nonexistent_char_xyz")
        assert result is None


class TestGetAvatarUrl:
    def test_returns_db_value(self, db_conn):
        from repositories.character_repository import list_visible_characters, get_avatar_url
        chars = list_visible_characters(db_conn)
        if not chars:
            pytest.skip("No characters in test DB")
        char_id = chars[0]["id"]
        # 直接从 DB 获取真实值作为预期
        row = db_conn.execute(
            "SELECT avatar_url FROM characters WHERE id = %s", (char_id,)
        ).fetchone()
        expected = row["avatar_url"] if row else None
        result = get_avatar_url(db_conn, char_id)
        assert result == expected

    def test_not_found(self, db_conn):
        from repositories.character_repository import get_avatar_url
        result = get_avatar_url(db_conn, "nonexistent_char_xyz")
        assert result is None
