"""
数据库性能监控服务

功能：
- 跟踪查询执行时间
- 识别慢查询
- 提供性能统计
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Any

from core.config import logger

# 性能统计数据
_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
    "count": 0,
    "total_time": 0.0,
    "max_time": 0.0,
    "min_time": float('inf'),
    "slow_queries": 0,
})
_stats_lock = Lock()

# 慢查询阈值（秒）
SLOW_QUERY_THRESHOLD = 0.1


def track_query(operation: str, duration: float) -> None:
    """记录查询性能数据"""
    with _stats_lock:
        stats = _stats[operation]
        stats["count"] += 1
        stats["total_time"] += duration
        stats["max_time"] = max(stats["max_time"], duration)
        stats["min_time"] = min(stats["min_time"], duration)
        
        if duration > SLOW_QUERY_THRESHOLD:
            stats["slow_queries"] += 1
            logger.warning("慢查询检测: %s 耗时 %.3fs", operation, duration)


def get_stats() -> dict[str, Any]:
    """获取性能统计数据"""
    with _stats_lock:
        result = {}
        for operation, stats in _stats.items():
            avg_time = stats["total_time"] / stats["count"] if stats["count"] > 0 else 0
            result[operation] = {
                "count": stats["count"],
                "total_time": round(stats["total_time"], 3),
                "avg_time": round(avg_time, 3),
                "max_time": round(stats["max_time"], 3),
                "min_time": round(stats["min_time"], 3) if stats["min_time"] != float('inf') else 0,
                "slow_queries": stats["slow_queries"],
            }
        return result


def reset_stats() -> None:
    """重置统计数据"""
    with _stats_lock:
        _stats.clear()


class QueryTimer:
    """查询计时器上下文管理器"""
    
    def __init__(self, operation: str):
        self.operation = operation
        self.start_time = 0.0
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        track_query(self.operation, duration)
