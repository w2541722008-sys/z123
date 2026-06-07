"""
Token 管理 — 生成、验证、续期、吊销。

安全设计：
    - Token 用 secrets.token_urlsafe(32) 生成（256 位熵）
    - SHA-256 哈希后存库，数据库泄露也无法直接使用 token
    - 支持 access/refresh 双 token 类型
    - 滑动续期：token 剩余有效期不足 7 天时自动延长
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import psycopg2

from core.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    TOKEN_EXPIRE_DAYS,
)
from core.database import get_conn
from core.auth._cache import _cache

logger = logging.getLogger(__name__)

_SLIDING_EXTEND_THRESHOLD = timedelta(days=7)


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

    用户登录时会同步删掉自己名下所有已过期的旧 token。
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
    except psycopg2.Error:
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
        logger.exception("create_token_pair 事务失败")
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

    失败返回 None。
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

        stored_fp = row["device_fingerprint"] or ""
        if device_fingerprint and stored_fp and device_fingerprint != stored_fp:
            logger.warning("refresh token 设备指纹不匹配")
            return None

        user_id = row["user_id"]

        conn.execute(
            "DELETE FROM auth_tokens WHERE refresh_token_hash = %s AND token_type = 'access'",
            (refresh_hash,),
        )

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
        logger.exception("rotate_access_token 事务失败")
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
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_conn()
    try:
        if current_refresh_token:
            current_hash = _hash_token_value(current_refresh_token)
            conn.execute(
                """
                DELETE FROM auth_tokens
                WHERE user_id = %s AND token_type = 'access'
                  AND refresh_token_hash != %s
                  AND refresh_token_hash != ''
                """,
                (user_id, current_hash),
            )
            cursor = conn.execute(
                """
                DELETE FROM auth_tokens
                WHERE user_id = %s AND token_type = 'refresh'
                  AND token != %s
                """,
                (user_id, current_hash),
            )
        else:
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
        logger.exception("revoke_user_device_tokens 事务失败")
        raise
    finally:
        if owns_conn:
            conn.close()


def delete_token(token: str, *, commit: bool = True) -> int:
    """
    删除指定的 token（用于登出）。

    此操作不可逆，删除后用户需要重新登录。
    """
    token_hash = _hash_token_value(token)
    if _cache["delete"] is not None:
        _cache["delete"](f"auth_token:{token_hash}")

    conn = get_conn()
    try:
        cursor = conn.execute("DELETE FROM auth_tokens WHERE token = %s", (token_hash,))
        if commit:
            conn.commit()
        return int(cursor.rowcount)
    except psycopg2.Error:
        if commit:
            conn.rollback()
        raise
    finally:
        conn.close()


def _sliding_extend_token(token_hash: str, expires_at_str: str | None, now: datetime, *, conn=None) -> None:
    """
    Token 滑动续期：当 token 剩余有效期不足 7 天时，自动延长至 TOKEN_EXPIRE_DAYS。

    续期操作是幂等的。
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
        try:
            conn.execute(
                "UPDATE auth_tokens SET expires_at = %s WHERE token = %s",
                (new_expires, token_hash),
            )
            logging.info("Token 已自动续期: user_id=***")
        except (psycopg2.Error, psycopg2.OperationalError) as e:
            logging.warning("Token 自动续期失败: %s", e, exc_info=True)
    else:
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
