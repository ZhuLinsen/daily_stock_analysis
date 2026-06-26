# -*- coding: utf-8 -*-
"""AI 服务频率限制模块测试。"""

from __future__ import annotations

import time

import pytest

from src.ai_services.rate_limiter import RateLimiter, TokenBucket, get_default_limiter


class TestTokenBucket:
    """测试令牌桶。"""

    def test_acquire_basic(self) -> None:
        bucket = TokenBucket(rate=10, capacity=10)
        assert bucket.acquire()  # 应有足够令牌
        assert bucket.rate == 10
        assert bucket.capacity == 10

    def test_acquire_consume_all(self) -> None:
        bucket = TokenBucket(rate=10, capacity=5)
        for _ in range(5):
            assert bucket.acquire()
        # 第 6 次应失败（桶已空）
        assert not bucket.acquire()

    def test_refill_over_time(self) -> None:
        bucket = TokenBucket(rate=100, capacity=10)
        # 消耗所有令牌
        for _ in range(10):
            bucket.acquire()
        assert not bucket.acquire()
        # 等待令牌补充
        time.sleep(0.05)
        assert bucket.acquire()  # 应有令牌补充

    def test_wait_time_zero_when_available(self) -> None:
        bucket = TokenBucket(rate=10, capacity=10)
        assert bucket.wait_time() == 0.0

    def test_wait_time_positive_when_empty(self) -> None:
        bucket = TokenBucket(rate=10, capacity=5)
        for _ in range(5):
            bucket.acquire()
        wait = bucket.wait_time()
        assert wait > 0

    def test_multi_token_acquire(self) -> None:
        bucket = TokenBucket(rate=10, capacity=20)
        assert bucket.acquire(tokens=5)
        assert bucket.acquire(tokens=5)
        assert bucket.acquire(tokens=5)
        assert bucket.acquire(tokens=5)
        assert not bucket.acquire()  # 已空

    def test_infinite_wait_time_when_zero_rate(self) -> None:
        bucket = TokenBucket(rate=0, capacity=5)
        # 先消耗所有令牌
        for _ in range(5):
            bucket.acquire()
        wait = bucket.wait_time()
        assert wait == float("inf")

    def test_thread_safety(self) -> None:
        """令牌桶应线程安全。"""
        import threading

        bucket = TokenBucket(rate=1000, capacity=100)
        errors = []

        def worker() -> None:
            for _ in range(20):
                try:
                    bucket.acquire()
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestRateLimiter:
    """测试限流管理器。"""

    def test_acquire_per_service(self) -> None:
        limiter = RateLimiter()
        # DeepSeek 应有较高配额
        assert limiter.acquire("deepseek")
        assert limiter.acquire("hongdie")

    def test_set_rate(self) -> None:
        limiter = RateLimiter()
        limiter.set_rate("test_service", rps=5, burst=3)

        for _ in range(3):
            assert limiter.acquire("test_service")
        # 第 4 次应失败（突发只有 3）
        assert not limiter.acquire("test_service")

    def test_set_rate_updates_existing_bucket(self) -> None:
        limiter = RateLimiter()
        # 先获取桶
        limiter.get_bucket("test")
        # 更新速率
        limiter.set_rate("test", rps=1, burst=1)

    def test_reset(self) -> None:
        limiter = RateLimiter()
        limiter.get_bucket("deepseek")
        limiter.get_bucket("hongdie")
        limiter.reset()
        # 重置后应重新创建桶
        assert limiter.acquire("deepseek")

    def test_set_rate_updates_defaults(self) -> None:
        """设置速率应更新默认配置。"""
        limiter = RateLimiter()
        limiter.set_rate("custom", rps=20, burst=40)
        for _ in range(40):
            assert limiter.acquire("custom")
        assert not limiter.acquire("custom")

    def test_wait_time(self) -> None:
        limiter = RateLimiter()
        wait = limiter.wait_time("deepseek")
        assert wait >= 0

    def test_call_with_rate_limit_success(self) -> None:
        limiter = RateLimiter()
        result = limiter.call_with_rate_limit("deepseek", lambda x: x + 1, 41)
        assert result == 42

    def test_call_with_rate_limit_retry_on_error(self) -> None:
        call_count = 0

        def flaky_fn() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "success"

        limiter = RateLimiter()
        # 给足够多的突发容量
        limiter.set_rate("flaky", rps=100, burst=100)

        result = limiter.call_with_rate_limit(
            "flaky",
            flaky_fn,
            max_retries=3,
            base_delay=0.01,
        )
        assert result == "success"
        assert call_count == 3

    def test_call_with_rate_limit_fails_after_retries(self) -> None:
        call_count = 0

        def always_fail() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("persistent error")

        limiter = RateLimiter()
        limiter.set_rate("failing", rps=100, burst=100)

        with pytest.raises(ValueError, match="persistent error"):
            limiter.call_with_rate_limit(
                "failing",
                always_fail,
                max_retries=2,
                base_delay=0.01,
            )
        assert call_count == 3  # 1 次 + 2 次重试


class TestDefaultLimiter:
    """测试默认全局限流器。"""

    def test_get_default_limiter_singleton(self) -> None:
        limiter1 = get_default_limiter()
        limiter2 = get_default_limiter()
        assert limiter1 is limiter2

    def test_default_rates(self) -> None:
        limiter = get_default_limiter()
        # 验证默认配置
        bucket = limiter.get_bucket("deepseek")
        assert bucket.capacity == 60
        bucket = limiter.get_bucket("hongdie")
        assert bucket.capacity == 20
