"""
Routers 包 - API 路由层

这个包存放所有 FastAPI 路由（API 端点）。

设计原则：
- 每个模块对应一个功能域（auth、characters、chat、admin）
- 路由函数只处理 HTTP 请求/响应，业务逻辑委托给 services/
- 使用 FastAPI 的 APIRouter 组织路由

使用方式：
    from routers import auth, characters, chat, admin
    app.include_router(auth.router, prefix="/api")
"""
