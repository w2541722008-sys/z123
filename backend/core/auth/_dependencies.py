"""
认证依赖注入 — FastAPI Depends 函数和数据类。

提供：
    - CurrentUser: 当前用户数据类
    - get_current_user: 强制登录的 FastAPI 依赖
    - get_optional_user: 可选登录的 FastAPI 依赖
    - get_admin_user: 管理员白名单校验的 FastAPI 依赖
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, Request

from core.config import ADMIN_EMAILS
from core.database import get_conn
from core.exceptions import ForbiddenError, UnauthorizedError
from core.plan_constants import serialize_plan_info

logger = logging.getLogger(__name__)
from core.auth._cache import _cache
from core.auth._cookies import _COOKIE_NAME
from core.auth._token import _hash_token_value


@dataclass
class CurrentUser:
    """当前已登录用户的信息，通过 FastAPI Depends 注入到路由函数。"""

    id: int | str
    email: str
    nickname: str
    plan_type: str = "free"
    effective_plan: str = "free"
    plan_expires_at: str = ""
    is_admin: bool = False
    avatar_url: str = ""

    def to_dict(self) -> dict[str, Any]:
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
        return cls(**data)


def _is_admin_email(email: str) -> bool:
    """判断邮箱是否属于管理后台白名单。"""
    normalized = (email or "").strip().lower()
    return bool(normalized) and normalized in ADMIN_EMAILS


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
        - 缓存 TTL 为 300 秒（5 分钟）
    """
    token_hash = _hash_token_value(token)
    cache_key = f"auth_token:{token_hash}"

    if _cache["get"] is not None:
        cached = _cache["get"](cache_key)
        if cached is not None:
            try:
                return CurrentUser.from_dict(cached)
            except (KeyError, TypeError):
                if _cache["delete"] is not None:
                    _cache["delete"](cache_key)

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

        conn.commit()
    except Exception:
        logger.exception("令牌验证事务失败")
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

    if _cache["set"] is not None:
        _cache["set"](cache_key, user.to_dict(), ttl=300)

    return user


def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser | None:
    """
    从 Cookie 或 Authorization 头读取 token，验证后返回当前用户信息（可选）。

    验证失败返回 None（不抛异常）。
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

    Raises:
        HTTPException: 401 未登录或登录已过期
    """
    user = get_optional_user(request, authorization)
    if not user:
        raise UnauthorizedError("未登录或登录已过期")
    return user


def get_admin_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """要求当前登录用户必须属于管理员邮箱白名单。"""
    user = get_current_user(request, authorization)
    if not user.is_admin:
        raise ForbiddenError("你没有管理后台权限")
    return user
