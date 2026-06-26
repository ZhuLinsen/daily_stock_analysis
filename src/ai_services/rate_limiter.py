# -*- coding: utf-8 -*-
"""AI 服务 API 调用频率限制模块。

基于令牌桶算法实现，支持分服务/分模型的独立限流策略，
并提供指数退避重试机制以应对限流响应。
"""

from __future__ import annotations

import logging
import random
import time
from threading import RLock
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TokenBucket:
    """令牌桶限流器。

    支持按服务/模型分桶限流，线程安全。

    Usage:
        bucket = TokenBucket(rate=10, capacity=20)  # 每秒10个，突发20个
        if bucket.acquire():
            call_api()
    """

    def __init__(
        self,
        rate: float = 10.0,
        capacity: float = 20.0,
    ) -> None:
        """
        Args:
            rate: 令牌补充速率（个/秒）
            capacity: 桶容量（最大突发请求数）
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = RLock()

    def acquire(self, tokens: float = 1.0) -> bool:
        """尝试获取指定数量的令牌。

        Args:
            tokens: 需要的令牌数

        Returns:
            是否获取成功
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def wait_time(self, tokens: float = 1.0) -> float:
        """获取获取令牌需要等待的时间（秒）。"""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                return 0.0
            deficit = tokens - self._tokens
            return deficit / self._rate if self._rate > 0 else float("inf")

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def capacity(self) -> float:
        return self._capacity


class RateLimiter:
    """多维度限流管理器。

    按服务标识维护独立的令牌桶，支持灵活的限流配置。

    Usage:
        limiter = RateLimiter()
        limiter.set_rate("deepseek", rps=30, burst=60)
        if limiter.acquire("deepseek"):
            call_service()
    """

    def __init__(self) -> None:
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = RLock()
        # 默认限流配置（requests/sec, burst）
        self._defaults: Dict[str, tuple] = {
            "deepseek": (30, 60),       # DeepSeek: 30 RPS, burst 60
            "hongdie": (10, 20),        # 红蝶AI: 10 RPS, burst 20
            "default": (10, 20),        # 默认: 10 RPS, burst 20
        }

    def get_bucket(self, service: str) -> TokenBucket:
        """获取或创建指定服务的令牌桶。"""
        with self._lock:
            if service not in self._buckets:
                rate, capacity = self._defaults.get(service, self._defaults["default"])
                self._buckets[service] = TokenBucket(rate=rate, capacity=capacity)
            return self._buckets[service]

    def acquire(self, service: str, tokens: float = 1.0) -> bool:
        """尝试获取令牌。

        Args:
            service: 服务标识
            tokens: 需要的令牌数

        Returns:
            是否获取成功
        """
        return self.get_bucket(service).acquire(tokens)

    def wait_time(self, service: str, tokens: float = 1.0) -> float:
        """获取需要等待的时间。"""
        return self.get_bucket(service).wait_time(tokens)

    def set_rate(self, service: str, rps: float, burst: float) -> None:
        """设置指定服务的限流参数。

        Args:
            service: 服务标识
            rps: 每秒请求数
            burst: 突发容量
        """
        with self._lock:
            self._defaults[service] = (rps, burst)
            if service in self._buckets:
                self._buckets[service] = TokenBucket(rate=rps, capacity=burst)

    def reset(self) -> None:
        """重置所有限流器。"""
        with self._lock:
            self._buckets.clear()

    def call_with_rate_limit(
        self,
        service: str,
        fn: Callable[..., Any],
        *args: Any,
        max_retries: int = 3,
        base_delay: float = 1.0,
        **kwargs: Any,
    ) -> Any:
        """在限流保护下调用函数，超出限流时指数退避重试。

        Args:
            service: 服务标识
            fn: 要调用的函数
            *args: 函数参数
            max_retries: 最大重试次数
            base_delay: 基础延迟（秒），每次重试翻倍
            **kwargs: 函数关键字参数

        Returns:
            函数返回值

        Raises:
            最后一次重试的异常
        """
        last_exc: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            if self.acquire(service):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    # 如果已经是最后一次尝试，直接抛出
                    if attempt >= max_retries:
                        raise
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "[RateLimiter] %s call failed (attempt %d/%d), retrying in %.1fs: %s",
                        service,
                        attempt + 1,
                        max_retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
            else:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"[{service}] 超出限流重试次数 ({max_retries})"
                    )
                wait = self.wait_time(service)
                delay = max(wait, base_delay * (2 ** attempt)) + random.uniform(0, 0.5)
                logger.warning(
                    "[RateLimiter] %s rate limited, waiting %.1fs (attempt %d/%d)",
                    service,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(delay)

        if last_exc:
            raise last_exc


# 全局默认限流器实例
_default_limiter = RateLimiter()


def get_default_limiter() -> RateLimiter:
    """获取全局默认限流器实例。"""
    return _default_limiter
