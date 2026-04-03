"""
AI Friend 后端主入口

这个文件是 FastAPI 应用的入口点，职责：
    1. 创建 FastAPI 应用实例
    2. 配置 CORS 中间件
    3. 注册所有路由
    4. 挂载静态文件
    5. 启动时初始化数据库

所有业务逻辑已拆分到：
    - config.py      - 配置常量
    - database.py    - 数据库连接和初始化
    - auth.py        - 认证核心
    - models.py      - Pydantic 模型
    - services/      - 业务逻辑层
    - routers/       - API 路由层

启动方式：
    开发模式：python main.py
    生产模式：uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

# 标准库导入
import logging
import os
import time
import uuid
from pathlib import Path

# 第三方库导入
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# 项目内部导入
import config as _cfg
from auth import get_current_user
from config import FRONTEND_DIR, FRONTEND_STATIC_DIR, validate_production_config
from database import get_conn, get_db, init_db_pool, close_db_pool

# 导入路由
from routers import admin, auth, billing, characters, chat

# ============================================================
# 创建 FastAPI 应用
# ============================================================
app = FastAPI(title="aifriend backend", version="0.3.0")

# ============================================================
# CORS 跨域配置
# ============================================================
# 从环境变量读取允许的域名，支持 credentials 时必须指定具体域名
_allowed_origins_str = os.environ.get("ALLOWED_ORIGINS", "")
if _allowed_origins_str:
    # 逗号分隔，去除空白
    ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_str.split(",") if o.strip()]
else:
    # 默认开发环境
    ALLOWED_ORIGINS = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 请求日志中间件
# ============================================================
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录关键 API 请求的日志，便于问题排查和安全审计。"""
    start_time = time.time()
    
    # 只记录 API 请求
    if request.url.path.startswith("/api/"):
        logging.info(f"请求: {request.method} {request.url.path}")
    
    response = await call_next(request)
    
    # 记录关键操作（登录、注册、聊天）
    if request.url.path in ["/api/register", "/api/login", "/api/chat", "/api/guest-chat"]:
        duration = time.time() - start_time
        logging.info(
            f"完成: {request.method} {request.url.path} "
            f"状态={response.status_code} 耗时={duration:.2f}s"
        )
    
    return response

# ============================================================
# 注册路由
# ============================================================
app.include_router(auth.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(characters.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# ============================================================
# 静态文件服务
# ============================================================
@app.get("/", response_class=HTMLResponse)
def serve_index():
    """返回前端首页 index.html。"""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>前端文件未找到，请检查路径</h1>", status_code=404)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/admin.html", response_class=HTMLResponse)
def serve_admin():
    """返回后台管理页面（模块化版本，包含完整功能）。"""
    admin_path = FRONTEND_STATIC_DIR / "admin" / "index.html"
    if not admin_path.exists():
        return HTMLResponse("<h1>admin 页面未找到</h1>", status_code=404)
    return HTMLResponse(admin_path.read_text(encoding="utf-8"))


@app.get("/forgot-password.html", response_class=HTMLResponse)
def serve_forgot_password():
    """返回忘记密码页面 forgot-password.html。"""
    # forgot-password.html 在 frontend/ 子目录下
    forgot_path = FRONTEND_STATIC_DIR / "forgot-password.html"
    if not forgot_path.exists():
        return HTMLResponse("<h1>forgot-password.html 未找到</h1>", status_code=404)
    return HTMLResponse(forgot_path.read_text(encoding="utf-8"))


# 挂载 frontend/ 子目录（CSS、JS、图片等资源）
if FRONTEND_STATIC_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_STATIC_DIR)), name="frontend")


# ============================================================
# 启动和关闭事件
# ============================================================
@app.on_event("startup")
def on_startup() -> None:
    """应用启动时初始化数据库连接池、验证配置并启动后台清理任务。"""
    init_db_pool(_cfg.DATABASE_URL)
    logging.info("✅ 数据库连接池已初始化")

    # 启动订单超时清理后台任务（每小时执行一次）
    import threading
    def cleanup_expired_orders_task():
        """后台定期清理超时订单。"""
        from routers.billing import _close_expired_pending_orders
        while True:
            conn = None
            try:
                conn = get_conn()
                _close_expired_pending_orders(conn)
                logging.info("✅ 已清理超时订单")
            except Exception as e:
                logging.error(f"❌ 订单清理失败: {e}", exc_info=True)
            finally:
                if conn is not None:
                    conn.close()
            time.sleep(3600)  # 每小时执行一次

    threading.Thread(target=cleanup_expired_orders_task, daemon=True).start()
    logging.info("✅ 订单清理后台任务已启动")

    # 验证生产环境配置
    missing_configs = validate_production_config()
    if missing_configs:
        logging.warning("⚠️  检测到缺失的生产环境配置：")
        for config in missing_configs:
            logging.warning(f"  - {config}")
        logging.warning("请检查 .env 文件，参考 .env.example")


@app.on_event("shutdown")
def on_shutdown() -> None:
    """应用关闭时清理数据库连接池。"""
    close_db_pool()
    logging.info("✅ 数据库连接池已关闭")


# ============================================================
# 全局异常处理
# ============================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    全局异常处理器，防止生产环境暴露敏感错误信息。
    
    - HTTPException: 保持原有的状态码和消息
    - 其他异常: 记录详细日志，返回通用错误消息
    """
    # HTTPException 直接返回
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    
    # 其他异常记录日志并返回通用错误
    logging.error(f"未处理的异常: {type(exc).__name__}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )


# ============================================================
# 健康检查
# ============================================================
@app.get("/api/health")
def health() -> dict[str, str | bool]:
    """
    健康检查端点，用于监控服务状态。
    
    检查项：
    - 数据库连接是否正常
    - 关键配置是否已设置
    
    Returns:
        包含状态信息的字典
    """
    from config import utc_now_iso
    
    result = {
        "status": "ok",
        "time": utc_now_iso(),
        "database": False,
        "config": False,
    }
    
    # 检查数据库连接
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
        result["database"] = True
    except Exception:
        result["status"] = "degraded"
    
    # 检查关键配置
    missing_configs = validate_production_config()
    result["config"] = len(missing_configs) == 0
    if missing_configs:
        result["status"] = "degraded"
    
    return result


# ============================================================
# 头像服务
# ============================================================
def _resolve_media_response(raw_value: str, *, fallback_path: Path | None = None):
    """把数据库中的图片值解析成可返回的响应。"""
    import logging
    _log = logging.getLogger(__name__)
    
    media_value = (raw_value or "").strip()

    if media_value:
        try:
            if media_value.startswith(("http://", "https://", "/frontend/")):
                return RedirectResponse(media_value)

            candidate = Path(media_value)
            if candidate.exists():
                return FileResponse(candidate)

            if not candidate.is_absolute():
                project_relative = FRONTEND_DIR / media_value
                if project_relative.exists():
                    return FileResponse(project_relative)
        except Exception as _media_exc:
            _log.warning(f"avatar resolve failed for value={media_value[:80]}: {_media_exc}")

    if fallback_path and fallback_path.exists():
        return FileResponse(fallback_path)

    raise HTTPException(status_code=404, detail="图片未找到")


@app.get("/api/avatar/{character_id}")
def get_avatar(character_id: str):
    """
    返回角色卡头像图片。

    流程：
        1. 从数据库查询角色头像路径
        2. 如果路径存在且文件存在，返回该文件
        3. 否则返回默认头像

    Args:
        character_id: 角色 ID

    Returns:
        PNG 图片文件

    Raises:
        HTTPException: 404 角色不存在或头像未找到
    """
    conn = get_db()
    try:
        # 查询角色头像路径
        row = conn.execute(
            "SELECT avatar_url FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        default_avatar = FRONTEND_DIR / "frontend" / "assets" / "default-avatar.png"
        return _resolve_media_response(row["avatar_url"] or "", fallback_path=default_avatar)
    finally:
        conn.close()


@app.get("/api/cover/{character_id}")
def get_cover(character_id: str):
    """返回角色卡封面图片，支持本地文件、静态路径和外链。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT avatar_url, cover_url FROM characters WHERE id = %s",
            (character_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="角色不存在")

        default_avatar = FRONTEND_DIR / "frontend" / "assets" / "default-avatar.png"
        cover_value = (row["cover_url"] or "").strip() or (row["avatar_url"] or "").strip()
        return _resolve_media_response(cover_value, fallback_path=default_avatar)
    finally:
        conn.close()


# ============================================================
# 用户头像服务
# ============================================================

AVATARS_DIR = Path(__file__).parent.parent / "avatars"
AVATARS_DIR.mkdir(exist_ok=True)

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@app.post("/api/user/avatar")
async def upload_user_avatar(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """
    上传/更换用户头像。

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

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件扩展名")

    with get_db() as conn:
        row = conn.execute(
            "SELECT avatar_url FROM users WHERE id = %s", (user.id,)
        ).fetchone()
        old_avatar_url = row["avatar_url"] if row else None

        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = AVATARS_DIR / filename
        filepath.write_bytes(content)

        avatar_url = f"/avatars/{filename}"

        conn.execute(
            "UPDATE users SET avatar_url = %s, updated_at = NOW() WHERE id = %s",
            (avatar_url, user.id),
        )

    if old_avatar_url and old_avatar_url.startswith("/avatars/"):
        try:
            old_file = Path(__file__).parent.parent / old_avatar_url.lstrip("/")
            if old_file.exists() and old_file.is_file():
                old_file.unlink()
        except OSError:
            pass

    return {"avatar_url": avatar_url}


@app.get("/api/user/avatar")
def get_user_avatar(user=Depends(get_current_user)):
    """获取当前登录用户的头像图片。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT avatar_url FROM users WHERE id = %s", (user.id,)
        ).fetchone()
        avatar_value = row["avatar_url"] if row else None

    default_avatar = FRONTEND_DIR / "frontend" / "assets" / "default-avatar.png"
    return _resolve_media_response(avatar_value or "", fallback_path=default_avatar)


# 挂载用户上传的头像目录
app.mount("/avatars", StaticFiles(directory=str(AVATARS_DIR)), name="avatars")


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    import uvicorn
    # 开发模式启动（带热重载）
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
