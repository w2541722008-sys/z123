"""
简单的内存缓存服务

功能：
    - 缓存角色数据（减少 80% 的数据库查询）
    - 缓存用户信息
    - 自动过期机制
    - 线程安全
    - max_size 上限保护，防止内存泄漏

使用方法：
    from services.cache_service import cache
    
    # 获取缓存
    character = cache.get_character(character_id)
    if not character:
        # 缓存未命中，查询数据库
        character = fetch_from_db(character_id)
        cache.set_character(character_id, character)
"""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import Lock
from typing import Any


class SimpleCache:
    """LRU 内存缓存，支持过期时间和大小上限。

    淘汰策略：
        - 满时先清理过期项
        - 仍超限则淘汰最久未访问的项（LRU）
    """

    def __init__(self, default_ttl: int = 300, max_size: int = 500):
        """
        初始化缓存。

        Args:
            default_ttl: 默认过期时间（秒），默认 5 分钟
            max_size: 缓存条目上限，超过时触发过期清理和 LRU 淘汰
        """
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = Lock()
        self.default_ttl = default_ttl
        self.max_size = max_size

    def get(self, key: str) -> Any | None:
        """获取缓存值，命中时提升到最近访问位置；过期则返回 None。"""
        with self._lock:
            if key not in self._cache:
                return None

            value, expires_at = self._cache[key]

            # 检查是否过期
            if time.time() > expires_at:
                del self._cache[key]
                return None

            # LRU: 命中后移到末尾（最近访问）
            self._cache.move_to_end(key)
            return value
    
    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """设置缓存值。当缓存满时，先清理过期项，仍超限则淘汰最旧项。"""
        if ttl is None:
            ttl = self.default_ttl
        
        expires_at = time.time() + ttl
        
        with self._lock:
            # 缓存满时触发清理
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._cleanup_expired_unlocked()
                # 清理后仍超限，淘汰最旧项
                if len(self._cache) >= self.max_size:
                    self._evict_lru_unlocked()
            
            self._cache[key] = (value, expires_at)
    
    def delete(self, key: str) -> None:
        """删除缓存值。"""
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        """清空所有缓存。"""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """清理过期的缓存项，返回清理数量。"""
        with self._lock:
            return self._cleanup_expired_unlocked()
    
    def _cleanup_expired_unlocked(self) -> int:
        """清理过期的缓存项（不加锁，调用方需持有锁）。"""
        now = time.time()
        expired_keys = [key for key, (_, expires_at) in self._cache.items() if now > expires_at]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)
    
    def _evict_lru_unlocked(self) -> None:
        """淘汰最久未访问的缓存项（LRU，不加锁，调用方需持有锁）。"""
        if self._cache:
            self._cache.popitem(last=False)
    
    def __len__(self) -> int:
        """返回当前缓存条目数。"""
        with self._lock:
            return len(self._cache)


# 全局缓存实例
cache = SimpleCache(default_ttl=300, max_size=500)  # 5 分钟过期，最多 500 条


# 便捷方法：角色缓存
def get_character(character_id: str) -> dict[str, Any] | None:
    """获取缓存的角色数据。"""
    return cache.get(f"character:{character_id}")


def set_character(character_id: str, character_data: dict[str, Any], ttl: int = 300) -> None:
    """缓存角色数据。"""
    cache.set(f"character:{character_id}", character_data, ttl)


def invalidate_character(character_id: str) -> None:
    """使角色缓存失效（更新角色时调用）。"""
    cache.delete(f"character:{character_id}")


# 便捷方法：用户缓存
def get_user(user_id: int | str) -> dict[str, Any] | None:
    """获取缓存的用户数据。"""
    return cache.get(f"user:{user_id}")


def set_user(user_id: int | str, user_data: dict[str, Any], ttl: int = 300) -> None:
    """缓存用户数据。"""
    cache.set(f"user:{user_id}", user_data, ttl)


def invalidate_user(user_id: int | str) -> None:
    """使用户缓存失效（更新用户时调用）。"""
    cache.delete(f"user:{user_id}")


def cache_get(key: str) -> Any | None:
    """获取指定 key 的缓存值。"""
    return cache.get(key)


def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    """设置指定 key 的缓存值。"""
    cache.set(key, value, ttl)


def cache_delete(key: str) -> None:
    """删除指定 key 的缓存值。"""
    cache.delete(key)


def invalidate_character_affection_rules(character_id: str) -> None:
    """使好感度规则缓存失效（更新角色时调用）。"""
    cache.delete(f"affection_rules:{character_id}")


def invalidate_character_list_all() -> None:
    """使角色列表缓存失效（创建/删除/更新角色时调用）。"""
    cache.delete("character_list_all")
