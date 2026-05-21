"""
Services 包 - 业务逻辑层

设计原则：
- 每个模块负责一个业务领域
- 函数接收数据库连接和参数，返回处理结果
- 不依赖 FastAPI 的 Request/Response 对象

依赖方向：services/ → repositories/ → core/ + constants/

公共 API（推荐直接从子模块导入）：
    from services.character_state import get_character_state, apply_state_delta, is_affection_enabled
    from services.memory_service import get_recent_messages, get_summary_text, get_summary_for_prompt
    from services.memory_service import refresh_memory_summary, run_memory_summary_background
    from services.chat_send import build_reply_with_fallback, save_assistant_message
    from services.chat_query import get_character_or_404, ensure_opening_message
    from services.plan_service import get_plan_policy, ensure_plan_access
    from utils.stream_filter import normalize_reply_text, sanitize_stream_chunk, parse_state_update_tag
    from services.world_info_service import resolve_triggered_memories, resolve_post_rules
"""
