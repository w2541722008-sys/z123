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
from repositories import user_repository as user_repo
from services.cache_service import invalidate_user
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

@router.get("/admin/users")
def admin_list_users(
    search: str = "",
    plan: str = "",
    page: int = 1,
    limit: int = 20,
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    管理后台：查看用户列表，支持搜索、档位筛选和分页。

    参数：
        search: 按邮箱或昵称模糊搜索
        plan: 按档位筛选（free/vip/svip）
        page: 页码（从 1 开始）
        limit: 每页条数（最多 100）
    """
    _validate_pagination_params(page, limit, max_limit=100)

    # 动态构建 WHERE 条件
    conditions = []
    params: list[Any] = []

    if search:
        conditions.append("(email LIKE %s OR nickname LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])
    if plan:
        conditions.append("plan_type = %s")
        params.append(plan)

    where_clause = _build_where_clause(conditions)

    # 查询总数
    total = _count_with_where(conn, "FROM users", where_clause, params)

    # 查询列表（分页）
    offset, safe_limit = _normalize_pagination(page, limit, max_limit=100)

    rows = user_repo.list_users(
        conn,
        where_clause=where_clause,
        params=tuple(params),
        limit=safe_limit,
        offset=offset,
    )

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


@router.get("/admin/users/export")
def admin_export_users(conn: ConnType = Depends(get_db_dep)) -> list[dict[str, Any]]:
    """
    管理后台：导出全部用户 CSV 数据（不分页，返回完整列表）。
    """
    rows = user_repo.export_all_users(conn)

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


@router.get("/admin/users/{user_id}")
def admin_get_user(user_id: str, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
    """
    管理后台：获取用户详情（含对话数、关联角色数）。
    """
    row = user_repo.get_user_by_id(conn, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 对话统计
    chat_row = user_repo.get_user_stats(conn, user_id)

    # 关联角色数
    linked_char_count = user_repo.get_user_linked_char_count(conn, user_id)

    # 最后登录时间（从 ai_request_logs 推断）
    last_login = user_repo.get_user_last_login(conn, user_id)

    plan_info = serialize_plan_info(row["plan_type"], row.get("plan_expires_at"))

    return {
        "id": row["id"],
        "email": row["email"],
        "nickname": row["nickname"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_login": last_login,
        "chat_count": chat_row["chat_count"] if chat_row else 0,
        "char_count": chat_row["char_count"] if chat_row else 0,
        "linked_char_count": linked_char_count,
        **plan_info,
    }


@router.patch("/admin/users/{user_id}")
def admin_edit_user(
    user_id: str,
    body: AdminUserEditPayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    管理后台：编辑用户邮箱或昵称。
    路由：PATCH /api/admin/users/{user_id}（通过 /api/admin 挂载点）
    """
    user_row = user_repo.get_user_id_email(conn, user_id)
    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    updates: dict[str, Any] = {}
    if body.email is not None:
        updates["email"] = body.email.strip()
    if body.nickname is not None:
        updates["nickname"] = body.nickname.strip()

    if not updates:
        raise HTTPException(status_code=400, detail="没有提供任何更新字段")

    # 白名单校验：确保 f-string 拼接的列名来自安全来源
    # 注意：不使用 assert，因为 python -O 会跳过 assert 导致安全防护失效
    _ALLOWED_USER_UPDATE_FIELDS = {"email", "nickname"}
    invalid_fields = set(updates.keys()) - _ALLOWED_USER_UPDATE_FIELDS
    if invalid_fields:
        raise HTTPException(status_code=400, detail=f"非法更新字段: {invalid_fields}")

    user_repo.update_user_fields(conn, user_id, updates)

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

    # 清除用户缓存，确保前台获取最新数据
    invalidate_user(str(user_id))

    return {
        "ok": True,
        "message": f"用户 {user_row['email']} 信息已更新",
        "updated_fields": list(updates.keys()),
    }


@router.delete("/admin/users/{user_id}")
def admin_delete_user(
    user_id: str,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
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
    user_row = user_repo.get_user_id_email(conn, user_id)
    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 按顺序删除关联数据
    user_repo.delete_user_cascade(conn, user_id)

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


@router.post("/admin/users/batch-plan")
def admin_batch_update_plan(
    body: AdminBatchPlanPayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    管理后台：批量设置用户档位。
    """
    if body.plan_type == "free":
        plan_expires_at = None
    else:
        plan_expires_at = (
            datetime.now(timezone.utc) + timedelta(days=body.duration_days)
        )

    updated = 0
    for uid in body.user_ids:
        user_repo.update_user_plan(conn, uid, body.plan_type, plan_expires_at)
        invalidate_user(str(uid))
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


@router.post("/admin/users/{user_id}/plan")
def admin_update_user_plan(
    user_id: str,
    body: AdminUserPlanUpdatePayload,
    current_user: CurrentUser = Depends(get_admin_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """管理后台：手动设置某个用户的会员档位。"""
    user_row = user_repo.get_user_id_email_nickname(conn, user_id)
    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    if body.plan_type == "free":
        plan_expires_at = None
    else:
        plan_expires_at = (datetime.now(timezone.utc) + timedelta(days=body.duration_days))

    user_repo.update_user_plan(conn, user_id, body.plan_type, plan_expires_at)

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

    invalidate_user(str(user_id))

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
