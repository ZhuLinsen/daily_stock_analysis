# -*- coding: utf-8 -*-
"""红蝶AI 服务测试。"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import litellm
import pytest

from src.ai_services.config import (
    AIServiceSettings,
    HONGDIE_DEFAULT_BASE_URL,
    HONGDIE_DEFAULT_MODEL,
)
from src.ai_services.errors import (
    AIAuthenticationError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServiceError,
    AITimeoutError,
)
from src.ai_services.hongdie_service import (
    HONGDIE_MODELS,
    HONGDIE_RATE_LIMIT_BURST,
    HONGDIE_RATE_LIMIT_RPS,
    HongdieService,
)


class MockMessage:
    """模拟 litellm 返回的 message 对象。"""

    def __init__(self, content: str) -> None:
        self.content = content


class MockChoice:
    """模拟 litellm 返回的 choice 对象。"""

    def __init__(self, content: str) -> None:
        self.message = MockMessage(content)


class MockResponse:
    """模拟 litellm 返回的 response 对象。"""

    def __init__(self, content: str = "test_response") -> None:
        self.choices = [MockChoice(content)]


class TestHongdieService:
    """测试 HongdieService。"""

    def _make_service(self, **overrides: Any) -> HongdieService:
        """创建测试用服务实例（禁用缓存和限流）。"""
        settings = AIServiceSettings(enabled=True, api_key="sk-test", **overrides)
        return HongdieService(
            settings,
            enable_cache=False,
            enable_rate_limiter=False,
        )

    @pytest.fixture(autouse=True)
    def _mock_litellm_completion(self) -> None:
        """每个测试前 mock litellm.completion。

        将 litellm.completion 替换为一个 MagicMock（self._mock），
        测试方法中通过 self._mock.return_value / self._mock.side_effect
        来控制模拟行为。
        """
        self._mock = MagicMock()
        original_completion = litellm.completion
        litellm.completion = self._mock

        yield

        litellm.completion = original_completion

    def test_service_name(self) -> None:
        service = self._make_service()
        assert service.service_name == "hongdie"

    def test_get_default_base_url(self) -> None:
        assert HongdieService.get_default_base_url() == "https://tokento.vip/v1"

    def test_get_supported_models(self) -> None:
        models = HongdieService.get_supported_models()
        assert len(models) > 0
        assert "gpt-4o-mini" in models
        assert "gpt-4o" in models
        assert all(m in HONGDIE_MODELS for m in models)

    def test_default_constructor(self) -> None:
        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        assert service.is_configured is True

    def test_models_constant(self) -> None:
        assert "gpt-4o-mini" in HONGDIE_MODELS
        assert "gpt-4o" in HONGDIE_MODELS
        assert len(HONGDIE_MODELS) >= 3

    def test_rate_limit_constants(self) -> None:
        assert HONGDIE_RATE_LIMIT_RPS > 0
        assert HONGDIE_RATE_LIMIT_BURST > 0

    def test_generate_text_success(self) -> None:
        self._mock.return_value = MockResponse("Hello from Hongdie")

        service = HongdieService(
            AIServiceSettings(
                enabled=True,
                api_key="sk-hongdie-key",
                base_url="https://tokento.vip/v1",
                model="gpt-4o-mini",
            ),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        result = service.generate_text("Hello", use_cache=False)
        assert result == "Hello from Hongdie"

        # 验证 litellm.completion 被正确调用
        self._mock.assert_called_once()
        call_kwargs = self._mock.call_args[1]
        assert call_kwargs["model"] == "openai/gpt-4o-mini"
        assert call_kwargs["api_key"] == "sk-hongdie-key"
        assert call_kwargs["api_base"] == "https://tokento.vip/v1"
        assert call_kwargs["messages"][0]["role"] == "user"
        assert call_kwargs["messages"][0]["content"] == "Hello"

    def test_generate_text_uses_default_base_url_when_empty(self) -> None:
        """base_url 为空时应使用默认地址。"""
        self._mock.return_value = MockResponse("response")

        service = HongdieService(
            AIServiceSettings(
                enabled=True,
                api_key="sk-test",
                base_url="",  # 空 base_url
            ),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text("Hello", use_cache=False)

        call_kwargs = self._mock.call_args[1]
        assert call_kwargs["api_base"] == "https://tokento.vip/v1"

    def test_generate_text_with_system_prompt(self) -> None:
        self._mock.return_value = MockResponse("response")

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text(
            "Hello",
            system_prompt="You are helpful",
            use_cache=False,
        )

        call_kwargs = self._mock.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_generate_text_with_custom_params(self) -> None:
        self._mock.return_value = MockResponse("response")

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text(
            "Hello",
            model="gpt-4o",
            temperature=0.3,
            max_tokens=1024,
            timeout=45.0,
            use_cache=False,
        )

        call_kwargs = self._mock.call_args[1]
        assert call_kwargs["model"] == "openai/gpt-4o"
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["max_tokens"] == 1024
        assert call_kwargs["timeout"] == 45.0

    def test_generate_text_with_extra_params(self) -> None:
        self._mock.return_value = MockResponse("response")

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text(
            "Hello",
            use_cache=False,
            extra_params={"top_p": 0.9},
        )

        call_kwargs = self._mock.call_args[1]
        assert call_kwargs["top_p"] == 0.9

    def test_generate_text_empty_choices(self) -> None:
        """空 choices 应抛出错误。"""
        mock_response = MagicMock()
        mock_response.choices = []
        self._mock.return_value = mock_response

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIInvalidResponseError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_empty_content(self) -> None:
        """空 content 应抛出错误。"""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_response.choices = [mock_choice]
        self._mock.return_value = mock_response

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIInvalidResponseError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_authentication_error(self) -> None:
        self._mock.side_effect = Exception("Authentication failed: 401")

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="invalid-key"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIAuthenticationError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_rate_limit_error(self) -> None:
        self._mock.side_effect = Exception("Rate limit exceeded: 429")

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIRateLimitError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_timeout_error(self) -> None:
        self._mock.side_effect = Exception("Connection timed out")

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AITimeoutError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_server_error(self) -> None:
        self._mock.side_effect = Exception("HTTP 500 Server Error")

        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIServiceError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_missing_litellm(self) -> None:
        """litellm 已安装，此测试仅验证服务可正常创建。"""
        service = HongdieService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        assert service.is_configured is True

    def test_check_connection_not_configured(self) -> None:
        service = HongdieService(
            AIServiceSettings(enabled=False, api_key=""),
        )
        result = service.check_connection()
        assert result["ok"] is False

    def test_default_settings_from_config(self) -> None:
        settings = AIServiceSettings(
            enabled=True,
            api_key="sk-test",
            base_url=HONGDIE_DEFAULT_BASE_URL,
            model=HONGDIE_DEFAULT_MODEL,
        )
        service = HongdieService(settings)
        assert service.settings.base_url == HONGDIE_DEFAULT_BASE_URL
        assert service.settings.model == HONGDIE_DEFAULT_MODEL
