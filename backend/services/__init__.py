"""
Services 包 - 业务逻辑层

这个包存放核心业务逻辑，不直接处理 HTTP 请求，只处理数据。

设计原则：
- 每个模块负责一个业务领域（角色状态、记忆管理、聊天）
- 函数接收数据库连接和参数，返回处理结果
- 不依赖 FastAPI 的 Request/Response 对象

依赖方向：services/ → core/

使用方式：
    from services.character_state import get_character_state, apply_state_delta
    from services.memory_service import get_summary_text, refresh_memory_summary
"""
