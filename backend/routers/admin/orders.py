"""
管理后台 - 子模块（从 admin.py 自动拆分）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import CurrentUser, get_admin_user, get_current_user
from core.database import ConnType, get_db_dep
from core.schemas import (
    AdminUserPlanUpdatePayload,
    AdminUserEditPayload,
    AdminBatchPlanPayload,
)
from services.plan_service import plan_display_name, serialize_plan_info

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])

from ._shared import (
    _ADMIN_EDITABLE_FIELDS,
    _build_where_clause,
    _count_with_where,
    _normalize_pagination,
    _transaction,
    _validate_pagination_params,
    _write_audit_log,
)

@router.get("/admin/orders")
def admin_list_membership_orders(
    search: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 20,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    管理后台：查看会员订单列表，支持搜索、状态筛选和分页。

    参数：
        search: 按订单号或用户邮箱模糊搜索
        status: 按状态筛选（pending/paid/expired/closed/refunded）
        page: 页码（从 1 开始）
        limit: 每页条数（最多 100）
    """
    _validate_pagination_params(page, limit, max_limit=100)

    # 动态构建 WHERE 条件
    conditions = []
    params: list[Any] = []

    if search:
        conditions.append("(o.order_no LIKE %s OR u.email LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if status:
        conditions.append("o.status = %s")
        params.append(status)

    where_clause = _build_where_clause(conditions)

    # 查询总数
    total = _count_with_where(
        conn,
        "FROM membership_orders o LEFT JOIN users u ON u.id = o.user_id",
        where_clause,
        params,
    )

    # 分页
    offset, safe_limit = _normalize_pagination(page, limit, max_limit=100)

    rows = conn.execute(
        f"""
        SELECT o.id, o.order_no, o.user_id, o.plan_type, o.amount_cents, o.currency,
               o.duration_days, o.status, o.payment_provider, o.provider_trade_no,
               o.checkout_url, o.created_at, o.paid_at, o.expires_at, o.closed_at,
               COALESCE(u.email, '') AS user_email,
               COALESCE(u.nickname, '') AS user_nickname
        FROM membership_orders o
        LEFT JOIN users u ON u.id = o.user_id
        {where_clause}
        ORDER BY o.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params) + (safe_limit, offset),
    ).fetchall()

    return {
        "total": total,
        "page": page,
        "limit": safe_limit,
        "orders": [
            {
                "id": row["id"],
                "order_no": row["order_no"],
                "user_id": row["user_id"],
                "user_email": row["user_email"],
                "user_nickname": row["user_nickname"],
                "plan_type": row["plan_type"],
                "plan_label": plan_display_name(row["plan_type"]),
                "amount_cents": row["amount_cents"],
                "currency": row["currency"],
                "duration_days": row["duration_days"],
                "status": row["status"],
                "payment_provider": row["payment_provider"],
                "provider_trade_no": row["provider_trade_no"],
                "checkout_url": row["checkout_url"],
                "created_at": row["created_at"],
                "paid_at": row["paid_at"],
                "expires_at": row["expires_at"],
                "closed_at": row["closed_at"],
            }
            for row in rows
        ],
    }


@router.get("/admin/orders/export")
def admin_export_orders(conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    """
    管理后台：导出全部订单 CSV 数据。
    """
    rows = conn.execute(
        """
        SELECT o.id, o.order_no, o.user_id, o.plan_type, o.amount_cents, o.currency,
               o.duration_days, o.status, o.payment_provider, o.provider_trade_no,
               o.checkout_url, o.created_at, o.paid_at, o.expires_at, o.closed_at,
               COALESCE(u.email, '') AS user_email,
               COALESCE(u.nickname, '') AS user_nickname
        FROM membership_orders o
        LEFT JOIN users u ON u.id = o.user_id
        ORDER BY o.id DESC
        """
    ).fetchall()

    return [
        {
            "id": row["id"],
            "order_no": row["order_no"],
            "user_id": row["user_id"],
            "user_email": row["user_email"],
            "user_nickname": row["user_nickname"],
            "plan_type": row["plan_type"],
            "plan_label": plan_display_name(row["plan_type"]),
            "amount_cents": row["amount_cents"],
            "currency": row["currency"],
            "duration_days": row["duration_days"],
            "status": row["status"],
            "payment_provider": row["payment_provider"],
            "provider_trade_no": row["provider_trade_no"],
            "checkout_url": row["checkout_url"],
            "created_at": row["created_at"],
            "paid_at": row["paid_at"],
            "expires_at": row["expires_at"],
            "closed_at": row["closed_at"],
        }
        for row in rows
    ]


@router.get("/admin/orders/{order_id}")
def admin_get_order(order_id: int, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    """
    管理后台：获取订单完整详情。
    """
    row = conn.execute(
        """
        SELECT o.*, COALESCE(u.email, '') AS user_email, COALESCE(u.nickname, '') AS user_nickname
        FROM membership_orders o
        LEFT JOIN users u ON u.id = o.user_id
        WHERE o.id = %s
        """,
        (order_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")

    return {
        "id": row["id"],
        "order_no": row["order_no"],
        "user_id": row["user_id"],
        "user_email": row["user_email"],
        "user_nickname": row["user_nickname"],
        "plan_type": row["plan_type"],
        "plan_label": plan_display_name(row["plan_type"]),
        "amount_cents": row["amount_cents"],
        "currency": row["currency"],
        "duration_days": row["duration_days"],
        "status": row["status"],
        "payment_provider": row["payment_provider"],
        "provider_trade_no": row["provider_trade_no"],
        "checkout_url": row["checkout_url"],
        "created_at": row["created_at"],
        "paid_at": row["paid_at"],
        "expires_at": row["expires_at"],
        "closed_at": row["closed_at"],
    }
