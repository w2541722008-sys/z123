"""
缓存回调变量 — 避免 core 层反向依赖 services。

使用可变 dict 而非模块级变量，确保 register_cache_callbacks 设置的
回调对所有导入此模块的代码立即可见（避免跨模块 import 时值的快照问题）。
"""

from __future__ import annotations

from typing import Any, Callable

_cache: dict[str, Callable | None] = {
    "get": None,
    "set": None,
    "delete": None,
}
