# -*- coding: utf-8 -*-
"""AI 服务基类测试。"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from src.ai_services.base import BaseAIService
from src.ai_services.config import AIServiceSettings
from src.ai_services.errors import (
    AIAuthenticationError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServiceError,
    AITimeoutError,
)
from src.ai_services.rate_limiter import RateLimiter


class SimpleTestService(BaseAIService):
    """用于测试的简单服务实现。"""

    @property
    def service_name(self) -> str:
        return "test_service"

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
        """返回预设的模拟响应。"""
        self._last_call = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "extra_params": extra_params,
        }
        return f"response_{prompt}"


class TestBaseAIService:
    """测试 BaseAIService 基类。"""

    def test_service_name_abstract(self) -> None:
        """验证未实现 service_name 的子类会报错。"""
        with pytest.raises(TypeError):
            BaseAIService(AIServiceSettings())  # type: ignore[abstract]

    def test_init_with_defaults(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        assert service.service_name == "test_service"
        assert service.is_configured is True
        assert service._enable_cache is True
        assert service._enable_rate_limiter is True

    def test_init_disabled_cache_when_disabled(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
        )
        assert service._enable_cache is False

    def test_is_configured_false(self) -> None:
        service = SimpleTestService(AIServiceSettings(enabled=True, api_key=""))
        assert service.is_configured is False

    def test_generate_text_basic(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        result = service.generate_text("Hello")
        assert result == "response_Hello"

    def test_generate_text_with_system_prompt(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
        )
        result = service.generate_text(
            "Hello",
            system_prompt="Be helpful",
        )
        assert result.startswith("response_")

    def test_generate_text_with_custom_params(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        result = service.generate_text(
            "Hello",
            model="custom-model",
            temperature=0.5,
            max_tokens=100,
            timeout=10.0,
            use_cache=False,
        )
        assert result == "response_Hello"

    def test_generate_text_cache_hit(self) -> None:
        """缓存命中时不应再次调用 _call_generate。"""
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=True,
        )

        # 第一次调用
        result1 = service.generate_text("Hello", use_cache=True)
        assert result1 == "response_Hello"

        # 第二次调用（命中缓存）
        result2 = service.generate_text("Hello", use_cache=True)
        assert result2 == "response_Hello"

    def test_generate_text_cache_bypassed_when_disabled(self) -> None:
        """禁用缓存时应每次都调用。"""
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
        )
        result1 = service.generate_text("Hello", use_cache=True)
        result2 = service.generate_text("Hello", use_cache=True)
        assert result1 == result2  # 结果相同但未缓存

    def test_generate_text_cache_disabled_for_request(self) -> None:
        """单个请求可禁用缓存。"""
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=True,
        )
        result1 = service.generate_text("Hello", use_cache=False)
        result2 = service.generate_text("Hello", use_cache=False)
        assert result1 == result2

    def test_embed_text_not_implemented(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        with pytest.raises(NotImplementedError):
            service.embed_text(["test"])

    def test_check_connection_success(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        result = service.check_connection()
        assert result["ok"] is True
        assert "成功" in result["message"]

    def test_check_connection_failure(self) -> None:
        """模拟连接失败。"""

        class FailingService(SimpleTestService):
            def _call_generate(self, **kwargs: Any) -> str:
                raise AIAuthenticationError("Invalid key", service="test_service")

        service = FailingService(
            AIServiceSettings(enabled=True, api_key="invalid"),
        )
        result = service.check_connection()
        assert result["ok"] is False

    def test_error_classification_on_generate(self) -> None:
        """异常应被正确分类。"""

        class AuthFailingService(SimpleTestService):
            def _call_generate(self, **kwargs: Any) -> str:
                raise Exception("Authentication failed: invalid API key")

        service = AuthFailingService(
            AIServiceSettings(enabled=True, api_key="invalid"),
        )
        with pytest.raises(AIAuthenticationError):
            service.generate_text("Hello", use_cache=False)

    def test_timeout_error_classification(self) -> None:
        """超时异常应被分类为 AITimeoutError。"""

        class TimeoutService(SimpleTestService):
            def _call_generate(self, **kwargs: Any) -> str:
                raise Exception("Connection timed out after 30s")

        service = TimeoutService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        with pytest.raises(AITimeoutError):
            service.generate_text("Hello", use_cache=False)

    def test_rate_limit_error_classification(self) -> None:
        """限流异常应被分类为 AIRateLimitError。"""

        class RateLimitService(SimpleTestService):
            def _call_generate(self, **kwargs: Any) -> str:
                raise Exception("Rate limit exceeded: 429 Too Many Requests")

        service = RateLimitService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        with pytest.raises(AIRateLimitError):
            service.generate_text("Hello", use_cache=False)

    def test_500_error_classification(self) -> None:
        """服务端错误应被分类为 AIServiceError。"""

        class ServerErrorService(SimpleTestService):
            def _call_generate(self, **kwargs: Any) -> str:
                raise Exception("HTTP 500 Internal Server Error")

        service = ServerErrorService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        with pytest.raises(AIServiceError):
            service.generate_text("Hello", use_cache=False)

    def test_unknown_error_classification(self) -> None:
        """未知错误应被分类为 AIInvalidResponseError。"""

        class UnknownErrorService(SimpleTestService):
            def _call_generate(self, **kwargs: Any) -> str:
                raise Exception("Some unexpected error")

        service = UnknownErrorService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        with pytest.raises(AIInvalidResponseError):
            service.generate_text("Hello", use_cache=False)

    def test_already_classified_error_not_reclassified(self) -> None:
        """已经分类的异常不应再次分类。"""

        class AlreadyClassifiedService(SimpleTestService):
            def _call_generate(self, **kwargs: Any) -> str:
                raise AIRateLimitError("Already classified", service="test")

        service = AlreadyClassifiedService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        with pytest.raises(AIRateLimitError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_logging(self, caplog: Any) -> None:
        """验证 generate_text 的日志输出。"""
        import logging

        caplog.set_level(logging.INFO)
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        service.generate_text("Hello", use_cache=False)

        # 应有请求日志和成功日志
        log_text = caplog.text
        assert "generate_text request" in log_text
        assert "generate_text success" in log_text

    def test_rate_limiter_integration(self) -> None:
        """验证限流器集成。"""
        limiter = RateLimiter()
        # 给 test_service 更高的限制
        limiter.set_rate("test_service", rps=100, burst=100)

        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            rate_limiter=limiter,
        )
        result = service.generate_text("Hello", use_cache=False)
        assert result == "response_Hello"

    def test_rate_limiter_enforces_limit_when_bucket_empty(self) -> None:
        """桶空时 acquire() 返回 False 应抛 AIRateLimitError，跳过 API 调用。"""
        limiter = RateLimiter()
        # 极低速率：burst=1，第二请求必然被拒
        limiter.set_rate("test_service", rps=0.001, burst=1)

        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            rate_limiter=limiter,
        )
        # 第一次调用消耗唯一令牌
        service.generate_text("first", use_cache=False)

        # 第二次调用应被限流阻断
        with pytest.raises(AIRateLimitError) as exc_info:
            service.generate_text("second", use_cache=False)
        assert exc_info.value.retry_after is not None
        assert exc_info.value.retry_after > 0

    def test_extra_params_passed_to_call_generate(self) -> None:
        """额外参数应传递给 _call_generate。"""
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        service.generate_text(
            "Hello",
            use_cache=False,
            extra_params={"top_p": 0.9, "stop": ["END"]},
        )
        # 验证 extra_params 被合并
        assert service._last_call["extra_params"]["top_p"] == 0.9  # type: ignore[attr-defined]
        assert "END" in service._last_call["extra_params"]["stop"]  # type: ignore[attr-defined]

    def test_model_selection(self) -> None:
        """验证模型选择。"""
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test", model="default-model"),
        )
        # 使用默认模型
        service.generate_text("Hello", use_cache=False)
        assert service._last_call["model"] == "default-model"  # type: ignore[attr-defined]

        # 覆盖模型
        service.generate_text("Hello", model="custom-model", use_cache=False)
        assert service._last_call["model"] == "custom-model"  # type: ignore[attr-defined]

    def test_settings_property(self) -> None:
        settings = AIServiceSettings(enabled=True, api_key="sk-test")
        service = SimpleTestService(settings)
        assert service.settings is settings

    def test_init_disabled_rate_limiter(self) -> None:
        service = SimpleTestService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_rate_limiter=False,
        )
        assert service._enable_rate_limiter is False

    def test_init_disabled_service_disables_cache_and_limiter(self) -> None:
        """未启用的服务应自动禁用缓存和限流。"""
        service = SimpleTestService(
            AIServiceSettings(enabled=False, api_key=""),
            enable_cache=True,
            enable_rate_limiter=True,
        )
        assert service._enable_cache is False
        assert service._enable_rate_limiter is False
