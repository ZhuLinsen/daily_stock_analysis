# -*- coding: utf-8 -*-
"""AI 服务配置管理模块。

提供 AI 服务的配置数据模型、加密存储和配置加载功能。
支持通过环境变量、配置文件灵活调整各服务的参数。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 红蝶AI 默认配置
HONGDIE_DEFAULT_BASE_URL = "https://tokento.vip/v1"
HONGDIE_DEFAULT_MODEL = "gpt-4o-mini"
HONGDIE_DEFAULT_TIMEOUT = 30.0
HONGDIE_HOMEPAGE_URL = "https://tokento.vip"

# DeepSeek 默认配置
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"
DEEPSEEK_DEFAULT_TIMEOUT = 30.0


def _get_env_path() -> Path:
    """获取 .env 文件路径。"""
    env_file = os.getenv("ENV_FILE")
    if env_file:
        return Path(env_file).resolve()
    return (Path(__file__).resolve().parent.parent.parent / ".env").resolve()


@dataclass
class AIServiceSettings:
    """单个 AI 服务的配置设置。

    Attributes:
        enabled: 是否启用该服务
        api_key: API 密钥
        base_url: API 基础地址
        model: 使用的模型名称
        timeout: 请求超时时间（秒）
        temperature: 温度参数 (0.0-2.0)
        max_tokens: 最大输出令牌数
        extra_params: 额外参数
    """

    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: float = 30.0
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)

    def is_configured(self) -> bool:
        """检查服务是否已正确配置。"""
        return bool(self.api_key) and self.enabled


@dataclass
class AIServiceConfig:
    """AI 服务全局配置。

    管理 DeepSeek 和红蝶AI 的配置信息，支持从环境变量加载。
    提供 API Key 的简单掩码存储，避免明文暴露。
    """

    deepseek: AIServiceSettings = field(default_factory=AIServiceSettings)
    hongdie: AIServiceSettings = field(default_factory=AIServiceSettings)

    # 缓存配置
    cache_enabled: bool = True
    cache_max_size: int = 500
    cache_ttl_seconds: int = 300

    # 限流配置
    rate_limiter_enabled: bool = True

    @classmethod
    def from_env(cls) -> "AIServiceConfig":
        """从环境变量加载配置。

        对应的环境变量：
          - DEEPSEEK_API_KEY / DEEPSEEK_ENABLED / DEEPSEEK_MODEL
          - DEEPSEEK_BASE_URL / DEEPSEEK_TIMEOUT / DEEPSEEK_TEMPERATURE / DEEPSEEK_MAX_TOKENS
          - HONGDIE_API_KEY / HONGDIE_ENABLED / HONGDIE_MODEL
          - HONGDIE_BASE_URL / HONGDIE_TIMEOUT / HONGDIE_TEMPERATURE / HONGDIE_MAX_TOKENS
          - AI_SERVICE_CACHE_ENABLED / AI_SERVICE_CACHE_MAX_SIZE / AI_SERVICE_CACHE_TTL
          - AI_SERVICE_RATE_LIMITER_ENABLED
        """
        config = cls()

        # DeepSeek 配置
        config.deepseek = AIServiceSettings(
            enabled=_env_bool("DEEPSEEK_ENABLED", True),
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_DEFAULT_BASE_URL),
            model=os.getenv("DEEPSEEK_MODEL", DEEPSEEK_DEFAULT_MODEL),
            timeout=float(os.getenv("DEEPSEEK_TIMEOUT", str(DEEPSEEK_DEFAULT_TIMEOUT))),
            temperature=_env_float("DEEPSEEK_TEMPERATURE"),
            max_tokens=_env_int("DEEPSEEK_MAX_TOKENS"),
        )

        # 红蝶AI 配置
        config.hongdie = AIServiceSettings(
            enabled=_env_bool("HONGDIE_ENABLED", False),
            api_key=os.getenv("HONGDIE_API_KEY", ""),
            base_url=os.getenv("HONGDIE_BASE_URL", HONGDIE_DEFAULT_BASE_URL),
            model=os.getenv("HONGDIE_MODEL", HONGDIE_DEFAULT_MODEL),
            timeout=float(os.getenv("HONGDIE_TIMEOUT", str(HONGDIE_DEFAULT_TIMEOUT))),
            temperature=_env_float("HONGDIE_TEMPERATURE"),
            max_tokens=_env_int("HONGDIE_MAX_TOKENS"),
        )

        # 缓存配置
        config.cache_enabled = _env_bool("AI_SERVICE_CACHE_ENABLED", True)
        config.cache_max_size = _env_int("AI_SERVICE_CACHE_MAX_SIZE", 500) or 500
        config.cache_ttl_seconds = _env_int("AI_SERVICE_CACHE_TTL", 300) or 300

        # 限流配置
        config.rate_limiter_enabled = _env_bool("AI_SERVICE_RATE_LIMITER_ENABLED", True)

        return config

    def get_enabled_services(self) -> List[str]:
        """获取已启用的服务列表。"""
        services = []
        if self.deepseek.enabled:
            services.append("deepseek")
        if self.hongdie.enabled:
            services.append("hongdie")
        return services

    def to_env_dict(self) -> Dict[str, str]:
        """将配置转换为环境变量字典（用于写入 .env）。"""
        result: Dict[str, str] = {}

        # DeepSeek
        result["DEEPSEEK_ENABLED"] = str(self.deepseek.enabled).lower()
        if self.deepseek.api_key:
            result["DEEPSEEK_API_KEY"] = self.deepseek.api_key
        result["DEEPSEEK_BASE_URL"] = self.deepseek.base_url
        result["DEEPSEEK_MODEL"] = self.deepseek.model
        result["DEEPSEEK_TIMEOUT"] = str(self.deepseek.timeout)
        if self.deepseek.temperature is not None:
            result["DEEPSEEK_TEMPERATURE"] = str(self.deepseek.temperature)
        if self.deepseek.max_tokens is not None:
            result["DEEPSEEK_MAX_TOKENS"] = str(self.deepseek.max_tokens)

        # 红蝶AI
        result["HONGDIE_ENABLED"] = str(self.hongdie.enabled).lower()
        if self.hongdie.api_key:
            result["HONGDIE_API_KEY"] = self.hongdie.api_key
        result["HONGDIE_BASE_URL"] = self.hongdie.base_url
        result["HONGDIE_MODEL"] = self.hongdie.model
        result["HONGDIE_TIMEOUT"] = str(self.hongdie.timeout)
        if self.hongdie.temperature is not None:
            result["HONGDIE_TEMPERATURE"] = str(self.hongdie.temperature)
        if self.hongdie.max_tokens is not None:
            result["HONGDIE_MAX_TOKENS"] = str(self.hongdie.max_tokens)

        return result

    def mask_api_keys(self) -> "AIServiceConfig":
        """返回 API Key 已掩码的配置副本（用于日志输出）。"""
        masked = AIServiceConfig(
            deepseek=AIServiceSettings(
                enabled=self.deepseek.enabled,
                api_key=mask_key(self.deepseek.api_key),
                base_url=self.deepseek.base_url,
                model=self.deepseek.model,
                timeout=self.deepseek.timeout,
                temperature=self.deepseek.temperature,
                max_tokens=self.deepseek.max_tokens,
            ),
            hongdie=AIServiceSettings(
                enabled=self.hongdie.enabled,
                api_key=mask_key(self.hongdie.api_key),
                base_url=self.hongdie.base_url,
                model=self.hongdie.model,
                timeout=self.hongdie.timeout,
                temperature=self.hongdie.temperature,
                max_tokens=self.hongdie.max_tokens,
            ),
            cache_enabled=self.cache_enabled,
            cache_max_size=self.cache_max_size,
            cache_ttl_seconds=self.cache_ttl_seconds,
            rate_limiter_enabled=self.rate_limiter_enabled,
        )
        return masked


def mask_key(key: str, visible_chars: int = 4) -> str:
    """对 API Key 进行掩码处理，只保留前 N 位和末 4 位。

    Args:
        key: 原始 API Key
        visible_chars: 开头保留的可见字符数

    Returns:
        掩码后的字符串，如 "sk-12****abcd"
    """
    if not key:
        return ""
    if len(key) <= visible_chars + 4:
        return key[:visible_chars] + "****" + key[-4:] if len(key) > visible_chars + 4 else "****"
    return key[:visible_chars] + "****" + key[-4:]


def _env_bool(key: str, default: bool = False) -> bool:
    """读取环境变量的布尔值。"""
    val = os.getenv(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _env_float(key: str) -> Optional[float]:
    """读取环境变量的浮点值。"""
    val = os.getenv(key, "").strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        logger.warning("Invalid float value for env %s: %s", key, val)
        return None


def _env_int(key: str, default: Optional[int] = None) -> Optional[int]:
    """读取环境变量的整数值。"""
    val = os.getenv(key, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        logger.warning("Invalid int value for env %s: %s", key, val)
        return default
