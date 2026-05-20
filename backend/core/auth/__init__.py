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

子模块：
    _password.py     — 密码哈希和验证
    _token.py        — Token 生成、续期、吊销
    _dependencies.py — CurrentUser 数据类、FastAPI 依赖注入
    _cookies.py      — HttpOnly Cookie 配置和读写
    _cache.py        — 缓存回调变量（IoC 注入点）

使用示例：
    >>> from fastapi import Depends
    >>> from core.auth import get_current_user, CurrentUser
    >>>
    >>> @app.get("/profile")
    >>> def get_profile(user: CurrentUser = Depends(get_current_user)):
    >>>     return {"nickname": user.nickname}
"""

from __future__ import annotations

from typing import Any, Callable

from core.auth._cache import _cache

# ── 密码 ──
from core.auth._password import (
    _sha256_hash_password,
    hash_password_bcrypt,
    verify_password,
)

# ── Token ──
from core.auth._token import (
    _hash_token_value,
    _sliding_extend_token,
    create_token,
    create_token_pair,
    delete_token,
    revoke_user_device_tokens,
    rotate_access_token,
)

# ── Cookie ──
from core.auth._cookies import (
    clear_auth_cookie,
    clear_refresh_cookie,
    set_auth_cookie,
    set_refresh_cookie,
)

# ── 依赖注入 ──
from core.auth._dependencies import (
    CurrentUser,
    _extract_token_from_request,
    _is_admin_email,
    generate_device_fingerprint,
    get_admin_user,
    get_current_user,
    get_optional_user,
)


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
    from core.auth._cache import _cache
    _cache["get"] = cache_get_fn
    _cache["set"] = cache_set_fn
    _cache["delete"] = cache_delete_fn
