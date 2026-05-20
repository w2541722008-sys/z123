"""
密码哈希模块 — bcrypt 和旧版 SHA-256 密码处理。

安全设计：
    - bcrypt 自带随机盐，故意设计得慢以抵抗 GPU/ASIC 暴力破解
    - SHA-256 验证使用 hmac.compare_digest 防止时序攻击
    - 支持平滑迁移：老用户 SHA-256 密码登录时自动升级为 bcrypt
"""

from __future__ import annotations

import hashlib
import hmac

import bcrypt

from core.config import APP_SECRET


def _sha256_hash_password(password: str) -> str:
    """
    旧版密码哈希（SHA-256 + APP_SECRET 盐）。

    警告：
        此函数仅用于向后兼容，新用户必须使用 bcrypt。
        SHA-256 计算速度快，容易被 GPU 暴力破解，不适合密码存储。
    """
    return hashlib.sha256(f"{APP_SECRET}:{password}".encode("utf-8")).hexdigest()


def hash_password_bcrypt(password: str, rounds: int = 10) -> str:
    """
    用 bcrypt 给密码加密，返回哈希字符串。

    rounds=10 是平衡安全和速度的推荐参数，普通服务器约耗时 40-80ms。
    旧版 rounds=12 的哈希仍可正常验证（bcrypt 自动识别 rounds）。
    """
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds))
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str, algo: str = "sha256") -> bool:
    """
    验证用户输入的密码是否正确。

    bcrypt 验证使用 bcrypt.checkpw（内部已防时序攻击）。
    SHA-256 验证使用 hmac.compare_digest（防止时序攻击）。
    """
    if algo == "bcrypt":
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    else:
        return hmac.compare_digest(_sha256_hash_password(password), password_hash)
