# -*- coding: utf-8 -*-
"""AI 服务缓存模块测试。"""

from __future__ import annotations

import time

from src.ai_services.cache import AIServiceCache, get_default_cache


class TestAIServiceCache:
    """测试缓存基础功能。"""

    def test_make_key_consistency(self) -> None:
        """相同参数应生成相同缓存键。"""
        key1 = AIServiceCache.make_key("deepseek", "deepseek-chat", "Hello")
        key2 = AIServiceCache.make_key("deepseek", "deepseek-chat", "Hello")
        assert key1 == key2

    def test_make_key_different_prompt(self) -> None:
        """不同提示词应生成不同缓存键。"""
        key1 = AIServiceCache.make_key("deepseek", "deepseek-chat", "Hello")
        key2 = AIServiceCache.make_key("deepseek", "deepseek-chat", "World")
        assert key1 != key2

    def test_make_key_with_system_prompt(self) -> None:
        """系统提示词应影响缓存键。"""
        key1 = AIServiceCache.make_key(
            "deepseek", "deepseek-chat", "Hello",
            system_prompt="Be helpful",
        )
        key2 = AIServiceCache.make_key(
            "deepseek", "deepseek-chat", "Hello",
            system_prompt="Be concise",
        )
        assert key1 != key2

    def test_make_key_with_temperature(self) -> None:
        """温度参数应影响缓存键（精确到 4 位小数）。"""
        key1 = AIServiceCache.make_key(
            "deepseek", "deepseek-chat", "Hello",
            temperature=0.7,
        )
        key2 = AIServiceCache.make_key(
            "deepseek", "deepseek-chat", "Hello",
            temperature=0.70001,
        )
        assert key1 == key2  # 四舍五入后应相同

        key3 = AIServiceCache.make_key(
            "deepseek", "deepseek-chat", "Hello",
            temperature=0.7,
        )
        key4 = AIServiceCache.make_key(
            "deepseek", "deepseek-chat", "Hello",
            temperature=0.8,
        )
        assert key3 != key4

    def test_make_key_different_services(self) -> None:
        """不同服务应生成不同缓存键。"""
        key1 = AIServiceCache.make_key("deepseek", "deepseek-chat", "Hello")
        key2 = AIServiceCache.make_key("hongdie", "gpt-4o", "Hello")
        assert key1 != key2

    def test_get_set(self) -> None:
        """基础 get/set 功能。"""
        cache = AIServiceCache(max_size=100, ttl_seconds=60)
        key = cache.make_key("deepseek", "deepseek-chat", "Hello")
        cache.set(key, "Hello World")
        result = cache.get(key)
        assert result == "Hello World"

    def test_get_missing(self) -> None:
        """获取不存在的键应返回 None。"""
        cache = AIServiceCache()
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_ttl(self) -> None:
        """超过 TTL 的缓存应失效。"""
        cache = AIServiceCache(max_size=100, ttl_seconds=0.1)
        key = cache.make_key("deepseek", "deepseek-chat", "Hello")
        cache.set(key, "test")
        time.sleep(0.15)
        result = cache.get(key)
        assert result is None

    def test_cache_zero_ttl(self) -> None:
        """TTL 为 0 表示永不过期。"""
        cache = AIServiceCache(max_size=100, ttl_seconds=0)
        key = cache.make_key("deepseek", "deepseek-chat", "Hello")
        cache.set(key, "test")
        result = cache.get(key)
        assert result == "test"

    def test_cache_lru_eviction(self) -> None:
        """超过最大容量时淘汰最久未使用的条目。"""
        cache = AIServiceCache(max_size=2, ttl_seconds=0)
        key1 = cache.make_key("s1", "m1", "p1")
        key2 = cache.make_key("s2", "m2", "p2")
        key3 = cache.make_key("s3", "m3", "p3")

        cache.set(key1, "v1")
        cache.set(key2, "v2")
        cache.set(key3, "v3")  # 应淘汰 key1

        assert cache.get(key1) is None  # 已被淘汰
        assert cache.get(key2) == "v2"
        assert cache.get(key3) == "v3"

    def test_invalidate(self) -> None:
        """失效指定缓存条目。"""
        cache = AIServiceCache(max_size=100, ttl_seconds=60)
        key = cache.make_key("deepseek", "deepseek-chat", "Hello")
        cache.set(key, "test")
        cache.invalidate(key)
        assert cache.get(key) is None

    def test_clear(self) -> None:
        """清空所有缓存。"""
        cache = AIServiceCache(max_size=100, ttl_seconds=60)
        key1 = cache.make_key("deepseek", "deepseek-chat", "Hello")
        key2 = cache.make_key("hongdie", "gpt-4o", "World")
        cache.set(key1, "v1")
        cache.set(key2, "v2")
        cache.clear()
        assert cache.get(key1) is None
        assert cache.get(key2) is None
        stats = cache.stats
        assert stats["size"] == 0
        assert stats["hit_count"] == 0

    def test_get_cached_or_compute(self) -> None:
        """缓存模式：命中返回缓存，未命中计算并缓存。"""
        cache = AIServiceCache(max_size=100, ttl_seconds=60)
        call_count = 0

        def compute() -> str:
            nonlocal call_count
            call_count += 1
            return f"result_{call_count}"

        key = cache.make_key("deepseek", "deepseek-chat", "test")
        # 第一次调用：计算
        result1 = cache.get_cached_or_compute(key, compute)
        assert result1 == "result_1"
        assert call_count == 1

        # 第二次调用：命中缓存
        result2 = cache.get_cached_or_compute(key, compute)
        assert result2 == "result_1"
        assert call_count == 1  # 未再次调用

    def test_stats(self) -> None:
        """缓存统计信息。"""
        cache = AIServiceCache(max_size=100, ttl_seconds=60)

        key1 = cache.make_key("s1", "m1", "p1")
        key2 = cache.make_key("s2", "m2", "p2")

        cache.set(key1, "v1")
        cache.get(key1)  # hit
        cache.get(key2)  # miss
        cache.get(key1)  # hit

        stats = cache.stats
        assert stats["size"] == 1
        assert stats["max_size"] == 100
        assert stats["hit_count"] == 2
        assert stats["miss_count"] == 1
        assert stats["hit_rate"] == 2 / 3

    def test_max_size_eviction_order(self) -> None:
        """验证淘汰顺序是 LRU（最近最少使用）。"""
        cache = AIServiceCache(max_size=2, ttl_seconds=0)

        key_a = cache.make_key("s", "m", "a")
        key_b = cache.make_key("s", "m", "b")
        key_c = cache.make_key("s", "m", "c")

        # 设置 a, b, 访问 a, 设置 c -> 应淘汰 b (因为 b 最久未使用)
        cache.set(key_a, "va")
        cache.set(key_b, "vb")
        cache.get(key_a)  # 访问 a, 使 a 成为最近使用
        cache.set(key_c, "vc")  # 应淘汰 b

        assert cache.get(key_a) == "va"  # a 应该还在
        assert cache.get(key_b) is None  # b 被淘汰
        assert cache.get(key_c) == "vc"


class TestDefaultCache:
    """测试默认全局缓存。"""

    def test_get_default_cache_singleton(self) -> None:
        """get_default_cache 应返回同一实例。"""
        cache1 = get_default_cache()
        cache2 = get_default_cache()
        assert cache1 is cache2

    def test_default_cache_uses_test_defaults(self) -> None:
        """默认缓存应使用合理的默认值。"""
        cache = get_default_cache()
        stats = cache.stats
        assert stats["max_size"] == 500
        assert stats["ttl_seconds"] == 300
