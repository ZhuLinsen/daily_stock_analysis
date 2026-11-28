# -*- coding: utf-8 -*-
"""
===================================
全局异常处理中间件
===================================

职责：
1. 捕获未处理的异常
2. 统一错误响应格式
3. 记录错误日志
"""

import logging
import math
import traceback
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    全局异常处理中间件
    
    捕获所有未处理的异常，返回统一格式的错误响应
    """
    
    async def dispatch(
        self, 
        request: Request, 
        call_next: Callable
    ) -> Response:
        """
        处理请求，捕获异常
        
        Args:
            request: 请求对象
            call_next: 下一个处理器
            
        Returns:
            Response: 响应对象
        """
        try:
            response = await call_next(request)
            return response
            
        except Exception as e:
            # 记录错误日志
            logger.error(
                f"Unhandled exception: {e}\n"
                f"Request path: {request.url.path}\n"
                f"Request method: {request.method}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            
            # 返回统一格式的错误响应
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "message": "服务器内部错误，请稍后重试",
                    "detail": str(e) if logger.isEnabledFor(logging.DEBUG) else None
                }
            )


_SENSITIVE_VALIDATION_FIELD_MARKERS = (
    "api_key",
    "api_keys",
    "extra_headers",
    "headers",
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "credential",
    "hmac",
)


def _is_sensitive_validation_location(loc: Any, request_path: str) -> bool:
    parts = [str(part).lower() for part in (loc if isinstance(loc, (list, tuple)) else ())]
    if any(any(marker in part for marker in _SENSITIVE_VALIDATION_FIELD_MARKERS) for part in parts):
        return True
    lower_path = (request_path or "").lower()
    if lower_path.startswith(("/api/v1/system/config", "/api/v1/auth")):
        if any(part in {"items", "content", "value", "body"} for part in parts):
            return True
    return False


def _sanitize_validation_errors(errors: Any, request_path: str) -> Any:
    if not isinstance(errors, list):
        return errors
    sanitized: list[Any] = []
    for entry in errors:
        if not isinstance(entry, dict):
            sanitized.append(entry)
            continue
        cleaned = dict(entry)
        if _is_sensitive_validation_location(cleaned.get("loc"), request_path):
            if "input" in cleaned:
                cleaned["input"] = "[REDACTED]"
            if isinstance(cleaned.get("ctx"), dict):
                cleaned["ctx"] = {
                    k: ("[REDACTED]" if k in {"input", "given", "value"} else v)
                    for k, v in cleaned["ctx"].items()
                }
        sanitized.append(cleaned)
    return sanitized


def add_error_handlers(app) -> None:
    """
    添加全局异常处理器
    
    为 FastAPI 应用添加各类异常的处理器
    
    Args:
        app: FastAPI 应用实例
    """
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """处理 HTTP 异常"""
        # 如果 detail 已经是 ErrorResponse 格式的 dict，直接使用
        if isinstance(exc.detail, dict) and "error" in exc.detail and "message" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail
            )
        # 否则将 detail 包装成 ErrorResponse 格式
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": str(exc.detail) if exc.detail else "HTTP Error",
                "detail": None
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理请求验证异常"""
        sanitized_errors = _sanitize_validation_errors(exc.errors(), request.url.path)
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": "请求参数验证失败",
                # Validation errors echo input values. Sensitive fields are redacted above,
                # and overflowing JSON numbers must not turn a rejected request into a 500.
                "detail": jsonable_encoder(
                    sanitized_errors,
                    custom_encoder={float: lambda value: value if math.isfinite(value) else str(value)},
                )
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理通用异常"""
        logger.error(
            f"Unhandled exception: {exc}\n"
            f"Request path: {request.url.path}\n"
            f"Traceback: {traceback.format_exc()}"
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "服务器内部错误",
                "detail": None
            }
        )
