"""health_service 单元测试 — 覆盖 DB/媒体健康检查和 TTL 缓存逻辑。"""

import time
from unittest.mock import MagicMock, patch

import pytest

from services import health_service


def _reset_caches():
    """每个测试前重置模块级缓存，避免测试间相互污染。"""
    health_service._db_health_cache = {"ok": False, "ts": 0.0}
    health_service._media_health_cache = {"ok": True, "missing_count": 0, "samples": [], "ts": 0.0}


# ── check_db_health ──────────────────────────────────────────────

def test_check_db_health_returns_true_on_success():
    _reset_caches()
    mock_conn = MagicMock()
    with patch("services.health_service.get_conn", return_value=mock_conn):
        assert health_service.check_db_health() is True
    mock_conn.execute.assert_called_once_with("SELECT 1")
    mock_conn.close.assert_called_once()


def test_check_db_health_returns_false_on_error():
    _reset_caches()
    with patch("services.health_service.get_conn", side_effect=Exception("connection refused")):
        assert health_service.check_db_health() is False


def test_check_db_health_uses_cache_within_ttl():
    now = time.time()
    health_service._db_health_cache = {"ok": True, "ts": now}
    with patch("services.health_service.get_conn") as mock_get:
        assert health_service.check_db_health() is True
        mock_get.assert_not_called()


def test_check_db_health_refreshes_after_ttl_expires():
    _reset_caches()
    # 模拟缓存已过期（ts 在 31 秒前）
    health_service._db_health_cache = {"ok": True, "ts": time.time() - 31}
    mock_conn = MagicMock()
    with patch("services.health_service.get_conn", return_value=mock_conn):
        assert health_service.check_db_health() is True
    mock_conn.execute.assert_called_once()


# ── media_path_exists ────────────────────────────────────────────

def test_media_path_exists_empty_or_none():
    assert health_service.media_path_exists("") is True
    assert health_service.media_path_exists(None) is True


@pytest.mark.parametrize("value", [
    "http://cdn.example.com/avatar.png",
    "https://cdn.example.com/cover.jpg",
    "/frontend/img/bg.jpg",
    "/api/avatar/luna.png",
    "/api/cover/luna.png",
])
def test_media_path_exists_url_or_static_prefix(value):
    assert health_service.media_path_exists(value) is True


def test_media_path_exists_real_file(tmp_path):
    f = tmp_path / "test.png"
    f.write_text("")
    assert health_service.media_path_exists(str(f)) is True


def test_media_path_exists_missing_file():
    assert health_service.media_path_exists("/nonexistent/path/xyz123.png") is False


# ── check_media_health ───────────────────────────────────────────

def test_check_media_health_ok_when_all_media_present():
    _reset_caches()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {"id": "char1", "avatar_url": "http://cdn.com/a.png", "cover_url": "/frontend/bg.jpg"},
    ]
    with patch("services.health_service.get_conn", return_value=mock_conn):
        result = health_service.check_media_health()
    assert result["ok"] is True
    assert result["missing_count"] == 0


def test_check_media_health_reports_missing_files():
    _reset_caches()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {"id": "char1", "avatar_url": "/nonexistent/avatar.png", "cover_url": ""},
    ]
    with patch("services.health_service.get_conn", return_value=mock_conn):
        result = health_service.check_media_health()
    assert result["ok"] is False
    assert result["missing_count"] == 1
    assert "char1:avatar_url:" in result["samples"][0]


def test_check_media_health_db_error_graceful():
    _reset_caches()
    with patch("services.health_service.get_conn", side_effect=Exception("db down")):
        result = health_service.check_media_health()
    assert result["ok"] is False
    assert result["missing_count"] == 1


def test_check_media_health_uses_cache_within_ttl():
    now = time.time()
    health_service._media_health_cache = {
        "ok": True, "missing_count": 0, "samples": [], "ts": now,
    }
    with patch("services.health_service.get_conn") as mock_get:
        result = health_service.check_media_health()
    assert result["ok"] is True
    mock_get.assert_not_called()


def test_check_media_health_force_bypasses_cache():
    health_service._media_health_cache = {
        "ok": True, "missing_count": 0, "samples": [], "ts": time.time(),
    }
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    with patch("services.health_service.get_conn", return_value=mock_conn):
        result = health_service.check_media_health(force=True)
    assert result["ok"] is True
    mock_conn.execute.assert_called_once()
