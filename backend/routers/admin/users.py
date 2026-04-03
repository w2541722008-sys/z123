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
from models import (
    AdminUserPlanUpdatePayload,
    AdminUserEditPayload,
    AdminBatchPlanPayload,
)
from services.plan_service import plan_display_name, serialize_plan_info

router = APIRouter(dependencies=[Depends(get_admin_user)], tags=["admin"])

from ._shared import _ADMIN_EDITABLE_FIELDS, _transaction, _write_audit_log

@router.get("/admin/users")
def admin_list_users(
    search: str = "",
    plan: str = "",
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """
    管理后台：查看用户列表，支持搜索、档位筛选和分页。

    参数：
        search: 按邮箱或昵称模糊搜索
        plan: 按档位筛选（free/vip/svip）
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
            conditions.append("(email LIKE %s OR nickname LIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        if plan:
            conditions.append("plan_type = %s")
            params.append(plan)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # 查询总数
        count_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM users {where_clause}",
            tuple(params),
        ).fetchone()
        total = count_row["total"]

        # 查询列表（分页）
        offset = (max(1, page) - 1) * min(limit, 100)
        safe_limit = min(limit, 100)

        rows = conn.execute(
            f"""
            SELECT id, email, COALESCE(nickname, '') AS nickname,
                   COALESCE(plan_type, 'free') AS plan_type,
                   COALESCE(CAST(plan_expires_at AS VARCHAR), '') AS plan_expires_at,
                   created_at, updated_at
            FROM users
            {where_clause}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params) + (safe_limit, offset),
        ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            plan_info = serialize_plan_info(row["plan_type"], row["plan_expires_at"])
            items.append({
                "id": row["id"],
                "email": row["email"],
                "nickname": row["nickname"] or row["email"].split("@")[0],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                **plan_info,
            })

        return {
            "total": total,
            "page": page,
            "limit": safe_limit,
            "items": items,
        }
    finally:
        conn.close()


@router.get("/admin/users/export")
def admin_export_users() -> list[dict[str, Any]]:
    """
    管理后台：导出全部用户 CSV 数据（不分页，返回完整列表）。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.email, COALESCE(u.nickname, '') AS nickname,
                   COALESCE(u.plan_type, 'free') AS plan_type,
                   COALESCE(CAST(u.plan_expires_at AS VARCHAR), '') AS plan_expires_at,
                   u.created_at, u.updated_at,
                   COALESCE(c.chat_count, 0) AS chat_count,
                   COALESCE(c.char_count, 0) AS char_count,
                   COALESCE(p.char_count, 0) AS linked_char_count
            FROM users u
            LEFT JOIN (
                SELECT user_id,
                       COUNT(*) AS chat_count,
                       SUM(COALESCE(LENGTH(content), 0)) AS char_count
                FROM chat_messages
                GROUP BY user_id
            ) c ON c.user_id = u.id
            LEFT JOIN (
                SELECT user_id, COUNT(*) AS char_count
                FROM user_character_profiles
                GROUP BY user_id
            ) p ON p.user_id = u.id
            ORDER BY u.id DESC
            """
        ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            plan_info = serialize_plan_info(row["plan_type"], row["plan_expires_at"])
            items.append({
                "id": row["id"],
                "email": row["email"],
                "nickname": row["nickname"] or row["email"].split("@")[0],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "chat_count": row["chat_count"],
                "char_count": row["char_count"],
                "linked_char_count": row["linked_char_count"],
                **plan_info,
            })
        return items
    finally:
        conn.close()


@router.get("/admin/users/{user_id}")
def admin_get_user(user_id: str) -> dict[str, Any]:
    """
    管理后台：获取用户详情（含对话数、关联角色数）。
    """
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 对话统计
        chat_row = conn.execute(
            """
            SELECT COUNT(*) AS chat_count,
                   COALESCE(SUM(LENGTH(content)), 0) AS char_count
            FROM chat_messages WHERE user_id = %s
            """,
            (user_id,),
        ).fetchone()

        # 关联角色数
        char_row = conn.execute(
            "SELECT COUNT(*) AS char_count FROM user_character_profiles WHERE user_id = %s",
            (user_id,),
        ).fetchone()

        # 最后登录时间（从 ai_request_logs 推断）
        last_login_row = conn.execute(
            "SELECT MAX(created_at) AS last_login FROM ai_request_logs WHERE user_id = %s",
            (user_id,),
        ).fetchone()

        plan_info = serialize_plan_info(row["plan_type"], row.get("plan_expires_at"))

        return {
            "id": row["id"],
            "email": row["email"],
            "nickname": row["nickname"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login": last_login_row["last_login"] if last_login_row else None,
            "chat_count": chat_row["chat_count"] if chat_row else 0,
            "char_count": chat_row["char_count"] if chat_row else 0,
            "linked_char_count": char_row["char_count"] if char_row else 0,
            **plan_info,
        }
    finally:
        conn.close()


@router.patch("/admin/users/{user_id}")
def admin_edit_user(
    user_id: str,
    body: AdminUserEditPayload,
    current_user: CurrentUser = Depends(get_admin_user),
) -> dict[str, Any]:
    """
    管理后台：编辑用户邮箱或昵称。
    路由：PATCH /api/admin/users/{user_id}（通过 /api/admin 挂载点）
    """
    conn = get_conn()
    try:
        user_row = conn.execute(
            "SELECT id, email FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="用户不存在")

        updates: dict[str, Any] = {}
        if body.email is not None:
            updates["email"] = body.email.strip()
        if body.nickname is not None:
            updates["nickname"] = body.nickname.strip()

        if not updates:
            raise HTTPException(status_code=400, detail="没有提供任何更新字段")

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        conn.execute(
            f"UPDATE users SET {set_clause}, updated_at = %s WHERE id = %s",
            list(updates.values()) + [utc_now_iso(), user_id],
        )

        # 写入审计日志
        _write_audit_log(
            conn,
            operator_id=current_user.id,
            operator_email=current_user.email,
            action="edit_user",
            target_type="user",
            target_id=str(user_id),
            detail={"updated_fields": updates, "target_email": user_row["email"]},
        )
        conn.commit()

        return {
            "ok": True,
            "message": f"用户 {user_row['email']} 信息已更新",
            "updated_fields": list(updates.keys()),
        }
    finally:
        conn.close()


@router.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: str,
    current_user: CurrentUser = Depends(get_admin_user),
) -> dict[str, Any]:
    """
    管理后台：删除用户及其关联数据（聊天记录、角色关系、订单）。

    关联数据清理顺序：
    1. ai_request_logs（依赖 user_id）
    2. chat_messages（依赖 user_id）
    3. user_character_profiles（依赖 user_id）
    4. membership_orders（依赖 user_id）
    5. users（最后删用户本身）
    """
    conn = get_conn()
    try:
        user_row = conn.execute(
            "SELECT id, email FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 按顺序删除关联数据
        conn.execute("DELETE FROM ai_request_logs WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM chat_messages WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM user_character_profiles WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM membership_orders WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))

        # 写入审计日志
        _write_audit_log(
            conn,
            operator_id=current_user.id,
            operator_email=current_user.email,
            action="delete_user",
            target_type="user",
            target_id=str(user_id),
            detail={"deleted_email": user_row["email"]},
        )
        conn.commit()

        return {
            "ok": True,
            "message": f"用户 {user_row['email']}（ID: {user_id}）已删除，关联数据已清理",
        }
    finally:
        conn.close()


@router.post("/admin/users/batch-plan")
def admin_batch_update_plan(
    body: AdminBatchPlanPayload,
    current_user: CurrentUser = Depends(get_admin_user),
) -> dict[str, Any]:
    """
    管理后台：批量设置用户档位。
    """
    conn = get_conn()
    try:
        if body.plan_type == "free":
            plan_expires_at = ""
        else:
            plan_expires_at = (
                datetime.now(timezone.utc) + timedelta(days=body.duration_days)
            ).isoformat()

        updated = 0
        for uid in body.user_ids:
            conn.execute(
                "UPDATE users SET plan_type = %s, plan_expires_at = %s, updated_at = %s WHERE id = %s",
                (body.plan_type, plan_expires_at, utc_now_iso(), uid),
            )
            updated += 1

        _write_audit_log(
            conn,
            operator_id=current_user.id,
            operator_email=current_user.email,
            action="batch_update",
            target_type="user",
            target_id=None,
            detail={
                "user_ids": body.user_ids,
                "plan_type": body.plan_type,
                "duration_days": body.duration_days,
            },
        )
        conn.commit()

        return {
            "ok": True,
            "message": f"已为 {updated} 位用户设置为 {plan_display_name(body.plan_type)}",
            "updated_count": updated,
        }
    finally:
        conn.close()


@router.post("/admin/users/{user_id}/plan")
def admin_update_user_plan(
    user_id: str,
    body: AdminUserPlanUpdatePayload,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """管理后台：手动设置某个用户的会员档位。"""
    conn = get_conn()
    try:
        user_row = conn.execute(
            "SELECT id, email, COALESCE(nickname, '') AS nickname FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="用户不存在")

        if body.plan_type == "free":
            plan_expires_at = ""
        else:
            plan_expires_at = (datetime.now(timezone.utc) + timedelta(days=body.duration_days)).isoformat()

        conn.execute(
            "UPDATE users SET plan_type = %s, plan_expires_at = %s, updated_at = %s WHERE id = %s",
            (body.plan_type, plan_expires_at, utc_now_iso(), user_id),
        )

        # 记录审计日志
        _write_audit_log(
            conn,
            operator_id=current_user.id,
            operator_email=current_user.email,
            action="update_user_plan",
            target_type="user",
            target_id=user_id,
            detail={
                "email": user_row["email"],
                "nickname": user_row["nickname"],
                "new_plan": body.plan_type,
                "duration_days": body.duration_days,
                "plan_expires_at": plan_expires_at,
            },
        )
        
        conn.commit()

        plan_info = serialize_plan_info(body.plan_type, plan_expires_at)
        return {
            "ok": True,
            "message": f"已将用户 {user_row['email']} 设置为 {plan_display_name(plan_info['effective_plan'])}",
            "user": {
                "id": user_row["id"],
                "email": user_row["email"],
                "nickname": user_row["nickname"] or user_row["email"].split("@")[0],
                **plan_info,
            },
        }
    finally:
        conn.close()



