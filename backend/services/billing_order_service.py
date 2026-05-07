"""
计费与订单服务 - 管理会员订单和每日 token 预算

核心功能：
    - 创建/查询/取消订单
    - VIP/SVIP 会员激活
    - 每日 token 预算检查与扣减
    - 订单超时自动关闭
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from core.config import utc_now, logger
from core.database import get_conn

ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_CLOSED = "closed"


def close_expired_pending_orders(
    conn,
    user_id: int | str | None = None,
    *,
    commit: bool = True,
) -> int:
    now = utc_now()
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
    if commit:
        conn.commit()
    return int(cursor.rowcount)


def start_order_cleanup_daemon(*, interval_seconds: int = 3600) -> threading.Thread:
    """启动订单清理后台线程。"""
    def cleanup_expired_orders_task() -> None:
        while True:
            conn = None
            try:
                conn = get_conn()
                close_expired_pending_orders(conn)
                logger.info("✅ 已清理超时订单")
            except Exception as e:
                logger.error("❌ 订单清理失败: %s", e, exc_info=True)
            finally:
                if conn is not None:
                    conn.close()
            time.sleep(interval_seconds)

    cleanup_thread = threading.Thread(target=cleanup_expired_orders_task, daemon=True)
    cleanup_thread.start()
    return cleanup_thread
