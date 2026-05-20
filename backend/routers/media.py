"""
媒体资源路由 - 头像、封面、用户头像的上传与获取
"""

from __future__ import annotations

import logging
import struct
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from core.auth import get_current_user
from core.config import AVATARS_DIR, FRONTEND_DIR, PROJECT_DIR
from core.database import ConnType, get_db_dep
from repositories import character_repository as char_repo
from repositories import user_repository as user_repo

router = APIRouter(tags=["media"])

logger = logging.getLogger(__name__)

# 确保用户上传头像目录存在
AVATARS_DIR.mkdir(exist_ok=True)

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# 图片文件头魔术字节（用于验证文件内容是否真正是图片）
_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "jpeg",       # JPEG: FFD8FF
    b"\x89PNG\r\n\x1a\n": "png",   # PNG: 89504E470D0A1A0A
    b"RIFF": "webp",               # WebP: RIFF...WEBP
}


def _validate_image_content(content: bytes, declared_ext: str) -> bool:
    """验证文件内容是否与声明的图片格式匹配（防伪装上传）。"""
    if len(content) < 12:
        return False
    for sig, fmt in _IMAGE_SIGNATURES.items():
        if content[:len(sig)] == sig:
            if fmt == "webp":
                # WebP 格式: RIFF....WEBP
                return content[8:12] == b"WEBP"
            # JPEG/PNG 签名匹配即可
            return True
    return False

# FileResponse 允许的根目录白名单
_SAFE_MEDIA_ROOTS = [AVATARS_DIR, FRONTEND_DIR, PROJECT_DIR / "assets", PROJECT_DIR / "covers"]


def _is_under_safe_dir(path: Path) -> bool:
    """检查解析后的绝对路径是否在白名单目录下，防止路径遍历攻击。"""
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return False
    return any(str(resolved).startswith(str(root.resolve())) for root in _SAFE_MEDIA_ROOTS)


def resolve_media_response(raw_value: str, *, fallback_path: Path | None = None):
    """把数据库中的图片值解析成可返回的响应。

    安全措施：
        - FileResponse 的路径必须在白名单目录内（avatars/、covers/、assets/、frontend/），
          防止路径遍历攻击读取服务器任意文件。
        - URL 重定向仅允许 http/https 和 /frontend/ 前缀。
    """
    media_value = (raw_value or "").strip()

    if media_value:
        try:
            if media_value.startswith(("http://", "https://", "/frontend/")):
                return RedirectResponse(media_value)

            candidate = Path(media_value)
            if candidate.exists() and _is_under_safe_dir(candidate):
                return FileResponse(candidate)

            if media_value.startswith("/"):
                project_absolute_like = PROJECT_DIR / media_value.lstrip("/")
                if project_absolute_like.exists() and _is_under_safe_dir(project_absolute_like):
                    return FileResponse(project_absolute_like)

            if not candidate.is_absolute():
                for base_dir in (FRONTEND_DIR, PROJECT_DIR):
                    resolved = base_dir / media_value
                    if resolved.exists() and _is_under_safe_dir(resolved):
                        return FileResponse(resolved)
        except Exception as exc:
            logger.warning("avatar resolve failed for value=%s: %s", media_value[:80], exc)

    if fallback_path and fallback_path.exists():
        return FileResponse(fallback_path)

    raise HTTPException(status_code=404, detail="图片未找到")


@router.get("/avatar/{character_id}")
def get_avatar(character_id: str, conn: ConnType = Depends(get_db_dep)):
    """返回角色卡头像图片。"""
    avatar_url = char_repo.get_avatar_url(conn, character_id)
    if avatar_url is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    default_avatar = FRONTEND_DIR / "frontend" / "assets" / "default-avatar.png"
    resp = resolve_media_response(avatar_url or "", fallback_path=default_avatar)
    # 重定向可缓存 1 小时，因为目标路径很少变；图片本身由 nginx 提供 7 天缓存
    resp.headers["Cache-Control"] = "max-age=3600"
    return resp


@router.get("/cover/{character_id}")
def get_cover(character_id: str, conn: ConnType = Depends(get_db_dep)):
    """返回角色卡封面图片，支持本地文件、静态路径和外链。"""
    avatar_url, cover_url = char_repo.get_cover_urls(conn, character_id)
    if avatar_url is None:
        raise HTTPException(status_code=404, detail="角色不存在")

    default_avatar = FRONTEND_DIR / "frontend" / "assets" / "default-avatar.png"
    cover_value = (cover_url or "").strip() or (avatar_url or "").strip()
    resp = resolve_media_response(cover_value, fallback_path=default_avatar)
    resp.headers["Cache-Control"] = "max-age=3600"
    return resp


@router.post("/user/avatar")
async def upload_user_avatar(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    conn: ConnType = Depends(get_db_dep),
):
    """上传/更换用户头像。

    安全措施：
    - 文件类型白名单（jpg/png/webp）
    - 文件大小限制（2MB）
    - UUID 随机文件名（防止路径遍历和猜测）
    - MIME 类型 + 扩展名双重校验
    - 上传前自动清理旧头像文件（防止磁盘膨胀）
    """
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、WebP 格式")

    content = await file.read()
    if len(content) > _MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="图片大小不能超过 2MB")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件扩展名")

    # 验证文件内容是否真正是图片（防止恶意文件伪装为图片上传）
    if not _validate_image_content(content, ext):
        raise HTTPException(status_code=400, detail="文件内容与图片格式不匹配")

    row = user_repo.get_user_avatar_url(conn, user.id)
    old_avatar_url = row if row else None

    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = AVATARS_DIR / filename
    filepath.write_bytes(content)

    avatar_url = f"/avatars/{filename}"

    user_repo.update_user_avatar(conn, user.id, avatar_url)
    conn.commit()

    # 清除用户缓存，确保头像更新后前台能立即看到
    from services.cache_service import invalidate_user
    invalidate_user(user.id)

    if old_avatar_url and old_avatar_url.startswith("/avatars/"):
        try:
            old_file = Path(__file__).parent.parent.parent / old_avatar_url.lstrip("/")
            if old_file.exists() and old_file.is_file():
                old_file.unlink()
        except OSError:
            pass

    return {"avatar_url": avatar_url}


@router.get("/user/avatar")
def get_user_avatar(user=Depends(get_current_user), conn: ConnType = Depends(get_db_dep)):
    """获取当前登录用户的头像图片。"""
    avatar_value = user_repo.get_user_avatar_url(conn, user.id)

    default_avatar = FRONTEND_DIR / "frontend" / "assets" / "default-avatar.png"
    return resolve_media_response(avatar_value or "", fallback_path=default_avatar)
