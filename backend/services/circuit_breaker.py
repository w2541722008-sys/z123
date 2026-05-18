"""AI 模型熔断器 — Circuit Breaker 状态机

状态转换：
  CLOSED → OPEN: 时间窗口内连续失败 >= FAILURE_THRESHOLD
  OPEN → HALF_OPEN: 经过 OPEN_TIMEOUT_SECONDS 后自动转换
  HALF_OPEN → CLOSED: 探针请求成功
  HALF_OPEN → OPEN: 探针请求失败

OPEN 状态下直接返回 503，不等待模型超时，避免级联故障。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(RuntimeError):
    """熔断器 OPEN 状态异常，调用方应返回 HTTP 503。"""
    pass


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _BreakerEntry:
    """单个熔断器的运行时状态。"""
    state: State = State.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    open_since: float = 0.0
    half_open_requests: int = 0


class CircuitBreaker:
    """线程安全的 AI 模型熔断器。

    按 endpoint (base_url) 分组跟踪失败，支持并发请求场景。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        failure_window_seconds: float = 60.0,
        open_timeout_seconds: float = 30.0,
        half_open_max_requests: int = 1,
    ):
        self._failure_threshold = failure_threshold
        self._failure_window = failure_window_seconds
        self._open_timeout = open_timeout_seconds
        self._half_open_max = half_open_max_requests
        self._entries: dict[str, _BreakerEntry] = {}
        self._lock = threading.Lock()

    def _get_entry(self, endpoint_key: str) -> _BreakerEntry:
        if endpoint_key not in self._entries:
            self._entries[endpoint_key] = _BreakerEntry()
        return self._entries[endpoint_key]

    def _reset_failures(self, entry: _BreakerEntry) -> None:
        entry.failure_count = 0
        entry.last_failure_time = 0.0

    def before_request(self, endpoint_key: str) -> None:
        """在发起模型请求前调用。OPEN 状态时抛出 RuntimeError（上游转 503）。"""
        with self._lock:
            entry = self._get_entry(endpoint_key)
            now = time.monotonic()

            if entry.state == State.CLOSED:
                # 如果距上次失败已超过窗口，重置计数
                if entry.failure_count > 0 and (now - entry.last_failure_time) > self._failure_window:
                    self._reset_failures(entry)
                return  # 放行

            if entry.state == State.OPEN:
                if (now - entry.open_since) >= self._open_timeout:
                    # 转换到 HALF_OPEN，放行一次探针请求
                    entry.state = State.HALF_OPEN
                    entry.half_open_requests = 0
                    logger.info("熔断器 HALF_OPEN: endpoint=%s", endpoint_key)
                    return  # 放行探针
                # 仍然 OPEN，拒绝
                raise CircuitBreakerOpenError("AI 模型服务暂时不可用，请稍后重试")

            if entry.state == State.HALF_OPEN:
                if entry.half_open_requests >= self._half_open_max:
                    raise CircuitBreakerOpenError("AI 模型服务暂时不可用，请稍后重试")
                entry.half_open_requests += 1
                return  # 放行探针

    def report_success(self, endpoint_key: str) -> None:
        """报告请求成功。HALF_OPEN → CLOSED。"""
        with self._lock:
            entry = self._get_entry(endpoint_key)
            if entry.state == State.HALF_OPEN:
                entry.state = State.CLOSED
                self._reset_failures(entry)
                logger.info("熔断器已恢复: endpoint=%s", endpoint_key)
            elif entry.state == State.CLOSED:
                self._reset_failures(entry)

    def report_failure(self, endpoint_key: str) -> None:
        """报告请求失败。可能触发 CLOSED → OPEN 或 HALF_OPEN → OPEN。"""
        with self._lock:
            entry = self._get_entry(endpoint_key)
            now = time.monotonic()

            if entry.state == State.HALF_OPEN:
                entry.state = State.OPEN
                entry.open_since = now
                entry.failure_count = self._failure_threshold
                logger.warning("熔断器 HALF_OPEN 探针失败，重新 OPEN: endpoint=%s", endpoint_key)
                return

            if entry.state == State.CLOSED:
                if entry.failure_count == 0 or (now - entry.last_failure_time) <= self._failure_window:
                    entry.failure_count += 1
                else:
                    # 窗口外，重新计数
                    entry.failure_count = 1
                entry.last_failure_time = now

                if entry.failure_count >= self._failure_threshold:
                    entry.state = State.OPEN
                    entry.open_since = now
                    logger.warning(
                        "熔断器触发 OPEN: endpoint=%s failures=%d/%d",
                        endpoint_key, entry.failure_count, self._failure_threshold,
                    )

    def get_state(self, endpoint_key: str) -> dict[str, Any]:
        """查询熔断器状态（调试/监控用）。"""
        with self._lock:
            entry = self._get_entry(endpoint_key)
            return {
                "state": entry.state.value,
                "failure_count": entry.failure_count,
                "threshold": self._failure_threshold,
                "open_remaining_seconds": max(0, self._open_timeout - (time.monotonic() - entry.open_since))
                if entry.state == State.OPEN else 0,
            }


# 单例（应用级共享）
_breaker: CircuitBreaker | None = None


def get_circuit_breaker(
    failure_threshold: int | None = None,
    failure_window_seconds: float | None = None,
    open_timeout_seconds: float | None = None,
) -> CircuitBreaker:
    """获取全局熔断器实例（延迟初始化，支持参数覆盖）。"""
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker(
            failure_threshold=failure_threshold or 5,
            failure_window_seconds=failure_window_seconds or 60.0,
            open_timeout_seconds=open_timeout_seconds or 30.0,
        )
    return _breaker
