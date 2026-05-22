"""管理后台审计日志 — 纯 SQL 层。

将 _helpers._write_audit_log 的 INSERT 下沉至此，
消除 router 层对 admin_audit_logs 表的直接写入。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.database import ConnType

logger = logging.getLogger(__name__)


def insert_audit_log(
    conn: ConnType,
    *,
    operator_id: int,
    operator_email: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """写入一条操作日志。写入失败时仅记录 warning，不抛异常。"""
    try:
        conn.execute(
            """
            INSERT INTO admin_audit_logs
            (operator_id, operator_email, action, target_type, target_id, detail)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                operator_id,
                operator_email,
                action,
                target_type,
                target_id,
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
    except Exception as exc:
        logger.warning("审计日志写入失败: %s", exc)
