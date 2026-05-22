"""会员订单相关的数据访问层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.database import ConnType
from constants.order_status import ORDER_STATUS_CLOSED, ORDER_STATUS_PENDING

ORDER_SELECT_FIELDS = """
order_no, plan_type, amount_cents, currency, duration_days,
status, payment_provider, provider_trade_no, checkout_url,
created_at, paid_at, expires_at, closed_at
"""


def fetch_order_by_no(
    conn: ConnType, *, order_no: str, user_id: int | str | None = None
) -> dict[str, Any] | None:
    """按订单号读取订单；传 user_id 时额外校验归属。"""
    if user_id is None:
        return conn.execute(
            f"""
            SELECT {ORDER_SELECT_FIELDS}
            FROM membership_orders
            WHERE order_no = %s
            LIMIT 1
            """,
            (order_no,),
        ).fetchone()
    return conn.execute(
        f"""
        SELECT {ORDER_SELECT_FIELDS}
        FROM membership_orders
        WHERE order_no = %s AND user_id = %s
        LIMIT 1
        """,
        (order_no, user_id),
    ).fetchone()


def find_pending_order(
    conn: ConnType, *, user_id: int | str, plan_type: str, status: str
) -> dict[str, Any] | None:
    """查找用户的待支付订单。"""
    return conn.execute(
        f"""
        SELECT {ORDER_SELECT_FIELDS}
        FROM membership_orders
        WHERE user_id = %s AND plan_type = %s AND status = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, plan_type, status),
    ).fetchone()


def insert_order(
    conn: ConnType,
    *,
    order_no: str,
    user_id: int | str,
    plan_type: str,
    amount_cents: int,
    duration_days: int,
    status: str,
    expires_at: datetime | None,
) -> None:
    """插入新订单。created_at 由 DB DEFAULT now() 填充。"""
    conn.execute(
        """
        INSERT INTO membership_orders(
            order_no, user_id, plan_type, amount_cents, currency,
            duration_days, status, payment_provider, provider_trade_no,
            checkout_url, expires_at, meta_json
        ) VALUES (%s, %s, %s, %s, 'CNY', %s, %s, '', '', '', %s, '{}'::jsonb)
        """,
        (
            order_no,
            user_id,
            plan_type,
            amount_cents,
            duration_days,
            status,
            expires_at,
        ),
    )


def close_pending_order(
    conn: ConnType,
    *,
    order_no: str,
    user_id: int | str,
    current_status: str,
    new_status: str,
) -> int:
    """关闭待支付订单，返回受影响行数。closed_at/updated_at 自动更新。"""
    cursor = conn.execute(
        """
        UPDATE membership_orders
        SET status = %s, closed_at = now(), updated_at = now()
        WHERE order_no = %s AND user_id = %s AND status = %s
        """,
        (new_status, order_no, user_id, current_status),
    )
    return cursor.rowcount


def list_user_orders(
    conn: ConnType, *, user_id: int | str, limit: int
) -> list[dict[str, Any]]:
    """获取用户的订单列表。"""
    return conn.execute(
        f"""
        SELECT {ORDER_SELECT_FIELDS}
        FROM membership_orders
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (user_id, limit),
    ).fetchall()


# ============================================================
# 管理后台 — 订单查询（带用户 LEFT JOIN）
# ============================================================

_ADMIN_ORDER_SELECT_FIELDS = """
o.id, o.order_no, o.user_id, o.plan_type, o.amount_cents, o.currency,
o.duration_days, o.status, o.payment_provider, o.provider_trade_no,
o.checkout_url, o.created_at, o.paid_at, o.expires_at, o.closed_at,
COALESCE(u.email, '') AS user_email,
COALESCE(u.nickname, '') AS user_nickname
"""


def count_orders_with_users(
    conn: ConnType, *, where_clause: str = "", params: tuple = ()
) -> int:
    """管理后台：按条件统计订单数（含用户 LEFT JOIN）。"""
    row = conn.execute(
        f"SELECT COUNT(*) AS total FROM membership_orders o LEFT JOIN users u ON u.id = o.user_id {where_clause}",
        params,
    ).fetchone()
    return int(row["total"]) if row else 0


def list_orders_with_users(
    conn: ConnType, *, where_clause: str = "", params: tuple = (), limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """管理后台：分页查询订单列表（含用户 LEFT JOIN）。"""
    return conn.execute(
        f"""
        SELECT {_ADMIN_ORDER_SELECT_FIELDS}
        FROM membership_orders o
        LEFT JOIN users u ON u.id = o.user_id
        {where_clause}
        ORDER BY o.id DESC
        LIMIT %s OFFSET %s
        """,
        params + (limit, offset),
    ).fetchall()


def export_all_orders_with_users(conn: ConnType) -> list[dict[str, Any]]:
    """管理后台：导出全部订单（含用户 LEFT JOIN）。"""
    return conn.execute(
        f"""
        SELECT {_ADMIN_ORDER_SELECT_FIELDS}
        FROM membership_orders o
        LEFT JOIN users u ON u.id = o.user_id
        ORDER BY o.id DESC
        """
    ).fetchall()


def close_expired_orders(
    conn: ConnType, *, user_id: int | str | None = None, now: Any = None
) -> int:
    """关闭过期的待支付订单，返回受影响行数。"""
    from datetime import datetime, timezone
    if now is None:
        now = datetime.now(timezone.utc)
    if user_id is None:
        cursor = conn.execute(
            """
            UPDATE membership_orders
            SET status = %s, closed_at = %s, updated_at = now()
            WHERE status = %s
              AND expires_at IS NOT NULL
              AND expires_at <= %s
            """,
            (ORDER_STATUS_CLOSED, now, ORDER_STATUS_PENDING, now),
        )
    else:
        cursor = conn.execute(
            """
            UPDATE membership_orders
            SET status = %s, closed_at = %s, updated_at = now()
            WHERE user_id = %s
              AND status = %s
              AND expires_at IS NOT NULL
              AND expires_at <= %s
            """,
            (ORDER_STATUS_CLOSED, now, user_id, ORDER_STATUS_PENDING, now),
        )
    return int(cursor.rowcount)


def get_order_with_user_by_id(conn: ConnType, order_id: int) -> dict[str, Any] | None:
    """管理后台：按 ID 查询单个订单（含用户 LEFT JOIN）。"""
    return conn.execute(
        """
        SELECT o.*, COALESCE(u.email, '') AS user_email, COALESCE(u.nickname, '') AS user_nickname
        FROM membership_orders o
        LEFT JOIN users u ON u.id = o.user_id
        WHERE o.id = %s
        """,
        (order_id,),
    ).fetchone()
