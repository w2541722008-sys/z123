"""会员支付预留路由。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import CurrentUser, get_current_user
from config import (
    BILLING_PENDING_EXPIRE_MINUTES,
    SVIP_PLAN_DURATION_DAYS,
    SVIP_PLAN_PRICE_CENTS,
    VIP_PLAN_DURATION_DAYS,
    VIP_PLAN_PRICE_CENTS,
    utc_now_iso,
)
from database import get_conn
from models import BillingCreateOrderPayload
from services.billing_order_service import close_expired_pending_orders
from services.plan_service import SVIP_PLAN, VIP_PLAN, plan_display_name

router = APIRouter()


ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_CLOSED = "closed"
ORDER_SELECT_FIELDS = """
order_no, plan_type, amount_cents, currency, duration_days,
status, payment_provider, provider_trade_no, checkout_url,
created_at, paid_at, expires_at, closed_at
"""


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


def _pending_order_expires_at() -> str:
    """返回待支付订单的过期时间。"""
    return (datetime.now(timezone.utc) + timedelta(minutes=BILLING_PENDING_EXPIRE_MINUTES)).isoformat()


def _is_order_expired(row) -> bool:
    """判断一笔待支付订单是否已经超时。"""
    expires_at = (row["expires_at"] or "").strip()
    if row["status"] != ORDER_STATUS_PENDING or not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)
    except ValueError:
        return False


def _fetch_order_by_no(conn, *, order_no: str, user_id: int | None = None):
    """按订单号读取订单；传 user_id 时额外校验归属。"""
    if user_id is None:
        return conn.execute(
            f"""
            SELECT {ORDER_SELECT_FIELDS}
            FROM membership_orders
            WHERE order_no = %s
            LIMIT 1
            """,
            (order_no,),
        ).fetchone()
    return conn.execute(
        f"""
        SELECT {ORDER_SELECT_FIELDS}
        FROM membership_orders
        WHERE order_no = %s AND user_id = %s
        LIMIT 1
        """,
        (order_no, user_id),
    ).fetchone()


def _close_expired_pending_orders(conn, user_id: int | None = None, *, commit: bool = True) -> int:
    return close_expired_pending_orders(conn, user_id=user_id, commit=commit)


def _cancel_pending_order(
    conn,
    *,
    user_id: int,
    order_no: str,
    commit: bool = True,
) -> dict[str, Any]:
    """用户主动取消自己的一笔待支付订单。"""
    row = _fetch_order_by_no(conn, order_no=order_no, user_id=user_id)
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    if row["status"] == ORDER_STATUS_PAID:
        raise HTTPException(status_code=409, detail="已支付订单不能取消")
    if row["status"] == ORDER_STATUS_CLOSED:
        raise HTTPException(status_code=409, detail="该订单已关闭，无需重复取消")

    closed_at = utc_now_iso()
    cursor = conn.execute(
        """
        UPDATE membership_orders
        SET status = %s, closed_at = %s
        WHERE order_no = %s AND user_id = %s AND status = %s
        """,
        (ORDER_STATUS_CLOSED, closed_at, order_no, user_id, ORDER_STATUS_PENDING),
    )
    if cursor.rowcount != 1:
        raise HTTPException(status_code=409, detail="订单状态已变更，请刷新后重试")
    if commit:
        conn.commit()
    return _serialize_order(_fetch_order_by_no(conn, order_no=order_no, user_id=user_id))


def _serialize_order(row) -> dict[str, Any]:
    """统一序列化订单字段，避免多个接口手写不一致。"""
    is_expired = _is_order_expired(row)
    can_cancel = row["status"] == ORDER_STATUS_PENDING and not is_expired
    return {
        "order_no": row["order_no"],
        "plan_type": row["plan_type"],
        "plan_label": plan_display_name(row["plan_type"]),
        "amount_cents": row["amount_cents"],
        "currency": row["currency"],
        "duration_days": row["duration_days"],
        "status": row["status"],
        "status_label": {
            ORDER_STATUS_PENDING: "待支付",
            ORDER_STATUS_PAID: "已支付",
            ORDER_STATUS_CLOSED: "已关闭",
        }.get(row["status"], row["status"]),
        "payment_provider": row["payment_provider"],
        "provider_trade_no": row["provider_trade_no"],
        "checkout_url": row["checkout_url"],
        "created_at": row["created_at"],
        "paid_at": row["paid_at"],
        "expires_at": row["expires_at"],
        "closed_at": row["closed_at"],
        "payment_ready": False,
        "is_expired": is_expired,
        "can_cancel": can_cancel,
    }


@router.get("/billing/plans")
def billing_plans() -> dict[str, Any]:
    """前台读取当前可售卖的会员套餐。"""
    return {
        "plans": [
            {
                **plan,
                "payment_ready": False,
                "pending_expire_minutes": BILLING_PENDING_EXPIRE_MINUTES,
            }
            for plan in PLAN_PRODUCTS.values()
        ]
    }


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
    expires_at = _pending_order_expires_at()

    conn = get_conn()
    created_order = None
    try:
        _close_expired_pending_orders(conn, user.id, commit=False)

        existing_order = conn.execute(
            f"""
            SELECT {ORDER_SELECT_FIELDS}
            FROM membership_orders
            WHERE user_id = %s AND plan_type = %s AND status = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (user.id, product["plan_type"], ORDER_STATUS_PENDING),
        ).fetchone()
        if existing_order:
            conn.commit()
            return {
                "ok": True,
                "reused_pending_order": True,
                "message": "你已有一笔待支付订单，先继续使用这笔，避免重复创建。",
                "order": _serialize_order(existing_order),
            }

        conn.execute(
            """
            INSERT INTO membership_orders(
                order_no, user_id, plan_type, amount_cents, currency,
                duration_days, status, payment_provider, provider_trade_no,
                checkout_url, created_at, paid_at, expires_at, closed_at, meta_json
            ) VALUES (%s, %s, %s, %s, 'CNY', %s, %s, '', '', '', %s, '', %s, '', '{}')
            """,
            (
                order_no,
                user.id,
                product["plan_type"],
                product["price_cents"],
                product["duration_days"],
                ORDER_STATUS_PENDING,
                now,
                expires_at,
            ),
        )
        conn.commit()
        created_order = _fetch_order_by_no(conn, order_no=order_no, user_id=user.id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "ok": True,
        "reused_pending_order": False,
        "message": "订单已创建，但当前还未接入真实网页支付回调。你可以先用它联调前端流程，后续再接支付平台。",
        "order": _serialize_order(created_order),
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
        _close_expired_pending_orders(conn, user.id)
        rows = conn.execute(
            f"""
            SELECT {ORDER_SELECT_FIELDS}
            FROM membership_orders
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (user.id, safe_limit),
        ).fetchall()
        return {"orders": [_serialize_order(row) for row in rows]}
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
        _close_expired_pending_orders(conn, user.id)
        row = _fetch_order_by_no(conn, order_no=order_no, user_id=user.id)
        if not row:
            raise HTTPException(status_code=404, detail="订单不存在")
        return {"order": _serialize_order(row)}
    finally:
        conn.close()


@router.post("/billing/orders/{order_no}/cancel")
def billing_cancel_order(
    order_no: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """主动取消一笔待支付订单。"""
    conn = get_conn()
    try:
        _close_expired_pending_orders(conn, user.id, commit=False)
        order = _cancel_pending_order(conn, user_id=user.id, order_no=order_no, commit=False)
        conn.commit()
        return {
            "ok": True,
            "message": "订单已取消",
            "order": order,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
