"""会员支付预留路由。"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import CurrentUser, get_current_user
from config import (
    SVIP_PLAN_DURATION_DAYS,
    SVIP_PLAN_PRICE_CENTS,
    VIP_PLAN_DURATION_DAYS,
    VIP_PLAN_PRICE_CENTS,
    utc_now_iso,
)
from database import get_conn
from models import BillingCreateOrderPayload
from services.plan_service import SVIP_PLAN, VIP_PLAN, plan_display_name

router = APIRouter()


PLAN_PRODUCTS = {
    VIP_PLAN: {
        "plan_type": VIP_PLAN,
        "title": "VIP 月卡",
        "price_cents": VIP_PLAN_PRICE_CENTS,
        "duration_days": VIP_PLAN_DURATION_DAYS,
        "description": "中高端模型、更高每日额度。",
    },
    SVIP_PLAN: {
        "plan_type": SVIP_PLAN,
        "title": "SVIP 月卡",
        "price_cents": SVIP_PLAN_PRICE_CENTS,
        "duration_days": SVIP_PLAN_DURATION_DAYS,
        "description": "旗舰模型、最高额度与 SVIP 专属角色。",
    },
}


def _build_order_no() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"AF{timestamp}{secrets.token_hex(3).upper()}"


@router.get("/billing/plans")
def billing_plans() -> dict[str, Any]:
    """前台读取当前可售卖的会员套餐。"""
    return {"plans": list(PLAN_PRODUCTS.values())}


@router.post("/billing/orders")
def billing_create_order(
    payload: BillingCreateOrderPayload,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """创建会员订单预留记录（支付网关后续再接）。"""
    product = PLAN_PRODUCTS.get(payload.plan_type)
    if not product:
        raise HTTPException(status_code=400, detail="暂不支持该会员套餐")

    order_no = _build_order_no()
    now = utc_now_iso()

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO membership_orders(
                order_no, user_id, plan_type, amount_cents, currency,
                duration_days, status, payment_provider, provider_trade_no,
                checkout_url, created_at, paid_at, expires_at, closed_at, meta_json
            ) VALUES (?, ?, ?, ?, 'CNY', ?, 'pending', '', '', '', ?, '', '', '', '{}')
            """,
            (
                order_no,
                user.id,
                product["plan_type"],
                product["price_cents"],
                product["duration_days"],
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "payment_ready": False,
        "message": "订单已创建，但当前还未接入真实网页支付回调。你可以先用它联调前端流程，后续再接支付平台。",
        "order": {
            "order_no": order_no,
            "plan_type": product["plan_type"],
            "plan_label": plan_display_name(product["plan_type"]),
            "title": product["title"],
            "amount_cents": product["price_cents"],
            "duration_days": product["duration_days"],
            "status": "pending",
            "checkout_url": "",
            "created_at": now,
        },
    }


@router.get("/billing/orders")
def billing_list_my_orders(
    limit: int = 20,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """查看当前用户自己的会员订单。"""
    safe_limit = max(1, min(limit, 100))
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT order_no, plan_type, amount_cents, currency, duration_days,
                   status, payment_provider, checkout_url, created_at, paid_at,
                   expires_at, closed_at
            FROM membership_orders
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user.id, safe_limit),
        ).fetchall()
        return {
            "orders": [
                {
                    "order_no": row["order_no"],
                    "plan_type": row["plan_type"],
                    "plan_label": plan_display_name(row["plan_type"]),
                    "amount_cents": row["amount_cents"],
                    "currency": row["currency"],
                    "duration_days": row["duration_days"],
                    "status": row["status"],
                    "payment_provider": row["payment_provider"],
                    "checkout_url": row["checkout_url"],
                    "created_at": row["created_at"],
                    "paid_at": row["paid_at"],
                    "expires_at": row["expires_at"],
                    "closed_at": row["closed_at"],
                }
                for row in rows
            ]
        }
    finally:
        conn.close()


@router.get("/billing/orders/{order_no}")
def billing_get_order(
    order_no: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """查看某一笔订单详情。"""
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT order_no, plan_type, amount_cents, currency, duration_days,
                   status, payment_provider, provider_trade_no, checkout_url,
                   created_at, paid_at, expires_at, closed_at
            FROM membership_orders
            WHERE order_no = ? AND user_id = ?
            LIMIT 1
            """,
            (order_no, user.id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="订单不存在")
        return {
            "order_no": row["order_no"],
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