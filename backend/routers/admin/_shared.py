"""
管理后台 - 共享常量和工具函数
"""

import json
from typing import Any

from fastapi import HTTPException

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


def _count_with_where(conn: Any, count_from_sql: str, where_clause: str, params: list[Any]) -> int:
    count_row = conn.execute(
        f"SELECT COUNT(*) AS total {count_from_sql} {where_clause}",
        tuple(params),
    ).fetchone()
    return count_row["total"]


def _write_audit_log(
    conn: Any,
    operator_id: str,
    operator_email: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """
    内部函数：写入一条操作日志。
    注意：此函数不自行 commit，调用方负责提交事务。
    """
    from config import utc_now_iso
    try:
        conn.execute(
            """
            INSERT INTO admin_audit_logs
            (operator_id, operator_email, action, target_type, target_id, detail, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                operator_id,
                operator_email,
                action,
                target_type,
                target_id,
                json.dumps(detail or {}, ensure_ascii=False),
                utc_now_iso(),
            ),
        )
    except Exception:
        pass
