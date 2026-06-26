# -*- coding: utf-8 -*-
"""DeepSeek AI 服务测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ai_services.config import (
    AIServiceSettings,
    DEEPSEEK_DEFAULT_BASE_URL,
    DEEPSEEK_DEFAULT_MODEL,
)
from src.ai_services.deepseek_service import (
    DEEPSEEK_MODELS,
    DEEPSEEK_RATE_LIMIT_BURST,
    DEEPSEEK_RATE_LIMIT_RPS,
    DeepSeekService,
)
from src.ai_services.errors import (
    AIAuthenticationError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServiceError,
    AITimeoutError,
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


class TestDeepSeekService:
    """测试 DeepSeekService。"""

    def test_service_name(self) -> None:
        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        assert service.service_name == "deepseek"

    def test_get_supported_models(self) -> None:
        models = DeepSeekService.get_supported_models()
        assert len(models) > 0
        assert "deepseek-chat" in models
        assert "deepseek-v4-flash" in models
        assert all(m in DEEPSEEK_MODELS for m in models)

    def test_default_constructor(self) -> None:
        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
        )
        assert service.is_configured is True

    def test_models_constant(self) -> None:
        assert "deepseek-chat" in DEEPSEEK_MODELS
        assert "deepseek-v4-flash" in DEEPSEEK_MODELS
        assert "deepseek-v4-pro" in DEEPSEEK_MODELS
        assert len(DEEPSEEK_MODELS) >= 3

    def test_rate_limit_constants(self) -> None:
        assert DEEPSEEK_RATE_LIMIT_RPS > 0
        assert DEEPSEEK_RATE_LIMIT_BURST > 0

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_success(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.return_value = MockResponse("Hello from DeepSeek")

        service = DeepSeekService(
            AIServiceSettings(
                enabled=True,
                api_key="sk-test-key",
                model="deepseek-chat",
            ),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        result = service.generate_text("Hello", use_cache=False)
        assert result == "Hello from DeepSeek"

        # 验证 litellm.completion 被正确调用
        mock_litellm.completion.assert_called_once()
        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs["model"] == "deepseek/deepseek-chat"
        assert call_kwargs["api_key"] == "sk-test-key"
        assert call_kwargs["messages"][0]["role"] == "user"
        assert call_kwargs["messages"][0]["content"] == "Hello"

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_with_system_prompt(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.return_value = MockResponse("response")

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text(
            "Hello",
            system_prompt="You are a helpful assistant",
            use_cache=False,
        )

        call_kwargs = mock_litellm.completion.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant"
        assert messages[1]["role"] == "user"

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_with_custom_params(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.return_value = MockResponse("response")

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text(
            "Hello",
            model="deepseek-v4-flash",
            temperature=0.5,
            max_tokens=2048,
            timeout=60.0,
            use_cache=False,
        )

        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs["model"] == "deepseek/deepseek-v4-flash"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 2048
        assert call_kwargs["timeout"] == 60.0

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_with_base_url(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.return_value = MockResponse("response")

        service = DeepSeekService(
            AIServiceSettings(
                enabled=True,
                api_key="sk-test",
                base_url="https://custom.deepseek.com/v1",
            ),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text("Hello", use_cache=False)

        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs["api_base"] == "https://custom.deepseek.com/v1"

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_with_extra_params(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.return_value = MockResponse("response")

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        service.generate_text(
            "Hello",
            use_cache=False,
            extra_params={"top_p": 0.9, "stop": ["END"]},
        )

        call_kwargs = mock_litellm.completion.call_args[1]
        assert call_kwargs["top_p"] == 0.9
        assert call_kwargs["stop"] == ["END"]

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_empty_choices(self, mock_litellm: MagicMock) -> None:
        """空 choices 应抛出错误。"""
        mock_response = MagicMock()
        mock_response.choices = []
        mock_litellm.completion.return_value = mock_response

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIInvalidResponseError):
            service.generate_text("Hello", use_cache=False)

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_empty_content(self, mock_litellm: MagicMock) -> None:
        """空 content 应抛出错误。"""
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_response.choices = [mock_choice]
        mock_litellm.completion.return_value = mock_response

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIInvalidResponseError):
            service.generate_text("Hello", use_cache=False)

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_authentication_error(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.side_effect = Exception("Authentication failed: 401")

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="invalid-key"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIAuthenticationError):
            service.generate_text("Hello", use_cache=False)

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_rate_limit_error(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.side_effect = Exception("Rate limit exceeded: 429")

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIRateLimitError):
            service.generate_text("Hello", use_cache=False)

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_timeout_error(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.side_effect = Exception("Connection timed out")

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AITimeoutError):
            service.generate_text("Hello", use_cache=False)

    @patch("src.ai_services.deepseek_service.litellm")
    def test_generate_text_server_error(self, mock_litellm: MagicMock) -> None:
        mock_litellm.completion.side_effect = Exception("HTTP 500 Internal Server Error")

        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        with pytest.raises(AIServiceError):
            service.generate_text("Hello", use_cache=False)

    def test_generate_text_missing_litellm(self) -> None:
        """litellm 已安装，此测试仅验证服务可正常创建。"""
        # litellm is installed at module level now
        service = DeepSeekService(
            AIServiceSettings(enabled=True, api_key="sk-test"),
            enable_cache=False,
            enable_rate_limiter=False,
        )
        assert service.is_configured is True

    def test_check_connection_not_configured(self) -> None:
        service = DeepSeekService(
            AIServiceSettings(enabled=False, api_key=""),
        )
        result = service.check_connection()
        assert result["ok"] is False

    def test_default_settings_from_config(self) -> None:
        settings = AIServiceSettings(
            enabled=True,
            api_key="sk-test",
            base_url=DEEPSEEK_DEFAULT_BASE_URL,
            model=DEEPSEEK_DEFAULT_MODEL,
        )
        service = DeepSeekService(settings)
        assert service.settings.base_url == DEEPSEEK_DEFAULT_BASE_URL
        assert service.settings.model == DEEPSEEK_DEFAULT_MODEL
