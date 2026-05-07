"""
管理后台 - 子模块（从 admin.py 自动拆分）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import CurrentUser, get_admin_user, get_current_user
from core.database import ConnType, get_conn, get_db_dep
from services.db_monitor import get_stats, reset_stats
from services.health_service import check_media_health

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])

from ._helpers import _ADMIN_EDITABLE_FIELDS, _normalize_pagination, _transaction, _write_audit_log


def _parse_audit_detail(raw: Any) -> dict[str, Any]:
    """安全解析审计日志 detail 列（text 存储 JSON 或 jsonb 返回 dict）。"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}

@router.get("/admin/db-stats")
def get_db_stats() -> dict[str, Any]:
    """获取数据库查询性能统计。"""
    return {
        "ok": True,
        "stats": get_stats(),
    }


@router.post("/admin/db-stats/reset")
def reset_db_stats() -> dict[str, Any]:
    """重置数据库性能统计。"""
    reset_stats()
    return {"ok": True, "message": "性能统计已重置"}


# ============================================================
# 运营仪表盘
# ============================================================
@router.get("/admin/dashboard/stats")
def admin_dashboard_stats(conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    """
    管理后台：获取仪表盘核心统计数据。

    返回：总用户数、今日新增、付费用户数、今日订单数、
          今日收入、即将到期用户数、各档位分布。
    """
    # 总用户数
    total_users_row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
    total_users = total_users_row["cnt"] if total_users_row else 0

    # 今日新增用户
    today_new_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM users WHERE DATE(created_at) = CURRENT_DATE"
    ).fetchone()
    today_new_users = today_new_row["cnt"] if today_new_row else 0

    # 付费用户数（vip 或 svip，且未过期）
    paid_users_row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM users
        WHERE plan_type IN ('vip', 'svip')
          AND (plan_expires_at IS NULL OR plan_expires_at > NOW())
        """
    ).fetchone()
    paid_users = paid_users_row["cnt"] if paid_users_row else 0

    # 今日订单数（已支付）
    today_orders_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM membership_orders WHERE status = 'paid' AND DATE(created_at) = CURRENT_DATE"
    ).fetchone()
    today_orders = today_orders_row["cnt"] if today_orders_row else 0

    # 今日收入（已支付订单，单位：分）
    today_revenue_row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM membership_orders WHERE status = 'paid' AND DATE(created_at) = CURRENT_DATE"
    ).fetchone()
    today_revenue = today_revenue_row["total"] if today_revenue_row else 0

    # 即将到期用户数（3天内到期）
    expiring_soon_row = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM users
        WHERE plan_type IN ('vip', 'svip')
          AND plan_expires_at IS NOT NULL
          AND plan_expires_at > NOW()
          AND plan_expires_at <= NOW() + INTERVAL '3 days'
        """
    ).fetchone()
    expiring_soon = expiring_soon_row["cnt"] if expiring_soon_row else 0

    # 各档位分布
    plan_dist_row = conn.execute(
        """
        SELECT plan_type, COUNT(*) AS cnt
        FROM users
        GROUP BY plan_type
        """
    ).fetchall()
    plan_distribution = {row["plan_type"] or "free": row["cnt"] for row in plan_dist_row}

    return {
        "total_users": total_users,
        "today_new_users": today_new_users,
        "paid_users": paid_users,
        "paid_rate": round(paid_users / total_users * 100, 1) if total_users > 0 else 0,
        "today_orders": today_orders,
        "today_revenue": today_revenue,
        "avg_order_value": round(today_revenue / today_orders) if today_orders > 0 else 0,
        "expiring_soon": expiring_soon,
        "plan_distribution": plan_distribution,
    }


@router.get("/admin/dashboard/trend")
def admin_dashboard_trend(days: int = 7, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    """
    管理后台：获取近 N 天用户增长和订单趋势。

    参数：
        days: 天数，默认 7 天（最多 30 天）
    """
    safe_days = max(1, min(days, 30))

    # 生成日期序列
    date_series = conn.execute(
        """
        SELECT generate_series AS day
        FROM generate_series(
            CURRENT_DATE - INTERVAL '%s days',
            CURRENT_DATE,
            '1 day'::interval
        )
        """,
        (safe_days - 1,),
    ).fetchall()

    trend = []
    for row in date_series:
        day_str = str(row["day"])[:10]  # 取 YYYY-MM-DD

        user_cnt_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE DATE(created_at) = %s",
            (day_str,),
        ).fetchone()

        order_cnt_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM membership_orders WHERE status = 'paid' AND DATE(created_at) = %s",
            (day_str,),
        ).fetchone()

        revenue_row = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM membership_orders WHERE status = 'paid' AND DATE(created_at) = %s",
            (day_str,),
        ).fetchone()

        trend.append({
            "date": day_str,
            "new_users": user_cnt_row["cnt"] if user_cnt_row else 0,
            "new_orders": order_cnt_row["cnt"] if order_cnt_row else 0,
            "revenue": revenue_row["total"] if revenue_row else 0,
        })

    return {"trend": trend, "days": safe_days}


# ============================================================
# 操作日志
# ============================================================

@router.get("/admin/audit-logs")
def admin_list_audit_logs(
    action: str = "",
    target_type: str = "",
    page: int = 1,
    limit: int = 50,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    管理后台：获取操作日志列表。

    参数：
        action: 按操作类型筛选（delete_user/edit_user/update_plan/batch_update 等）
        target_type: 按对象类型筛选（user/order/character）
        page: 页码
        limit: 每页条数（最多 200）
    """
    conditions = []
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

    offset, safe_limit = _normalize_pagination(page, limit, max_limit=200)

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

    return {
        "total": total,
        "page": page,
        "limit": safe_limit,
        "logs": [
            {
                "id": row["id"],
                "operator_id": row["operator_id"],
                "operator_email": row["operator_email"],
                "action": row["action"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "detail": _parse_audit_detail(row["detail"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


@router.get("/admin/media-missing")
def admin_media_missing(refresh: bool = Query(False, description="是否强制刷新媒体健康缓存")) -> dict[str, Any]:
    media_health: dict[str, Any] = check_media_health(force=refresh)
    samples = [str(s) for s in (media_health.get("samples") or [])]
    missing_count = int(media_health.get("missing_count") or 0)
    return {
        "ok": bool(media_health.get("ok")),
        "missing_count": missing_count,
        "items": samples,
        "truncated": missing_count > len(samples),
    }
