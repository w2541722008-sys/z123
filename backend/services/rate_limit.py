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

    _MAX_KEYS = 8192  # 内存硬限制，防止 key 无限增长

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

            if len(self._events) > self._MAX_KEYS:
                self._cleanup_locked(now)
                # 清理后仍超限，移除最早的 key 以保护内存
                if len(self._events) > self._MAX_KEYS:
                    oldest_key = next(iter(self._events))
                    self._events.pop(oldest_key, None)
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
    """获取请求来源真实 IP。

    仅在请求来自可信代理时读取 X-Real-IP / X-Forwarded-For，
    否则直接使用直连 IP，防止客户端伪造头绕过限流。

    可信代理通过环境变量 TRUSTED_PROXY_IPS 配置（逗号分隔），
    未配置时默认信任 127.0.0.1 / ::1（本机 Nginx）。
    """
    direct_ip = (request.client.host.strip() if request.client and request.client.host else "") or "unknown"

    # 检查直连方是否为可信代理
    if direct_ip not in _TRUSTED_PROXIES:
        return direct_ip

    # 请求来自可信代理，安全读取转接头
    x_real_ip = (request.headers.get("x-real-ip") or "").strip()
    if x_real_ip:
        return x_real_ip

    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        first_ip = xff.split(",")[0].strip()
        if first_ip:
            return first_ip

    return direct_ip


def _load_trusted_proxies() -> set[str]:
    """从环境变量加载可信代理 IP 集合。"""
    import os
    raw = os.environ.get("TRUSTED_PROXY_IPS", "").strip()
    if raw:
        return {ip.strip() for ip in raw.split(",") if ip.strip()}
    # 默认仅信任本机反向代理
    return {"127.0.0.1", "::1"}


_TRUSTED_PROXIES = _load_trusted_proxies()


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