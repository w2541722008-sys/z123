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
from contextlib import asynccontextmanager
from pathlib import Path

# 第三方库导入
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# 项目内部导入
import config as _cfg
from config import FRONTEND_DIR, FRONTEND_STATIC_DIR, PROJECT_DIR, validate_production_config
from database import init_db_pool, close_db_pool
from services.health_service import check_db_health, check_media_health
from services.jobs_facade import start_order_cleanup_daemon

# 导入路由
from routers import admin, auth, billing, characters, chat, media

# ============================================================
# 启动和关闭事件（使用现代 lifespan 模式）
# ============================================================
_cleanup_thread = None  # 可选删除：仅用于调试参考，非功能依赖

def _default_allowed_origins() -> list[str]:
    return [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]


def _load_allowed_origins(env: dict[str, str] | os._Environ[str]) -> list[str]:
    allowed_origins_str = env.get("ALLOWED_ORIGINS", "")
    if allowed_origins_str:
        return [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]
    return _default_allowed_origins()


def _tracked_request_paths() -> set[str]:
    return {
        "/api/auth/register",
        "/api/auth/login",
        "/api/chat/send",
        "/api/chat/stream",
        "/api/chat/guest-stream",
        "/api/chat/regenerate",
        "/api/chat/continue",
    }


def _register_api_routers(app: FastAPI) -> None:
    for router in (auth.router, billing.router, characters.router, chat.router, media.router, admin.router):
        app.include_router(router, prefix="/api")


def _serve_html_file(path: Path, missing_message: str) -> HTMLResponse:
    if not path.exists():
        return HTMLResponse(missing_message, status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化资源，关闭时清理。"""
    init_db_pool(_cfg.DATABASE_URL)
    logging.info("✅ 数据库连接池已初始化")

    global _cleanup_thread
    _cleanup_thread = start_order_cleanup_daemon(interval_seconds=3600)
    logging.info("✅ 订单清理后台任务已启动")

    missing_configs = validate_production_config()
    if missing_configs:
        logging.warning("⚠️  检测到缺失的生产环境配置：")
        for config in missing_configs:
            logging.warning(f"  - {config}")
        logging.warning("请检查 .env 文件，参考 .env.example")

    media_health = check_media_health(force=True)
    if media_health["ok"]:
        logging.info("✅ 媒体资源自检通过")
    else:
        logging.warning(
            f"⚠️ 媒体资源自检发现缺失: {media_health['missing_count']}，样例: {', '.join(media_health['samples'])}"
        )

    yield

    close_db_pool()
    logging.info("✅ 数据库连接池已关闭")

app = FastAPI(title="aifriend backend", version="0.3.0", lifespan=lifespan)

# ============================================================
# CORS 跨域配置
# ============================================================
TRACKED_REQUEST_PATHS = _tracked_request_paths()
ALLOWED_ORIGINS = _load_allowed_origins(os.environ)

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
    tracked_paths = TRACKED_REQUEST_PATHS

    # 只记录 API 请求
    if request.url.path.startswith("/api/"):
        logging.info(f"请求: {request.method} {request.url.path}")

    response = await call_next(request)

    # 记录关键操作（登录、注册、聊天）
    if request.url.path in tracked_paths:
        duration = time.time() - start_time
        logging.info(
            f"完成: {request.method} {request.url.path} "
            f"状态={response.status_code} 耗时={duration:.2f}s"
        )

    return response

# ============================================================
# 注册路由
# ============================================================
_register_api_routers(app)


# ============================================================
# 静态文件服务
# ============================================================
@app.get("/", response_class=HTMLResponse)
def serve_index():
    """返回前端首页 index.html。"""
    return _serve_html_file(FRONTEND_DIR / "index.html", "<h1>前端文件未找到，请检查路径</h1>")


@app.get("/admin.html", response_class=HTMLResponse)
def serve_admin():
    """返回后台管理页面（模块化版本，包含完整功能）。"""
    return _serve_html_file(FRONTEND_STATIC_DIR / "admin" / "index.html", "<h1>admin 页面未找到</h1>")


@app.get("/forgot-password.html", response_class=HTMLResponse)
def serve_forgot_password():
    """返回忘记密码页面 forgot-password.html。"""
    return _serve_html_file(FRONTEND_STATIC_DIR / "forgot-password.html", "<h1>forgot-password.html 未找到</h1>")


# 挂载 frontend/ 子目录（CSS、JS、图片等资源）
if FRONTEND_STATIC_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_STATIC_DIR)), name="frontend")
    app.mount("/api/frontend", StaticFiles(directory=str(FRONTEND_STATIC_DIR)), name="frontend_api")


# ============================================================
# 健康检查端点
# ============================================================
@app.get("/api/health")
def health() -> dict[str, str | bool | int]:
    """
    健康检查端点，用于监控服务状态。

    检查项：
    - 数据库连接是否正常（带 TTL 缓存，避免高频监控压垮数据库）
    - 关键配置是否完整
    - 媒体资源是否完整

    Returns:
        包含状态信息的字典
    """
    from config import utc_now_iso

    db_ok = check_db_health()
    missing_configs = validate_production_config()
    config_ok = len(missing_configs) == 0
    media_health = check_media_health()
    media_ok = bool(media_health["ok"])

    status = "ok" if (db_ok and config_ok and media_ok) else "degraded"

    return {
        "status": status,
        "time": utc_now_iso(),
        "database": db_ok,
        "config": config_ok,
        "media": media_ok,
        "media_missing": int(media_health["missing_count"]),
    }


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


# 挂载用户上传的头像目录
AVATARS_DIR = Path(__file__).parent.parent / "avatars"
app.mount("/avatars", StaticFiles(directory=str(AVATARS_DIR)), name="avatars")


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    import uvicorn
    # 开发模式启动（带热重载）
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
