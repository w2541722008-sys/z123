from __future__ import annotations

import logging
import threading
import time

from database import get_conn
from services.billing_order_service import close_expired_pending_orders


def start_order_cleanup_daemon(*, interval_seconds: int = 3600) -> threading.Thread:
    def cleanup_expired_orders_task() -> None:
        while True:
            conn = None
            try:
                conn = get_conn()
                close_expired_pending_orders(conn)
                logging.info("✅ 已清理超时订单")
            except Exception as e:
                logging.error(f"❌ 订单清理失败: {e}", exc_info=True)
            finally:
                if conn is not None:
                    conn.close()
            time.sleep(interval_seconds)

    cleanup_thread = threading.Thread(target=cleanup_expired_orders_task, daemon=True)
    cleanup_thread.start()
    return cleanup_thread
