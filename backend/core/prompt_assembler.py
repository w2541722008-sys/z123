"""
兼容性重导出层 - prompt_assembler 已迁移至 services/prompt_assembler.py

迁移原因：
    core/ 层不应依赖 services/ 层，但 prompt_assembler 依赖了
    services.memory_service / services.token_budget / services.runtime_bundle，
    违反了 routers/ → services/ → core/ 的分层约束。

实际实现：services/prompt_assembler.py
"""
from services.prompt_assembler import *  # noqa: F401,F403
