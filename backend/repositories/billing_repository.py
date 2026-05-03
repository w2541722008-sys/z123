"""会员订单相关的数据访问层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.database import ConnType

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
