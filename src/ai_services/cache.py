# -*- coding: utf-8 -*-
"""AI 服务请求缓存模块。

提供可配置的 LRU 缓存，避免对相同请求参数重复调用 AI 服务。
缓存键基于服务标识、模型、提示词和参数的规范化哈希值。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from threading import RLock
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class AIServiceCache:
    """AI 服务请求缓存。

    基于最近最少使用(LRU)策略，支持 TTL 过期和最大条目限制。
    线程安全，适用于多线程环境。

    Usage:
        cache = AIServiceCache(max_size=1000, ttl_seconds=300)
        key = cache.make_key("deepseek", "deepseek-chat", "Hello")
        result = cache.get(key)
        if result is None:
            result = await call_service()
            cache.set(key, result)
    """

    def __init__(
        self,
        max_size: int = 500,
        ttl_seconds: int = 300,
    ) -> None:
        """
        Args:
            max_size: 缓存最大条目数，超过后淘汰最久未使用的条目
            ttl_seconds: 缓存存活时间（秒），0 表示永不过期
        """
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._access_order: Dict[str, float] = {}
        self._lock = RLock()
        self._hit_count = 0
        self._miss_count = 0

    @staticmethod
    def make_key(
        service: str,
        model: str,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成缓存键。

        Args:
            service: 服务标识（如 "deepseek"）
            model: 模型名称（如 "deepseek-chat"）
            prompt: 提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大令牌数
            extra_params: 额外参数

        Returns:
            规范化的缓存键哈希值
        """
        payload: Dict[str, Any] = {
            "service": service,
            "model": model,
            "prompt": prompt,
        }
        if system_prompt is not None:
            payload["system_prompt"] = system_prompt
        if temperature is not None:
            payload["temperature"] = round(temperature, 4)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra_params:
            payload["extra"] = extra_params

        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存结果。

        Args:
            key: 缓存键

        Returns:
            缓存的结果，不存在或已过期时返回 None
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._miss_count += 1
                return None

            result, expire_at = entry
            if self._ttl_seconds > 0 and time.monotonic() > expire_at:
                self._cache.pop(key, None)
                self._access_order.pop(key, None)
                self._miss_count += 1
                return None

            self._access_order[key] = time.monotonic()
            self._hit_count += 1
            return result

    def set(self, key: str, value: Any) -> None:
        """设置缓存条目。

        Args:
            key: 缓存键
            value: 要缓存的值
        """
        with self._lock:
            expire_at = 0.0
            if self._ttl_seconds > 0:
                expire_at = time.monotonic() + self._ttl_seconds

            # 淘汰最久未使用的条目
            while len(self._cache) >= self._max_size and key not in self._cache:
                oldest_key = min(self._access_order, key=self._access_order.get)  # type: ignore[arg-type]
                self._cache.pop(oldest_key, None)
                self._access_order.pop(oldest_key, None)

            self._cache[key] = (value, expire_at)
            self._access_order[key] = time.monotonic()

    def invalidate(self, key: str) -> None:
        """失效指定缓存条目。

        Args:
            key: 缓存键
        """
        with self._lock:
            self._cache.pop(key, None)
            self._access_order.pop(key, None)

    def clear(self) -> None:
        """清空所有缓存。"""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._hit_count = 0
            self._miss_count = 0

    @property
    def stats(self) -> Dict[str, Any]:
        """返回缓存统计信息。"""
        with self._lock:
            total = self._hit_count + self._miss_count
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl_seconds,
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "hit_rate": self._hit_count / total if total > 0 else 0.0,
            }

    def get_cached_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], Any],
    ) -> Any:
        """缓存模式：命中直接返回，未命中计算后缓存。

        Args:
            key: 缓存键
            compute_fn: 未命中时的计算函数

        Returns:
            计算结果
        """
        cached = self.get(key)
        if cached is not None:
            return cached

        result = compute_fn()
        self.set(key, result)
        return result


# 全局默认缓存实例
_default_cache = AIServiceCache()


def get_default_cache() -> AIServiceCache:
    """获取全局默认缓存实例。"""
    return _default_cache
