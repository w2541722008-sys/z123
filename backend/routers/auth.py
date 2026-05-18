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
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

# 第三方库导入
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

# 本地模块导入
from core.auth import (
    CurrentUser,
    _extract_token_from_request,
    clear_auth_cookie,
    create_token,
    create_token_pair,
    delete_token,
    generate_device_fingerprint,
    get_current_user,
    hash_password_bcrypt,
    revoke_user_device_tokens,
    rotate_access_token,
    set_auth_cookie,
    verify_password,
    _is_admin_email,
)
from core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
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
)
from core.database import ConnType, get_db_dep
from core.database import ConnWrapper
from core.schemas import (
    ForgotPasswordPayload,
    LoginPayload,
    RegisterPayload,
    ResetPasswordPayload,
    VerifyCodePayload,
    _normalize_email,
)
from repositories import auth_repository as auth_repo
from repositories import user_repository as user_repo
from services.email import generate_reset_code, send_reset_code_email
from core.plan_constants import serialize_plan_info
from services.rate_limit import enforce_rate_limit, get_request_client_ip

router = APIRouter()


def _build_user_payload(
    *,
    user_id: int | str,
    email: str,
    nickname: str,
    plan_type: str = "free",
    plan_expires_at: str = "",
    is_admin: bool = False,
    avatar_url: str | None = None,
) -> dict[str, Any]:
    """统一构造登录态用户信息返回。"""
    plan_info = serialize_plan_info(plan_type, plan_expires_at)
    return {
        "id": user_id,
        "email": email,
        "nickname": nickname,
        "is_admin": is_admin,
        "avatar_url": avatar_url or "",
        **plan_info,
    }



_RESET_CODE_MAX_ATTEMPTS = 5  # 单个验证码最大错误尝试次数


def _get_latest_valid_reset_code(conn: ConnType, normalized_email: str, now: datetime) -> dict[str, Any] | None:
    return auth_repo.get_latest_valid_reset_code(conn, normalized_email, now)


def _verify_reset_code_or_raise(
    reset_code: dict[str, Any] | None,
    input_code: str,
    *,
    conn: ConnType | None = None,
    invalid_detail: str,
) -> None:
    if not reset_code:
        raise HTTPException(status_code=400, detail=invalid_detail)
    # 检查单码最大尝试次数
    attempts = reset_code.get("attempt_count", 0) or 0
    if attempts >= _RESET_CODE_MAX_ATTEMPTS:
        # 标记为已使用，防止继续尝试
        if conn is not None:
            auth_repo.mark_reset_code_used(conn, reset_code["id"])
        raise HTTPException(status_code=400, detail="验证码已失效，请重新获取")
    if not hmac.compare_digest(str(reset_code["code"]), str(input_code)):
        # 递增尝试计数
        if conn is not None:
            auth_repo.increment_reset_code_attempts(conn, reset_code["id"])
        raise HTTPException(status_code=400, detail=invalid_detail)


@router.post("/auth/register")
def auth_register(payload: RegisterPayload, request: Request, conn: ConnType = Depends(get_db_dep)) -> JSONResponse:
    """
    用户注册接口。

    流程：
        1. 检查邮箱是否已存在
        2. 使用 bcrypt 哈希密码
        3. 生成用户记录（昵称默认为邮箱前缀）
        4. 创建登录 token 并设置 HttpOnly Cookie

    Args:
        payload: 注册请求体（邮箱、密码、可选昵称）

    Returns:
        包含用户信息的对象（token 通过 HttpOnly Cookie 传递）

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

    try:
        # 步骤 1：检查邮箱是否已存在
        if user_repo.check_email_exists(conn, normalized_email):
            raise HTTPException(status_code=400, detail="该邮箱已被注册")

        # 步骤 2：密码哈希（bcrypt，rounds=12）
        password_hash = hash_password_bcrypt(payload.password)

        # 步骤 3：昵称默认为邮箱前缀
        nickname = payload.nickname or normalized_email.split("@")[0]

        # 步骤 4：插入用户记录，使用 RETURNING id 获取新生成的主键（PostgreSQL 专用）
        user_id = user_repo.insert_user(
            conn,
            email=normalized_email,
            password_hash=password_hash,
            password_algo="bcrypt",
            nickname=nickname,
        )
        if not user_id:
            raise RuntimeError("用户创建失败：无法获取新用户ID")

        # 步骤 5：生成双 token（access + refresh），并与用户创建保持同一事务
        device_fp = generate_device_fingerprint(request)
        tokens = create_token_pair(user_id, conn=conn, commit=False, device_fingerprint=device_fp)
        conn.commit()

        # 设置 HttpOnly Cookie + 返回双 token
        body = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": _build_user_payload(
                user_id=user_id,
                email=normalized_email,
                nickname=nickname,
                plan_type="free",
                plan_expires_at="",
                is_admin=_is_admin_email(normalized_email),
            ),
        }
        response = JSONResponse(body)
        set_auth_cookie(response, tokens["access_token"])
        return response
    except Exception:
        conn.rollback()
        raise


@router.post("/auth/login")
def auth_login(payload: LoginPayload, request: Request, conn: ConnType = Depends(get_db_dep)) -> JSONResponse:
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

    try:
        # 步骤 1：查询用户
        row = user_repo.find_user_by_email(conn, normalized_email)

        if not row:
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        # 步骤 2：验证密码
        algo = row["password_algo"] or "sha256"
        if not verify_password(payload.password, row["password_hash"], algo):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        # 步骤 3：平滑迁移 - 旧 SHA-256 密码升级为 bcrypt
        if algo != "bcrypt":
            new_hash = hash_password_bcrypt(payload.password)
            user_repo.update_password(conn, row["id"], new_hash)

        # 步骤 4：生成双 token（access + refresh），并与密码升级保持同一事务
        device_fp = generate_device_fingerprint(request)
        tokens = create_token_pair(row["id"], conn=conn, commit=False, device_fingerprint=device_fp)
        conn.commit()
        nickname = row["nickname"] or normalized_email.split("@")[0]

        # 设置 HttpOnly Cookie + 返回双 token
        body = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": _build_user_payload(
                user_id=row["id"],
                email=row["email"],
                nickname=nickname,
                plan_type=row["plan_type"],
                plan_expires_at=row["plan_expires_at"],
                is_admin=_is_admin_email(row["email"]),
                avatar_url=row.get("avatar_url"),
            ),
        }
        response = JSONResponse(body)
        set_auth_cookie(response, tokens["access_token"])
        return response
    except Exception:
        conn.rollback()
        raise


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
        avatar_url=user.avatar_url,
    )


@router.post("/auth/logout")
def auth_logout(
    request: Request,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    """
    用户登出接口。

    删除当前 access token，使其失效，并清除 HttpOnly Cookie。

    Args:
        request: FastAPI 请求对象（用于读取 Cookie）
        authorization: HTTP Authorization 头
        user: 当前登录用户（通过 Depends 自动注入）

    Returns:
        成功标记
    """
    token = _extract_token_from_request(request, authorization)
    if token:
        delete_token(token)

    response = JSONResponse({"ok": True})
    clear_auth_cookie(response)
    return response


# ============================================================
# 双 Token 管理接口
# ============================================================

_REFRESH_TOKEN_COOKIE = "aifriend_refresh"


@router.post("/auth/refresh")
def auth_refresh(request: Request, conn: ConnType = Depends(get_db_dep)) -> JSONResponse:
    """
    用 refresh token 换取新的 access token。

    Refresh token 从 Cookie 或 Authorization 头读取。
    验证通过后旧 access token 失效，返回新 access token。

    安全：验证设备指纹匹配，防止 refresh token 被窃取后跨设备使用。
    """
    # 从请求中提取 refresh token
    auth_header = request.headers.get("Authorization", "")
    refresh_token = None
    if auth_header.startswith("Bearer "):
        refresh_token = auth_header.split(" ", 1)[1].strip()
    if not refresh_token:
        refresh_token = request.cookies.get(_REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        # 兼容：也尝试从 aifriend_session cookie 读取
        refresh_token = request.cookies.get(_COOKIE_NAME)

    if not refresh_token:
        raise HTTPException(status_code=401, detail="缺少 refresh token")

    device_fp = generate_device_fingerprint(request)
    new_access = rotate_access_token(refresh_token, device_fingerprint=device_fp, conn=conn)

    if not new_access:
        raise HTTPException(status_code=401, detail="refresh token 无效或已过期")

    response = JSONResponse({
        "access_token": new_access,
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    })
    set_auth_cookie(response, new_access)
    return response


@router.post("/auth/logout-others")
def auth_logout_others(
    request: Request,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
) -> dict[str, Any]:
    """
    踢出其他设备：使当前用户的其他所有设备的 refresh token 失效。

    需要提供当前 refresh token 以保留当前设备。
    """
    # 从请求中尝试提取 refresh token
    refresh_token = request.cookies.get(_REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        refresh_token = request.cookies.get(_COOKIE_NAME)
    # 兼容：也尝试从 Authorization 头获取
    if not refresh_token and authorization and authorization.startswith("Bearer "):
        refresh_token = authorization.split(" ", 1)[1].strip()

    deleted = revoke_user_device_tokens(user.id, refresh_token or "", conn=conn)
    logger.info("用户 %s 踢出其他设备，删除 %s 个 token", user.id, deleted)
    return {"ok": True, "deleted_devices": deleted}


# ============================================================
# 密码重置相关接口
# ============================================================

@router.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordPayload, request: Request, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
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

    try:
        # 步骤 1：检查邮箱是否存在
        user = user_repo.find_user_by_email(conn, normalized_email)
        # find_user_by_email 返回完整字段，但我们只需 id 和 email
        if not user:
            logger.info("密码重置请求：邮箱不存在或未命中用户 %s", normalized_email)
            return {"ok": True, "message": "如果该邮箱已注册，验证码会发送至您的邮箱，10 分钟内有效"}

        now = datetime.now(timezone.utc)

        # 步骤 2：检查 60 秒内是否已发送过验证码（防刷机制）
        recent_code = auth_repo.check_recent_reset_code(
            conn, normalized_email, (now - timedelta(seconds=60)).isoformat()
        )

        if recent_code:
            raise HTTPException(
                status_code=429,
                detail="请求过于频繁，请 60 秒后再试"
            )

        # 步骤 3：生成验证码
        code = generate_reset_code()

        # 步骤 4：计算过期时间（10 分钟后）
        expires_at = now + timedelta(minutes=10)

        # 步骤 5：存入数据库
        auth_repo.insert_reset_code(
            conn,
            email=normalized_email,
            code=code,
            expires_at=expires_at,
        )

        # 步骤 6：发送邮件
        email_sent = send_reset_code_email(user["email"], code)

        if not email_sent:
            raise HTTPException(status_code=500, detail="邮件发送失败，请稍后重试")

        conn.commit()
        logger.info("密码重置验证码已发送: %s", user["email"])
        return {"ok": True, "message": "验证码已发送至您的邮箱，10 分钟内有效"}

    except Exception:
        conn.rollback()
        raise


@router.post("/auth/verify-code")
def verify_reset_code(payload: VerifyCodePayload, request: Request, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
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

    now = datetime.now(timezone.utc)

    reset_code = _get_latest_valid_reset_code(conn, normalized_email, now)
    _verify_reset_code_or_raise(
        reset_code,
        payload.code,
        conn=conn,
        invalid_detail="验证码已过期或无效",
    )
    conn.commit()
    return {"ok": True, "message": "验证通过"}


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordPayload, request: Request, conn: ConnType = Depends(get_db_dep)) -> dict[str, Any]:
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

    try:
        now = datetime.now(timezone.utc).isoformat()

        # 步骤 1：查找并验证验证码
        reset_code = _get_latest_valid_reset_code(conn, normalized_email, now)
        _verify_reset_code_or_raise(
            reset_code,
            payload.code,
            conn=conn,
            invalid_detail="验证码无效或已过期",
        )
        if reset_code is None:
            raise HTTPException(status_code=400, detail="验证码无效或已过期")

        # 步骤 2：查找用户
        user = user_repo.find_user_by_email(conn, normalized_email)

        if not user:
            raise HTTPException(status_code=400, detail="用户不存在")

        # 步骤 3：生成新密码哈希
        new_hash = hash_password_bcrypt(payload.new_password)

        # 步骤 4：更新密码
        user_repo.update_password(conn, user["id"], new_hash)

        # 步骤 5：标记验证码已使用
        auth_repo.mark_reset_code_used(conn, reset_code["id"])

        # 步骤 6：清理该邮箱其他未使用的验证码
        auth_repo.delete_other_reset_codes(conn, normalized_email, reset_code["id"])

        conn.commit()

        # 清除用户缓存，确保后续查询获取最新数据
        from services.cache_service import invalidate_user
        invalidate_user(str(user["id"]))

        logger.info("密码重置成功: %s", user["email"])
        return {"ok": True, "message": "密码重置成功，请使用新密码登录"}

    except Exception:
        conn.rollback()
        raise
