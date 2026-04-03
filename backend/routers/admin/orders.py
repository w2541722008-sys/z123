"""
管理后台 - 子模块（从 admin.py 自动拆分）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import CurrentUser, get_admin_user, get_current_user
from config import utc_now_iso
from database import get_conn


router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])

from ._shared import _ADMIN_EDITABLE_FIELDS, _transaction, _write_audit_log

@router.get("/admin/orders")
def admin_list_membership_orders(
    search: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """
    管理后台：查看会员订单列表，支持搜索、状态筛选和分页。

    参数：
        search: 按订单号或用户邮箱模糊搜索
        status: 按状态筛选（pending/paid/expired/closed/refunded）
        page: 页码（从 1 开始）
        limit: 每页条数（最多 100）
    """
    # 验证分页参数
    if page < 1:
        raise HTTPException(status_code=400, detail="page参数必须大于等于1")
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit参数必须在1-100之间")
    
    conn = get_conn()
    try:
        # 动态构建 WHERE 条件
        conditions = []
        params: list[Any] = []

        if search:
            conditions.append("(o.order_no LIKE %s OR u.email LIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        if status:
            conditions.append("o.status = %s")
            params.append(status)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # 查询总数
        count_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM membership_orders o LEFT JOIN users u ON u.id = o.user_id {where_clause}",
            tuple(params),
        ).fetchone()
        total = count_row["total"]

        # 分页
        offset = (max(1, page) - 1) * min(limit, 100)
        safe_limit = min(limit, 100)

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
    finally:
        conn.close()


@router.get("/admin/orders/export")
def admin_export_orders() -> list[dict[str, Any]]:
    """
    管理后台：导出全部订单 CSV 数据。
    """
    conn = get_conn()
    try:
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
    finally:
        conn.close()


@router.get("/admin/orders/{order_id}")
def admin_get_order(order_id: int) -> dict[str, Any]:
    """
    管理后台：获取订单完整详情。
    """
    conn = get_conn()
    try:
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
    finally:
        conn.close()



