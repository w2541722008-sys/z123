"""
管理后台路由 - 处理角色管理、调试接口、高级配置

端点：
    GET  /api/admin/characters                    - 角色列表（管理后台）
    POST /api/admin/characters                    - 新建角色
    GET  /api/admin/character/{id}                - 角色详情
    POST /api/admin/character/{id}                - 更新角色
    DELETE /api/admin/character/{id}              - 删除角色
    
    # 高级配置 - 记忆条目
    GET  /api/admin/character/{id}/memories       - 获取记忆条目列表
    POST /api/admin/character/{id}/memories       - 创建记忆条目
    PUT  /api/admin/character/{id}/memories/{mid} - 更新记忆条目
    DELETE /api/admin/character/{id}/memories/{mid} - 删除记忆条目
    
    # 高级配置 - 开场白
    GET  /api/admin/character/{id}/greetings      - 获取开场白列表
    POST /api/admin/character/{id}/greetings      - 创建开场白
    PUT  /api/admin/character/{id}/greetings/{gid} - 更新开场白
    DELETE /api/admin/character/{id}/greetings/{gid} - 删除开场白
    
    # 高级配置 - 剧情线
    GET  /api/admin/character/{id}/storylines     - 获取剧情线列表
    POST /api/admin/character/{id}/storylines     - 创建剧情线
    PUT  /api/admin/character/{id}/storylines/{sid} - 更新剧情线
    DELETE /api/admin/character/{id}/storylines/{sid} - 删除剧情线
    
    # 高级配置 - 后置规则
    GET  /api/admin/character/{id}/post-rules     - 获取后置规则列表
    POST /api/admin/character/{id}/post-rules     - 创建后置规则
    PUT  /api/admin/character/{id}/post-rules/{rid} - 更新后置规则
    DELETE /api/admin/character/{id}/post-rules/{rid} - 删除后置规则
    
    # 高级配置 - 剧情事件
    GET  /api/admin/character/{id}/story-events   - 获取剧情事件列表
    POST /api/admin/character/{id}/story-events   - 创建剧情事件
    PUT  /api/admin/character/{id}/story-events/{eid} - 更新剧情事件
    DELETE /api/admin/character/{id}/story-events/{eid} - 删除剧情事件
    
    # 高级配置 - 记忆分类
    GET  /api/admin/character/{id}/memory-categories - 获取记忆分类列表
    POST /api/admin/character/{id}/memory-categories - 创建记忆分类
    PUT  /api/admin/character/{id}/memory-categories/{cid} - 更新记忆分类
    DELETE /api/admin/character/{id}/memory-categories/{cid} - 删除记忆分类
    
    # 高级配置 - 关键词测试
    POST /api/admin/character/{id}/test-keywords  - 测试关键词匹配
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
    AdminUpdatePayload,
    AdminUserPlanUpdatePayload,
    AdminUserEditPayload,
    AdminBatchPlanPayload,
    MemoryEntryPayload,
    GreetingPayload,
    StorylinePayload,
    KeywordTestPayload,
    PostRulePayload,
    StoryEventPayload,
    MemoryCategoryPayload,
)
from services.memory_service import get_summary_for_prompt
from utils.json_utils import parse_json_list, parse_json_object
from services.plan_service import plan_display_name, serialize_plan_info
from services.cache_service import cache_delete, invalidate_character
from services.db_monitor import get_stats, reset_stats
from prompt_assembler import build_message_preview

router = APIRouter(dependencies=[Depends(get_admin_user)])

# 管理后台可编辑的字段白名单
_ADMIN_EDITABLE_FIELDS = {
    "name", "abbr", "subtitle", "description", "tags",
    "opening_message", "system_prompt", "sort_order",
    "is_visible", "home_priority", "card_type",
    "required_plan",
    "affection_enabled", "affection_rules_json",
    "import_locked", "avatar_url", "cover_url",
}


# ============================================================
# 事务管理辅助函数
# ============================================================
def _transaction(conn, func):
    """
    在事务中执行函数，出错时自动回滚。
    
    用法:
        conn = get_conn()
        try:
            def _do_work():
                conn.execute("INSERT ...")
                conn.execute("UPDATE ...")
                return result
            result = _transaction(conn, _do_work)
        finally:
            conn.close()
    """
    try:
        result = func()
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e


@router.get("/admin/characters")
def admin_list_characters() -> list[dict[str, Any]]:
    """管理后台：获取所有角色列表（包含隐藏角色）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, name, abbr, subtitle, avatar_url, description, tags,
                   card_type, required_plan, is_visible, home_priority, sort_order
            FROM characters
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "abbr": row["abbr"],
                "subtitle": row["subtitle"] or "",
                "avatar_url": row["avatar_url"] or "",
                "description": (row["description"] or "")[:100] + "..." if row["description"] else "",
                "tags": parse_json_list(row["tags"]),
                "card_type": row["card_type"] or "intimate",
                "required_plan": row["required_plan"] or "guest",
                "is_visible": bool(row["is_visible"]),
                "home_priority": row["home_priority"],
                "sort_order": row["sort_order"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/characters")
def admin_create_character(
    body: dict[str, Any],
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    管理后台：创建新角色。
    
    必填字段：id, name, system_prompt
    可选字段：abbr, subtitle, description, opening_message, tags, card_type, home_priority, is_visible
    """
    # 验证必填字段
    char_id = body.get("id", "").strip()
    name = body.get("name", "").strip()
    system_prompt = body.get("system_prompt", "").strip()
    
    if not char_id:
        raise HTTPException(status_code=400, detail="角色ID不能为空")
    if not name:
        raise HTTPException(status_code=400, detail="角色名不能为空")
    if not system_prompt:
        raise HTTPException(status_code=400, detail="主指令（System Prompt）不能为空")
    
    # 验证ID格式
    if not char_id.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="角色ID只能包含英文、数字和下划线")
    
    conn = get_conn()
    try:
        def _do_create():
            # 检查ID是否已存在
            existing = conn.execute(
                "SELECT id FROM characters WHERE id = %s",
                (char_id,)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail=f"角色ID '{char_id}' 已存在")
            
            # 准备数据
            abbr = body.get("abbr", name).strip() or name
            subtitle = body.get("subtitle", "").strip()
            description = body.get("description", "").strip()
            opening_message = body.get("opening_message", "").strip()
            tags = body.get("tags", "[]")
            card_type = body.get("card_type", "intimate")
            required_plan = body.get("required_plan", "guest")
            avatar_url = body.get("avatar_url", "").strip()
            cover_url = body.get("cover_url", "").strip()
            home_priority = int(body.get("home_priority", 10))
            is_visible = 1 if body.get("is_visible", True) else 0
            
            # 验证tags是有效的JSON
            try:
                import json
                tags_list = json.loads(tags) if tags else []
                if not isinstance(tags_list, list):
                    raise HTTPException(status_code=400, detail="tags必须是JSON数组格式")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="tags格式错误，必须是有效的JSON")
            
            # 验证card_type和required_plan
            valid_card_types = ["intimate", "friend", "mentor", "entertainment"]
            valid_plans = ["guest", "free", "vip", "svip"]
            if card_type not in valid_card_types:
                raise HTTPException(status_code=400, detail=f"card_type必须是以下之一: {', '.join(valid_card_types)}")
            if required_plan not in valid_plans:
                raise HTTPException(status_code=400, detail=f"required_plan必须是以下之一: {', '.join(valid_plans)}")
            
            # 验证home_priority范围
            if not (0 <= home_priority <= 9999):
                raise HTTPException(status_code=400, detail="home_priority必须在0-9999之间")
            
            # 插入新角色
            conn.execute(
                """
                INSERT INTO characters (
                    id, name, abbr, subtitle, avatar_url, cover_url, description,
                    system_prompt, opening_message, tags,
                    card_type, required_plan, home_priority, is_visible, sort_order,
                    mock_reply_style, asset_type, source_kind, source_path,
                    embedded_format, raw_card_json, structured_asset_json,
                    import_diagnostics, import_locked, affection_enabled, affection_rules_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    char_id, name, abbr, subtitle, avatar_url, cover_url, description,
                    system_prompt, opening_message, tags,
                    card_type, required_plan, home_priority, is_visible, home_priority,
                    "温柔、体贴、会关心人", "character", "manual", "",
                    "json", "", "{}",
                    "[]", 0, 1, "{}"
                )
            )
            
            # 记录审计日志
            _write_audit_log(
                conn,
                operator_id=current_user.id,
                operator_email=current_user.email,
                action="create_character",
                target_type="character",
                target_id=char_id,
                detail={"name": name, "card_type": card_type, "required_plan": required_plan},
            )
            
            return {"ok": True, "id": char_id, "message": f"角色 '{name}' 创建成功"}
        
        result = _transaction(conn, _do_create)
        
        # 清除角色列表缓存（在事务外执行）
        cache_delete("character_list_all")
        
        return result
    finally:
        conn.close()


@router.get("/admin/character/{character_id}")
def admin_get_character(character_id: str) -> dict[str, Any]:
    """管理后台：获取角色详情。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 解析结构化数据 - 优先使用 runtime_cache_json（这是真正用于 Prompt 组装的数据）
        runtime_layers = parse_json_object(row.get("runtime_cache_json"), fallback={})
        if not runtime_layers:
            # 如果没有 runtime_cache_json，尝试从 structured_asset_json 读取
            structured = parse_json_object(row.get("structured_asset_json"), fallback={})
            runtime_layers = structured.get("runtime_layers", {})

        # 把 runtime_layers 的列表值转成字符串（方便编辑）
        runtime_layers_str = {}
        for k, v in runtime_layers.items():
            if isinstance(v, list):
                runtime_layers_str[k] = "\n---\n".join(str(x) for x in v)
            else:
                runtime_layers_str[k] = str(v)

        return {
            "id": row["id"],
            "name": row["name"],
            "abbr": row["abbr"],
            "subtitle": row["subtitle"] or "",
            "avatar_url": row["avatar_url"] or "",
            "cover_url": row["cover_url"] or "",
            "description": row["description"] or "",
            "tags": parse_json_list(row["tags"]),
            "opening_message": row["opening_message"] or "",
            "system_prompt": row["system_prompt"] or "",
            "sort_order": row["sort_order"],
            "is_visible": bool(row["is_visible"]),
            "home_priority": row["home_priority"],
            "card_type": row["card_type"] or "intimate",
            "required_plan": row["required_plan"] or "guest",
            "affection_enabled": bool(row["affection_enabled"]),
            "affection_rules_json": row["affection_rules_json"] or "{}",
            "import_locked": bool(row["import_locked"]),
            "source_kind": row["source_kind"],
            "source_path": row["source_path"],
            "asset_type": row["asset_type"] or "character",
            "embedded_format": row["embedded_format"] or "json",
            "mock_reply_style": row["mock_reply_style"] or "",
            "import_diagnostics": row["import_diagnostics"] or "[]",
            "runtime_layers": runtime_layers_str,
        }
    finally:
        conn.close()


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


@router.delete("/admin/character/{character_id}")
def admin_delete_character(
    character_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """管理后台：删除角色及其关联配置/记录。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, name FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 删除关联数据（按依赖关系顺序）
        # 1. 用户角色关联数据
        conn.execute("DELETE FROM user_character_profiles WHERE character_id = %s", (character_id,))
        # 2. 角色状态数据
        conn.execute("DELETE FROM character_states WHERE character_id = %s", (character_id,))
        # 3. 开场白数据
        conn.execute("DELETE FROM character_greetings WHERE character_id = %s", (character_id,))
        # 4. 记忆条目
        conn.execute("DELETE FROM character_memories WHERE character_id = %s", (character_id,))
        # 5. 记忆分类
        conn.execute("DELETE FROM memory_categories WHERE character_id = %s", (character_id,))
        # 6. 后置规则
        conn.execute("DELETE FROM character_post_rules WHERE character_id = %s", (character_id,))
        # 7. 剧情事件
        conn.execute("DELETE FROM story_events WHERE character_id = %s", (character_id,))
        # 8. 剧情线
        conn.execute("DELETE FROM character_storylines WHERE character_id = %s", (character_id,))
        # 9. 最后删除角色本身
        conn.execute("DELETE FROM characters WHERE id = %s", (character_id,))
        
        # 记录审计日志
        _write_audit_log(
            conn,
            operator_id=current_user.id,
            operator_email=current_user.email,
            action="delete_character",
            target_type="character",
            target_id=character_id,
            detail={"name": row["name"]},
        )
        
        conn.commit()
        
        # 清除缓存
        invalidate_character(character_id)
        cache_delete("character_list_all")
        
        return {"ok": True, "id": character_id, "name": row["name"]}
    finally:
        conn.close()


@router.post("/admin/character/{character_id}")
def admin_update_character(
    character_id: str,
    body: AdminUpdatePayload,
) -> dict[str, Any]:
    """
    管理后台：更新角色指定字段。
    
    支持 rl__XXX 前缀写回 runtime_layers。
    """
    # 分离普通字段和 rl__ 字段
    safe_direct = {k: v for k, v in body.updates.items() if k in _ADMIN_EDITABLE_FIELDS}
    rl_updates = {k[4:]: v for k, v in body.updates.items() if k.startswith("rl__")}

    if not safe_direct and not rl_updates:
        raise HTTPException(status_code=400, detail="没有合法的可更新字段")

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, structured_asset_json FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 1. 直接更新普通字段
        if safe_direct:
            set_clause = ", ".join(f"{k} = %s" for k in safe_direct)
            conn.execute(
                f"UPDATE characters SET {set_clause} WHERE id = %s",
                list(safe_direct.values()) + [character_id],
            )

        # 2. 更新 structured_asset_json 和 runtime_cache_json 里的 runtime_layers
        if rl_updates:
            try:
                # 优先从 structured_asset_json 读取，没有则从 runtime_cache_json 读取
                sj_raw = row.get("structured_asset_json") or "{}"
                sj = json.loads(sj_raw) if sj_raw else {}
                
                # 如果没有 structured_asset_json，尝试从 runtime_cache_json 构建
                if not sj:
                    rc_raw = row.get("runtime_cache_json") or "{}"
                    rc = json.loads(rc_raw) if rc_raw else {}
                    sj = {"runtime_layers": rc}
                
                rl = sj.setdefault("runtime_layers", {})
                for k, v in rl_updates.items():
                    orig = rl.get(k)
                    if isinstance(orig, list) and isinstance(v, str):
                        rl[k] = [x.strip() for x in v.split("\n---\n") if x.strip()]
                    else:
                        rl[k] = v
                
                # 同时更新两个字段，确保一致性
                new_structured_json = json.dumps(sj, ensure_ascii=False)
                new_runtime_json = json.dumps(rl, ensure_ascii=False)
                
                conn.execute(
                    "UPDATE characters SET structured_asset_json = %s, runtime_cache_json = %s WHERE id = %s",
                    (new_structured_json, new_runtime_json, character_id),
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"更新 runtime_layers 失败: {e}")

        conn.commit()
        
        # 清除缓存
        invalidate_character(character_id)
        cache_delete("character_list_all")
        
        return {"ok": True, "updated": list(safe_direct.keys()) + [f"rl__{k}" for k in rl_updates]}
    finally:
        conn.close()


def _split_csv_ids(raw: str | None) -> list[str]:
    """将逗号分隔的 ID 字符串拆分为列表（兼容 int 和 uuid 格式）。"""
    out: list[str] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(part)
    return out


def _affection_rules_use_default(raw: Any) -> bool:
    """判断是否处于“留空即使用系统默认规则”的状态。"""
    text = str(raw or "").strip()
    if not text:
        return True
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and len(parsed) == 0


def _basic_config_warnings(character: dict[str, Any], runtime_layers: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not (character.get("name") or "").strip():
        warnings.append("角色名为空")
    if not (character.get("system_prompt") or "").strip():
        warnings.append("主指令 system_prompt 为空")
    if not (character.get("opening_message") or "").strip():
        warnings.append("默认开场白为空")
    if not str(runtime_layers.get("base_profile") or "").strip():
        warnings.append("runtime_layers.base_profile 为空")
    if not str(runtime_layers.get("examples") or "").strip():
        warnings.append("示例对话 examples 为空")
    if character.get("is_visible") and not (character.get("subtitle") or "").strip():
        warnings.append("角色已设为可见，但副标题为空")
    if character.get("affection_enabled"):
        raw_rules = character.get("affection_rules_json")
        if not _affection_rules_use_default(raw_rules):
            rules = parse_json_object(raw_rules, fallback={})
            if not rules:
                warnings.append("已启用好感度系统，但好感度规则 JSON 无法解析，请检查格式")
    return warnings



@router.get("/admin/character/{character_id}/config-summary")
def admin_character_config_summary(character_id: str) -> dict[str, Any]:
    """角色配置概览与健康检查。"""
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT id, name, subtitle, opening_message, system_prompt, is_visible,
                   card_type,
                   affection_enabled, affection_rules_json, structured_asset_json
            FROM characters
            WHERE id = %s
            """,
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        structured = parse_json_object(row["structured_asset_json"], fallback={})
        runtime_layers = structured.get("runtime_layers", {}) or {}

        counts = {
            "memory_count": conn.execute("SELECT COUNT(*) FROM character_memories WHERE character_id = %s", (character_id,)).fetchone()["count"],
            "memory_category_count": conn.execute("SELECT COUNT(*) FROM memory_categories WHERE character_id = %s", (character_id,)).fetchone()["count"],
            "greeting_count": conn.execute("SELECT COUNT(*) FROM character_greetings WHERE character_id = %s", (character_id,)).fetchone()["count"],
            "storyline_count": conn.execute("SELECT COUNT(*) FROM character_storylines WHERE character_id = %s", (character_id,)).fetchone()["count"],
            "post_rule_count": conn.execute("SELECT COUNT(*) FROM character_post_rules WHERE character_id = %s", (character_id,)).fetchone()["count"],
            "story_event_count": conn.execute("SELECT COUNT(*) FROM story_events WHERE character_id = %s", (character_id,)).fetchone()["count"],
        }
        active_counts = {
            "memory_count": conn.execute("SELECT COUNT(*) FROM character_memories WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
            "greeting_count": conn.execute("SELECT COUNT(*) FROM character_greetings WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
            "storyline_count": conn.execute("SELECT COUNT(*) FROM character_storylines WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
            "post_rule_count": conn.execute("SELECT COUNT(*) FROM character_post_rules WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
            "story_event_count": conn.execute("SELECT COUNT(*) FROM story_events WHERE character_id = %s AND is_active = 1", (character_id,)).fetchone()["count"],
        }
        greeting_phase_coverage = len(conn.execute(
            "SELECT DISTINCT story_phase FROM character_greetings WHERE character_id = %s AND is_active = 1",
            (character_id,),
        ).fetchall())

        default_storyline_id_row = conn.execute(
            "SELECT id FROM character_storylines WHERE character_id = %s AND is_default = 1 ORDER BY id ASC LIMIT 1",
            (character_id,),
        ).fetchone()
        active_greetings = conn.execute(
            "SELECT COUNT(*) FROM character_greetings WHERE character_id = %s AND is_active = 1",
            (character_id,),
        ).fetchone()["count"]

        warnings = _basic_config_warnings(dict(row), runtime_layers)
        if counts["memory_count"] > 0 and active_counts["memory_count"] == 0:
            warnings.append("存在记忆条目，但全部处于禁用状态")
        elif 0 < active_counts["memory_count"] < 3:
            warnings.append("启用中的记忆条目较少，建议至少准备 3 条高频记忆")
        if counts["storyline_count"] > 0 and not default_storyline_id_row:
            warnings.append("存在剧情线，但未设置默认剧情线")
        if counts["greeting_count"] > 0 and active_greetings == 0:
            warnings.append("存在开场白，但全部处于禁用状态")
        elif counts["greeting_count"] > 0 and greeting_phase_coverage < 2:
            warnings.append("开场白阶段覆盖偏少，建议至少覆盖 2 个关系阶段")
        if counts["post_rule_count"] > 0 and active_counts["post_rule_count"] == 0:
            warnings.append("存在后置规则，但全部处于禁用状态")
        if row["card_type"] in {"intimate", "scenario"} and counts["greeting_count"] == 0:
            warnings.append("当前角色还没有多阶段开场白，首次体验会偏单一")

        empty_unlock_event_count = 0
        empty_event_content_count = 0
        if counts["story_event_count"] > 0:
            events = conn.execute(
                "SELECT id, unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id, event_content FROM story_events WHERE character_id = %s",
                (character_id,),
            ).fetchall()
            valid_memory_ids = {r["id"] for r in conn.execute("SELECT id FROM character_memories WHERE character_id = %s", (character_id,)).fetchall()}
            valid_greeting_ids = {r["id"] for r in conn.execute("SELECT id FROM character_greetings WHERE character_id = %s", (character_id,)).fetchall()}
            valid_storyline_ids = {r["id"] for r in conn.execute("SELECT id FROM character_storylines WHERE character_id = %s", (character_id,)).fetchall()}
            for event in events:
                bad_m = [x for x in _split_csv_ids(event["unlocked_memory_ids"]) if x not in valid_memory_ids]
                bad_g = [x for x in _split_csv_ids(event["unlocked_greeting_ids"]) if x not in valid_greeting_ids]
                bad_s = event["unlocked_storyline_id"] and event["unlocked_storyline_id"] not in valid_storyline_ids
                has_unlocks = bool(_split_csv_ids(event["unlocked_memory_ids"]) or _split_csv_ids(event["unlocked_greeting_ids"]) or event["unlocked_storyline_id"])
                has_event_content = bool((event["event_content"] or "").strip())
                if not has_unlocks:
                    empty_unlock_event_count += 1
                if not has_event_content:
                    empty_event_content_count += 1
                if bad_m or bad_g or bad_s:
                    warnings.append(f"剧情事件 #{event['id']} 存在失效的解锁对象引用")
                    break
        if empty_unlock_event_count:
            warnings.append(f"有 {empty_unlock_event_count} 个剧情事件还没有配置任何解锁内容。")
        if empty_event_content_count:
            warnings.append(f"有 {empty_event_content_count} 个剧情事件没有触发文案，剧情衔接可能偏生硬")

        checks = [
            bool((row["name"] or "").strip()),
            bool((row["system_prompt"] or "").strip()),
            bool((row["opening_message"] or "").strip()),
            bool(str(runtime_layers.get("base_profile") or "").strip()),
            bool(str(runtime_layers.get("examples") or "").strip()),
            active_counts["memory_count"] > 0,
            active_counts["greeting_count"] > 0,
            (row["card_type"] == "world") or greeting_phase_coverage >= 2,
            (not row["affection_enabled"]) or _affection_rules_use_default(row["affection_rules_json"]) or bool(parse_json_object(row["affection_rules_json"], fallback={})),
            counts["storyline_count"] == 0 or bool(default_storyline_id_row),
            counts["story_event_count"] == 0 or empty_unlock_event_count == 0,
        ]
        completion_score = round(sum(1 for x in checks if x) / len(checks) * 100)

        last_updated_candidates = []
        for table in ["character_memories", "memory_categories", "character_greetings", "character_storylines", "character_post_rules", "story_events"]:
            r = conn.execute(f"SELECT MAX(updated_at) as max FROM {table} WHERE character_id = %s", (character_id,)).fetchone()
            if r and r["max"]:
                # updated_at 可能是 datetime 对象或字符串，统一转字符串后比较
                last_updated_candidates.append(str(r["max"]))

        return {
            "character_id": row["id"],
            "name": row["name"],
            "subtitle": row["subtitle"] or "",
            "runtime_layer_count": len(runtime_layers),
            "default_storyline_id": default_storyline_id_row["id"] if default_storyline_id_row else None,
            "last_updated": max(last_updated_candidates) if last_updated_candidates else "",
            "completeness": completion_score,
            "warnings": warnings,
            "stats": {
                "memories": counts["memory_count"],
                "active_memories": active_counts["memory_count"],
                "categories": counts["memory_category_count"],
                "greetings": counts["greeting_count"],
                "active_greetings": active_counts["greeting_count"],
                "greeting_phase_coverage": greeting_phase_coverage,
                "storylines": counts["storyline_count"],
                "active_storylines": active_counts["storyline_count"],
                "post_rules": counts["post_rule_count"],
                "active_post_rules": active_counts["post_rule_count"],
                "events": counts["story_event_count"],
                "active_events": active_counts["story_event_count"],
                "empty_unlock_events": empty_unlock_event_count,
                "empty_event_content_events": empty_event_content_count,
            },
        }
    finally:
        conn.close()


@router.get("/admin/character/{character_id}/message-preview")
def admin_message_preview(
    character_id: str,
    affection: int = Query(30, description="好感度 (0-100)"),
    story_phase: str = Query("stranger", description="关系阶段 (stranger/acquaintance/friend/lover)"),
    mood: str = Query("neutral", description="心情 (neutral/happy/sad/angry/flirty)"),
    storyline_id: int | None = Query(None, description="当前剧情线ID"),
) -> dict[str, Any]:
    """管理后台：预览组装后的 Prompt 消息（无登录态，可配置角色状态）。
    
    查询参数：
        - affection: 好感度 (0-100)，默认 30
        - story_phase: 关系阶段，默认 stranger
        - mood: 心情，默认 neutral
        - storyline_id: 当前剧情线ID，可选
    """
    conn = get_conn()
    try:
        char_row = conn.execute("SELECT * FROM characters WHERE id = %s", (character_id,)).fetchone()
        if not char_row:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 构建角色状态
        character_state = {
            "affection": max(0, min(100, affection)),
            "story_phase": story_phase,
            "mood": mood,
            "storyline_id": storyline_id,
            "custom_vars": {},
        }

        preview = build_message_preview(
            character=char_row,
            recent_messages=[],
            memory_summary="",
            user_name="用户",
            character_state=character_state,
        )
        structured = parse_json_object(char_row["structured_asset_json"], fallback={})
        return {
            "character_id": character_id,
            "character_state": character_state,
            "message_count": preview.get("message_count", 0),
            "messages": preview.get("messages", []),
            "runtime_layers": preview.get("runtime_layers") or structured.get("runtime_layers", {}),
            "related_assets": preview.get("related_assets", []),
        }
    finally:
        conn.close()





# ============================================================
# 高级配置 API - 记忆条目
# ============================================================
def _assert_memory_category_owned(
    conn: Any,
    character_id: str,
    category_id: str | None,
) -> None:
    """category_id 必须属于该角色的记忆分类，否则 400。"""
    if category_id is None:
        return
    row = conn.execute(
        "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
        (category_id, character_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="分类不存在或不属于该角色")


def _assert_storyline_owned(
    conn: Any,
    character_id: str,
    storyline_id: str | None,
) -> None:
    """storyline_id 必须属于该角色，否则 400。"""
    if storyline_id is None:
        return
    row = conn.execute(
        "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
        (storyline_id, character_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="剧情线不存在或不属于该角色")


def _assert_story_event_unlock_refs_owned(
    conn: Any,
    character_id: str,
    unlocked_memory_ids: str | None,
    unlocked_greeting_ids: str | None,
    unlocked_storyline_id: str | None,
) -> None:
    """剧情事件的解锁目标必须都属于当前角色且处于启用状态。"""
    memory_ids = _split_csv_ids(unlocked_memory_ids)
    greeting_ids = _split_csv_ids(unlocked_greeting_ids)

    if memory_ids:
        valid_memory_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM character_memories WHERE character_id = %s AND is_active = 1",
                (character_id,),
            ).fetchall()
        }
        bad_ids = [x for x in memory_ids if x not in valid_memory_ids]
        if bad_ids:
            raise HTTPException(status_code=400, detail=f"存在无效或已禁用的记忆解锁对象：{bad_ids}")

    if greeting_ids:
        valid_greeting_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM character_greetings WHERE character_id = %s AND is_active = 1",
                (character_id,),
            ).fetchall()
        }
        bad_ids = [x for x in greeting_ids if x not in valid_greeting_ids]
        if bad_ids:
            raise HTTPException(status_code=400, detail=f"存在无效或已禁用的开场白解锁对象：{bad_ids}")

    # 验证剧情线是否属于当前角色且处于启用状态
    if unlocked_storyline_id:
        row = conn.execute(
            "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s AND is_active = 1",
            (unlocked_storyline_id, character_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="解锁的剧情线不存在、不属于该角色或已被禁用")


@router.get("/admin/character/{character_id}/memories")
def list_memories(character_id: str) -> list[dict[str, Any]]:
    """获取角色的记忆条目列表（World Info）。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, keywords, trigger_logic, content, category_id, position,
                   priority, is_active, comment, created_at, updated_at
            FROM character_memories
            WHERE character_id = %s
            ORDER BY priority ASC, id ASC
            """,
            (character_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "keywords": row["keywords"],
                "trigger_logic": row["trigger_logic"],
                "content": row["content"],
                "category_id": row["category_id"],
                "position": row["position"],
                "priority": row["priority"],
                "is_active": bool(row["is_active"]),
                "comment": row["comment"] or "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/memories")
def create_memory(
    character_id: str,
    body: MemoryEntryPayload,
) -> dict[str, Any]:
    """创建新的记忆条目。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        _assert_memory_category_owned(conn, character_id, body.category_id)

        now = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO character_memories
            (character_id, keywords, trigger_logic, content, category_id, position,
             priority, is_active, comment, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                body.keywords,
                body.trigger_logic,
                body.content,
                body.category_id,
                body.position,
                body.priority,
                body.is_active,
                body.comment,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"id": new_id, "ok": True}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/memories/{memory_id}")
def update_memory(
    character_id: str,
    memory_id: str,
    body: MemoryEntryPayload,
) -> dict[str, Any]:
    """更新记忆条目。"""
    conn = get_conn()
    try:
        # 检查记忆条目是否存在且属于该角色
        mem = conn.execute(
            "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
            (memory_id, character_id),
        ).fetchone()
        if not mem:
            raise HTTPException(status_code=404, detail="记忆条目不存在")

        _assert_memory_category_owned(conn, character_id, body.category_id)

        now = utc_now_iso()
        conn.execute(
            """
            UPDATE character_memories SET
                keywords = %s,
                trigger_logic = %s,
                content = %s,
                category_id = %s,
                position = %s,
                priority = %s,
                is_active = %s,
                comment = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.keywords,
                body.trigger_logic,
                body.content,
                body.category_id,
                body.position,
                body.priority,
                body.is_active,
                body.comment,
                now,
                memory_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/memories/{memory_id}")
def delete_memory(
    character_id: str,
    memory_id: str,
) -> dict[str, Any]:
    """删除记忆条目。"""
    conn = get_conn()
    try:
        # 检查记忆条目是否存在且属于该角色
        mem = conn.execute(
            "SELECT id FROM character_memories WHERE id = %s AND character_id = %s",
            (memory_id, character_id),
        ).fetchone()
        if not mem:
            raise HTTPException(status_code=404, detail="记忆条目不存在")

        conn.execute(
            "DELETE FROM character_memories WHERE id = %s",
            (memory_id,),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


# ============================================================
# 高级配置 API - 开场白
# ============================================================
@router.get("/admin/character/{character_id}/greetings")
def list_greetings(character_id: str) -> list[dict[str, Any]]:
    """获取角色的多阶段开场白列表。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, story_phase, mood, content, storyline_id,
                   priority, is_active, use_count, comment, created_at, updated_at
            FROM character_greetings
            WHERE character_id = %s
            ORDER BY story_phase, priority ASC, id ASC
            """,
            (character_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "story_phase": row["story_phase"],
                "mood": row["mood"],
                "content": row["content"],
                "storyline_id": row["storyline_id"],
                "priority": row["priority"],
                "is_active": bool(row["is_active"]),
                "use_count": row["use_count"],
                "comment": row["comment"] or "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/greetings")
def create_greeting(
    character_id: str,
    body: GreetingPayload,
) -> dict[str, Any]:
    """创建新的开场白。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        _assert_storyline_owned(conn, character_id, body.storyline_id)

        now = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO character_greetings
            (character_id, story_phase, mood, content, storyline_id,
             priority, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                body.story_phase,
                body.mood,
                body.content,
                body.storyline_id,
                body.priority,
                body.is_active,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"id": new_id, "ok": True}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/greetings/{greeting_id}")
def update_greeting(
    character_id: str,
    greeting_id: str,
    body: GreetingPayload,
) -> dict[str, Any]:
    """更新开场白。"""
    conn = get_conn()
    try:
        # 检查开场白是否存在且属于该角色
        g = conn.execute(
            "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
            (greeting_id, character_id),
        ).fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="开场白不存在")

        _assert_storyline_owned(conn, character_id, body.storyline_id)

        now = utc_now_iso()
        conn.execute(
            """
            UPDATE character_greetings SET
                story_phase = %s,
                mood = %s,
                content = %s,
                storyline_id = %s,
                priority = %s,
                is_active = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.story_phase,
                body.mood,
                body.content,
                body.storyline_id,
                body.priority,
                body.is_active,
                now,
                greeting_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/greetings/{greeting_id}")
def delete_greeting(
    character_id: str,
    greeting_id: str,
) -> dict[str, Any]:
    """删除开场白。"""
    conn = get_conn()
    try:
        # 检查开场白是否存在且属于该角色
        g = conn.execute(
            "SELECT id FROM character_greetings WHERE id = %s AND character_id = %s",
            (greeting_id, character_id),
        ).fetchone()
        if not g:
            raise HTTPException(status_code=404, detail="开场白不存在")

        conn.execute(
            "DELETE FROM character_greetings WHERE id = %s",
            (greeting_id,),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


# ============================================================
# 高级配置 API - 剧情线
# ============================================================
@router.get("/admin/character/{character_id}/storylines")
def list_storylines(character_id: str) -> list[dict[str, Any]]:
    """获取角色的剧情线列表。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, name, description, unlock_score, is_default,
                   is_active, sort_order, created_at, updated_at
            FROM character_storylines
            WHERE character_id = %s
            ORDER BY sort_order ASC, id ASC
            """,
            (character_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"] or "",
                "unlock_score": row["unlock_score"],
                "is_default": bool(row["is_default"]),
                "is_active": bool(row["is_active"]),
                "sort_order": row["sort_order"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/storylines")
def create_storyline(
    character_id: str,
    body: StorylinePayload,
) -> dict[str, Any]:
    """创建新的剧情线。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 如果设为默认，先取消其他默认
        if body.is_default:
            conn.execute(
                "UPDATE character_storylines SET is_default = 0 WHERE character_id = %s",
                (character_id,),
            )

        now = utc_now_iso()
        # 创建剧情线 - 使用数据库实际存在的字段
        import json
        cur = conn.execute(
            """
            INSERT INTO character_storylines
            (character_id, name, description,
             unlock_score, is_default, is_active, sort_order, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                body.name,
                body.description,
                body.unlock_score,
                body.is_default,
                body.is_active,
                body.sort_order,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"id": new_id, "ok": True}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/storylines/{storyline_id}")
def update_storyline(
    character_id: str,
    storyline_id: str,
    body: StorylinePayload,
) -> dict[str, Any]:
    """更新剧情线。"""
    conn = get_conn()
    try:
        # 检查剧情线是否存在且属于该角色
        sl = conn.execute(
            "SELECT id FROM character_storylines WHERE id = %s AND character_id = %s",
            (storyline_id, character_id),
        ).fetchone()
        if not sl:
            raise HTTPException(status_code=404, detail="剧情线不存在")

        # 如果设为默认，先取消其他默认
        if body.is_default:
            conn.execute(
                """UPDATE character_storylines SET is_default = 0 
                   WHERE character_id = %s AND id != %s""",
                (character_id, storyline_id),
            )

        now = utc_now_iso()
        conn.execute(
            """
            UPDATE character_storylines SET
                name = %s,
                description = %s,
                unlock_score = %s,
                is_default = %s,
                is_active = %s,
                sort_order = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.name,
                body.description,
                body.unlock_score,
                body.is_default,
                body.is_active,
                body.sort_order,
                now,
                storyline_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/storylines/{storyline_id}")
def delete_storyline(
    character_id: str,
    storyline_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """删除剧情线。"""
    conn = get_conn()
    try:
        # 检查剧情线是否存在且属于该角色
        sl = conn.execute(
            "SELECT id, name FROM character_storylines WHERE id = %s AND character_id = %s",
            (storyline_id, character_id),
        ).fetchone()
        if not sl:
            raise HTTPException(status_code=404, detail="剧情线不存在")

        # 清理关联数据：将引用该剧情线的字段置为空
        # 1. 开场白中的 storyline_id
        conn.execute(
            "UPDATE character_greetings SET storyline_id = NULL WHERE storyline_id = %s",
            (storyline_id,),
        )
        # 2. 后置规则中的 storyline_id
        conn.execute(
            "UPDATE character_post_rules SET storyline_id = NULL WHERE storyline_id = %s",
            (storyline_id,),
        )
        # 3. 剧情事件中的解锁剧情线（如果设置为该剧情线，则清空）
        conn.execute(
            "UPDATE story_events SET unlocked_storyline_id = NULL WHERE unlocked_storyline_id = %s",
            (storyline_id,),
        )

        # 删除剧情线本身
        conn.execute(
            "DELETE FROM character_storylines WHERE id = %s",
            (storyline_id,),
        )

        # 记录审计日志
        _write_audit_log(
            conn,
            operator_id=current_user.id,
            operator_email=current_user.email,
            action="delete_storyline",
            target_type="storyline",
            target_id=storyline_id,
            detail={
                "character_id": character_id,
                "storyline_name": sl["name"],
            },
        )
        
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.get("/admin/character/{character_id}/storylines/{storyline_id}/delete-impact")
def storyline_delete_impact(
    character_id: str,
    storyline_id: str,
) -> dict[str, Any]:
    """删除剧情线前，预览会影响哪些配置。"""
    conn = get_conn()
    try:
        storyline = conn.execute(
            """
            SELECT id, name, is_default
            FROM character_storylines
            WHERE id = %s AND character_id = %s
            """,
            (storyline_id, character_id),
        ).fetchone()
        if not storyline:
            raise HTTPException(status_code=404, detail="剧情线不存在")

        greetings = conn.execute(
            """
            SELECT id, story_phase, content
            FROM character_greetings
            WHERE character_id = %s AND storyline_id = %s
            ORDER BY id ASC
            """,
            (character_id, storyline_id),
        ).fetchall()
        post_rules = conn.execute(
            """
            SELECT id, name
            FROM character_post_rules
            WHERE character_id = %s AND storyline_id = %s
            ORDER BY id ASC
            """,
            (character_id, storyline_id),
        ).fetchall()
        unlock_events = conn.execute(
            """
            SELECT id, title
            FROM story_events
            WHERE character_id = %s AND unlocked_storyline_id = %s
            ORDER BY id ASC
            """,
            (character_id, storyline_id),
        ).fetchall()

        return {
            "character_id": character_id,
            "storyline": {
                "id": storyline["id"],
                "name": storyline["name"],
                "is_default": bool(storyline["is_default"]),
            },
            "impact": {
                "greetings": [
                    {
                        "id": row["id"],
                        "label": f"{row['story_phase']} / {(row['content'] or '')[:24]}",
                    }
                    for row in greetings
                ],
                "post_rules": [
                    {
                        "id": row["id"],
                        "label": row["name"] or f"规则#{row['id']}",
                    }
                    for row in post_rules
                ],
                "unlock_events": [
                    {
                        "id": row["id"],
                        "label": row["title"] or f"事件#{row['id']}",
                    }
                    for row in unlock_events
                ],
            },
            "summary": {
                "greeting_count": len(greetings),
                "post_rule_count": len(post_rules),
                "unlock_event_count": len(unlock_events),
            },
        }
    finally:
        conn.close()


# ============================================================
# 高级配置 API - 关键词测试
# ============================================================
@router.post("/admin/character/{character_id}/test-keywords")
def test_keywords(
    character_id: str,
    body: KeywordTestPayload,
) -> list[dict[str, Any]]:
    """
    测试关键词匹配。
    
    输入一段文本，返回所有会被触发的记忆条目。
    """
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 获取所有启用的记忆条目
        rows = conn.execute(
            """
            SELECT id, keywords, trigger_logic, content
            FROM character_memories
            WHERE character_id = %s AND is_active = 1
            ORDER BY priority ASC
            """,
            (character_id,),
        ).fetchall()

        results = []
        text_lower = body.text.lower()

        for row in rows:
            keywords = [k.strip().lower() for k in row["keywords"].split(",") if k.strip()]
            if not keywords:
                continue

            trigger_logic = row["trigger_logic"] or "any"
            matched = []

            if trigger_logic == "all":
                # 所有关键词都必须匹配
                if all(kw in text_lower for kw in keywords):
                    matched = keywords
            else:
                # 任意关键词匹配
                matched = [kw for kw in keywords if kw in text_lower]

            if matched:
                results.append({
                    "id": row["id"],
                    "keywords": row["keywords"],
                    "content": row["content"],
                    "matched_keywords": matched,
                    "trigger_logic": trigger_logic,
                })

        return results
    finally:
        conn.close()


# ============================================================
# 高级配置 API - 后置规则
# ============================================================
@router.get("/admin/character/{character_id}/post-rules")
def list_post_rules(character_id: str) -> list[dict[str, Any]]:
    """获取角色的后置规则列表。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, name, content, storyline_id, story_phase,
                   priority, is_active, created_at, updated_at
            FROM character_post_rules
            WHERE character_id = %s
            ORDER BY priority ASC, id ASC
            """,
            (character_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "content": row["content"],
                "storyline_id": row["storyline_id"],
                "story_phase": row["story_phase"],
                "priority": row["priority"],
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/post-rules")
def create_post_rule(
    character_id: str,
    body: PostRulePayload,
) -> dict[str, Any]:
    """创建新的后置规则。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        _assert_storyline_owned(conn, character_id, body.storyline_id)

        now = utc_now_iso()
        # story_phase 为空时存空字符串（数据库该列有NOT NULL约束）
        story_phase_val = body.story_phase if body.story_phase else ""
        cur = conn.execute(
            """
            INSERT INTO character_post_rules
            (character_id, name, content, storyline_id, story_phase,
             priority, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                body.name,
                body.content,
                body.storyline_id,
                story_phase_val,
                body.priority,
                body.is_active,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"ok": True, "id": new_id}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/post-rules/{rule_id}")
def update_post_rule(
    character_id: str,
    rule_id: str,
    body: PostRulePayload,
) -> dict[str, Any]:
    """更新后置规则。"""
    conn = get_conn()
    try:
        # 检查规则是否存在且属于该角色
        rule = conn.execute(
            "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
            (rule_id, character_id),
        ).fetchone()
        if not rule:
            raise HTTPException(status_code=404, detail="后置规则不存在")

        _assert_storyline_owned(conn, character_id, body.storyline_id)

        now = utc_now_iso()
        # story_phase 为空时存空字符串（数据库该列有NOT NULL约束）
        story_phase_val = body.story_phase if body.story_phase else ""
        conn.execute(
            """
            UPDATE character_post_rules SET
                name = %s,
                content = %s,
                storyline_id = %s,
                story_phase = %s,
                priority = %s,
                is_active = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.name,
                body.content,
                body.storyline_id,
                story_phase_val,
                body.priority,
                body.is_active,
                now,
                rule_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/post-rules/{rule_id}")
def delete_post_rule(
    character_id: str,
    rule_id: str,
) -> dict[str, Any]:
    """删除后置规则。"""
    conn = get_conn()
    try:
        # 检查规则是否存在且属于该角色
        rule = conn.execute(
            "SELECT id FROM character_post_rules WHERE id = %s AND character_id = %s",
            (rule_id, character_id),
        ).fetchone()
        if not rule:
            raise HTTPException(status_code=404, detail="后置规则不存在")

        conn.execute(
            "DELETE FROM character_post_rules WHERE id = %s",
            (rule_id,),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


# ============================================================
# 高级配置 API - 剧情事件
# ============================================================
@router.get("/admin/character/{character_id}/story-events")
def list_story_events(character_id: str) -> list[dict[str, Any]]:
    """获取角色的剧情事件列表。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, title, description, trigger_score,
                   unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
                   event_content, sort_order, is_active, created_at, updated_at
            FROM story_events
            WHERE character_id = %s
            ORDER BY trigger_score ASC, sort_order ASC, id ASC
            """,
            (character_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"] or "",
                "trigger_score": row["trigger_score"],
                "unlocked_memory_ids": row["unlocked_memory_ids"] or "",
                "unlocked_greeting_ids": row["unlocked_greeting_ids"] or "",
                "unlocked_storyline_id": row["unlocked_storyline_id"],
                "event_content": row["event_content"] or "",
                "sort_order": row["sort_order"],
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/story-events")
def create_story_event(
    character_id: str,
    body: StoryEventPayload,
) -> dict[str, Any]:
    """创建新的剧情事件。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        _assert_story_event_unlock_refs_owned(
            conn,
            character_id,
            body.unlocked_memory_ids,
            body.unlocked_greeting_ids,
            body.unlocked_storyline_id,
        )

        now = utc_now_iso()
        # event_id 是数据库 NOT NULL 且无默认值的列，用 uuid 生成
        # unlocked_storyline_id 是 bigint 外键且可为 NULL，前端不传时应存 NULL
        import uuid
        # 将空字符串转为 None，以便数据库存 NULL 而不是空字符串
        unlocked_sl_id = body.unlocked_storyline_id if body.unlocked_storyline_id else None
        cur = conn.execute(
            """
            INSERT INTO story_events
            (character_id, event_id, title, description, trigger_score,
             unlocked_memory_ids, unlocked_greeting_ids, unlocked_storyline_id,
             event_content, sort_order, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                str(uuid.uuid4()),
                body.title,
                body.description,
                body.trigger_score,
                body.unlocked_memory_ids or "",
                body.unlocked_greeting_ids or "",
                unlocked_sl_id,
                body.event_content or "",
                body.sort_order,
                body.is_active,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"ok": True, "id": new_id}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/story-events/{event_id}")
def update_story_event(
    character_id: str,
    event_id: str,
    body: StoryEventPayload,
) -> dict[str, Any]:
    """更新剧情事件。"""
    conn = get_conn()
    try:
        # 检查事件是否存在且属于该角色
        event = conn.execute(
            "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
            (event_id, character_id),
        ).fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="剧情事件不存在")

        _assert_story_event_unlock_refs_owned(
            conn,
            character_id,
            body.unlocked_memory_ids,
            body.unlocked_greeting_ids,
            body.unlocked_storyline_id,
        )

        now = utc_now_iso()
        # 将空字符串转为 None，以便数据库存 NULL
        unlocked_sl_id = body.unlocked_storyline_id if body.unlocked_storyline_id else None
        conn.execute(
            """
            UPDATE story_events SET
                title = %s,
                description = %s,
                trigger_score = %s,
                unlocked_memory_ids = %s,
                unlocked_greeting_ids = %s,
                unlocked_storyline_id = %s,
                event_content = %s,
                sort_order = %s,
                is_active = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.title,
                body.description,
                body.trigger_score,
                body.unlocked_memory_ids or "",
                body.unlocked_greeting_ids or "",
                unlocked_sl_id,
                body.event_content or "",
                body.sort_order,
                body.is_active,
                now,
                event_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/story-events/{event_id}")
def delete_story_event(
    character_id: str,
    event_id: str,
) -> dict[str, Any]:
    """删除剧情事件。"""
    conn = get_conn()
    try:
        # 检查事件是否存在且属于该角色
        event = conn.execute(
            "SELECT id FROM story_events WHERE id = %s AND character_id = %s",
            (event_id, character_id),
        ).fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="剧情事件不存在")

        conn.execute(
            "DELETE FROM story_events WHERE id = %s",
            (event_id,),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


# ============================================================
# 高级配置 API - 记忆分类
# ============================================================
@router.get("/admin/character/{character_id}/memory-categories")
def list_memory_categories(character_id: str) -> list[dict[str, Any]]:
    """获取角色的记忆分类列表。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        rows = conn.execute(
            """
            SELECT id, name, description, color, sort_order, created_at, updated_at
            FROM memory_categories
            WHERE character_id = %s
            ORDER BY sort_order ASC, id ASC
            """,
            (character_id,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"] or "",
                "color": row["color"] or "#1890FF",
                "sort_order": row["sort_order"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/admin/character/{character_id}/memory-categories")
def create_memory_category(
    character_id: str,
    body: MemoryCategoryPayload,
) -> dict[str, Any]:
    """创建新的记忆分类。"""
    conn = get_conn()
    try:
        # 检查角色是否存在
        char = conn.execute(
            "SELECT id FROM characters WHERE id = %s", (character_id,)
        ).fetchone()
        if not char:
            raise HTTPException(status_code=404, detail="角色不存在")

        now = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO memory_categories
            (character_id, name, description, color, sort_order, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                character_id,
                body.name,
                body.description,
                body.color,
                body.sort_order,
                now,
                now,
            ),
        )
        conn.commit()
        new_id = cur.fetchone()["id"]
        return {"ok": True, "id": new_id}
    finally:
        conn.close()


@router.put("/admin/character/{character_id}/memory-categories/{category_id}")
def update_memory_category(
    character_id: str,
    category_id: str,
    body: MemoryCategoryPayload,
) -> dict[str, Any]:
    """更新记忆分类。"""
    conn = get_conn()
    try:
        # 检查分类是否存在且属于该角色
        cat = conn.execute(
            "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
            (category_id, character_id),
        ).fetchone()
        if not cat:
            raise HTTPException(status_code=404, detail="记忆分类不存在")

        now = utc_now_iso()
        conn.execute(
            """
            UPDATE memory_categories SET
                name = %s,
                description = %s,
                color = %s,
                sort_order = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (
                body.name,
                body.description,
                body.color,
                body.sort_order,
                now,
                category_id,
            ),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.delete("/admin/character/{character_id}/memory-categories/{category_id}")
def delete_memory_category(
    character_id: str,
    category_id: str,
) -> dict[str, Any]:
    """删除记忆分类。"""
    conn = get_conn()
    try:
        # 检查分类是否存在且属于该角色
        cat = conn.execute(
            "SELECT id FROM memory_categories WHERE id = %s AND character_id = %s",
            (category_id, character_id),
        ).fetchone()
        if not cat:
            raise HTTPException(status_code=404, detail="记忆分类不存在")

        # 检查是否有记忆条目使用此分类
        mem_count = conn.execute(
            "SELECT COUNT(*) FROM character_memories WHERE category_id = %s",
            (category_id,),
        ).fetchone()["count"]
        
        if mem_count > 0:
            raise HTTPException(
                status_code=400, 
                detail=f"该分类下还有 {mem_count} 个记忆条目，请先移除或修改这些条目"
            )

        conn.execute(
            "DELETE FROM memory_categories WHERE id = %s",
            (category_id,),
        )
        conn.commit()

        return {"ok": True}
    finally:
        conn.close()


@router.get("/admin/character/{character_id}/memory-categories/{category_id}/delete-impact")
def memory_category_delete_impact(
    character_id: str,
    category_id: str,
) -> dict[str, Any]:
    """删除记忆分类前，预览引用影响。"""
    conn = get_conn()
    try:
        category = conn.execute(
            """
            SELECT id, name
            FROM memory_categories
            WHERE id = %s AND character_id = %s
            """,
            (category_id, character_id),
        ).fetchone()
        if not category:
            raise HTTPException(status_code=404, detail="记忆分类不存在")

        memories = conn.execute(
            """
            SELECT id, keywords, comment
            FROM character_memories
            WHERE character_id = %s AND category_id = %s
            ORDER BY priority ASC, id ASC
            """,
            (character_id, category_id),
        ).fetchall()

        return {
            "character_id": character_id,
            "category": {
                "id": category["id"],
                "name": category["name"],
            },
            "impact": {
                "memories": [
                    {
                        "id": row["id"],
                        "label": row["keywords"] or row["comment"] or f"记忆#{row['id']}",
                    }
                    for row in memories
                ]
            },
            "summary": {
                "memory_count": len(memories),
            },
        }
    finally:
        conn.close()


# ============================================================
# 数据库性能监控
# ============================================================
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
def admin_dashboard_stats() -> dict[str, Any]:
    """
    管理后台：获取仪表盘核心统计数据。

    返回：总用户数、今日新增、付费用户数、今日订单数、
          今日收入、即将到期用户数、各档位分布。
    """
    conn = get_conn()
    try:
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
    finally:
        conn.close()


@router.get("/admin/dashboard/trend")
def admin_dashboard_trend(days: int = 7) -> dict[str, Any]:
    """
    管理后台：获取近 N 天用户增长和订单趋势。

    参数：
        days: 天数，默认 7 天（最多 30 天）
    """
    safe_days = max(1, min(days, 30))

    conn = get_conn()
    try:
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
    finally:
        conn.close()


# ============================================================
# 操作日志
# ============================================================
def _write_audit_log(
    conn: Any,
    operator_id: str,
    operator_email: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """
    内部函数：写入一条操作日志。

    注意：此函数不自行 commit，调用方负责提交事务。
    """
    conn.execute(
        """
        INSERT INTO admin_audit_logs
        (operator_id, operator_email, action, target_type, target_id, detail, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            operator_id,
            operator_email,
            action,
            target_type,
            target_id,
            json.dumps(detail or {}, ensure_ascii=False),
            utc_now_iso(),
        ),
    )


@router.get("/admin/audit-logs")
def admin_list_audit_logs(
    action: str = "",
    target_type: str = "",
    page: int = 1,
    limit: int = 50,
) -> dict[str, Any]:
    """
    管理后台：获取操作日志列表。

    参数：
        action: 按操作类型筛选（delete_user/edit_user/update_plan/batch_update 等）
        target_type: 按对象类型筛选（user/order/character）
        page: 页码
        limit: 每页条数（最多 200）
    """
    conn = get_conn()
    try:
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

        offset = (max(1, page) - 1) * min(limit, 200)
        safe_limit = min(limit, 200)

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
                    "detail": row["detail"] if row["detail"] else {},
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        }
    finally:
        conn.close()
