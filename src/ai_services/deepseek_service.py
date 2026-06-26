# -*- coding: utf-8 -*-
"""DeepSeek AI 服务实现。

基于 litellm 实现 DeepSeek API 的调用，支持：
  - 文本生成（generate_text）
  - 多模型版本选择（deepseek-chat, deepseek-v4-flash, deepseek-v4-pro 等）
  - 温度、最大令牌数等参数控制
  - 连接健康检查

DeepSeek API 文档: https://platform.deepseek.com/api-docs
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import litellm

from src.ai_services.base import BaseAIService
from src.ai_services.config import AIServiceSettings

logger = logging.getLogger(__name__)

# DeepSeek 支持的模型列表
DEEPSEEK_MODELS = [
    "deepseek-chat",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-reasoner",
]

# DeepSeek API 速率限制
DEEPSEEK_RATE_LIMIT_RPS = 30  # requests per second
DEEPSEEK_RATE_LIMIT_BURST = 60


class DeepSeekService(BaseAIService):
    """DeepSeek AI 服务。

    Usage:
        config = AIServiceConfig.from_env()
        service = DeepSeekService(config.deepseek)
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
        return "deepseek"

    @staticmethod
    def get_supported_models() -> List[str]:
        """获取支持的模型列表。"""
        return list(DEEPSEEK_MODELS)

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
        """调用 DeepSeek API 生成文本。

        使用 litellm 的 deepseek/ 前缀路由到 DeepSeek API。
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 构建调用参数
        kwargs: Dict[str, Any] = {
            "model": f"deepseek/{model}",
            "messages": messages,
            "timeout": timeout,
            "api_key": self._settings.api_key,
        }

        if temperature is not None:
            kwargs["temperature"] = temperature

        # DeepSeek 的默认 base_url
        if self._settings.base_url:
            kwargs["api_base"] = self._settings.base_url

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # 合并额外参数
        for key, value in extra_params.items():
            if key not in kwargs:
                kwargs[key] = value

        logger.debug(
            "[DeepSeek] Calling model=%s, temperature=%s, max_tokens=%s, timeout=%s",
            model,
            temperature,
            max_tokens,
            timeout,
        )

        response = litellm.completion(**kwargs)

        # 提取生成的文本
        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise ValueError("DeepSeek API returned empty choices")

        content = choice.message.content
        if content is None:
            raise ValueError("DeepSeek API returned empty message content")

        return str(content)
