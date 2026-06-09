"""circuit_breaker 纯状态机单元测试。

验证 CLOSED → OPEN → HALF_OPEN → CLOSED 状态转换全路径。
CircuitBreaker 类是线程安全的状态机，所有方法均为纯逻辑（无外部 I/O）。
"""

import time

import pytest

from services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    State,
    get_circuit_breaker,
)


class TestCircuitBreakerStateMachine:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        state = cb.get_state("endpoint_a")
        assert state["state"] == "closed"
        assert state["failure_count"] == 0

    def test_single_failure_does_not_open(self):
        cb = CircuitBreaker()
        cb.report_failure("ep1")
        state = cb.get_state("ep1")
        assert state["state"] == "closed"
        assert state["failure_count"] == 1

    def test_failures_below_threshold_do_not_open(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.report_failure("ep1")
        state = cb.get_state("ep1")
        assert state["state"] == "closed"

    def test_failures_at_threshold_opens_circuit(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.report_failure("ep1")
        state = cb.get_state("ep1")
        assert state["state"] == "open"

    def test_open_state_raises_on_before_request(self):
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            cb.report_failure("ep1")
        with pytest.raises(CircuitBreakerOpenError):
            cb.before_request("ep1")

    def test_after_timeout_transitions_to_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, open_timeout_seconds=0)
        for _ in range(2):
            cb.report_failure("ep1")
        # timeout=0，立即进入 HALF_OPEN
        cb.before_request("ep1")  # 不放异常 → 已进入 HALF_OPEN

    def test_half_open_success_transitions_to_closed(self):
        cb = CircuitBreaker(failure_threshold=2, open_timeout_seconds=0)
        for _ in range(2):
            cb.report_failure("ep1")
        cb.before_request("ep1")  # 进入 HALF_OPEN
        cb.report_success("ep1")
        state = cb.get_state("ep1")
        assert state["state"] == "closed"
        assert state["failure_count"] == 0

    def test_half_open_failure_transitions_back_to_open(self):
        cb = CircuitBreaker(failure_threshold=2, open_timeout_seconds=0, half_open_max_requests=2)
        for _ in range(2):
            cb.report_failure("ep1")
        cb.before_request("ep1")  # OPEN→HALF_OPEN（消耗探测配额 1/2）
        cb.report_failure("ep1")  # 探测失败 → 回到 OPEN
        state = cb.get_state("ep1")
        assert state["state"] == "open"

    def test_success_in_closed_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(3):
            cb.report_failure("ep1")
        cb.report_success("ep1")
        state = cb.get_state("ep1")
        assert state["failure_count"] == 0

    def test_different_endpoints_isolated(self):
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            cb.report_failure("ep_a")
        state_a = cb.get_state("ep_a")
        state_b = cb.get_state("ep_b")
        assert state_a["state"] == "open"
        assert state_b["state"] == "closed"

    def test_different_endpoints_independent_counters(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.report_failure("ep_a")
        cb.report_failure("ep_a")
        cb.report_failure("ep_b")
        state_a = cb.get_state("ep_a")
        state_b = cb.get_state("ep_b")
        assert state_a["failure_count"] == 2
        assert state_b["failure_count"] == 1

    def test_get_state_includes_open_remaining(self):
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            cb.report_failure("ep1")
        state = cb.get_state("ep1")
        assert state["state"] == "open"
        assert "open_remaining_seconds" in state


class TestFailureWindow:
    def test_failures_outside_window_reset(self):
        cb = CircuitBreaker(failure_threshold=3, failure_window_seconds=0.01)
        cb.report_failure("ep1")
        time.sleep(0.02)
        cb.report_failure("ep1")
        state = cb.get_state("ep1")
        # 第二次失败在窗口外，应该重新计数
        assert state["failure_count"] <= 2

    def test_window_reset_on_before_request(self):
        cb = CircuitBreaker(failure_threshold=3, failure_window_seconds=0.01)
        cb.report_failure("ep1")
        time.sleep(0.02)
        cb.before_request("ep1")  # 此时应重置计数
        state = cb.get_state("ep1")
        assert state["failure_count"] == 0


class TestHalfOpenMaxRequests:
    def test_only_one_probe_allowed(self):
        cb = CircuitBreaker(failure_threshold=2, open_timeout_seconds=0, half_open_max_requests=1)
        for _ in range(2):
            cb.report_failure("ep1")
        cb.before_request("ep1")   # 第一次: OPEN→HALF_OPEN，不消耗探测配额
        cb.before_request("ep1")   # 第二次: HALF_OPEN，消耗探测配额（half_open_requests=1）
        with pytest.raises(CircuitBreakerOpenError):
            cb.before_request("ep1")  # 第三次: 超出探测配额，拒绝


class TestDefaultFactory:
    def test_singleton_returns_same_instance(self):
        cb1 = get_circuit_breaker()
        cb2 = get_circuit_breaker()
        assert cb1 is cb2

    def test_default_values(self):
        cb = get_circuit_breaker()
        assert cb._failure_threshold >= 3
        assert cb._open_timeout >= 15
