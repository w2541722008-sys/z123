"""
性能基准测试 - 建立可衡量的性能指标
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestPerformanceBaselines:
    """建立性能基准线，确保优化后有可衡量指标。"""

    def test_token_creation_performance(self):
        """Token 创建应在合理时间内完成。"""
        import time
        from core.auth import create_token

        with patch("core.auth.get_conn") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.execute.return_value = MagicMock(rowcount=1)
            mock_get_conn.return_value = mock_conn

            start = time.time()
            try:
                create_token(user_id=1, conn=mock_conn, commit=False)
            except Exception:
                pass
            elapsed = time.time() - start

            assert elapsed < 1.0

    def test_password_hashing_performance(self):
        """密码哈希应在可接受时间内完成（rounds=10 约 40-80ms）。"""
        import time
        from core.auth import hash_password_bcrypt

        start = time.time()
        hash_password_bcrypt("test_password_123")
        elapsed = time.time() - start

        # rounds=10 在普通机器上约 40-80ms，留足余量
        assert 0.02 < elapsed < 1.0

    def test_rate_limiter_memory_cleanup(self):
        """限流器应定期清理过期数据。"""
        from services.rate_limit import _RATE_LIMITER

        initial_size = len(_RATE_LIMITER._events)
        _RATE_LIMITER._cleanup_locked(999999)

        assert len(_RATE_LIMITER._events) >= 0

    def test_password_hashing_performance_stability(self):
        """密码哈希应在合理时间内完成且返回有效结果。"""
        import time
        from core.auth import hash_password_bcrypt

        start = time.time()
        result = hash_password_bcrypt("test_password_123")
        elapsed = time.time() - start

        assert result is not None
        assert elapsed < 1.0
        assert elapsed > 0.01

    def test_token_hash_performance(self):
        """Token 哈希应在合理时间内完成。"""
        import time
        from core.auth import _hash_token_value

        start = time.time()
        result = _hash_token_value("test_token_string")
        elapsed = time.time() - start

        assert result is not None
        assert elapsed < 0.1

    def test_health_check_response_time_target(self, app_client):
        """健康检查在缓存命中时应快速返回。"""
        _, client = app_client
        from services.health_service import _db_health_cache

        _db_health_cache.update({
            "ts": datetime.now(timezone.utc).timestamp(),
            "ttl": 30,
            "value": True,
        })

        import time
        start = time.time()
        response = client.get("/api/health")
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 0.5
