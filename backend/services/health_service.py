"""
健康检查服务

提供数据库和媒体资源的健康检查功能，带缓存机制避免高频查询压垮数据库。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from core.config import FRONTEND_DIR, PROJECT_DIR
from core.database import get_db

logger = logging.getLogger(__name__)

# 缓存配置
_db_health_cache: dict[str, Any] = {"ok": False, "ts": 0.0}
_DB_HEALTH_TTL = 30

_media_health_cache: dict[str, Any] = {"ok": True, "missing_count": 0, "samples": [], "ts": 0.0}
_MEDIA_HEALTH_TTL = 60


def check_db_health() -> bool:
    """检查数据库健康状态（带 TTL 缓存，30 秒内不重复查询）。"""
    now = time.time()
    if now - _db_health_cache["ts"] < _DB_HEALTH_TTL:
        return bool(_db_health_cache["ok"])
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            _db_health_cache["ok"] = True
    except Exception:
        _db_health_cache["ok"] = False
    finally:
        _db_health_cache["ts"] = time.time()
    return bool(_db_health_cache["ok"])


def media_path_exists(media_value: str) -> bool:
    """检查媒体资源路径是否存在。

    支持以下格式：
        - URL（http/https）→ 直接返回 True
        - 静态路径前缀（/frontend/、/api/avatar/、/api/cover/）→ 直接返回 True
        - 绝对路径 / 相对路径 → 检查文件系统
    """
    value = (media_value or "").strip()
    if not value:
        return True

    if value.startswith(("http://", "https://", "/frontend/", "/api/avatar/", "/api/cover/")):
        return True

    candidate = Path(value)
    if candidate.exists():
        return True

    if value.startswith("/"):
        absolute_like = PROJECT_DIR / value.lstrip("/")
        return absolute_like.exists()

    return (FRONTEND_DIR / value).exists() or (PROJECT_DIR / value).exists()


def check_media_health(*, force: bool = False) -> dict[str, object]:
    """检查媒体资源健康状态（带 TTL 缓存，60 秒内不重复查询）。"""
    now = time.time()
    if (not force) and now - _media_health_cache["ts"] < _MEDIA_HEALTH_TTL:
        return {
            "ok": bool(_media_health_cache["ok"]),
            "missing_count": int(_media_health_cache["missing_count"]),
            "samples": list(_media_health_cache["samples"]),
        }

    missing: list[str] = []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, avatar_url, cover_url FROM characters"
            ).fetchall()
            for row in rows:
                character_id = row.get("id", "unknown")
                for field in ("avatar_url", "cover_url"):
                    value = (row.get(field) or "").strip()
                    if not value:
                        continue
                    if not media_path_exists(value):
                        missing.append(f"{character_id}:{field}:{value}")
    except Exception as exc:
        logging.warning("媒体资源健康检查失败: %s", exc)
        _media_health_cache["ok"] = False
        _media_health_cache["missing_count"] = 1
        _media_health_cache["samples"] = [f"health-check-error:{exc}"]
        _media_health_cache["ts"] = time.time()
        return {
            "ok": False,
            "missing_count": 1,
            "samples": [f"health-check-error:{exc}"],
        }

    _media_health_cache["ok"] = len(missing) == 0
    _media_health_cache["missing_count"] = len(missing)
    _media_health_cache["samples"] = missing[:5]
    _media_health_cache["ts"] = time.time()
    return {
        "ok": bool(_media_health_cache["ok"]),
        "missing_count": int(_media_health_cache["missing_count"]),
        "samples": list(_media_health_cache["samples"]),
    }
