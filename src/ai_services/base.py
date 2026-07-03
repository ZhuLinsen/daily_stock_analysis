# -*- coding: utf-8 -*-
"""AI 服务抽象基类。

定义统一的 AI 服务接口规范，所有具体服务（DeepSeek、红蝶AI 等）
都实现此接口，确保业务层代码无需修改即可切换不同 AI 服务。
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.ai_services.cache import AIServiceCache, get_default_cache
from src.ai_services.config import AIServiceSettings
from src.ai_services.errors import (
    AIError,
    AIRateLimitError,
    classify_litellm_error,
)
from src.ai_services.rate_limiter import RateLimiter, get_default_limiter

logger = logging.getLogger(__name__)


class BaseAIService(ABC):
    """AI 服务抽象基类。

    所有 AI 服务实现的统一接口，提供：
      - generate_text: 文本生成
      - embed_text: 文本嵌入（可选）
      - 标准化的日志记录
      - 缓存支持
      - 限流支持
      - 错误分类

    子类必须实现:
      - _call_generate: 实际调用 LLM 的核心方法
      - service_name: 服务标识
    """

    def __init__(
        self,
        settings: AIServiceSettings,
        *,
        cache: Optional[AIServiceCache] = None,
        rate_limiter: Optional[RateLimiter] = None,
        enable_cache: bool = True,
        enable_rate_limiter: bool = True,
    ) -> None:
        """
        Args:
            settings: 服务配置
            cache: 缓存实例，默认使用全局缓存
            rate_limiter: 限流器实例，默认使用全局限流器
            enable_cache: 是否启用缓存
            enable_rate_limiter: 是否启用限流
        """
        self._settings = settings
        self._cache = cache or get_default_cache()
        self._rate_limiter = rate_limiter or get_default_limiter()
        self._enable_cache = enable_cache and settings.enabled
        self._enable_rate_limiter = enable_rate_limiter and settings.enabled

    @property
    @abstractmethod
    def service_name(self) -> str:
        """返回服务标识名称。"""
        ...

    @property
    def settings(self) -> AIServiceSettings:
        """获取当前服务配置。"""
        return self._settings

    @property
    def is_configured(self) -> bool:
        """检查服务是否已正确配置。"""
        return self._settings.is_configured()

    def generate_text(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        use_cache: bool = True,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成文本。

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            model: 模型名称，默认使用配置中的模型
            temperature: 温度参数，默认使用配置值
            max_tokens: 最大输出令牌数
            timeout: 请求超时时间（秒）
            use_cache: 是否使用缓存
            extra_params: 传给底层 LLM 的额外参数

        Returns:
            生成的文本内容

        Raises:
            AIAuthenticationError: API Key 无效
            AIRateLimitError: 请求频率过高
            AITimeoutError: 请求超时
            AIInvalidResponseError: 响应格式异常
            AIServiceError: 服务端错误
        """
        start_time = time.monotonic()
        effective_model = model or self._settings.model
        effective_temperature = temperature if temperature is not None else self._settings.temperature
        effective_max_tokens = max_tokens or self._settings.max_tokens
        effective_timeout = timeout or self._settings.timeout
        merged_extra = {**self._settings.extra_params, **(extra_params or {})}

        # 日志记录请求参数（脱敏）
        log_params = {
            "service": self.service_name,
            "model": effective_model,
            "temperature": effective_temperature,
            "max_tokens": effective_max_tokens,
            "timeout": effective_timeout,
            "prompt_length": len(prompt),
            "system_prompt_length": len(system_prompt) if system_prompt else 0,
            "use_cache": use_cache and self._enable_cache,
        }
        logger.info("[%s] generate_text request: %s", self.service_name, log_params)

        # 缓存命中检查
        if use_cache and self._enable_cache:
            cache_key = self._cache.make_key(
                self.service_name,
                effective_model,
                prompt,
                system_prompt=system_prompt,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
                extra_params=merged_extra or None,
            )
            cached_result = self._cache.get(cache_key)
            if cached_result is not None:
                elapsed = time.monotonic() - start_time
                logger.info(
                    "[%s] generate_text cache hit, elapsed=%.3fs",
                    self.service_name,
                    elapsed,
                )
                return cached_result
        else:
            cache_key = None

        try:
            # 限流保护 — 桶空时直接抛错，不调用 API
            if self._enable_rate_limiter:
                if not self._rate_limiter.acquire(self.service_name):
                    wait = self._rate_limiter.wait_time(self.service_name)
                    raise AIRateLimitError(
                        f"Rate limit exceeded for {self.service_name}, "
                        f"retry after {wait:.1f}s",
                        retry_after=wait,
                    )

            # 调用底层 LLM
            result = self._call_generate(
                prompt=prompt,
                system_prompt=system_prompt,
                model=effective_model,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
                timeout=effective_timeout,
                extra_params=merged_extra,
            )

            elapsed = time.monotonic() - start_time
            logger.info(
                "[%s] generate_text success, elapsed=%.3fs, output_length=%d",
                self.service_name,
                elapsed,
                len(result),
            )

            # 写入缓存
            if cache_key is not None and self._enable_cache:
                self._cache.set(cache_key, result)

            return result

        except AIError:
            # 已经是分类后的异常，直接向上传递
            elapsed = time.monotonic() - start_time
            logger.error(
                "[%s] generate_text failed after %.3fs",
                self.service_name,
                elapsed,
                exc_info=True,
            )
            raise

        except Exception as exc:
            # 未分类异常，分类后抛出
            elapsed = time.monotonic() - start_time
            logger.error(
                "[%s] generate_text failed after %.3fs",
                self.service_name,
                elapsed,
                exc_info=True,
            )
            raise classify_litellm_error(
                exc,
                service=self.service_name,
                model=effective_model,
            )

    @abstractmethod
    def _call_generate(
        self,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: float,
        extra_params: Dict[str, Any],
    ) -> str:
        """执行实际的 LLM 调用。

        子类必须实现此方法，封装对具体 LLM 服务的调用逻辑。
        """
        ...

    def embed_text(
        self,
        texts: List[str],
        *,
        model: Optional[str] = None,
    ) -> List[List[float]]:
        """文本嵌入（可选实现）。

        默认抛出 NotImplementedError。子类可重写以支持嵌入能力。

        Args:
            texts: 待嵌入的文本列表
            model: 嵌入模型名称

        Returns:
            嵌入向量列表
        """
        raise NotImplementedError(
            f"{self.service_name} does not support embed_text"
        )

    def check_connection(self) -> Dict[str, Any]:
        """检查服务连接状态。

        Returns:
            包含连接状态的字典：
              - ok: bool 是否连接成功
              - message: str 状态信息
              - service: str 服务名称
              - model: str 当前模型
        """
        if not self.is_configured:
            return {
                "ok": False,
                "message": "服务未配置（缺少 API Key 或未启用）",
                "service": self.service_name,
                "model": self._settings.model,
            }
        try:
            self.generate_text(
                "Respond with just the word 'ok'.",
                max_tokens=10,
                temperature=0.0,
                use_cache=False,
            )
            return {
                "ok": True,
                "message": "连接成功",
                "service": self.service_name,
                "model": self._settings.model,
            }
        except AIError as exc:
            return {
                "ok": False,
                "message": exc.user_message,
                "service": self.service_name,
                "model": self._settings.model,
            }
        except Exception as exc:
            return {
                "ok": False,
                "message": f"连接失败: {exc}",
                "service": self.service_name,
                "model": self._settings.model,
            }
