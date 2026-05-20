"""
Cookie 认证配置 — HttpOnly Cookie 的读写操作。

安全设计：
    - 生产环境 Cookie 标记 Secure + SameSite=Strict（防 CSRF）
    - 所有 Cookie 标记 HttpOnly（防 XSS 读取）
    - Path 限定在 /api，前端静态文件不会收到 Cookie
"""

from __future__ import annotations

from fastapi import Response

from core.config import ENV, REFRESH_TOKEN_EXPIRE_DAYS, TOKEN_EXPIRE_DAYS

_COOKIE_NAME = "aifriend_session"
_COOKIE_MAX_AGE = TOKEN_EXPIRE_DAYS * 86400
_COOKIE_PATH = "/api"
_COOKIE_SAMESITE: str = "strict" if ENV == "production" else "lax"

_REFRESH_COOKIE_NAME = "aifriend_refresh"
_REFRESH_COOKIE_MAX_AGE = REFRESH_TOKEN_EXPIRE_DAYS * 86400


def set_auth_cookie(response: Response, token: str) -> None:
    """在响应中设置 HttpOnly 认证 Cookie（access token）。"""
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


def set_refresh_cookie(response: Response, token: str) -> None:
    """在响应中设置 HttpOnly Refresh Cookie。"""
    secure = ENV == "production"
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=token,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        path=_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=_COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response: Response) -> None:
    """清除 Refresh Cookie（登出时调用）。"""
    secure = ENV == "production"
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=_COOKIE_SAMESITE,
    )
