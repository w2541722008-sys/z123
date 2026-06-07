"""
管理后台 - 子模块（从 admin.py 自动拆分）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core.auth import get_admin_user
from core.database import ConnType, get_db_dep
from core.exceptions import BadRequestError, NotFoundError
from core.plan_constants import plan_display_name

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])

from ._helpers import (
    _build_where_clause,
    _normalize_pagination,
    _validate_pagination_params,
)
from repositories import billing_repository as billing_repo

_ADMIN_ORDER_FIELDS = (
    "id", "order_no", "user_id", "user_email", "user_nickname",
    "plan_type", "amount_cents", "currency", "duration_days",
    "status", "payment_provider", "provider_trade_no",
    "checkout_url", "created_at", "paid_at", "expires_at", "closed_at",
)


def _serialize_order_row(row: dict[str, Any]) -> dict[str, Any]:
    """将订单行序列化为 API 响应格式。"""
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


@router.get("/admin/orders")
def admin_list_membership_orders(
    search: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 20,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """管理后台：查看会员订单列表，支持搜索、状态筛选和分页。"""
    _validate_pagination_params(page, limit, max_limit=100)

    conditions: list[str] = []
    params: list[Any] = []

    if search:
        conditions.append("(o.order_no LIKE %s OR u.email LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if status:
        conditions.append("o.status = %s")
        params.append(status)

    where_clause = _build_where_clause(conditions)
    offset, safe_limit = _normalize_pagination(page, limit, max_limit=100)
    params_tuple = tuple(params)

    total = billing_repo.count_orders_with_users(conn, where_clause=where_clause, params=params_tuple)
    rows = billing_repo.list_orders_with_users(conn, where_clause=where_clause, params=params_tuple, limit=safe_limit, offset=offset)

    return {
        "total": total,
        "page": page,
        "limit": safe_limit,
        "orders": [_serialize_order_row(row) for row in rows],
    }


@router.get("/admin/orders/export")
def admin_export_orders(conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    """管理后台：导出全部订单 CSV 数据。"""
    rows = billing_repo.export_all_orders_with_users(conn)
    return [_serialize_order_row(row) for row in rows]


@router.get("/admin/orders/{order_id}")
def admin_get_order(order_id: int, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    """管理后台：获取订单完整详情。"""
    row = billing_repo.get_order_with_user_by_id(conn, order_id)
    if not row:
        raise NotFoundError(detail="订单不存在")
    return _serialize_order_row(row)
