"""用户相关的数据访问层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.database import ConnType


def find_user_by_email(conn: ConnType, normalized_email: str) -> dict[str, Any] | None:
    """按邮箱（小写归一化）查找用户。"""
    return conn.execute(
        """
        SELECT id, email, password_hash, password_algo, COALESCE(nickname, '') AS nickname,
               COALESCE(plan_type, 'free') AS plan_type,
               plan_expires_at,
               avatar_url
        FROM users WHERE LOWER(email) = %s
        """,
        (normalized_email,),
    ).fetchone()


def check_email_exists(conn: ConnType, normalized_email: str) -> bool:
    """检查邮箱是否已注册。"""
    row = conn.execute(
        "SELECT 1 FROM users WHERE LOWER(email) = %s",
        (normalized_email,),
    ).fetchone()
    return row is not None


def insert_user(
    conn: ConnType,
    *,
    email: str,
    password_hash: str,
    password_algo: str,
    nickname: str,
) -> int | None:
    """插入新用户并返回 ID。created_at/updated_at 由 DB DEFAULT now() 填充。"""
    cur = conn.execute(
        """
        INSERT INTO users(email, password_hash, password_algo, nickname)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (email, password_hash, password_algo, nickname),
    )
    row = cur.fetchone()
    return row.get("id") if row else None


def update_password(conn: ConnType, user_id: int | str, password_hash: str) -> None:
    """更新用户密码为 bcrypt。"""
    conn.execute(
        "UPDATE users SET password_hash = %s, password_algo = 'bcrypt', updated_at = now() WHERE id = %s",
        (password_hash, user_id),
    )


def get_user_avatar_url(conn: ConnType, user_id: int | str) -> str | None:
    """获取用户头像 URL。"""
    row = conn.execute(
        "SELECT avatar_url FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()
    return row["avatar_url"] if row else None


def update_user_avatar(conn: ConnType, user_id: int | str, avatar_url: str) -> None:
    """更新用户头像 URL。"""
    conn.execute(
        "UPDATE users SET avatar_url = %s, updated_at = now() WHERE id = %s",
        (avatar_url, user_id),
    )


# ============================================================
# Admin 相关
# ============================================================


def get_user_by_id(conn: ConnType, user_id: int | str) -> dict[str, Any] | None:
    """按 ID 获取用户完整信息。"""
    return conn.execute(
        "SELECT * FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()


def get_user_id_email(conn: ConnType, user_id: int | str) -> dict[str, Any] | None:
    """按 ID 获取用户 id 和 email（用于校验存在性）。"""
    return conn.execute(
        "SELECT id, email FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()


def get_user_id_email_nickname(
    conn: ConnType, user_id: int | str
) -> dict[str, Any] | None:
    """按 ID 获取用户 id、email、nickname。"""
    return conn.execute(
        "SELECT id, email, COALESCE(nickname, '') AS nickname FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()


def list_users(
    conn: ConnType,
    *,
    where_clause: str = "",
    params: tuple = (),
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """分页查询用户列表。"""
    return conn.execute(
        f"""
        SELECT id, email, COALESCE(nickname, '') AS nickname,
               COALESCE(plan_type, 'free') AS plan_type,
               plan_expires_at,
               created_at, updated_at
        FROM users
        {where_clause}
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """,
        params + (limit, offset),
    ).fetchall()


def count_users(conn: ConnType, *, where_clause: str = "", params: tuple = ()) -> int:
    """按筛选条件统计用户数量。"""
    row = conn.execute(
        f"SELECT COUNT(*) AS total FROM users {where_clause}",
        params,
    ).fetchone()
    return int(row["total"]) if row else 0


def export_all_users(conn: ConnType) -> list[dict[str, Any]]:
    """导出全部用户数据（含统计）。"""
    return conn.execute("""
        SELECT u.id, u.email, COALESCE(u.nickname, '') AS nickname,
               COALESCE(u.plan_type, 'free') AS plan_type,
               u.plan_expires_at,
               u.created_at, u.updated_at,
               COALESCE(c.chat_count, 0) AS chat_count,
               COALESCE(c.char_count, 0) AS char_count,
               COALESCE(p.char_count, 0) AS linked_char_count
        FROM users u
        LEFT JOIN (
            SELECT user_id,
                   COUNT(*) AS chat_count,
                   SUM(COALESCE(LENGTH(content), 0)) AS char_count
            FROM chat_messages
            GROUP BY user_id
        ) c ON c.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS char_count
            FROM user_character_profiles
            GROUP BY user_id
        ) p ON p.user_id = u.id
        ORDER BY u.id DESC
        """).fetchall()


def get_user_stats(conn: ConnType, user_id: int | str) -> dict[str, Any]:
    """获取用户对话统计。"""
    return conn.execute(
        """
        SELECT COUNT(*) AS chat_count,
               COALESCE(SUM(LENGTH(content)), 0) AS char_count
        FROM chat_messages WHERE user_id = %s
        """,
        (user_id,),
    ).fetchone()


def get_user_linked_char_count(conn: ConnType, user_id: int | str) -> int:
    """获取用户关联角色数。"""
    row = conn.execute(
        "SELECT COUNT(*) AS char_count FROM user_character_profiles WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    return row["char_count"] if row else 0


def get_user_last_login(conn: ConnType, user_id: int | str) -> datetime | None:
    """获取用户最后登录时间（从 ai_request_logs 推断）。"""
    row = conn.execute(
        "SELECT MAX(created_at) AS last_login FROM ai_request_logs WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    return row["last_login"] if row else None


def update_user_fields(
    conn: ConnType, user_id: int | str, updates: dict[str, Any]
) -> None:
    """按白名单更新用户字段（动态 SET 子句）。updated_at 自动更新。

    防御性白名单校验：即使调用方已过滤字段，repository 层也做二次校验。
    """
    _ALLOWED = {"email", "nickname"}
    for k in updates:
        if k not in _ALLOWED:
            raise ValueError(f"字段 '{k}' 不在允许更新的白名单中")
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    conn.execute(
        f"UPDATE users SET {set_clause}, updated_at = now() WHERE id = %s",
        list(updates.values()) + [user_id],
    )


def update_user_plan(
    conn: ConnType,
    user_id: int | str,
    plan_type: str,
    plan_expires_at: datetime | None,
) -> None:
    """更新用户会员档位。"""
    conn.execute(
        "UPDATE users SET plan_type = %s, plan_expires_at = %s, updated_at = now() WHERE id = %s",
        (plan_type, plan_expires_at, user_id),
    )


def delete_user_cascade(conn: ConnType, user_id: int | str) -> None:
    """级联删除用户及关联数据。"""
    conn.execute("DELETE FROM ai_request_logs WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM chat_messages WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM chat_summaries WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM user_character_profiles WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM character_states WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM user_story_progress WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM membership_orders WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
    conn.execute(
        "DELETE FROM password_reset_codes WHERE email = (SELECT email FROM users WHERE id = %s)",
        (user_id,),
    )
    conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
