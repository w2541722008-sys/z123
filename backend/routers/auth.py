"""
认证路由 - 处理登录、注册、登出、用户信息、密码重置

端点列表：
    POST /api/auth/register        - 注册新用户
    POST /api/auth/login           - 用户登录（支持密码平滑迁移）
    GET  /api/auth/me              - 获取当前用户信息
    POST /api/auth/logout          - 用户登出
    POST /api/auth/forgot-password - 发送密码重置验证码
    POST /api/auth/verify-code     - 验证密码重置验证码
    POST /api/auth/reset-password  - 重置密码

安全特性：
    - 密码使用 bcrypt 哈希，支持从旧版 SHA-256 平滑迁移
    - 密码重置验证码 10 分钟过期，60 秒防刷限制
    - 统一错误提示（不暴露邮箱是否已注册等敏感信息）
"""

from __future__ import annotations

# 标准库导入
from datetime import datetime, timedelta, timezone
from typing import Any

# 第三方库导入
from fastapi import APIRouter, Depends, Header, HTTPException, Request

# 本地模块导入
from auth import (
    CurrentUser,
    create_token,
    delete_token,
    get_current_user,
    hash_password_bcrypt,
    verify_password,
    _is_admin_email,
)
from config import (
    LOGIN_RATE_LIMIT_COUNT,
    LOGIN_RATE_LIMIT_EMAIL_COUNT,
    LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    PASSWORD_RESET_RATE_LIMIT_COUNT,
    PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS,
    REGISTER_RATE_LIMIT_COUNT,
    REGISTER_RATE_LIMIT_WINDOW_SECONDS,
    VERIFY_CODE_RATE_LIMIT_COUNT,
    VERIFY_CODE_RATE_LIMIT_WINDOW_SECONDS,
    logger,
    utc_now_iso,
)
from database import get_conn
from models import (
    BillingCreateOrderPayload,
    ForgotPasswordPayload,
    LoginPayload,
    RegisterPayload,
    ResetPasswordPayload,
    VerifyCodePayload,
)
from services.email import generate_reset_code, send_reset_code_email
from services.plan_service import serialize_plan_info
from services.rate_limit import enforce_rate_limit, get_request_client_ip

router = APIRouter()


def _build_user_payload(
    *,
    user_id: int,
    email: str,
    nickname: str,
    plan_type: str = "free",
    plan_expires_at: str = "",
    is_admin: bool = False,
) -> dict[str, Any]:
    """统一构造登录态用户信息返回。"""
    plan_info = serialize_plan_info(plan_type, plan_expires_at)
    return {
        "id": user_id,
        "email": email,
        "nickname": nickname,
        "is_admin": is_admin,
        **plan_info,
    }


def _normalize_email(email: str) -> str:
    """统一邮箱格式，减少大小写和首尾空格带来的问题。"""
    return email.strip().lower()


@router.post("/auth/register")
def auth_register(payload: RegisterPayload, request: Request) -> dict[str, Any]:
    """
    用户注册接口。

    流程：
        1. 检查邮箱是否已存在
        2. 使用 bcrypt 哈希密码
        3. 生成用户记录（昵称默认为邮箱前缀）
        4. 创建登录 token

    Args:
        payload: 注册请求体（邮箱、密码、可选昵称）

    Returns:
        包含 token 和用户信息的对象

    Raises:
        HTTPException: 400 邮箱已被注册
    """
    client_ip = get_request_client_ip(request)
    enforce_rate_limit(
        "auth_register_ip",
        client_ip,
        limit=REGISTER_RATE_LIMIT_COUNT,
        window_seconds=REGISTER_RATE_LIMIT_WINDOW_SECONDS,
        detail="注册请求过于频繁",
    )
    normalized_email = _normalize_email(payload.email)

    conn = get_conn()
    try:
        # 步骤 1：检查邮箱是否已存在
        existing = conn.execute(
            "SELECT 1 FROM users WHERE LOWER(email) = ?",
            (normalized_email,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="该邮箱已被注册")

        # 步骤 2：密码哈希（bcrypt，rounds=12）
        password_hash = hash_password_bcrypt(payload.password)

        # 步骤 3：昵称默认为邮箱前缀
        nickname = payload.nickname or normalized_email.split("@")[0]

        # 步骤 4：插入用户记录
        now = utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO users(email, password_hash, password_algo, nickname, created_at, updated_at)
            VALUES (?, ?, 'bcrypt', ?, ?, ?)
            """,
            (normalized_email, password_hash, nickname, now, now),
        )
        conn.commit()
        user_id = cur.lastrowid

        # 步骤 5：生成登录 token
        token = create_token(user_id)

        return {
            "token": token,
            "user": _build_user_payload(
                user_id=user_id,
                email=normalized_email,
                nickname=nickname,
                plan_type="free",
                plan_expires_at="",
                is_admin=_is_admin_email(normalized_email),
            ),
        }
    finally:
        conn.close()


@router.post("/auth/login")
def auth_login(payload: LoginPayload, request: Request) -> dict[str, Any]:
    """
    用户登录接口。

    流程：
        1. 根据邮箱查询用户
        2. 验证密码（支持 bcrypt 和旧版 SHA-256）
        3. 平滑迁移：旧 SHA-256 密码自动升级为 bcrypt
        4. 生成登录 token

    Args:
        payload: 登录请求体（邮箱、密码）

    Returns:
        包含 token 和用户信息的对象

    Raises:
        HTTPException: 401 邮箱或密码错误

    安全说明：
        - 统一返回 "邮箱或密码错误"，不区分是邮箱不存在还是密码错误
        - 防止通过错误信息枚举注册用户
    """
    client_ip = get_request_client_ip(request)
    normalized_email = _normalize_email(payload.email)
    enforce_rate_limit(
        "auth_login_ip",
        client_ip,
        limit=LOGIN_RATE_LIMIT_COUNT,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        detail="登录尝试过于频繁",
    )
    enforce_rate_limit(
        "auth_login_email",
        normalized_email,
        limit=LOGIN_RATE_LIMIT_EMAIL_COUNT,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        detail="该邮箱登录尝试过于频繁",
    )

    conn = get_conn()
    try:
        # 步骤 1：查询用户
        row = conn.execute(
            """
            SELECT id, email, password_hash, password_algo, COALESCE(nickname, '') AS nickname,
                   COALESCE(plan_type, 'free') AS plan_type,
                   COALESCE(plan_expires_at, '') AS plan_expires_at
            FROM users WHERE LOWER(email) = ?
            """,
            (normalized_email,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        # 步骤 2：验证密码
        algo = row["password_algo"] or "sha256"
        if not verify_password(payload.password, row["password_hash"], algo):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        # 步骤 3：平滑迁移 - 旧 SHA-256 密码升级为 bcrypt
        if algo != "bcrypt":
            new_hash = hash_password_bcrypt(payload.password)
            conn.execute(
                "UPDATE users SET password_hash = ?, password_algo = 'bcrypt', updated_at = ? WHERE id = ?",
                (new_hash, utc_now_iso(), row["id"]),
            )
            conn.commit()

        # 步骤 4：生成 token
        token = create_token(row["id"])
        nickname = row["nickname"] or normalized_email.split("@")[0]

        return {
            "token": token,
            "user": _build_user_payload(
                user_id=row["id"],
                email=row["email"],
                nickname=nickname,
                plan_type=row["plan_type"],
                plan_expires_at=row["plan_expires_at"],
                is_admin=_is_admin_email(row["email"]),
            ),
        }
    finally:
        conn.close()


@router.get("/auth/me")
def auth_me(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """
    获取当前登录用户信息。

    Args:
        user: 当前登录用户（通过 Depends 自动注入）

    Returns:
        用户基本信息（id、email、nickname）
    """
    return _build_user_payload(
        user_id=user.id,
        email=user.email,
        nickname=user.nickname,
        plan_type=user.plan_type,
        plan_expires_at=user.plan_expires_at,
        is_admin=user.is_admin,
    )


@router.post("/auth/logout")
def auth_logout(
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    用户登出接口。

    删除当前 token，使其失效。用户需要重新登录才能获取新的 token。

    Args:
        authorization: HTTP Authorization 头
        user: 当前登录用户（通过 Depends 自动注入）

    Returns:
        成功标记
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        delete_token(token)
    return {"ok": True}


# ============================================================
# 密码重置相关接口
# ============================================================

@router.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordPayload, request: Request) -> dict[str, Any]:
    """
    发送密码重置验证码。

    流程：
        1. 检查邮箱是否已注册
        2. 检查 60 秒内是否已发送过（防刷）
        3. 生成 6 位数字验证码
        4. 存入数据库（10 分钟过期）
        5. 发送邮件
        6. 邮件发送失败则回滚

    Args:
        payload: 包含邮箱的请求体

    Returns:
        成功标记和提示信息

    Raises:
        HTTPException: 429 请求过于频繁，500 邮件发送失败

    安全说明：
        - 即使邮箱不存在，也返回统一成功提示，避免枚举用户
    """
    client_ip = get_request_client_ip(request)
    enforce_rate_limit(
        "auth_forgot_password_ip",
        client_ip,
        limit=PASSWORD_RESET_RATE_LIMIT_COUNT,
        window_seconds=PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS,
        detail="找回密码请求过于频繁",
    )
    normalized_email = _normalize_email(payload.email)

    conn = get_conn()
    try:
        # 步骤 1：检查邮箱是否存在
        user = conn.execute(
            "SELECT id, email FROM users WHERE LOWER(email) = ?",
            (normalized_email,),
        ).fetchone()

        if not user:
            logger.info(f"密码重置请求：邮箱不存在或未命中用户 {normalized_email}")
            return {"ok": True, "message": "如果该邮箱已注册，验证码会发送至您的邮箱，10 分钟内有效"}

        now = datetime.now(timezone.utc)

        # 步骤 2：检查 60 秒内是否已发送过验证码（防刷机制）
        recent_code = conn.execute(
            """
            SELECT created_at FROM password_reset_codes
            WHERE email = ? AND used = 0 AND created_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (normalized_email, (now - timedelta(seconds=60)).isoformat()),
        ).fetchone()

        if recent_code:
            raise HTTPException(
                status_code=429,
                detail="请求过于频繁，请 60 秒后再试"
            )

        # 步骤 3：生成验证码
        code = generate_reset_code()

        # 步骤 4：计算过期时间（10 分钟后）
        expires_at = (now + timedelta(minutes=10)).isoformat()

        # 步骤 5：存入数据库
        conn.execute(
            """
            INSERT INTO password_reset_codes (email, code, expires_at, used, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (normalized_email, code, expires_at, now.isoformat()),
        )
        conn.commit()

        # 步骤 6：发送邮件
        email_sent = send_reset_code_email(user["email"], code)

        if not email_sent:
            # 邮件发送失败，删除刚插入的验证码（回滚）
            conn.execute(
                "DELETE FROM password_reset_codes WHERE email = ? AND code = ?",
                (normalized_email, code),
            )
            conn.commit()
            raise HTTPException(status_code=500, detail="邮件发送失败，请稍后重试")

        logger.info(f"密码重置验证码已发送: {user['email']}")
        return {"ok": True, "message": "验证码已发送至您的邮箱，10 分钟内有效"}

    finally:
        conn.close()


@router.post("/auth/verify-code")
def verify_reset_code(payload: VerifyCodePayload, request: Request) -> dict[str, Any]:
    """
    验证密码重置验证码。

    验证规则：
        - 验证码必须存在且未使用
        - 验证码未过期（10 分钟有效期）
        - 验证码必须匹配

    Args:
        payload: 包含邮箱和验证码的请求体

    Returns:
        成功标记

    Raises:
        HTTPException: 400 验证码过期或错误

    说明：
        邮箱会先做统一小写归一化，再查找验证码。
    """
    client_ip = get_request_client_ip(request)
    enforce_rate_limit(
        "auth_verify_code_ip",
        client_ip,
        limit=VERIFY_CODE_RATE_LIMIT_COUNT,
        window_seconds=VERIFY_CODE_RATE_LIMIT_WINDOW_SECONDS,
        detail="验证码校验过于频繁",
    )
    normalized_email = _normalize_email(payload.email)

    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()

        # 查找该邮箱最新有效的验证码
        reset_code = conn.execute(
            """
            SELECT id, code, expires_at, used
            FROM password_reset_codes
            WHERE email = ? AND used = 0 AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (normalized_email, now),
        ).fetchone()

        if not reset_code:
            raise HTTPException(status_code=400, detail="验证码已过期或无效")

        if reset_code["code"] != payload.code:
            raise HTTPException(status_code=400, detail="验证码错误")

        return {"ok": True, "message": "验证通过"}

    finally:
        conn.close()


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordPayload, request: Request) -> dict[str, Any]:
    """
    重置密码。

    流程：
        1. 验证验证码（有效且未过期）
        2. 查找用户
        3. 生成新密码哈希（bcrypt）
        4. 更新用户密码
        5. 标记验证码已使用
        6. 清理该邮箱其他未使用验证码

    Args:
        payload: 包含邮箱、验证码、新密码的请求体

    Returns:
        成功标记和提示信息

    Raises:
        HTTPException: 400 验证码无效或用户不存在

    说明：
        邮箱会先做统一小写归一化，再查找用户和验证码。
    """
    client_ip = get_request_client_ip(request)
    enforce_rate_limit(
        "auth_reset_password_ip",
        client_ip,
        limit=VERIFY_CODE_RATE_LIMIT_COUNT,
        window_seconds=VERIFY_CODE_RATE_LIMIT_WINDOW_SECONDS,
        detail="重置密码请求过于频繁",
    )
    normalized_email = _normalize_email(payload.email)

    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()

        # 步骤 1：查找并验证验证码
        reset_code = conn.execute(
            """
            SELECT id, code, expires_at, used
            FROM password_reset_codes
            WHERE email = ? AND used = 0 AND expires_at > ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (normalized_email, now),
        ).fetchone()

        if not reset_code or reset_code["code"] != payload.code:
            raise HTTPException(status_code=400, detail="验证码无效或已过期")

        # 步骤 2：查找用户
        user = conn.execute(
            "SELECT id, email FROM users WHERE LOWER(email) = ?",
            (normalized_email,),
        ).fetchone()

        if not user:
            raise HTTPException(status_code=400, detail="用户不存在")

        # 步骤 3：生成新密码哈希
        new_hash = hash_password_bcrypt(payload.new_password)

        # 步骤 4：更新密码
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, password_algo = 'bcrypt', updated_at = ?
            WHERE id = ?
            """,
            (new_hash, utc_now_iso(), user["id"]),
        )

        # 步骤 5：标记验证码已使用
        conn.execute(
            "UPDATE password_reset_codes SET used = 1 WHERE id = ?",
            (reset_code["id"],),
        )

        # 步骤 6：清理该邮箱其他未使用的验证码
        conn.execute(
            "DELETE FROM password_reset_codes WHERE email = ? AND id != ?",
            (normalized_email, reset_code["id"]),
        )

        conn.commit()

        logger.info(f"密码重置成功: {user['email']}")
        return {"ok": True, "message": "密码重置成功，请使用新密码登录"}

    finally:
        conn.close()
