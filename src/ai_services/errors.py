# -*- coding: utf-8 -*-
"""AI 服务异常定义与错误分类。

提供层次化的异常类型，覆盖认证、限流、超时、无效响应等场景。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class AIError(Exception):
    """AI 服务基类异常。"""

    def __init__(
        self,
        message: str,
        *,
        service: str = "",
        model: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.service = service
        self.model = model
        self.details = details or {}
        super().__init__(message)

    @property
    def user_message(self) -> str:
        """返回面向终端用户的友好提示。"""
        return str(self.args[0]) if self.args else "AI 服务发生未知错误"


class AIServiceError(AIError):
    """AI 服务内部错误（服务端错误如 500）。"""

    @property
    def user_message(self) -> str:
        service = self.service or "AI 服务"
        return f"{service} 服务暂时不可用，请稍后重试"


class AIAuthenticationError(AIError):
    """认证错误（API Key 无效、权限不足等）。"""

    def __init__(
        self,
        message: str,
        *,
        service: str = "",
        model: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, service=service, model=model, details=details)

    @property
    def user_message(self) -> str:
        service = self.service or "AI 服务"
        return f"{service} API Key 配置错误或已失效，请在设置中检查并更新"


class AIRateLimitError(AIError):
    """API 限流错误（请求频率过高或配额耗尽）。"""

    def __init__(
        self,
        message: str,
        *,
        service: str = "",
        model: str = "",
        retry_after: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, service=service, model=model, details=details)

    @property
    def user_message(self) -> str:
        service = self.service or "AI 服务"
        if self.retry_after:
            return f"{service} 请求频率过高，请在 {self.retry_after:.0f} 秒后重试"
        return f"{service} 请求已达频率限制，请稍后重试"


class AITimeoutError(AIError):
    """请求超时错误。"""

    def __init__(
        self,
        message: str,
        *,
        service: str = "",
        model: str = "",
        timeout: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.timeout = timeout
        super().__init__(message, service=service, model=model, details=details)

    @property
    def user_message(self) -> str:
        service = self.service or "AI 服务"
        if self.timeout:
            return f"{service} 请求超时（{self.timeout:.0f}秒），请检查网络连接或增加超时时间"
        return f"{service} 请求超时，请检查网络连接"


class AIInvalidResponseError(AIError):
    """无效响应错误（响应格式异常、内容为空等）。"""

    def __init__(
        self,
        message: str,
        *,
        service: str = "",
        model: str = "",
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message, service=service, model=model, details=details)

    @property
    def user_message(self) -> str:
        service = self.service or "AI 服务"
        if self.status_code:
            return f"{service} 返回异常状态码 {self.status_code}，请检查配置"
        return f"{service} 返回数据格式异常"


def classify_litellm_error(
    exc: Exception,
    *,
    service: str = "",
    model: str = "",
) -> AIError:
    """将 LiteLLM / OpenAI 异常分类为业务异常。"""
    exc_str = str(exc).lower()
    exc_repr = repr(exc).lower()

    # 认证错误
    if any(
        marker in exc_str or marker in exc_repr
        for marker in (
            "authentication",
            "unauthorized",
            "401",
            "403",
            "invalid_api_key",
            "auth",
            "permission",
            "credential",
        )
    ):
        return AIAuthenticationError(
            str(exc),
            service=service,
            model=model,
            details={"original_error": repr(exc)},
        )

    # 限流错误
    if any(
        marker in exc_str or marker in exc_repr
        for marker in (
            "rate limit",
            "rate_limit",
            "429",
            "too many",
            "quota",
            "insufficient_quota",
        )
    ):
        retry_after = None
        if hasattr(exc, "response") and hasattr(exc.response, "headers"):
            retry_after = exc.response.headers.get("retry-after")
            if retry_after:
                try:
                    retry_after = float(retry_after)
                except (ValueError, TypeError):
                    retry_after = None
        return AIRateLimitError(
            str(exc),
            service=service,
            model=model,
            retry_after=retry_after,
            details={"original_error": repr(exc)},
        )

    # 超时错误
    if any(
        marker in exc_str or marker in exc_repr
        for marker in ("timeout", "timed out", "connection error", "connection")
    ):
        return AITimeoutError(
            str(exc),
            service=service,
            model=model,
            details={"original_error": repr(exc)},
        )

    # 服务端错误
    if any(
        marker in exc_str or marker in exc_repr
        for marker in ("500", "502", "503", "service unavailable", "server error")
    ):
        return AIServiceError(
            str(exc),
            service=service,
            model=model,
            details={"original_error": repr(exc)},
        )

    # 默认归类为无效响应
    return AIInvalidResponseError(
        str(exc),
        service=service,
        model=model,
        details={"original_error": repr(exc)},
    )
