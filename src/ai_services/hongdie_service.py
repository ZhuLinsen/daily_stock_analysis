# -*- coding: utf-8 -*-
"""红蝶AI (Hongdie AI) 服务实现。

基于 OpenAI-compatible API 规范实现，使用 litellm 作为底层调用网关。
红蝶AI 提供兼容 OpenAI Chat Completions 格式的 API 接口。

默认地址: https://tokento.vip/v1
官网: https://tokento.vip
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import litellm

from src.ai_services.base import BaseAIService
from src.ai_services.config import (
    AIServiceSettings,
    HONGDIE_DEFAULT_BASE_URL,
)

logger = logging.getLogger(__name__)

# 红蝶AI 推荐的模型列表
HONGDIE_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "claude-sonnet-4",
    "gemini-2.0-flash",
    "deepseek-v3",
]

# 红蝶AI 速率限制（OpenAI-compatible 代理的典型限制）
HONGDIE_RATE_LIMIT_RPS = 10
HONGDIE_RATE_LIMIT_BURST = 20


class HongdieService(BaseAIService):
    """红蝶AI 服务。

    红蝶AI 提供 OpenAI-compatible API 代理服务，支持
    GPT、Claude、Gemini、DeepSeek 等多种主流模型。

    Usage:
        config = AIServiceConfig.from_env()
        service = HongdieService(config.hongdie)
        result = service.generate_text("Hello", system_prompt="Be helpful")
    """

    def __init__(
        self,
        settings: AIServiceSettings,
        **kwargs: Any,
    ) -> None:
        super().__init__(settings, **kwargs)

    @property
    def service_name(self) -> str:
        return "hongdie"

    @staticmethod
    def get_default_base_url() -> str:
        """获取默认 API 基础地址。"""
        return HONGDIE_DEFAULT_BASE_URL

    @staticmethod
    def get_supported_models() -> List[str]:
        """获取推荐模型列表（实际可用模型以红蝶AI官网为准）。"""
        return list(HONGDIE_MODELS)

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
        """调用红蝶AI API 生成文本。

        红蝶AI 使用 OpenAI-compatible API，通过 litellm 的
        openai/ 前缀 + 自定义 api_base 进行路由。
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 构建调用参数
        kwargs: Dict[str, Any] = {
            "model": f"openai/{model}",
            "messages": messages,
            "timeout": timeout,
            "api_key": self._settings.api_key,
            "api_base": self._settings.base_url or HONGDIE_DEFAULT_BASE_URL,
        }

        if temperature is not None:
            kwargs["temperature"] = temperature

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # 合并额外参数
        for key, value in extra_params.items():
            if key not in kwargs:
                kwargs[key] = value

        logger.debug(
            "[Hongdie] Calling model=%s via %s, temperature=%s, max_tokens=%s, timeout=%s",
            model,
            self._settings.base_url or HONGDIE_DEFAULT_BASE_URL,
            temperature,
            max_tokens,
            timeout,
        )

        response = litellm.completion(**kwargs)

        # 提取生成的文本
        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise ValueError("Hongdie API returned empty choices")

        content = choice.message.content
        if content is None:
            raise ValueError("Hongdie API returned empty message content")

        return str(content)
