"""管理后台仪表盘 + 审计日志 — 纯 SQL 层。

将 routers/admin/dashboard.py 中的裸 SQL 下沉至此，
router 层仅保留参数校验和响应格式化。
"""

from __future__ import annotations

from typing import Any

from core.database import ConnType


# ============================================================
# 仪表盘统计
# ============================================================

def get_dashboard_stats(conn: ConnType) -> dict[str, Any]:
    """返回仪表盘核心统计数据，内部逐项查询。"""
    return {
        "total_users": _count_users(conn),
        "today_new_users": _count_today_new_users(conn),
        "paid_users": _count_paid_users(conn),
        "today_orders": _count_today_paid_orders(conn),
        "today_revenue": _sum_today_revenue(conn),
        "expiring_soon": _count_expiring_soon(conn, days=3),
        "plan_distribution": _plan_distribution(conn),
    }


def _count_users(conn: ConnType) -> int:
    row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
    return row["cnt"] if row else 0


def _count_today_new_users(conn: ConnType) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM users WHERE DATE(created_at) = CURRENT_DATE"
    ).fetchone()
    return row["cnt"] if row else 0


def _count_paid_users(conn: ConnType) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM users
        WHERE plan_type IN ('vip', 'svip')
          AND (plan_expires_at IS NULL OR plan_expires_at > NOW())
        """
    ).fetchone()
    return row["cnt"] if row else 0


def _count_today_paid_orders(conn: ConnType) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM membership_orders WHERE status = 'paid' AND DATE(created_at) = CURRENT_DATE"
    ).fetchone()
    return row["cnt"] if row else 0


def _sum_today_revenue(conn: ConnType) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM membership_orders WHERE status = 'paid' AND DATE(created_at) = CURRENT_DATE"
    ).fetchone()
    return row["total"] if row else 0


def _count_expiring_soon(conn: ConnType, *, days: int = 3) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM users
        WHERE plan_type IN ('vip', 'svip')
          AND plan_expires_at IS NOT NULL
          AND plan_expires_at > NOW()
          AND plan_expires_at <= NOW() + (%s::text || ' days')::interval
        """,
        (days,),
    ).fetchone()
    return row["cnt"] if row else 0


def _plan_distribution(conn: ConnType) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT COALESCE(plan_type, 'free') AS plan_type, COUNT(*) AS cnt
        FROM users
        GROUP BY plan_type
        """
    ).fetchall()
    # 同名 plan_type 聚合求和，避免 NULL 行多行时字典推导式键碰撞导致计数丢失
    result: dict[str, int] = {}
    for row in rows:
        key = row["plan_type"]
        result[key] = result.get(key, 0) + row["cnt"]
    return result


# ============================================================
# 趋势数据
# ============================================================

def get_dashboard_trend(conn: ConnType, days: int) -> list[dict[str, Any]]:
    """返回近 N 天用户增长和订单趋势（单次查询，消除原 N+1 问题）。

    原实现对每个日期分别查询 users / orders / revenue，30 天时产生 91 次 DB 往返。
    本实现用一条 LEFT JOIN + GROUP BY 替代，固定 1 次往返。
    """
    rows = conn.execute(
        """
        SELECT d.day::date AS day,
               COUNT(u.id) FILTER (WHERE u.created_at IS NOT NULL) AS new_users,
               COUNT(o.id) FILTER (WHERE o.id IS NOT NULL) AS new_orders,
               COALESCE(SUM(o.amount_cents) FILTER (WHERE o.id IS NOT NULL), 0) AS revenue
        FROM generate_series(
            CURRENT_DATE - (%s - 1), CURRENT_DATE, '1 day'::interval
        ) AS d(day)
        LEFT JOIN users u ON DATE(u.created_at) = d.day::date
        LEFT JOIN membership_orders o ON DATE(o.created_at) = d.day::date AND o.status = 'paid'
        GROUP BY d.day
        ORDER BY d.day
        """,
        (days,),
    ).fetchall()

    return [
        {
            "date": str(row["day"]),
            "new_users": row["new_users"],
            "new_orders": row["new_orders"],
            "revenue": row["revenue"],
        }
        for row in rows
    ]


# ============================================================
# 审计日志
# ============================================================

def list_audit_logs(
    conn: ConnType,
    *,
    action: str = "",
    target_type: str = "",
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    """返回分页审计日志列表，支持按操作类型和对象类型筛选。

    返回 {"total": int, "rows": list[dict]}，分页和序列化由调用方处理。
    """
    conditions: list[str] = []
    params: list[Any] = []

    if action:
        conditions.append("action = %s")
        params.append(action)
    if target_type:
        conditions.append("target_type = %s")
        params.append(target_type)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    count_row = conn.execute(
        f"SELECT COUNT(*) AS total FROM admin_audit_logs {where_clause}",
        tuple(params),
    ).fetchone()
    total = count_row["total"]

    offset = (max(1, page) - 1) * max(1, min(limit, 200))
    safe_limit = max(1, min(limit, 200))

    rows = conn.execute(
        f"""
        SELECT id, operator_id, operator_email, action, target_type,
               target_id, detail, created_at
        FROM admin_audit_logs
        {where_clause}
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params) + (safe_limit, offset),
    ).fetchall()

    return {"total": total, "rows": rows}
