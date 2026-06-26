# -*- coding: utf-8 -*-
"""AI 服务工厂测试。"""

from __future__ import annotations

import os

import pytest

from src.ai_services.cache import AIServiceCache
from src.ai_services.config import AIServiceConfig
from src.ai_services.deepseek_service import DeepSeekService
from src.ai_services.factory import AIServiceFactory
from src.ai_services.hongdie_service import HongdieService
from src.ai_services.rate_limiter import RateLimiter


class TestAIServiceFactory:
    """测试 AIServiceFactory。"""

    def setup_method(self) -> None:
        AIServiceFactory.reset()

    def test_init_with_config(self) -> None:
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-deepseek-test"

        factory = AIServiceFactory(config=config)
        assert factory._config is config

    def test_from_env(self) -> None:
        """从环境变量创建工厂。"""
        os.environ["DEEPSEEK_API_KEY"] = "sk-env-test"
        try:
            factory = AIServiceFactory.from_env()
            assert factory._config.deepseek.api_key == "sk-env-test"
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)

    def test_get_service_deepseek(self) -> None:
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-deepseek"

        factory = AIServiceFactory(config=config)
        service = factory.get_service("deepseek")
        assert isinstance(service, DeepSeekService)
        assert service.is_configured is True

    def test_get_service_hongdie(self) -> None:
        config = AIServiceConfig()
        config.hongdie.enabled = True
        config.hongdie.api_key = "sk-hongdie"

        factory = AIServiceFactory(config=config)
        service = factory.get_service("hongdie")
        assert isinstance(service, HongdieService)
        assert service.is_configured is True

    def test_get_service_singleton(self) -> None:
        """同一服务应返回同一实例。"""
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-test"

        factory = AIServiceFactory(config=config)
        service1 = factory.get_service("deepseek")
        service2 = factory.get_service("deepseek")
        assert service1 is service2

    def test_get_service_not_configured(self) -> None:
        """未配置的服务应报错。"""
        config = AIServiceConfig()
        # DeepSeek 默认启用但无 API key，直接获取应返回服务实例（但 is_configured=False）
        factory = AIServiceFactory(config=config)
        service = factory.get_service("deepseek")
        assert service.is_configured is False

    def test_get_service_unknown(self) -> None:
        factory = AIServiceFactory()
        with pytest.raises(ValueError, match="不支持的 AI 服务"):
            factory.get_service("nonexistent")

    def test_get_available_services(self) -> None:
        services = AIServiceFactory.get_available_services()
        assert "deepseek" in services
        assert "hongdie" in services
        assert len(services) >= 2

    def test_create_all_enabled_deepseek_only(self) -> None:
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-test"

        factory = AIServiceFactory(config=config)
        services = factory.create_all_enabled()
        assert "deepseek" in services
        assert "hongdie" not in services

    def test_create_all_enabled_both(self) -> None:
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-deepseek"
        config.hongdie.enabled = True
        config.hongdie.api_key = "sk-hongdie"

        factory = AIServiceFactory(config=config)
        services = factory.create_all_enabled()
        assert "deepseek" in services
        assert "hongdie" in services
        assert len(services) == 2

    def test_create_all_enabled_none(self) -> None:
        """没有启用任何服务。"""
        config = AIServiceConfig()
        # deepseek 默认启用但没有 key 时会跳过
        config.deepseek.api_key = ""  # 确保没有 key

        factory = AIServiceFactory(config=config)
        services = factory.create_all_enabled()
        assert len(services) == 0

    def test_reset(self) -> None:
        """重置应清除所有缓存的服务实例。"""
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-test"

        factory = AIServiceFactory(config=config)
        service1 = factory.get_service("deepseek")

        AIServiceFactory.reset()
        service2 = factory.get_service("deepseek")
        assert service1 is not service2  # 重置后应创建新实例

    def test_shared_cache_and_limiter(self) -> None:
        """同一工厂创建的服务应共享缓存和限流器。"""
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-deepseek"
        config.hongdie.enabled = True
        config.hongdie.api_key = "sk-hongdie"

        cache = AIServiceCache(max_size=10, ttl_seconds=60)
        limiter = RateLimiter()

        factory = AIServiceFactory(
            config=config,
            cache=cache,
            rate_limiter=limiter,
        )

        deepseek = factory.get_service("deepseek")
        hongdie = factory.get_service("hongdie")

        # 验证共享
        assert deepseek._cache is hongdie._cache
        assert deepseek._rate_limiter is hongdie._rate_limiter

    def test_check_all_connections(self) -> None:
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = "sk-test"
        config.hongdie.enabled = True
        config.hongdie.api_key = "sk-test"

        # 由于没有实际网络连接，预期是失败状态
        factory = AIServiceFactory(config=config)
        results = factory.check_all_connections()
        assert "deepseek" in results
        assert "hongdie" in results

    def test_create_all_enabled_skips_not_configured(self) -> None:
        """未正确配置的服务应被跳过。"""
        config = AIServiceConfig()
        config.deepseek.enabled = True
        config.deepseek.api_key = ""  # 没有 key

        factory = AIServiceFactory(config=config)
        services = factory.create_all_enabled()
        assert "deepseek" not in services

    def test_service_registry_contains_all_services(self) -> None:
        """服务注册表应包含所有已知服务。"""
        registry = AIServiceFactory._service_registry()
        assert "deepseek" in registry
        assert registry["deepseek"] == DeepSeekService
        assert "hongdie" in registry
        assert registry["hongdie"] == HongdieService
