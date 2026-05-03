"""
Core 包 - 基础设施层

包含被 services/ 和 routers/ 共同依赖的底层模块：
    - config: 配置常量与环境变量
    - database: 数据库连接池与工具函数
    - auth: 认证核心（JWT/密码/权限）
    - schemas: Pydantic 请求/响应模型
    - model_adapter: AI 模型适配器

注意：
    prompt_assembler 已迁移至 services/，core/prompt_assembler.py 仅保留兼容性 re-export。
    迁移原因：prompt_assembler 依赖 services.memory_service / token_budget / runtime_bundle，
    违反 core 层不应依赖 services 层的分层约束。

依赖方向：routers/ → services/ → core/
"""
