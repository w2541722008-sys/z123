"""
管理后台 - 子模块（从 admin.py 自动拆分）
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.auth import get_admin_user
from core.database import ConnType, get_db_dep
from services.db_monitor import get_stats, reset_stats
from services.health_service import check_media_health

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])

from ._helpers import _normalize_pagination, _validate_pagination_params
from repositories import admin_dashboard_repository as dashboard_repo


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
    stats = dashboard_repo.get_dashboard_stats(conn)

    total_users = stats["total_users"]
    today_revenue = stats["today_revenue"]
    today_orders = stats["today_orders"]

    return {
        **stats,
        "paid_rate": round(stats["paid_users"] / total_users * 100, 1) if total_users > 0 else 0,
        "avg_order_value": round(today_revenue / today_orders) if today_orders > 0 else 0,
        "storage": dashboard_repo.get_database_size(conn),
    }


@router.get("/admin/dashboard/trend")
def admin_dashboard_trend(days: int = 7, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    """
    管理后台：获取近 N 天用户增长和订单趋势。

    参数：
        days: 天数，默认 7 天（最多 30 天）
    """
    safe_days = max(1, min(days, 30))
    return {"trend": dashboard_repo.get_dashboard_trend(conn, safe_days), "days": safe_days}


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
    _validate_pagination_params(page, limit, max_limit=200)
    _, safe_limit = _normalize_pagination(page, limit, max_limit=200)
    result = dashboard_repo.list_audit_logs(
        conn, action=action, target_type=target_type, page=page, limit=limit,
    )

    return {
        "total": result["total"],
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
            for row in result["rows"]
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
