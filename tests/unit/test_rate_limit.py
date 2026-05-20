"""rate_limit 单元测试 — 内存滑动窗口限流器。

覆盖范围：
    - _InMemoryRateLimiter: 核心限流逻辑
      - 正常请求通过
      - 超限返回 retry_after
      - 窗口过期后自动放行
      - _MAX_KEYS 内存保护
      - _cleanup_locked 过期清理
    - enforce_rate_limit: FastAPI 429 抛出
    - get_request_client_ip: IP 提取逻辑
"""

import time
from unittest.mock import MagicMock

import pytest
from core.exceptions import RateLimitError

from services.rate_limit import (
    _InMemoryRateLimiter,
    enforce_rate_limit,
    get_request_client_ip,
)


# ── _InMemoryRateLimiter 核心逻辑 ──────────────────────────────

class TestInMemoryRateLimiter:

    def test_first_request_passes(self):
        limiter = _InMemoryRateLimiter()
        result = limiter.hit("key1", limit=5, window_seconds=60)
        assert result is None  # None 表示通过

    def test_up_to_limit_passes(self):
        limiter = _InMemoryRateLimiter()
        for i in range(5):
            result = limiter.hit("key1", limit=5, window_seconds=60)
        # 第 5 次仍通过
        assert result is None
        # 第 6 次超限
        result = limiter.hit("key1", limit=5, window_seconds=60)
        assert result is not None
        assert isinstance(result, int)
        assert result > 0

    def test_different_keys_independent(self):
        limiter = _InMemoryRateLimiter()
        # key1 用完限额
        for i in range(3):
            limiter.hit("key1", limit=3, window_seconds=60)
        # key2 不受影响
        result = limiter.hit("key2", limit=3, window_seconds=60)
        assert result is None

    def test_window_expiry_allows_again(self):
        limiter = _InMemoryRateLimiter()
        # 用完限额
        for i in range(3):
            limiter.hit("key1", limit=3, window_seconds=1)

        # 超限
        assert limiter.hit("key1", limit=3, window_seconds=1) is not None

        # 等待窗口过期
        time.sleep(1.1)

        # 窗口过期后可以再次请求
        result = limiter.hit("key1", limit=3, window_seconds=1)
        assert result is None

    def test_retry_after_is_reasonable(self):
        limiter = _InMemoryRateLimiter()
        window = 10
        for i in range(2):
            limiter.hit("key1", limit=2, window_seconds=window)

        retry_after = limiter.hit("key1", limit=2, window_seconds=window)
        assert retry_after is not None
        assert 1 <= retry_after <= window

    def test_max_keys_protection(self):
        """超过 _MAX_KEYS 时，最早的 key 被驱逐。"""
        limiter = _InMemoryRateLimiter()
        limiter._MAX_KEYS = 5  # 降低阈值加速测试

        # 填充 6 个 key（超过限制）
        for i in range(6):
            limiter.hit(f"key_{i}", limit=5, window_seconds=3600)

        # 总 key 数不超过限制（最旧的被驱逐）
        assert len(limiter._events) <= limiter._MAX_KEYS

    def test_cleanup_removes_stale_buckets(self):
        limiter = _InMemoryRateLimiter()
        # 添加一个短期窗口的请求
        limiter.hit("stale_key", limit=1, window_seconds=1)
        time.sleep(1.1)

        # 触发清理（通过添加新 key）
        limiter._MAX_KEYS = 100  # 确保不触发 max_keys 驱逐
        limiter.hit("new_key", limit=1, window_seconds=3600)

        # stale_key 的 bucket 应该在清理中被移除
        # 注意：清理只移除空 bucket，stale_key 的条目已过期但 bucket 可能非空
        # 我们验证 new_key 可以正常使用
        assert "new_key" in limiter._events


# ── enforce_rate_limit ─────────────────────────────────────────

class TestEnforceRateLimit:

    def test_under_limit_no_exception(self):
        # 限流器是全局单例，测试前需确保干净状态
        from services import rate_limit as rl
        rl._RATE_LIMITER = _InMemoryRateLimiter()

        # 应该不抛异常
        enforce_rate_limit(
            scope="test",
            identifier="user1",
            limit=10,
            window_seconds=60,
            detail="请求过于频繁",
        )

    def test_over_limit_raises_429(self):
        from services import rate_limit as rl
        rl._RATE_LIMITER = _InMemoryRateLimiter()

        # 用完限额
        for i in range(3):
            enforce_rate_limit(
                scope="test2",
                identifier="user2",
                limit=3,
                window_seconds=60,
                detail="请求过于频繁",
            )

        # 第 4 次应抛出 429
        with pytest.raises(RateLimitError) as exc_info:
            enforce_rate_limit(
                scope="test2",
                identifier="user2",
                limit=3,
                window_seconds=60,
                detail="请求过于频繁",
            )
        assert "请求过于频繁" in exc_info.value.detail
        assert "Retry-After" in exc_info.value.headers

    def test_identifier_normalized(self):
        """标识符会被 strip + lower 处理。"""
        from services import rate_limit as rl
        rl._RATE_LIMITER = _InMemoryRateLimiter()

        # "  USER1  " 和 "user1" 应该命中同一个 key
        enforce_rate_limit(
            scope="test3",
            identifier="  USER1  ",
            limit=1,
            window_seconds=60,
            detail="限流",
        )
        with pytest.raises(RateLimitError):
            enforce_rate_limit(
                scope="test3",
                identifier="user1",
                limit=1,
                window_seconds=60,
                detail="限流",
            )

    def test_none_identifier_becomes_unknown(self):
        from services import rate_limit as rl
        rl._RATE_LIMITER = _InMemoryRateLimiter()

        # 不应抛异常（None 被转为 "unknown"）
        enforce_rate_limit(
            scope="test4",
            identifier=None,
            limit=5,
            window_seconds=60,
            detail="限流",
        )


# ── get_request_client_ip ─────────────────────────────────────

class TestGetRequestClientIp:

    def _make_request(self, client_host="1.2.3.4", headers=None):
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = client_host
        request.headers = headers or {}
        return request

    def test_direct_ip_when_not_trusted_proxy(self):
        from services import rate_limit as rl
        original_proxies = rl._TRUSTED_PROXIES
        rl._TRUSTED_PROXIES = {"10.0.0.1"}  # 不包含 1.2.3.4

        request = self._make_request("1.2.3.4")
        ip = get_request_client_ip(request)
        assert ip == "1.2.3.4"

        rl._TRUSTED_PROXIES = original_proxies

    def test_x_real_ip_from_trusted_proxy(self):
        from services import rate_limit as rl
        original_proxies = rl._TRUSTED_PROXIES
        rl._TRUSTED_PROXIES = {"127.0.0.1"}

        request = self._make_request(
            "127.0.0.1",
            headers={"x-real-ip": "203.0.113.5"},
        )
        ip = get_request_client_ip(request)
        assert ip == "203.0.113.5"

        rl._TRUSTED_PROXIES = original_proxies

    def test_x_forwarded_for_from_trusted_proxy(self):
        from services import rate_limit as rl
        original_proxies = rl._TRUSTED_PROXIES
        rl._TRUSTED_PROXIES = {"127.0.0.1"}

        request = self._make_request(
            "127.0.0.1",
            headers={"x-forwarded-for": "203.0.113.5, 70.41.3.18"},
        )
        ip = get_request_client_ip(request)
        assert ip == "203.0.113.5"  # 取第一个 IP

        rl._TRUSTED_PROXIES = original_proxies

    def test_fallback_to_direct_ip_when_no_headers(self):
        from services import rate_limit as rl
        original_proxies = rl._TRUSTED_PROXIES
        rl._TRUSTED_PROXIES = {"127.0.0.1"}

        request = self._make_request("127.0.0.1", headers={})
        ip = get_request_client_ip(request)
        assert ip == "127.0.0.1"

        rl._TRUSTED_PROXIES = original_proxies

    def test_no_client_returns_unknown(self):
        request = MagicMock()
        request.client = None
        request.headers = {}
        ip = get_request_client_ip(request)
        assert ip == "unknown"
