"""cache_service 单元测试 — 内存缓存。

覆盖范围：
    - SimpleCache 核心逻辑
      - get/set 基本操作
      - TTL 过期机制
      - max_size 淘汰策略
      - delete/clear 操作
      - 线程安全（基础验证）
    - 便捷方法：角色缓存、用户缓存、通用缓存
"""

import time
import threading

import pytest

from services.cache_service import (
    SimpleCache,
    cache,
    get_character,
    set_character,
    invalidate_character,
    get_user,
    set_user,
    invalidate_user,
    cache_get,
    cache_set,
    cache_delete,
    invalidate_character_affection_rules,
    invalidate_character_list_all,
)


# ── SimpleCache 核心逻辑 ───────────────────────────────────────

class TestSimpleCacheGetSet:

    def test_set_and_get(self):
        c = SimpleCache(default_ttl=60)
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_get_missing_key_returns_none(self):
        c = SimpleCache()
        assert c.get("nonexistent") is None

    def test_get_expired_returns_none(self):
        c = SimpleCache(default_ttl=1)
        c.set("k1", "v1", ttl=1)
        time.sleep(1.1)
        assert c.get("k1") is None

    def test_get_expired_removes_key(self):
        c = SimpleCache(default_ttl=1)
        c.set("k1", "v1", ttl=1)
        time.sleep(1.1)
        c.get("k1")
        assert len(c) == 0

    def test_custom_ttl(self):
        c = SimpleCache(default_ttl=1)
        c.set("short", "v", ttl=1)
        c.set("long", "v", ttl=300)
        time.sleep(1.1)
        assert c.get("short") is None
        assert c.get("long") == "v"

    def test_overwrite_existing_key(self):
        c = SimpleCache()
        c.set("k1", "old")
        c.set("k1", "new")
        assert c.get("k1") == "new"

    def test_various_value_types(self):
        c = SimpleCache()
        c.set("dict", {"a": 1})
        c.set("list", [1, 2, 3])
        c.set("int", 42)
        c.set("none", None)
        assert c.get("dict") == {"a": 1}
        assert c.get("list") == [1, 2, 3]
        assert c.get("int") == 42
        # None 是有效值（与 missing 区分开）
        assert c.get("none") is None
        # 但 None 和 missing 都返回 None — 这是设计上的取舍
        # 如需区分，可用 sentinel: _MISSING = object()


class TestSimpleCacheMaxSize:

    def test_evicts_lru_when_full(self):
        """缓存满时淘汰最久未访问的项（LRU）。"""
        c = SimpleCache(default_ttl=300, max_size=3)
        c.set("k1", "v1")
        c.set("k2", "v2")
        c.set("k3", "v3")
        # 访问 k1，使其成为最近访问
        c.get("k1")
        # 缓存已满，添加 k4 应淘汰 k2（最久未访问）
        c.set("k4", "v4")
        assert c.get("k2") is None
        assert c.get("k1") == "v1"  # 最近访问过，保留
        assert c.get("k4") == "v4"

    def test_evicts_without_prior_access(self):
        """未做过 get 时，淘汰最先插入的项。"""
        c = SimpleCache(default_ttl=300, max_size=2)
        c.set("k1", "v1")
        c.set("k2", "v2")
        c.set("k3", "v3")
        assert c.get("k1") is None  # k1 最先插入，最先淘汰
        assert c.get("k2") == "v2"
        assert c.get("k3") == "v3"

    def test_lru_access_refreshes_position(self):
        """get 使条目移到最近访问位置，不会被优先淘汰。"""
        c = SimpleCache(default_ttl=300, max_size=3)
        c.set("k1", "v1")
        c.set("k2", "v2")
        c.set("k3", "v3")
        # 反复访问 k1
        c.get("k1")
        c.get("k2")
        # k3 已是最久未访问
        c.set("k4", "v4")
        assert c.get("k3") is None
        assert c.get("k1") == "v1"
        assert c.get("k2") == "v2"

    def test_overwrite_does_not_trigger_eviction(self):
        c = SimpleCache(default_ttl=300, max_size=2)
        c.set("k1", "v1")
        c.set("k2", "v2")
        # 覆盖现有 key 不算新增，不应触发淘汰
        c.set("k1", "v1_updated")
        assert c.get("k1") == "v1_updated"
        assert c.get("k2") == "v2"

    def test_expired_cleanup_before_eviction(self):
        c = SimpleCache(default_ttl=300, max_size=3)
        c.set("k1", "v1", ttl=1)  # 短命
        c.set("k2", "v2")
        c.set("k3", "v3")
        time.sleep(1.1)

        # k1 已过期，添加 k4 时先清理过期项，无需淘汰 k2/k3
        c.set("k4", "v4")
        assert c.get("k2") == "v2"
        assert c.get("k3") == "v3"
        assert c.get("k4") == "v4"


class TestSimpleCacheDeleteClear:

    def test_delete_existing_key(self):
        c = SimpleCache()
        c.set("k1", "v1")
        c.delete("k1")
        assert c.get("k1") is None

    def test_delete_missing_key_no_error(self):
        c = SimpleCache()
        c.delete("nonexistent")  # 不应抛异常

    def test_clear_removes_all(self):
        c = SimpleCache()
        c.set("k1", "v1")
        c.set("k2", "v2")
        c.clear()
        assert len(c) == 0
        assert c.get("k1") is None

    def test_len_returns_count(self):
        c = SimpleCache()
        assert len(c) == 0
        c.set("k1", "v1")
        assert len(c) == 1
        c.set("k2", "v2")
        assert len(c) == 2


class TestSimpleCacheCleanupExpired:

    def test_cleanup_expired_returns_count(self):
        c = SimpleCache()
        c.set("k1", "v1", ttl=1)
        c.set("k2", "v2", ttl=1)
        c.set("k3", "v3", ttl=300)
        time.sleep(1.1)

        count = c.cleanup_expired()
        assert count == 2
        assert len(c) == 1
        assert c.get("k3") == "v3"

    def test_cleanup_no_expired_returns_zero(self):
        c = SimpleCache()
        c.set("k1", "v1", ttl=300)
        assert c.cleanup_expired() == 0


class TestSimpleCacheThreadSafety:

    def test_concurrent_access(self):
        """基础线程安全验证：并发读写不崩溃。"""
        c = SimpleCache(default_ttl=300, max_size=100)
        errors = []

        def writer(start):
            try:
                for i in range(50):
                    c.set(f"key_{start}_{i}", i)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(50):
                    c.get(f"key_0_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(0,)),
            threading.Thread(target=writer, args=(1,)),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ── 便捷方法 ──────────────────────────────────────────────────

class TestConvenienceMethods:

    def setup_method(self):
        """每个测试前清空全局缓存。"""
        cache.clear()

    def test_character_cache_roundtrip(self):
        set_character("char1", {"name": "角色1"})
        assert get_character("char1") == {"name": "角色1"}

    def test_character_invalidate(self):
        set_character("char1", {"name": "角色1"})
        invalidate_character("char1")
        assert get_character("char1") is None

    def test_user_cache_roundtrip(self):
        set_user(42, {"nickname": "测试用户"})
        assert get_user(42) == {"nickname": "测试用户"}

    def test_user_invalidate(self):
        set_user(42, {"nickname": "测试用户"})
        invalidate_user(42)
        assert get_user(42) is None

    def test_cache_get_set_delete(self):
        cache_set("test_key", "test_val")
        assert cache_get("test_key") == "test_val"
        cache_delete("test_key")
        assert cache_get("test_key") is None

    def test_invalidate_character_affection_rules(self):
        cache_set("affection_rules:char1", {"deep_conversation": 4})
        invalidate_character_affection_rules("char1")
        assert cache_get("affection_rules:char1") is None

    def test_invalidate_character_list_all(self):
        cache_set("character_list_all", [{"id": "char1"}])
        invalidate_character_list_all()
        assert cache_get("character_list_all") is None

    def test_missing_user_returns_none(self):
        assert get_user(99999) is None

    def test_missing_character_returns_none(self):
        assert get_character("nonexistent") is None
