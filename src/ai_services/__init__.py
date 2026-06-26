# -*- coding: utf-8 -*-
"""AI Services - 统一 AI 服务适配层

提供统一的 AI 服务调用接口，支持多种 AI 服务的无缝切换。
当前支持的服务：
  - DeepSeek: 通过 litellm 原生支持
  - 红蝶AI (Hongdie): OpenAI-compatible API

主要组件:
  - BaseAIService: 服务抽象基类
  - DeepSeekService: DeepSeek 服务实现
  - HongdieService: 红蝶AI 服务实现
  - AIServiceFactory: 服务工厂
  - AIServiceConfig: 配置管理
"""

from __future__ import annotations

from src.ai_services.base import BaseAIService
from src.ai_services.config import AIServiceConfig, AIServiceSettings
from src.ai_services.errors import (
    AIAuthenticationError,
    AIError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServiceError,
    AITimeoutError,
)
from src.ai_services.factory import AIServiceFactory
from src.ai_services.deepseek_service import DeepSeekService
from src.ai_services.hongdie_service import HongdieService

__all__ = [
    # 基类
    "BaseAIService",
    # 服务实现
    "DeepSeekService",
    "HongdieService",
    # 工厂
    "AIServiceFactory",
    # 配置
    "AIServiceConfig",
    "AIServiceSettings",
    # 错误类型
    "AIError",
    "AIServiceError",
    "AIAuthenticationError",
    "AIRateLimitError",
    "AITimeoutError",
    "AIInvalidResponseError",
]
