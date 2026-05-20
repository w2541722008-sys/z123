"""角色相关的数据访问层。"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


def get_user_overrides_map(
    conn: ConnType, user_id: int | str | None
) -> dict[str, tuple[str, str]]:
    """批量读取用户对角色的私有备注和签名，避免列表接口产生 N+1 查询。"""
    if not user_id:
        return {}

    rows = conn.execute(
        """
        SELECT character_id, remark, custom_signature
        FROM user_character_profiles
        WHERE user_id = %s
        """,
        (user_id,),
    ).fetchall()
    return {
        row["character_id"]: (row["remark"] or "", row["custom_signature"] or "")
        for row in rows
    }


def get_user_overrides(
    conn: ConnType,
    user_id: int | str | None,
    character_id: str,
) -> tuple[str, str]:
    """读取用户对单个角色的私有备注和签名。"""
    if not user_id:
        return "", ""

    row = conn.execute(
        """
        SELECT remark, custom_signature
        FROM user_character_profiles
        WHERE user_id = %s AND character_id = %s
        """,
        (user_id, character_id),
    ).fetchone()
    if not row:
        return "", ""
    return (row["remark"] or "", row["custom_signature"] or "")


def list_visible_characters(conn: ConnType) -> list[dict[str, Any]]:
    """获取所有可见角色列表（按 home_priority 排序）。"""
    rows = conn.execute(
        """
        SELECT id, name, abbr, subtitle, avatar_url, cover_url, description, opening_message, tags,
               card_type, home_priority, is_visible, required_plan
        FROM characters
        WHERE is_visible = 1
        ORDER BY home_priority ASC, sort_order ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_character_by_id(conn: ConnType, character_id: str) -> dict[str, Any] | None:
    """按 ID 获取角色行。"""
    return conn.execute(
        """
        SELECT id, name, abbr, subtitle, avatar_url, cover_url, description,
               opening_message, tags, card_type, home_priority, required_plan,
               structured_asset_json
        FROM characters
        WHERE id = %s
        """,
        (character_id,),
    ).fetchone()


def upsert_user_profile(
    conn: ConnType,
    *,
    user_id: int | str,
    character_id: str,
    remark: str,
    custom_signature: str,
) -> None:
    """插入或更新用户对角色的个性化配置。created_at/updated_at 由 DB 管理。"""
    conn.execute(
        """
        INSERT INTO user_character_profiles(user_id, character_id, remark, custom_signature)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT(user_id, character_id) DO UPDATE SET
            remark = excluded.remark,
            custom_signature = excluded.custom_signature,
            updated_at = now()
        """,
        (user_id, character_id, remark, custom_signature),
    )


def get_active_greetings(
    conn: ConnType, character_id: str
) -> list[dict[str, Any]]:
    """获取角色的活跃开场白列表。"""
    return conn.execute(
        """
        SELECT g.id, g.content, g.story_phase, g.mood, g.storyline_id,
               COALESCE(s.name, '') AS storyline_name
        FROM character_greetings g
        LEFT JOIN character_storylines s ON s.id = g.storyline_id
        WHERE g.character_id = %s AND g.is_active = 1 AND g.story_phase = 'stranger'
        ORDER BY g.priority ASC, g.id ASC
        """,
        (character_id,),
    ).fetchall()


def get_avatar_url(conn: ConnType, character_id: str) -> str | None:
    """获取角色头像 URL。"""
    row = conn.execute(
        "SELECT avatar_url FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    return row["avatar_url"] if row else None


def get_cover_urls(conn: ConnType, character_id: str) -> tuple[str | None, str | None]:
    """获取角色封面和头像 URL。"""
    row = conn.execute(
        "SELECT avatar_url, cover_url FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    if not row:
        return None, None
    return row["avatar_url"], row["cover_url"]


# ============================================================
# Admin 相关
# ============================================================

def admin_list_all_characters(conn: ConnType) -> list[dict[str, Any]]:
    """管理后台：获取所有角色列表（含不可见）。"""
    return conn.execute(
        """
        SELECT id, name, abbr, subtitle, avatar_url, description, tags,
               card_type, required_plan, is_visible, home_priority, sort_order
        FROM characters
        ORDER BY sort_order ASC, id ASC
        """
    ).fetchall()


def get_character_full(conn: ConnType, character_id: str) -> dict[str, Any] | None:
    """管理后台：获取角色完整信息。"""
    return conn.execute(
        "SELECT * FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()


def check_character_exists(conn: ConnType, character_id: str) -> dict[str, Any] | None:
    """检查角色 ID 是否已存在。"""
    return conn.execute(
        "SELECT id FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()


def insert_character(conn: ConnType, values: tuple) -> None:
    """管理后台：创建角色。created_at/updated_at 由 DB DEFAULT now() 填充。"""
    conn.execute(
        """
        INSERT INTO characters (
            id, name, abbr, subtitle, avatar_url, cover_url, description,
            system_prompt, opening_message, tags,
            card_type, required_plan, home_priority, is_visible, sort_order,
            mock_reply_style, asset_type, source_kind, source_path,
            embedded_format, raw_card_json, structured_asset_json,
            import_diagnostics, import_locked, affection_enabled, affection_rules_json
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        values,
    )


def update_character_fields(
    conn: ConnType, character_id: str, updates: dict[str, Any]
) -> None:
    """管理后台：按白名单更新角色字段。updated_at 自动更新。"""
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    conn.execute(
        f"UPDATE characters SET {set_clause}, updated_at = now() WHERE id = %s",
        list(updates.values()) + [character_id],
    )


def update_character_json_fields(
    conn: ConnType,
    character_id: str,
    structured_json: Any,
    runtime_json: Any,
) -> None:
    """管理后台：更新角色 structured_asset_json 和 runtime_cache_json。

    参数为 Python 对象（dict），psycopg2 自动序列化为 jsonb。
    """
    conn.execute(
        "UPDATE characters SET structured_asset_json = %s, runtime_cache_json = %s, updated_at = now() WHERE id = %s",
        (structured_json, runtime_json, character_id),
    )


def get_character_structured_json(conn: ConnType, character_id: str) -> dict[str, Any] | None:
    """获取角色的 structured_asset_json 和 runtime_cache_json。"""
    return conn.execute(
        "SELECT id, structured_asset_json FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()


def delete_character_cascade(conn: ConnType, character_id: str) -> dict[str, Any] | None:
    """级联删除角色及所有关联数据。返回被删除角色的 name。"""
    row = conn.execute(
        "SELECT id, name FROM characters WHERE id = %s",
        (character_id,),
    ).fetchone()
    if not row:
        return None

    conn.execute("DELETE FROM user_character_profiles WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM character_states WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM character_greetings WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM character_memories WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM memory_categories WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM character_post_rules WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM story_events WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM character_storylines WHERE character_id = %s", (character_id,))
    conn.execute("DELETE FROM characters WHERE id = %s", (character_id,))
    return dict(row)


# ============================================================
# Admin 洞察/摘要
# ============================================================

def get_character_config_fields(conn: ConnType, character_id: str) -> dict[str, Any] | None:
    """获取角色配置摘要所需的字段子集。"""
    return conn.execute(
        """
        SELECT id, name, subtitle, opening_message, system_prompt, is_visible,
               card_type,
               affection_enabled, affection_rules_json, structured_asset_json
        FROM characters
        WHERE id = %s
        """,
        (character_id,),
    ).fetchone()


def get_character_asset_stats(conn: ConnType, character_id: str) -> dict[str, int]:
    """返回角色各资产表的总数和活跃数（单次查询聚合，避免 N 次 COUNT）。"""
    rows = conn.execute(
        """
        SELECT
            'memory' AS kind, COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END), 0) AS active
        FROM character_memories WHERE character_id = %s
        UNION ALL
        SELECT 'category', COUNT(*), 0 FROM memory_categories WHERE character_id = %s
        UNION ALL
        SELECT 'greeting', COUNT(*),
            COALESCE(SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END), 0)
        FROM character_greetings WHERE character_id = %s
        UNION ALL
        SELECT 'storyline', COUNT(*),
            COALESCE(SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END), 0)
        FROM character_storylines WHERE character_id = %s
        UNION ALL
        SELECT 'post_rule', COUNT(*),
            COALESCE(SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END), 0)
        FROM character_post_rules WHERE character_id = %s
        UNION ALL
        SELECT 'story_event', COUNT(*),
            COALESCE(SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END), 0)
        FROM story_events WHERE character_id = %s
        """,
        (character_id,) * 6,
    ).fetchall()
    stats: dict[str, int] = {}
    for row in rows:
        stats[row["kind"] + "_count"] = row["total"]
        stats[row["kind"] + "_active"] = row["active"]
    return stats


def get_greeting_phase_coverage(conn: ConnType, character_id: str) -> int:
    """返回活跃开场白覆盖的阶段数。"""
    row = conn.execute(
        "SELECT COUNT(DISTINCT story_phase) AS cnt FROM character_greetings WHERE character_id = %s AND is_active = 1",
        (character_id,),
    ).fetchone()
    return row["cnt"] if row else 0


def get_default_storyline_id(conn: ConnType, character_id: str) -> int | None:
    """获取默认剧情线 ID。"""
    row = conn.execute(
        "SELECT id FROM character_storylines WHERE character_id = %s AND is_default = 1 ORDER BY id ASC LIMIT 1",
        (character_id,),
    ).fetchone()
    return row["id"] if row else None


def get_active_greeting_count(conn: ConnType, character_id: str) -> int:
    """获取活跃开场白数量。"""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM character_greetings WHERE character_id = %s AND is_active = 1",
        (character_id,),
    ).fetchone()
    return row["cnt"] if row else 0


def get_story_events_for_validation(conn: ConnType, character_id: str) -> list[dict[str, Any]]:
    """获取剧情事件用于解锁引用校验。"""
    return conn.execute(
        "SELECT id, unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id, event_content FROM story_events WHERE character_id = %s",
        (character_id,),
    ).fetchall()


def get_valid_asset_ids(conn: ConnType, character_id: str) -> dict[str, set[int]]:
    """返回角色所有有效的记忆/开场白/剧情线 ID 集合（用于验证引用）。"""
    memories = {r["id"] for r in conn.execute("SELECT id FROM character_memories WHERE character_id = %s", (character_id,)).fetchall()}
    greetings = {r["id"] for r in conn.execute("SELECT id FROM character_greetings WHERE character_id = %s", (character_id,)).fetchall()}
    storylines = {r["id"] for r in conn.execute("SELECT id FROM character_storylines WHERE character_id = %s", (character_id,)).fetchall()}
    return {"memories": memories, "greetings": greetings, "storylines": storylines}


def get_asset_max_updated_at(conn: ConnType, character_id: str) -> str | None:
    """返回角色所有资产表的最近更新时间。"""
    row = conn.execute(
        """
        SELECT MAX(ts) AS max_ts FROM (
            SELECT MAX(updated_at) AS ts FROM character_memories WHERE character_id = %s
            UNION ALL SELECT MAX(updated_at) FROM memory_categories WHERE character_id = %s
            UNION ALL SELECT MAX(updated_at) FROM character_greetings WHERE character_id = %s
            UNION ALL SELECT MAX(updated_at) FROM character_storylines WHERE character_id = %s
            UNION ALL SELECT MAX(updated_at) FROM character_post_rules WHERE character_id = %s
            UNION ALL SELECT MAX(updated_at) FROM story_events WHERE character_id = %s
        ) t
        """,
        (character_id,) * 6,
    ).fetchone()
    return str(row["max_ts"]) if row and row["max_ts"] else None
