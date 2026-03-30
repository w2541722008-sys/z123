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
import os
from pathlib import Path

# 第三方库导入
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# 本地模块导入
from config import FRONTEND_DIR, FRONTEND_STATIC_DIR
from database import get_conn, init_db

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
    """返回后台管理页面 admin.html。"""
    admin_path = FRONTEND_DIR / "admin.html"
    if not admin_path.exists():
        return HTMLResponse("<h1>admin.html 未找到</h1>", status_code=404)
    return HTMLResponse(admin_path.read_text(encoding="utf-8"))


@app.get("/forgot-password.html", response_class=HTMLResponse)
def serve_forgot_password():
    """返回忘记密码页面 forgot-password.html。"""
    forgot_path = FRONTEND_DIR / "forgot-password.html"
    if not forgot_path.exists():
        return HTMLResponse("<h1>forgot-password.html 未找到</h1>", status_code=404)
    return HTMLResponse(forgot_path.read_text(encoding="utf-8"))


# 挂载 frontend/ 子目录（CSS、JS、图片等资源）
if FRONTEND_STATIC_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_STATIC_DIR)), name="frontend")


# ============================================================
# 启动事件
# ============================================================
@app.on_event("startup")
def on_startup() -> None:
    """应用启动时初始化数据库。"""
    init_db()


# ============================================================
# 健康检查
# ============================================================
@app.get("/api/health")
def health() -> dict[str, str]:
    """健康检查端点。"""
    from config import utc_now_iso
    return {"status": "ok", "time": utc_now_iso()}


# ============================================================
# 头像服务
# ============================================================
def _resolve_media_response(raw_value: str, *, fallback_path: Path | None = None):
    """把数据库中的图片值解析成可返回的响应。"""
    media_value = (raw_value or "").strip()

    if media_value:
        if media_value.startswith(("http://", "https://", "/frontend/")):
            return RedirectResponse(media_value)

        candidate = Path(media_value)
        if candidate.exists():
            return FileResponse(candidate)

        if not candidate.is_absolute():
            project_relative = FRONTEND_DIR / media_value
            if project_relative.exists():
                return FileResponse(project_relative)

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
    conn = get_conn()
    try:
        # 查询角色头像路径
        row = conn.execute(
            "SELECT avatar_url FROM characters WHERE id = ?",
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
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT avatar_url, cover_url FROM characters WHERE id = ?",
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
# 主入口
# ============================================================
if __name__ == "__main__":
    import uvicorn
    # 开发模式启动（带热重载）
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
