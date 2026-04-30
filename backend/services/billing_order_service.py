"""
计费与订单服务 - 管理会员订单和每日 token 预算

核心功能：
    - 创建/查询/取消订单
    - VIP/SVIP 会员激活
    - 每日 token 预算检查与扣减
    - 订单超时自动关闭
"""

from __future__ import annotations

from config import utc_now_iso

ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_CLOSED = "closed"


def close_expired_pending_orders(
    conn,
    user_id: int | None = None,
    *,
    commit: bool = True,
) -> int:
    now = utc_now_iso()
    if user_id is None:
        cursor = conn.execute(
            """
            UPDATE membership_orders
            SET status = %s, closed_at = %s
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
            SET status = %s, closed_at = %s
            WHERE user_id = %s
              AND status = %s
              AND expires_at IS NOT NULL
              AND expires_at <= %s
            """,
            (ORDER_STATUS_CLOSED, now, user_id, ORDER_STATUS_PENDING, now),
        )
    if commit:
        conn.commit()
    return cursor.rowcount
