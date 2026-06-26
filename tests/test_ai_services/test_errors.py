# -*- coding: utf-8 -*-
"""AI 服务异常模块测试。"""

from __future__ import annotations

from src.ai_services.errors import (
    AIAuthenticationError,
    AIError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServiceError,
    AITimeoutError,
    classify_litellm_error,
)


class TestAIError:
    """测试 AIError 基类。"""

    def test_basic_error(self) -> None:
        error = AIError("something went wrong")
        assert str(error) == "something went wrong"
        assert error.service == ""
        assert error.model == ""
        assert error.details == {}
        assert error.user_message == "something went wrong"

    def test_error_with_service(self) -> None:
        error = AIError(
            "error",
            service="deepseek",
            model="deepseek-chat",
            details={"status": 500},
        )
        assert error.service == "deepseek"
        assert error.model == "deepseek-chat"
        assert error.details == {"status": 500}

    def test_empty_message(self) -> None:
        error = AIError("")
        assert error.user_message == ""

    def test_user_message_default(self) -> None:
        # Test when no args passed to the base class
        # Since AIError requires message, we test the fallback in user_message property
        error = AIError("test")
        assert error.user_message == "test"


class TestAIAuthenticationError:
    """测试认证错误。"""

    def test_auth_error_creation(self) -> None:
        error = AIAuthenticationError(
            "Invalid API key",
            service="deepseek",
            model="deepseek-chat",
        )
        assert "API Key" in error.user_message
        assert "deepseek" in error.user_message or "AI 服务" in error.user_message
        assert error.service == "deepseek"

    def test_auth_error_default_service(self) -> None:
        error = AIAuthenticationError("Invalid key")
        assert "API Key" in error.user_message

    def test_user_message_format(self) -> None:
        error = AIAuthenticationError("Invalid key", service="deepseek")
        msg = error.user_message
        assert "deepseek" in msg
        assert "API Key" in msg


class TestAIRateLimitError:
    """测试限流错误。"""

    def test_rate_limit_without_retry_after(self) -> None:
        error = AIRateLimitError("Rate limited")
        assert error.retry_after is None
        assert "频率限制" in error.user_message

    def test_rate_limit_with_retry_after(self) -> None:
        error = AIRateLimitError("Rate limited", retry_after=30.0)
        assert error.retry_after == 30.0
        assert "30" in error.user_message
        assert "秒" in error.user_message

    def test_rate_limit_with_service(self) -> None:
        error = AIRateLimitError("Rate limited", service="deepseek", retry_after=10.0)
        assert "deepseek" in error.user_message
        assert "10" in error.user_message


class TestAITimeoutError:
    """测试超时错误。"""

    def test_timeout_without_timeout_value(self) -> None:
        error = AITimeoutError("Request timed out", service="deepseek")
        assert error.timeout is None
        assert "超时" in error.user_message

    def test_timeout_with_timeout_value(self) -> None:
        error = AITimeoutError("Timed out", service="deepseek", timeout=30.0)
        assert error.timeout == 30.0
        assert "30" in error.user_message

    def test_timeout_message(self) -> None:
        error = AITimeoutError("Timed out")
        assert "超时" in error.user_message


class TestAIInvalidResponseError:
    """测试无效响应错误。"""

    def test_invalid_response_basic(self) -> None:
        error = AIInvalidResponseError("Bad response")
        assert "格式异常" in error.user_message or "异常" in error.user_message

    def test_invalid_response_with_status(self) -> None:
        error = AIInvalidResponseError(
            "Bad response",
            status_code=502,
        )
        assert "502" in error.user_message
        assert error.status_code == 502

    def test_invalid_response_with_body(self) -> None:
        error = AIInvalidResponseError(
            "Bad response",
            status_code=400,
            response_body='{"error":"bad request"}',
        )
        assert error.status_code == 400
        assert error.response_body is not None

    def test_user_message_with_service(self) -> None:
        error = AIInvalidResponseError(
            "Bad response",
            service="deepseek",
            status_code=502,
        )
        msg = error.user_message
        assert "deepseek" in msg
        assert "502" in msg


class TestAIServiceError:
    """测试服务端错误。"""

    def test_service_error(self) -> None:
        error = AIServiceError("Server error", service="deepseek")
        assert "不可用" in error.user_message or "稍后重试" in error.user_message

    def test_service_error_default(self) -> None:
        error = AIServiceError("Server error")
        assert "AI 服务" in error.user_message


class MockResponse:
    """模拟 HTTP 响应对象。"""

    def __init__(self, headers: dict) -> None:
        self.headers = headers


class TestClassifyLitellmError:
    """测试 LiteLLM 异常分类。"""

    def test_classify_authentication_error(self) -> None:
        exc = Exception("Authentication failed: invalid API key")
        result = classify_litellm_error(exc, service="deepseek", model="deepseek-chat")
        assert isinstance(result, AIAuthenticationError)
        assert result.service == "deepseek"

    def test_classify_401_error(self) -> None:
        exc = Exception("HTTP 401 Unauthorized")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AIAuthenticationError)

    def test_classify_rate_limit(self) -> None:
        exc = Exception("Rate limit exceeded: 429 Too Many Requests")
        result = classify_litellm_error(exc, service="hongdie")
        assert isinstance(result, AIRateLimitError)
        assert result.service == "hongdie"

    def test_classify_rate_limit_with_retry_header(self) -> None:
        # 模拟带 retry-after header 的限流错误
        class RateLimitException(Exception):
            def __init__(self) -> None:
                self.response = MockResponse({"retry-after": "30"})
                super().__init__("429 Too Many Requests")

        exc = RateLimitException()
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AIRateLimitError)
        assert result.retry_after == 30.0

    def test_classify_timeout(self) -> None:
        exc = Exception("Connection timed out after 30s")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AITimeoutError)

    def test_classify_connection_error(self) -> None:
        exc = Exception("Connection refused")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AITimeoutError)

    def test_classify_500_error(self) -> None:
        exc = Exception("HTTP 500 Internal Server Error")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AIServiceError)

    def test_classify_503_error(self) -> None:
        exc = Exception("Service Unavailable: 503")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AIServiceError)

    def test_classify_generic_error(self) -> None:
        exc = Exception("Some unknown error occurred")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AIInvalidResponseError)

    def test_classify_empty_service(self) -> None:
        exc = Exception("unknown error")
        result = classify_litellm_error(exc)
        assert isinstance(result, AIInvalidResponseError)
        assert result.service == ""

    def test_classify_auth_lowercase(self) -> None:
        """测试大小写不敏感的认证错误匹配。"""
        exc = Exception("AUTHENTICATION_ERROR: invalid credentials")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AIAuthenticationError)

    def test_classify_quota_error(self) -> None:
        exc = Exception("insufficient_quota: you have exceeded your quota")
        result = classify_litellm_error(exc, service="deepseek")
        assert isinstance(result, AIRateLimitError)
