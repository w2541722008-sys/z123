"""
认证模块 - 处理用户登录、注册、Token 管理

功能范围：
    - 密码哈希（bcrypt）和验证
    - Token 生成和验证
    - FastAPI 依赖注入（get_current_user, get_optional_user）

安全设计说明：
    - 密码使用 bcrypt 哈希，故意设计得慢以抵抗暴力破解
    - Token 使用 SHA-256 哈希后存库，数据库泄露也无法直接使用
    - 支持平滑迁移：老用户 SHA-256 密码登录时自动升级为 bcrypt

主要导出：
    - hash_password_bcrypt: 密码哈希函数
    - verify_password: 密码验证函数（支持 bcrypt 和旧版 SHA-256）
    - create_token: 生成登录 token
    - delete_token: 删除 token（登出）
    - get_current_user: FastAPI 依赖，强制登录
    - get_optional_user: FastAPI 依赖，可选登录
    - CurrentUser: 当前用户数据类

使用示例：
    >>> from fastapi import Depends
    >>> from auth import get_current_user, CurrentUser
    >>> 
    >>> @app.get("/profile")
    >>> def get_profile(user: CurrentUser = Depends(get_current_user)):
    >>>     return {"nickname": user.nickname}
"""

from __future__ import annotations

# 标准库导入
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Callable
from datetime import datetime, timedelta, timezone

# 第三方库导入
import bcrypt
from fastapi import Header, HTTPException, Request, Response
from starlette.responses import Response as StarletteResponse

# 本地模块导入
from core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES, ADMIN_EMAILS, APP_SECRET, DEBUG, ENV,
    REFRESH_TOKEN_EXPIRE_DAYS, TOKEN_EXPIRE_DAYS,
)
from core.database import get_conn
from core.plan_constants import serialize_plan_info


# ============================================================
# 缓存回调接口（避免 core 反向依赖 services）
# ============================================================
# core 层不直接 import services.cache_service，而是在应用启动时
# 通过 register_cache_callbacks() 注入具体实现。
_cache_get = None  # type: Callable[[str], Any] | None
_cache_set = None  # type: Callable[[str, Any, int | None], None] | None
_cache_delete = None  # type: Callable[[str], None] | None


def register_cache_callbacks(
    cache_get_fn,
    cache_set_fn,
    cache_delete_fn,
) -> None:
    """注册缓存回调函数，由 main.py 启动时调用。

    Args:
        cache_get_fn: (key: str) -> Any | None
        cache_set_fn: (key: str, value: Any, ttl: int | None) -> None
        cache_delete_fn: (key: str) -> None
    """
    global _cache_get, _cache_set, _cache_delete
    _cache_get = cache_get_fn
    _cache_set = cache_set_fn
    _cache_delete = cache_delete_fn


# ============================================================
# Cookie 认证配置
# ============================================================
_COOKIE_NAME = "aifriend_session"
_COOKIE_MAX_AGE = TOKEN_EXPIRE_DAYS * 86400  # 与 token 过期时间一致
_COOKIE_PATH = "/api"
_COOKIE_SAMESITE: str = "strict" if ENV == "production" else "lax"  # 生产环境 Strict 防 CSRF


def set_auth_cookie(response: Response, token: str) -> None:
    """在响应中设置 HttpOnly 认证 Cookie。"""
    secure = ENV == "production"
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=_COOKIE_MAX_AGE,
        path=_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=_COOKIE_SAMESITE,
    )


def clear_auth_cookie(response: Response) -> None:
    """清除认证 Cookie（登出时调用）。"""
    secure = ENV == "production"
    response.delete_cookie(
        key=_COOKIE_NAME,
        path=_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=_COOKIE_SAMESITE,
    )


# ============================================================
# 密码哈希
# ============================================================
def _sha256_hash_password(password: str) -> str:
    """
    旧版密码哈希（SHA-256 + APP_SECRET 盐）。

    警告：
        此函数仅用于向后兼容，新用户必须使用 bcrypt。
        SHA-256 计算速度快，容易被 GPU 暴力破解，不适合密码存储。

    Args:
        password: 明文密码

    Returns:
        64 字符的十六进制哈希字符串
    """
    return hashlib.sha256(f"{APP_SECRET}:{password}".encode("utf-8")).hexdigest()


def hash_password_bcrypt(password: str, rounds: int = 10) -> str:
    """
    用 bcrypt 给密码加密，返回哈希字符串。

    安全特性：
        - bcrypt 自带随机盐（salt），每次调用结果都不同
        - rounds=10 是平衡安全和速度的推荐参数，普通服务器约耗时 40-80ms
        - 故意设计得慢，抵抗 GPU/ASIC 暴力破解
        - 旧版 rounds=12 的哈希仍可正常验证（bcrypt 自动识别 rounds）

    Args:
        password: 明文密码（长度建议 >= 8）
        rounds: bcrypt 计算轮数，默认 10。值越大越安全但越慢

    Returns:
        bcrypt 哈希字符串（包含算法版本、rounds、盐和哈希值）

    示例：
        >>> hash_pw = hash_password_bcrypt("my_password")
        >>> print(hash_pw)
        $2b$10$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I1K
    """
    # bcrypt 只接受 bytes，需要先编码；哈希结果也是 bytes，解码成 str 存库
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds))
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str, algo: str = "sha256") -> bool:
    """
    验证用户输入的密码是否正确。

    安全特性：
        - bcrypt 验证使用 bcrypt.checkpw，内部已防时序攻击
        - SHA-256 验证使用 hmac.compare_digest，防止时序攻击（避免通过响应时间推断密码）

    Args:
        password: 用户输入的明文密码
        password_hash: 数据库里存的哈希值
        algo: 哈希算法标识，'bcrypt' 或 'sha256'（老用户默认 sha256）

    Returns:
        True 表示密码正确，False 表示密码错误

    注意：
        即使密码错误，函数执行时间也保持恒定，防止时序攻击
    """
    if algo == "bcrypt":
        # bcrypt 验证：直接用 checkpw，不需要 hmac.compare_digest（bcrypt 内部已防时序攻击）
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    else:
        # 旧版 SHA-256 验证，用 hmac.compare_digest 防止时序攻击
        return hmac.compare_digest(_sha256_hash_password(password), password_hash)


async def hash_password_bcrypt_async(password: str, rounds: int = 10) -> str:
    """异步版密码哈希，将 CPU 密集的 bcrypt 操作放入线程池执行。

    适用于 async def 路由，避免阻塞事件循环。
    当前同步路由仍使用 hash_password_bcrypt（FastAPI 自动放入线程池）。
    """
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(hash_password_bcrypt, password, rounds)


async def verify_password_async(password: str, password_hash: str, algo: str = "sha256") -> bool:
    """异步版密码验证，将 CPU 密集的 bcrypt 操作放入线程池执行。"""
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(verify_password, password, password_hash, algo)


def _hash_token_value(token: str) -> str:
    """把客户端 Bearer Token 哈希成数据库里保存的值。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cleanup_expired_tokens(
    conn,
    *,
    token_candidates: tuple[str, ...] | None = None,
    user_id: int | str | None = None,
    now_iso: str,
    commit: bool = True,
) -> int:
    """清理已过期 token，支持按 token 候选或按用户范围删除。"""
    if not token_candidates and user_id is None:
        return 0

    if token_candidates:
        placeholders = ", ".join(["%s"] * len(token_candidates))
        cursor = conn.execute(
            f"DELETE FROM auth_tokens WHERE token IN ({placeholders}) AND expires_at IS NOT NULL AND expires_at <= %s",
            (*token_candidates, now_iso),
        )
    else:
        cursor = conn.execute(
            "DELETE FROM auth_tokens WHERE user_id = %s AND expires_at IS NOT NULL AND expires_at <= %s",
            (user_id, now_iso),
        )

    if commit and cursor.rowcount > 0:
        conn.commit()
    return int(cursor.rowcount)


# ============================================================
# 当前用户数据类
# ============================================================
@dataclass
class CurrentUser:
    """
    表示当前已登录用户的信息。
    
    通过 FastAPI 的 Depends(get_current_user) 注入到路由函数中。
    """
    id: int | str
    email: str
    nickname: str
    plan_type: str = "free"
    effective_plan: str = "free"
    plan_expires_at: str = ""
    is_admin: bool = False
    avatar_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，用于缓存存储。"""
        return {
            "id": self.id,
            "email": self.email,
            "nickname": self.nickname,
            "plan_type": self.plan_type,
            "effective_plan": self.effective_plan,
            "plan_expires_at": self.plan_expires_at,
            "is_admin": self.is_admin,
            "avatar_url": self.avatar_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurrentUser:
        """从缓存字典反序列化。"""
        return cls(**data)


def _is_admin_email(email: str) -> bool:
    """判断邮箱是否属于管理后台白名单。"""
    normalized = (email or "").strip().lower()
    return bool(normalized) and normalized in ADMIN_EMAILS


# ============================================================
# Token 管理
# ============================================================
def create_token(
    user_id: int | str,
    *,
    conn=None,
    commit: bool = True,
    token_type: str = "access",
    device_fingerprint: str = "",
    refresh_token_hash: str = "",
) -> str:
    """
    生成一个新的登录 token，并写入数据库。

    安全设计：
        - 用 secrets.token_urlsafe(32) 生成 32 字节随机串（256 位熵），
          再经过 SHA-256 哈希后存入数据库（数据库泄露也无法直接使用 token）
        - 支持 access/refresh 双 token 类型
        - 设备指纹绑定：refresh token 可绑定到特定设备
        - 用户登录时会同步删掉自己名下所有已过期的旧 token

    Args:
        user_id: 用户 ID
        conn: 可选外部数据库连接
        commit: 是否在函数内部提交事务
        token_type: 'access' 或 'refresh'
        device_fingerprint: 设备指纹哈希（仅 refresh token 需要）
        refresh_token_hash: 关联的 refresh token 哈希（仅 access token 需要）

    Returns:
        返回给客户端使用的原始 Bearer Token
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token_value(raw_token)

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    if token_type == "refresh":
        expires_at = (now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    else:
        expires_at = (now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)).isoformat()

    owns_conn = conn is None
    if owns_conn:
        conn = get_conn()
    try:
        _cleanup_expired_tokens(conn, user_id=user_id, now_iso=now_iso, commit=False)
        conn.execute(
            "INSERT INTO auth_tokens(token, user_id, created_at, expires_at, token_type, device_fingerprint, refresh_token_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (token_hash, user_id, now_iso, expires_at, token_type, device_fingerprint, refresh_token_hash),
        )
        if commit:
            conn.commit()
    except Exception:
        if commit:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()

    return raw_token


def create_token_pair(
    user_id: int | str,
    *,
    conn=None,
    commit: bool = True,
    device_fingerprint: str = "",
) -> dict[str, str]:
    """
    生成 access_token + refresh_token 双 token 对。

    Access token 用于 API 鉴权（短期 15 min），
    Refresh token 用于续期（长期 30 day），绑定设备指纹。

    Args:
        user_id: 用户 ID
        conn: 可选外部数据库连接
        commit: 是否在函数内部提交事务
        device_fingerprint: 设备指纹哈希

    Returns:
        {"access_token": "...", "refresh_token": "..."}
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_conn()
    try:
        refresh_token = create_token(
            user_id, conn=conn, commit=False,
            token_type="refresh", device_fingerprint=device_fingerprint,
        )
        refresh_hash = _hash_token_value(refresh_token)
        access_token = create_token(
            user_id, conn=conn, commit=False,
            token_type="access", device_fingerprint=device_fingerprint,
            refresh_token_hash=refresh_hash,
        )
        if commit:
            conn.commit()
        return {"access_token": access_token, "refresh_token": refresh_token}
    except Exception:
        if commit:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def rotate_access_token(
    refresh_token: str,
    *,
    device_fingerprint: str = "",
    conn=None,
) -> str | None:
    """
    用 refresh token 换取新的 access token（旧 access token 失效）。

    验证 refresh token 有效 + 设备指纹匹配后：
    1. 删除旧 access token(s)
    2. 生成新 access token

    Returns:
        新 access token，失败返回 None
    """
    refresh_hash = _hash_token_value(refresh_token)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    owns_conn = conn is None
    if owns_conn:
        conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT user_id, device_fingerprint, expires_at
            FROM auth_tokens
            WHERE token = %s AND token_type = 'refresh'
              AND (expires_at IS NULL OR expires_at > %s)
            """,
            (refresh_hash, now_iso),
        ).fetchone()

        if not row:
            return None

        # 设备指纹验证
        stored_fp = row["device_fingerprint"] or ""
        if device_fingerprint and stored_fp and device_fingerprint != stored_fp:
            logger.warning("refresh token 设备指纹不匹配")
            return None

        user_id = row["user_id"]

        # 删除旧 access token(s)
        conn.execute(
            "DELETE FROM auth_tokens WHERE refresh_token_hash = %s AND token_type = 'access'",
            (refresh_hash,),
        )

        # 生成新 access token
        new_access = create_token(
            user_id, conn=conn, commit=False,
            token_type="access", device_fingerprint=stored_fp,
            refresh_token_hash=refresh_hash,
        )
        conn.commit()
        return new_access
    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def revoke_user_device_tokens(
    user_id: int | str,
    current_refresh_token: str = "",
    *,
    conn=None,
    commit: bool = True,
) -> int:
    """
    踢出用户的其他设备：删除所有不匹配 current_refresh_token 的 refresh token。

    同时级联删除关联的 access token。

    Args:
        user_id: 用户 ID
        current_refresh_token: 当前设备的 refresh token（保留此设备）
        conn: 可选外部数据库连接
        commit: 是否提交事务

    Returns:
        被删除的 refresh token 数量
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_conn()
    try:
        if current_refresh_token:
            current_hash = _hash_token_value(current_refresh_token)
            # 先删除其他设备的 access tokens
            conn.execute(
                """
                DELETE FROM auth_tokens
                WHERE user_id = %s AND token_type = 'access'
                  AND refresh_token_hash != %s
                  AND refresh_token_hash != ''
                """,
                (user_id, current_hash),
            )
            # 再删除其他设备的 refresh tokens
            cursor = conn.execute(
                """
                DELETE FROM auth_tokens
                WHERE user_id = %s AND token_type = 'refresh'
                  AND token != %s
                """,
                (user_id, current_hash),
            )
        else:
            # 没有指定保留 token，删除所有
            conn.execute(
                "DELETE FROM auth_tokens WHERE user_id = %s AND token_type = 'access'",
                (user_id,),
            )
            cursor = conn.execute(
                "DELETE FROM auth_tokens WHERE user_id = %s AND token_type = 'refresh'",
                (user_id,),
            )
        deleted = int(cursor.rowcount)
        if commit:
            conn.commit()
        return deleted
    except Exception:
        if commit:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def delete_token(token: str, *, commit: bool = True) -> int:
    """
    删除指定的 token（用于登出）。

    Args:
        token: 原始 token（客户端持有的 Bearer token）
        commit: 是否立即提交事务

    注意：
        此操作不可逆，删除后用户需要重新登录
    """
    token_hash = _hash_token_value(token)
    # 删除 token 时同步清除用户缓存，防止已登出的 token 仍命中缓存
    if _cache_delete is not None:
        _cache_delete(f"auth_token:{token_hash}")

    conn = get_conn()
    try:
        cursor = conn.execute("DELETE FROM auth_tokens WHERE token = %s", (token_hash,))
        if commit:
            conn.commit()
        return int(cursor.rowcount)
    except Exception:
        if commit:
            conn.rollback()
        raise
    finally:
        conn.close()


_SLIDING_EXTEND_THRESHOLD = timedelta(days=7)


def _sliding_extend_token(token_hash: str, expires_at_str: str | None, now: datetime, *, conn=None) -> None:
    """
    Token 滑动续期：当 token 剩余有效期不足阈值时，自动延长至 TOKEN_EXPIRE_DAYS。

    仅在以下条件同时满足时执行续期：
      1. token 有明确的过期时间（非 NULL）
      2. 距离过期不足 _SLIDING_EXTEND_THRESHOLD（7 天）

    续期操作是幂等的（重复调用不会产生副作用）。

    Args:
        token_hash: token 的 SHA-256 哈希值
        expires_at_str: token 过期时间字符串
        now: 当前时间
        conn: 可选，外部数据库连接；传入时复用同一连接和事务，不传时独立获取连接
    """
    if not expires_at_str:
        return
    try:
        expires_at = datetime.fromisoformat(expires_at_str)
        if (expires_at - now) > _SLIDING_EXTEND_THRESHOLD:
            return
    except (ValueError, TypeError):
        return

    new_expires = (now + timedelta(days=TOKEN_EXPIRE_DAYS)).isoformat()

    if conn is not None:
        # 复用外部连接，不自行 commit（由调用方管理事务）
        try:
            conn.execute(
                "UPDATE auth_tokens SET expires_at = %s WHERE token = %s",
                (new_expires, token_hash),
            )
            logging.info("Token 已自动续期: user_id=***")
        except Exception as e:
            logging.warning("Token 自动续期失败: %s", e, exc_info=True)
    else:
        # 兜底：独立连接（向后兼容调用方）
        extend_conn = None
        try:
            extend_conn = get_conn()
            extend_conn.execute(
                "UPDATE auth_tokens SET expires_at = %s WHERE token = %s",
                (new_expires, token_hash),
            )
            extend_conn.commit()
            logging.info("Token 已自动续期: user_id=***")
        except Exception as e:
            if extend_conn is not None:
                try:
                    extend_conn.rollback()
                except Exception:
                    pass
            logging.warning("Token 自动续期失败: %s", e, exc_info=True)
        finally:
            if extend_conn is not None:
                try:
                    extend_conn.close()
                except Exception:
                    pass


# ============================================================
# FastAPI 依赖注入
# ============================================================
def _extract_token_from_request(request: Request, authorization: str | None) -> str | None:
    """从 Cookie 或 Authorization 头中提取 token。优先 Cookie，回退 Header。"""
    cookie_token = request.cookies.get(_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def generate_device_fingerprint(request: Request) -> str:
    """生成设备指纹哈希。

    基于 User-Agent + 客户端 IP 前缀（前三段）+ X-Device-ID 头（可选）。
    用于将 refresh token 绑定到特定设备，防止 token 被窃取后在其它设备使用。
    """
    ua = request.headers.get("User-Agent", "")
    ip = request.client.host if request.client else ""
    ip_prefix = ".".join(ip.split(".")[:3]) if ip else ""
    device_id = request.headers.get("X-Device-ID", "")
    raw = f"{ua}|{ip_prefix}|{device_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _verify_token_and_get_user(token: str) -> CurrentUser | None:
    """验证 token 并返回 CurrentUser，失败返回 None。

    性能优化：
        - 优先从内存缓存获取用户信息，缓存命中时跳过 DB 查询
        - Token 续期复用同一数据库连接，避免额外获取连接
        - 缓存 TTL 为 300 秒（5 分钟），与角色缓存一致
    """
    token_hash = _hash_token_value(token)
    cache_key = f"auth_token:{token_hash}"

    # 1. 先查缓存
    if _cache_get is not None:
        cached = _cache_get(cache_key)
        if cached is not None:
            try:
                return CurrentUser.from_dict(cached)
            except (KeyError, TypeError):
                # 缓存数据损坏，清除后继续走 DB 查询
                if _cache_delete is not None:
                    _cache_delete(cache_key)

    # 2. 缓存未命中，查询数据库
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT users.id, users.email, COALESCE(users.nickname, '') AS nickname,
                   COALESCE(users.plan_type, 'free') AS plan_type,
                   COALESCE(CAST(users.plan_expires_at AS VARCHAR), '') AS plan_expires_at,
                   COALESCE(users.avatar_url, '') AS avatar_url,
                   auth_tokens.expires_at
            FROM auth_tokens
            JOIN users ON users.id = auth_tokens.user_id
            WHERE auth_tokens.token = %s
              AND auth_tokens.token_type = 'access'
              AND (auth_tokens.expires_at IS NULL OR auth_tokens.expires_at > %s)
            ORDER BY auth_tokens.created_at DESC
            LIMIT 1
            """,
            (token_hash, now_iso),
        ).fetchone()

        if not row:
            return None

        # 3. Token 续期（复用同一连接，续期成功后统一 commit）
        _sliding_extend_token(token_hash, row["expires_at"], now, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    nickname = row["nickname"] or row["email"].split("@")[0]
    plan_info = serialize_plan_info(row["plan_type"], row["plan_expires_at"])
    user = CurrentUser(
        id=row["id"],
        email=row["email"],
        nickname=nickname,
        plan_type=plan_info["plan_type"],
        effective_plan=plan_info["effective_plan"],
        plan_expires_at=plan_info["plan_expires_at"],
        is_admin=_is_admin_email(row["email"]),
        avatar_url=row.get("avatar_url", ""),
    )

    # 4. 写入缓存（TTL 5 分钟，与 Token 续期窗口匹配）
    if _cache_set is not None:
        _cache_set(cache_key, user.to_dict(), ttl=300)

    return user


def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser | None:
    """
    从 Cookie 或 Authorization 头读取 token，验证后返回当前用户信息（可选）。

    验证规则：
        - 优先从 HttpOnly Cookie 读取 token
        - Cookie 不存在时回退到 Authorization 头
        - token 必须存在于 auth_tokens 表
        - token 的 expires_at 不能早于当前时间

    Args:
        request: FastAPI 请求对象（用于读取 Cookie）
        authorization: HTTP Authorization 头，格式 "Bearer <token>"

    Returns:
        CurrentUser 对象，如果验证失败则返回 None
    """
    token = _extract_token_from_request(request, authorization)
    if not token:
        return None
    return _verify_token_and_get_user(token)


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """
    从 Cookie 或 Authorization 头读取 token，验证后返回当前用户信息（强制）。

    Args:
        request: FastAPI 请求对象（用于读取 Cookie）
        authorization: HTTP Authorization 头，格式 "Bearer <token>"

    Returns:
        CurrentUser 对象

    Raises:
        HTTPException: 401 未登录或登录已过期
    """
    user = get_optional_user(request, authorization)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


def get_admin_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """要求当前登录用户必须属于管理员邮箱白名单。"""
    user = get_current_user(request, authorization)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="你没有管理后台权限")
    return user
