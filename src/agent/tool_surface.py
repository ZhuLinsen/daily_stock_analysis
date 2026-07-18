# -*- coding: utf-8 -*-
"""Internal DSA Tool Surface for future external Agent runtimes."""

from __future__ import annotations

import contextvars
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, Optional

from src.agent.tools.execution import (
    ToolAccessContext,
    _guard_tool_stock_scope,
    build_tool_audit,
    redact_diagnostic_value,
    serialize_tool_result,
)
from src.agent.tools.registry import (
    SUPPORTED_TOOL_SURFACE_SCOPE_DIMENSIONS,
    ToolDefinition,
    ToolParameter,
    ToolRegistry,
)


_JSON_TYPE_TO_PYTHON = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


class ToolSurface:
    """Internal tool schema and execution surface.

    This is a Python API only.  It intentionally does not expose REST, MCP, or
    provider-specific runtime transport.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def list_tools(self, format: str = "public") -> list[dict]:
        """List tools in a stable schema format."""
        normalized = (format or "public").strip().lower()
        if normalized == "openai":
            return self._registry.to_openai_tools()
        if normalized == "public":
            return [tool_def.to_public_descriptor() for tool_def in self._registry.list_tools()]
        if normalized == "mcp_descriptor":
            return [tool_def.to_mcp_descriptor() for tool_def in self._registry.list_tools()]
        raise ValueError(f"Unsupported tool surface format: {format}")

    def execute_tool(
        self,
        name: str,
        arguments: Any,
        context: Optional[ToolAccessContext] = None,
    ) -> Dict[str, Any]:
        """Execute one registered tool by exact name and return structured output."""
        ctx = context or ToolAccessContext()
        started_at = time.time()
        tool_name = name if isinstance(name, str) else str(name)
        tool_def = self._registry.resolve(tool_name) if isinstance(name, str) else None

        if tool_def is None:
            if isinstance(name, str) and (":" in name or "." in name):
                return self._error_result(
                    tool_name=tool_name,
                    code="invalid_tool_name",
                    message="Tool name must exactly match a registered DSA tool.",
                    started_at=started_at,
                    context=ctx,
                    retriable=False,
                    arguments=arguments,
                )
            return self._error_result(
                tool_name=tool_name,
                code="tool_not_found",
                message="Tool not found.",
                started_at=started_at,
                context=ctx,
                retriable=False,
                arguments=arguments,
            )

        validation_error = _validate_arguments(tool_def, arguments)
        if validation_error is not None:
            return self._error_result(
                tool_name=tool_name,
                code="invalid_arguments",
                message=validation_error,
                started_at=started_at,
                context=ctx,
                retriable=False,
                arguments=arguments,
            )

        scope_contract_error = _validate_scope_contract(tool_def)
        if scope_contract_error is not None:
            return self._error_result(
                tool_name=tool_name,
                code="scope_contract_violation",
                message=scope_contract_error["message"],
                started_at=started_at,
                context=ctx,
                retriable=False,
                details=scope_contract_error["details"],
                arguments=arguments,
            )

        guard_result = None
        if _requires_stock_scope(tool_def):
            if ctx.stock_scope is None:
                return self._error_result(
                    tool_name=tool_name,
                    code="stock_scope_violation",
                    message="Tool call requires an explicit stock scope.",
                    started_at=started_at,
                    context=ctx,
                    retriable=False,
                    details={
                        "reason": "stock_scope_required",
                        "scope_dimensions": list(tool_def.policy.scope_dimensions),
                    },
                    arguments=arguments,
                )
            guard_result = _guard_tool_stock_scope(
                self._registry,
                tool_name,
                arguments,
                ctx.stock_scope,
            )
        if guard_result is not None:
            result_text = serialize_tool_result(guard_result)
            return self._error_result(
                tool_name=tool_name,
                code="stock_scope_violation",
                message="Tool call is outside the allowed stock scope.",
                started_at=started_at,
                context=ctx,
                retriable=False,
                details={
                    "expected_stock_code": guard_result.get("expected_stock_code"),
                    "requested_stock_code": guard_result.get("requested_stock_code"),
                    "allowed_stock_codes": guard_result.get("allowed_stock_codes", []),
                },
                result_text=result_text,
                arguments=arguments,
            )

        timeout = ctx.timeout_seconds
        try:
            if timeout is not None and timeout > 0:
                result = _execute_with_timeout(tool_def, arguments, float(timeout))
            else:
                result = tool_def.handler(**arguments)
        except FuturesTimeoutError:
            timeout_label = f"{float(timeout or 0):.2f}s"
            return self._error_result(
                tool_name=tool_name,
                code="timeout",
                message=f"Tool execution timed out after {timeout_label}.",
                started_at=started_at,
                context=ctx,
                retriable=True,
                details={
                    "timeout_seconds": float(timeout or 0),
                    "cancel_requested": True,
                    "handler_may_continue": True,
                },
                arguments=arguments,
            )
        except Exception:
            return self._error_result(
                tool_name=tool_name,
                code="handler_error",
                message="Tool handler failed.",
                started_at=started_at,
                context=ctx,
                retriable=False,
                arguments=arguments,
            )

        try:
            result_text = serialize_tool_result(result)
        except Exception:
            return self._error_result(
                tool_name=tool_name,
                code="serialization_error",
                message="Tool result could not be serialized.",
                started_at=started_at,
                context=ctx,
                retriable=False,
                arguments=arguments,
            )

        public_result = _public_payload_from_result_text(result_text)
        result_truncated = False
        if ctx.max_result_bytes is not None and ctx.max_result_bytes >= 0:
            result_text, result_truncated = _truncate_text_bytes(result_text, int(ctx.max_result_bytes))
            public_result = None if result_truncated else _public_payload_from_result_text(result_text)

        duration = time.time() - started_at
        return {
            "ok": True,
            "tool_name": tool_name,
            "result": public_result,
            "result_text": result_text,
            "error": None,
            "audit": build_tool_audit(
                tool_name=tool_name,
                arguments=arguments,
                result=result_text,
                duration=duration,
                context=ctx,
            ),
            "diagnostics": {
                "redacted": True,
                "result_length": len(result_text.encode("utf-8")),
                "result_truncated": result_truncated,
                "preview": redact_diagnostic_value(result_text),
            },
        }

    def _error_result(
        self,
        *,
        tool_name: str,
        code: str,
        message: str,
        started_at: float,
        context: ToolAccessContext,
        retriable: bool,
        details: Optional[Dict[str, Any]] = None,
        result_text: Optional[str] = None,
        arguments: Any = None,
    ) -> Dict[str, Any]:
        duration = time.time() - started_at
        safe_text = result_text or json.dumps(
            {"error": message, "code": code, "retriable": retriable},
            ensure_ascii=False,
        )
        result_truncated = False
        if context.max_result_bytes is not None and context.max_result_bytes >= 0:
            safe_text, result_truncated = _truncate_text_bytes(safe_text, int(context.max_result_bytes))
        return {
            "ok": False,
            "tool_name": tool_name,
            "result": None,
            "result_text": safe_text,
            "error": {
                "code": code,
                "message": message,
                "retriable": retriable,
                "details": details or {},
            },
            "audit": build_tool_audit(
                tool_name=tool_name,
                arguments=arguments if arguments is not None else {},
                result=safe_text,
                error_code=code,
                duration=duration,
                context=context,
            ),
            "diagnostics": {
                "redacted": True,
                "result_length": len(safe_text.encode("utf-8")),
                "result_truncated": result_truncated,
                "preview": redact_diagnostic_value(safe_text),
            },
        }


def _execute_with_timeout(tool_def: ToolDefinition, arguments: Dict[str, Any], timeout: float) -> Any:
    pool = ThreadPoolExecutor(max_workers=1)
    ctx = contextvars.copy_context()
    future = pool.submit(ctx.run, tool_def.handler, **arguments)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        future.cancel()
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _validate_arguments(tool_def: ToolDefinition, arguments: Any) -> Optional[str]:
    if not isinstance(arguments, dict):
        return "arguments must be an object"

    params = {param.name: param for param in tool_def.parameters}
    for param in tool_def.parameters:
        if param.required and param.name not in arguments:
            return f"missing required argument: {param.name}"

    accepts_extra = _handler_accepts_extra_kwargs(tool_def)
    for key in arguments:
        if key not in params and not accepts_extra:
            return f"unexpected argument: {key}"

    for key, value in arguments.items():
        param = params.get(key)
        if param is None:
            continue
        error = _validate_parameter_value(param, value)
        if error:
            return error
    return None


def _handler_accepts_extra_kwargs(tool_def: ToolDefinition) -> bool:
    return tool_def.accepts_extra_arguments()


def _requires_stock_scope(tool_def: ToolDefinition) -> bool:
    return "stock" in tool_def.policy.scope_dimensions


def _validate_scope_contract(tool_def: ToolDefinition) -> Optional[Dict[str, Any]]:
    dimensions = list(tool_def.policy.scope_dimensions)
    has_stock_param = any(param.name == "stock_code" for param in tool_def.parameters)
    declares_stock_scope = "stock" in dimensions
    unsupported = [
        dimension
        for dimension in dimensions
        if dimension not in SUPPORTED_TOOL_SURFACE_SCOPE_DIMENSIONS
    ]
    if unsupported:
        return {
            "message": "Tool declares scope dimensions that Phase 6a cannot enforce.",
            "details": {
                "scope_dimensions": dimensions,
                "unsupported_scope_dimensions": unsupported,
                "supported_scope_dimensions": sorted(SUPPORTED_TOOL_SURFACE_SCOPE_DIMENSIONS),
            },
        }
    if has_stock_param and not declares_stock_scope:
        return {
            "message": "Tool has stock_code parameter but does not declare stock scope.",
            "details": {
                "scope_dimensions": dimensions,
                "missing_scope_dimension": "stock",
            },
        }
    if declares_stock_scope and not has_stock_param:
        return {
            "message": "Tool declares stock scope but has no stock_code parameter.",
            "details": {
                "scope_dimensions": dimensions,
                "missing_parameter": "stock_code",
            },
        }
    return None


def _validate_parameter_value(param: ToolParameter, value: Any) -> Optional[str]:
    if value is None:
        return f"argument {param.name} must not be null"
    if param.enum and value not in param.enum:
        return f"argument {param.name} must be one of: {', '.join(map(str, param.enum))}"
    expected = _JSON_TYPE_TO_PYTHON.get(param.type)
    if not expected:
        return None
    if param.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"argument {param.name} must be integer"
        return None
    if param.type == "number":
        if isinstance(value, bool) or not isinstance(value, expected):
            return f"argument {param.name} must be number"
        return None
    if not isinstance(value, expected):
        return f"argument {param.name} must be {param.type}"
    return None


def _truncate_text_bytes(text: str, max_bytes: int) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    if max_bytes <= 0:
        return "", True
    marker = "<truncated>"
    marker_bytes = marker.encode("utf-8")
    if max_bytes <= len(marker_bytes):
        return raw[:max_bytes].decode("utf-8", errors="ignore"), True
    prefix = raw[: max_bytes - len(marker_bytes)].decode("utf-8", errors="ignore")
    return f"{prefix}{marker}", True


def _public_payload_from_result_text(result_text: str) -> Any:
    try:
        return json.loads(result_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return result_text
