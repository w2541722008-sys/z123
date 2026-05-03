"""
管理后台 - 共享常量和工具函数
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from core.database import ConnType
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# 管理后台可编辑的字段白名单
_ADMIN_EDITABLE_FIELDS = {
    "name", "abbr", "subtitle", "description", "tags",
    "opening_message", "system_prompt", "sort_order",
    "is_visible", "home_priority", "card_type",
    "required_plan",
    "affection_enabled", "affection_rules_json",
    "import_locked", "avatar_url", "cover_url",
}


def _transaction(conn, func):
    """
    在事务中执行函数，出错时自动回滚。
    """
    try:
        result = func()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


def _normalize_pagination(page: int, limit: int, *, max_limit: int) -> tuple[int, int]:
    safe_limit = min(limit, max_limit)
    offset = (max(1, page) - 1) * safe_limit
    return offset, safe_limit


def _validate_pagination_params(page: int, limit: int, *, max_limit: int) -> None:
    if page < 1:
        raise HTTPException(status_code=400, detail="page参数必须大于等于1")
    if limit < 1 or limit > max_limit:
        raise HTTPException(status_code=400, detail=f"limit参数必须在1-{max_limit}之间")


def _build_where_clause(conditions: list[str]) -> str:
    return "WHERE " + " AND ".join(conditions) if conditions else ""


# count_from_sql 允许的 SQL 片段白名单（防御性校验）
_ALLOWED_COUNT_FROM = {
    "FROM users",
    "FROM membership_orders o LEFT JOIN users u ON u.id = o.user_id",
}


def _count_with_where(conn: ConnType, count_from_sql: str, where_clause: str, params: list[Any]) -> int:
    # 白名单校验：确保 count_from_sql 来自安全来源，防止 SQL 注入
    # 注意：不使用 assert，因为 python -O 会跳过 assert 导致安全防护失效
    if count_from_sql not in _ALLOWED_COUNT_FROM:
        raise HTTPException(
            status_code=500,
            detail=f"非法 count_from_sql，如需新增请更新 _ALLOWED_COUNT_FROM 白名单",
        )
    count_row = conn.execute(
        f"SELECT COUNT(*) AS total {count_from_sql} {where_clause}",
        tuple(params),
    ).fetchone()
    return int(count_row["total"])


def _write_audit_log(
    conn: ConnType,
    operator_id: int,
    operator_email: str,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """
    内部函数：写入一条操作日志。
    注意：此函数不自行 commit，调用方负责提交事务。
    """
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
