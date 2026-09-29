# -*- coding: utf-8 -*-
"""Shared helpers for API error responses."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def error_body(error: str, message: str, *, detail: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": error,
        "message": message,
    }
    if detail is not None:
        body["detail"] = detail
    return body


def api_error(status_code: int, error: str, message: str, *, detail: Any = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=error_body(error, message, detail=detail),
    )


def error_json_response(status_code: int, error: str, message: str, *, detail: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(error, message, detail=detail),
    )
