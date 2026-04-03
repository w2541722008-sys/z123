"""
管理后台 - 共享常量和工具函数
"""

import json
from typing import Any

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
    except Exception as e:
        conn.rollback()
        raise e


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
