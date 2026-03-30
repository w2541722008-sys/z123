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
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# 第三方库导入
import bcrypt
from fastapi import Header, HTTPException

# 本地模块导入
from config import APP_SECRET, TOKEN_EXPIRE_DAYS
from database import get_conn
from services.plan_service import serialize_plan_info


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


def hash_password_bcrypt(password: str) -> str:
    """
    用 bcrypt 给密码加密，返回哈希字符串。

    安全特性：
        - bcrypt 自带随机盐（salt），每次调用结果都不同
        - rounds=12 是平衡安全和速度的经典参数，普通服务器约耗时 100-300ms
        - 故意设计得慢，抵抗 GPU/ASIC 暴力破解

    Args:
        password: 明文密码（长度建议 >= 8）

    Returns:
        bcrypt 哈希字符串（包含算法版本、rounds、盐和哈希值）

    示例：
        >>> hash_pw = hash_password_bcrypt("my_password")
        >>> print(hash_pw)
        $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiAYMyzJ/I1K
    """
    # bcrypt 只接受 bytes，需要先编码；哈希结果也是 bytes，解码成 str 存库
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
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


def _hash_token_value(token: str) -> str:
    """把客户端 Bearer Token 哈希成数据库里保存的值。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ============================================================
# 当前用户数据类
# ============================================================
@dataclass
class CurrentUser:
    """
    表示当前已登录用户的信息。
    
    通过 FastAPI 的 Depends(get_current_user) 注入到路由函数中。
    """
    id: int
    email: str
    nickname: str
    plan_type: str = "free"
    effective_plan: str = "free"
    plan_expires_at: str = ""


# ============================================================
# Token 管理
# ============================================================
def create_token(user_id: int) -> str:
    """
    生成一个新的登录 token，并写入数据库。

    安全设计：
        - 用 secrets.token_urlsafe(32) 生成 32 字节随机串（256 位熵），
          再经过 SHA-256 哈希后存入数据库（这样数据库泄露也无法直接使用 token）
        - 每个 token 都有明确的过期时间（默认 TOKEN_EXPIRE_DAYS=30 天）
        - 用户登录时会同步删掉自己名下所有已过期的旧 token，保持数据库干净

    Args:
        user_id: 用户 ID

    Returns:
        返回给客户端使用的原始 Bearer Token

    实现细节：
        1. 生成随机字符串：secrets.token_urlsafe(32)
        2. SHA-256 哈希后存入数据库
        3. 清理该用户所有已过期的旧 token
        4. 插入新 token 记录
    """
    # 步骤 1：生成原始 token（返回给客户端）
    raw_token = secrets.token_urlsafe(32)

    # 步骤 2：SHA-256 哈希后存库（数据库泄露也无法直接使用）
    token_hash = _hash_token_value(raw_token)

    # 步骤 3：计算过期时间
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=TOKEN_EXPIRE_DAYS)).isoformat()

    # 步骤 4：数据库操作（清理旧 token + 插入新 token）
    conn = get_conn()
    try:
        # 清理该用户所有已过期的旧 token（防止数据库无限膨胀）
        conn.execute(
            "DELETE FROM auth_tokens WHERE user_id = ? AND expires_at != '' AND expires_at < ?",
            (user_id, now.isoformat()),
        )
        # 插入新 token
        conn.execute(
            "INSERT INTO auth_tokens(token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now.isoformat(), expires_at),
        )
        conn.commit()
    finally:
        conn.close()

    return raw_token


def delete_token(token: str) -> None:
    """
    删除指定的 token（用于登出）。

    Args:
        token: 要删除的 token 哈希值

    注意：
        此操作不可逆，删除后用户需要重新登录
    """
    conn = get_conn()
    try:
        candidates = tuple({token, _hash_token_value(token)})
        placeholders = ", ".join(["?"] * len(candidates))
        conn.execute(f"DELETE FROM auth_tokens WHERE token IN ({placeholders})", candidates)
        conn.commit()
    finally:
        conn.close()


# ============================================================
# FastAPI 依赖注入
# ============================================================
def get_optional_user(authorization: str | None = Header(default=None)) -> CurrentUser | None:
    """
    从请求头里读取 Bearer token，验证后返回当前用户信息（可选）。

    验证规则：
        - token 必须存在于 auth_tokens 表
        - token 的 expires_at 不能早于当前时间
        - 为兼容旧版本，也接受“客户端直接持有 token 哈希值”的老 token

    Args:
        authorization: HTTP Authorization 头，格式 "Bearer <token>"

    Returns:
        CurrentUser 对象，如果验证失败则返回 None

    使用场景：
        用于不需要强制登录的接口，如浏览公开内容时识别已登录用户

    示例：
        >>> @app.get("/public")
        >>> def public_endpoint(user: CurrentUser | None = Depends(get_optional_user)):
        >>>     if user:
        >>>         return {"message": f"你好，{user.nickname}"}
        >>>     return {"message": "你好，游客"}
    """
    # 步骤 1：验证 Authorization 头格式
    if not authorization or not authorization.startswith("Bearer "):
        return None

    # 步骤 2：提取 token
    token = authorization.split(" ", 1)[1].strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    token_hash = _hash_token_value(token)

    # 步骤 3：查询数据库验证 token
    conn = get_conn()
    try:
        candidates = tuple({token, token_hash})
        placeholders = ", ".join(["?"] * len(candidates))
        row = conn.execute(
            f"""
            SELECT users.id, users.email, COALESCE(users.nickname, '') AS nickname,
                   COALESCE(users.plan_type, 'free') AS plan_type,
                   COALESCE(users.plan_expires_at, '') AS plan_expires_at
            FROM auth_tokens
            JOIN users ON users.id = auth_tokens.user_id
            WHERE auth_tokens.token IN ({placeholders})
              AND (auth_tokens.expires_at = '' OR auth_tokens.expires_at > ?)
            ORDER BY auth_tokens.created_at DESC
            LIMIT 1
            """,
            (*candidates, now_iso),
        ).fetchone()

        if not row:
            conn.execute(
                f"DELETE FROM auth_tokens WHERE token IN ({placeholders}) AND expires_at != '' AND expires_at <= ?",
                (*candidates, now_iso),
            )
            conn.commit()
    finally:
        conn.close()

    if not row:
        return None

    # 步骤 4：构造 CurrentUser（如果 nickname 为空，使用邮箱前缀）
    nickname = row["nickname"] or row["email"].split("@")[0]
    plan_info = serialize_plan_info(row["plan_type"], row["plan_expires_at"])
    return CurrentUser(
        id=row["id"],
        email=row["email"],
        nickname=nickname,
        plan_type=plan_info["plan_type"],
        effective_plan=plan_info["effective_plan"],
        plan_expires_at=plan_info["plan_expires_at"],
    )


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """
    从请求头里读取 Bearer token，验证后返回当前用户信息（强制）。

    Args:
        authorization: HTTP Authorization 头，格式 "Bearer <token>"

    Returns:
        CurrentUser 对象

    Raises:
        HTTPException: 401 未登录或登录已过期

    使用场景：
        用于需要强制登录的接口，如个人资料、聊天等

    示例：
        >>> @app.get("/profile")
        >>> def get_profile(user: CurrentUser = Depends(get_current_user)):
        >>>     return {"nickname": user.nickname, "email": user.email}
    """
    user = get_optional_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user
