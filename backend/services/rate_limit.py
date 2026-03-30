"""基础限流服务（轻量内存版）。

设计目标：
- 不引入 Redis / Nginx / 第三方限流库
- 保持逻辑简单，方便后续维护
- 先挡住明显的暴力登录和高频刷接口

注意：
- 当前实现适合本项目目前的单机 / 单进程为主的部署方式
- 如果未来改成多实例部署，再升级为 Redis 或网关层限流
"""

from __future__ import annotations

from collections import deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request


class _InMemoryRateLimiter:
    """简单的滑动窗口限流器。"""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = monotonic()
        with self._lock:
            bucket = self._events.get(key)
            if bucket is None:
                bucket = deque()
                self._events[key] = bucket

            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                return retry_after

            bucket.append(now)

            if len(self._events) > 4096:
                self._cleanup_locked(now)
            return None

    def _cleanup_locked(self, now: float) -> None:
        stale_before = now - 3600
        for key, bucket in list(self._events.items()):
            while bucket and bucket[0] <= stale_before:
                bucket.popleft()
            if not bucket:
                self._events.pop(key, None)


_RATE_LIMITER = _InMemoryRateLimiter()


def get_request_client_ip(request: Request) -> str:
    """获取请求来源 IP。当前默认只信任 FastAPI 识别到的客户端地址。"""
    if request.client and request.client.host:
        return request.client.host.strip() or "unknown"
    return "unknown"


def enforce_rate_limit(
    scope: str,
    identifier: str,
    *,
    limit: int,
    window_seconds: int,
    detail: str,
) -> None:
    """命中限流时抛出 429。"""
    normalized_identifier = (identifier or "unknown").strip().lower()
    key = f"{scope}:{normalized_identifier}"
    retry_after = _RATE_LIMITER.hit(key, limit=limit, window_seconds=window_seconds)
    if retry_after is None:
        return
    raise HTTPException(
        status_code=429,
        detail=f"{detail}，请 {retry_after} 秒后再试",
        headers={"Retry-After": str(retry_after)},
    )