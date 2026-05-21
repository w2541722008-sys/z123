"""db_monitor + health_service 基础测试。"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ── db_monitor ──────────────────────────────────────────

class TestDbMonitor:
    def test_track_query_records_stats(self):
        from services.db_monitor import track_query, get_stats, reset_stats
        reset_stats()
        track_query("SELECT", 0.05)
        track_query("SELECT", 0.03)
        stats = get_stats()
        assert stats["SELECT"]["count"] == 2
        assert stats["SELECT"]["avg_time"] == pytest.approx(0.04, abs=0.01)

    def test_slow_query_detected(self):
        from services.db_monitor import track_query, get_stats, reset_stats
        reset_stats()
        track_query("UPDATE", 0.5)  # 超过 0.1s 阈值
        stats = get_stats()
        assert stats["UPDATE"]["slow_queries"] == 1

    def test_get_stats_returns_copy(self):
        from services.db_monitor import get_stats, reset_stats
        reset_stats()
        s1 = get_stats()
        s1["intruder"] = True
        s2 = get_stats()
        assert "intruder" not in s2

    def test_reset_stats_clears_all(self):
        from services.db_monitor import track_query, get_stats, reset_stats
        track_query("SELECT", 0.01)
        reset_stats()
        assert get_stats() == {}

    def test_query_timer_context_manager(self):
        from services.db_monitor import QueryTimer, get_stats, reset_stats
        reset_stats()
        with QueryTimer("test_op"):
            time.sleep(0.001)  # 确保计时器有可测量的时间差
        stats = get_stats()
        assert stats["test_op"]["count"] == 1


# ── health_service.media_path_exists ────────────────────

class TestMediaPathExists:
    def test_http_url_always_true(self):
        from services.health_service import media_path_exists
        assert media_path_exists("https://cdn.example.com/img.png") is True

    def test_frontend_prefix_true(self):
        from services.health_service import media_path_exists
        assert media_path_exists("/frontend/assets/img.png") is True

    def test_api_avatar_prefix_true(self):
        from services.health_service import media_path_exists
        assert media_path_exists("/api/avatar/abc.png") is True

    def test_api_cover_prefix_true(self):
        from services.health_service import media_path_exists
        assert media_path_exists("/api/cover/xyz.jpg") is True

    def test_empty_value_true(self):
        from services.health_service import media_path_exists
        assert media_path_exists("") is True
        assert media_path_exists(None) is True

    def test_whitespace_only_true(self):
        from services.health_service import media_path_exists
        assert media_path_exists("   ") is True

    def test_existing_file_true(self):
        from services.health_service import media_path_exists
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            f.flush()
            try:
                assert media_path_exists(f.name) is True
            finally:
                os.unlink(f.name)

    def test_nonexistent_file_false(self):
        from services.health_service import media_path_exists
        assert media_path_exists("/nonexistent/path/file.png") is False
