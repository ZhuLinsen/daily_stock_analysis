# -*- coding: utf-8 -*-
"""AI 服务工厂。

基于配置创建对应的 AI 服务实例，支持按服务名称动态创建。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Type

from src.ai_services.base import BaseAIService
from src.ai_services.cache import AIServiceCache, get_default_cache
from src.ai_services.config import AIServiceConfig
from src.ai_services.deepseek_service import DeepSeekService
from src.ai_services.hongdie_service import HongdieService
from src.ai_services.rate_limiter import RateLimiter, get_default_limiter

logger = logging.getLogger(__name__)


class AIServiceFactory:
    """AI 服务工厂。

    根据配置创建和管理 AI 服务实例。支持单例复用和按需创建。

    Usage:
        config = AIServiceConfig.from_env()
        factory = AIServiceFactory(config)
        deepseek = factory.get_service("deepseek")
        result = deepseek.generate_text("Hello")
    """

    _services: Dict[str, BaseAIService] = {}

    def __init__(
        self,
        config: Optional[AIServiceConfig] = None,
        *,
        cache: Optional[AIServiceCache] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._config = config or AIServiceConfig.from_env()
        self._cache = cache or get_default_cache()
        self._rate_limiter = rate_limiter or get_default_limiter()

    @classmethod
    def _service_registry(cls) -> Dict[str, Type[BaseAIService]]:
        """返回服务类型注册表。"""
        return {
            "deepseek": DeepSeekService,
            "hongdie": HongdieService,
        }

    @classmethod
    def get_available_services(cls) -> Dict[str, str]:
        """获取所有可用的服务及其描述。

        Returns:
            Dict[str, str]: 服务名称 -> 描述
        """
        return {
            "deepseek": "DeepSeek AI 服务（支持 deepseek-chat, deepseek-v4-flash 等模型）",
            "hongdie": "红蝶AI 服务（OpenAI-compatible API 代理）",
        }

    def get_service(self, service_name: str) -> BaseAIService:
        """获取指定名称的服务实例（单例模式）。

        Args:
            service_name: 服务名称（"deepseek" 或 "hongdie"）

        Returns:
            服务实例

        Raises:
            ValueError: 服务名称不支持或未配置
        """
        # 检查缓存
        if service_name in self._services:
            return self._services[service_name]

        # 查找服务类
        registry = self._service_registry()
        if service_name not in registry:
            raise ValueError(
                f"不支持的 AI 服务: '{service_name}'。"
                f"可用服务: {', '.join(registry.keys())}"
            )

        # 获取设置
        settings = self._get_settings(service_name)
        if not settings:
            raise ValueError(
                f"AI 服务 '{service_name}' 未配置。"
                f"请先配置对应的 API Key 并启用服务。"
            )

        # 创建服务实例
        service_class = registry[service_name]
        service = service_class(
            settings=settings,
            cache=self._cache,
            rate_limiter=self._rate_limiter,
            enable_cache=self._config.cache_enabled,
            enable_rate_limiter=self._config.rate_limiter_enabled,
        )

        self._services[service_name] = service
        return service

    def _get_settings(self, service_name: str) -> Any:
        """获取指定服务的配置设置。"""
        config_map = {
            "deepseek": self._config.deepseek,
            "hongdie": self._config.hongdie,
        }
        return config_map.get(service_name)

    def create_all_enabled(self) -> Dict[str, BaseAIService]:
        """创建所有已启用服务的实例。"""
        services = {}
        for name in self._config.get_enabled_services():
            try:
                service = self.get_service(name)
                if service.is_configured:
                    services[name] = service
                    logger.info("[Factory] Created %s service", name)
            except Exception as exc:
                logger.warning("[Factory] Failed to create %s service: %s", name, exc)
        return services

    def check_all_connections(self) -> Dict[str, Dict[str, Any]]:
        """检查所有已配置服务的连接状态。"""
        results = {}
        for name in self._config.get_enabled_services():
            try:
                service = self.get_service(name)
                results[name] = service.check_connection()
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "message": str(exc),
                    "service": name,
                    "model": "",
                }
        return results

    @classmethod
    def reset(cls) -> None:
        """重置所有已创建的服务实例（主要用于测试）。"""
        cls._services.clear()

    @classmethod
    def from_env(cls, **kwargs: Any) -> "AIServiceFactory":
        """从环境变量创建工厂。"""
        config = AIServiceConfig.from_env()
        return cls(config=config, **kwargs)
