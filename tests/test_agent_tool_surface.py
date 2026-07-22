# -*- coding: utf-8 -*-
"""Tests for the internal DSA Tool Surface."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from src.agent.stock_scope import StockScope
from src.agent.tool_surface import ToolSurface
from src.agent.tools.execution import ToolAccessContext, check_tool_execution
from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolPolicy, ToolRegistry


def _single_tool_registry(tool: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _registry_with_echo(executed=None) -> ToolRegistry:
    calls = executed if executed is not None else []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echo a message.",
            parameters=[
                ToolParameter(name="message", type="string", description="Message"),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="Mode",
                    required=False,
                    default="plain",
                    enum=["plain", "loud"],
                ),
            ],
            handler=lambda message, mode="plain": calls.append((message, mode)) or {"message": message, "mode": mode},
            category="data",
            policy=ToolPolicy.declared(
                read_only=True,
                side_effects=[],
                permissions=["test:read"],
            ),
        )
    )
    return registry


def test_public_descriptor_does_not_expose_handler_and_includes_policy_scope() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="quote",
            description="Quote",
            parameters=[ToolParameter(name="stock_code", type="string", description="Stock")],
            handler=lambda stock_code: {"code": stock_code},
            category="data",
            policy=ToolPolicy.declared(
                read_only=True,
                side_effects=["network_read"],
                permissions=["market_data:read"],
                scope_dimensions=["stock"],
            ),
        )
    )

    descriptor = ToolSurface(registry).list_tools("public")[0]
    encoded = json.dumps(descriptor, ensure_ascii=False)

    assert descriptor["policy"]["policy_status"] == "declared"
    assert descriptor["policy"]["cancellation_safe"] is False
    assert descriptor["scope"]["scope_dimensions"] == ["stock"]
    assert descriptor["scope"]["requires_stock_scope"] is True
    assert "handler" not in encoded
    assert "callable" not in encoded
    assert "<function" not in encoded


def test_cancellation_safe_filter_only_lists_explicitly_safe_tools() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="safe",
            description="Safe",
            parameters=[],
            handler=lambda: None,
            policy=ToolPolicy.declared(read_only=True, cancellation_safe=True),
        )
    )
    registry.register(
        ToolDefinition(
            name="unsafe",
            description="Unsafe",
            parameters=[],
            handler=lambda: None,
            policy=ToolPolicy.declared(read_only=True),
        )
    )

    surface = ToolSurface(registry)

    assert [item["name"] for item in surface.list_tools("public")] == ["safe", "unsafe"]
    assert [
        item["name"]
        for item in surface.list_tools("public", cancellation_safe_only=True)
    ] == ["safe"]


def test_controlled_execution_rejects_tool_without_cancellation_contract() -> None:
    called = False

    def handler():
        nonlocal called
        called = True

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="unsafe",
            description="Unsafe",
            parameters=[],
            handler=handler,
            policy=ToolPolicy.declared(read_only=True),
        )
    )

    result = ToolSurface(registry).execute_tool(
        "unsafe",
        {},
        ToolAccessContext(cancel_event=threading.Event()),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "cancellation_unsupported"
    assert called is False


def test_cancellation_safe_handler_exits_before_controlled_call_returns() -> None:
    entered = threading.Event()
    cancel_event = threading.Event()
    results = []

    def handler():
        entered.set()
        while True:
            check_tool_execution()
            cancel_event.wait(0.01)

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="cooperative",
            description="Cooperative",
            parameters=[],
            handler=handler,
            policy=ToolPolicy.declared(read_only=True, cancellation_safe=True),
        )
    )
    thread = threading.Thread(
        target=lambda: results.append(
            ToolSurface(registry).execute_tool(
                "cooperative",
                {},
                ToolAccessContext(cancel_event=cancel_event),
            )
        )
    )

    thread.start()
    assert entered.wait(timeout=1)
    cancel_event.set()
    thread.join(timeout=1)

    assert thread.is_alive() is False
    assert results[0]["error"]["code"] == "cancelled"


def test_controlled_deadline_is_checked_before_safe_handler() -> None:
    called = False

    def handler():
        nonlocal called
        called = True

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="safe",
            description="Safe",
            parameters=[],
            handler=handler,
            policy=ToolPolicy.declared(read_only=True, cancellation_safe=True),
        )
    )

    result = ToolSurface(registry).execute_tool(
        "safe",
        {},
        ToolAccessContext(deadline=time.monotonic() - 1),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "timeout"
    assert called is False


def test_openai_schema_is_structurally_equal_to_registry_output() -> None:
    registry = _registry_with_echo()

    assert ToolSurface(registry).list_tools("openai") == registry.to_openai_tools()
    encoded = json.dumps(ToolSurface(registry).list_tools("openai"))
    assert "policy" not in encoded
    assert "permissions" not in encoded
    assert "side_effects" not in encoded
    assert "scope" not in encoded


def test_mcp_descriptor_is_descriptor_only() -> None:
    descriptor = ToolSurface(_registry_with_echo()).list_tools("mcp_descriptor")[0]
    expected_schema = _registry_with_echo().get("echo")._params_json_schema()
    expected_schema.setdefault("required", [])
    expected_schema["additionalProperties"] = False

    assert descriptor == {
        "name": "echo",
        "description": "Echo a message.",
        "inputSchema": expected_schema,
    }
    assert "transport" not in descriptor
    assert "server" not in descriptor


def test_execute_exact_tool_name_success() -> None:
    calls = []
    result = ToolSurface(_registry_with_echo(calls)).execute_tool(
        "echo",
        {"message": "hello"},
        ToolAccessContext(backend="test", session_id="s1"),
    )

    assert result["ok"] is True
    assert result["result"] == {"message": "hello", "mode": "plain"}
    assert json.loads(result["result_text"]) == {"message": "hello", "mode": "plain"}
    assert result["audit"]["backend"] == "test"
    assert result["audit"]["session_id"] == "s1"
    assert calls == [("hello", "plain")]


def test_rejects_unregistered_namespaced_and_unknown_tools() -> None:
    surface = ToolSurface(_registry_with_echo())

    assert surface.execute_tool("default_api:echo", {}, None)["error"]["code"] == "invalid_tool_name"
    assert surface.execute_tool("provider.tool", {}, None)["error"]["code"] == "invalid_tool_name"
    assert surface.execute_tool("provider:tool", {}, None)["error"]["code"] == "invalid_tool_name"
    assert surface.execute_tool("missing", {}, None)["error"]["code"] == "tool_not_found"


def test_registered_dotted_name_uses_exact_match_only() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="provider.tool",
            description="Exact dotted tool",
            parameters=[],
            handler=lambda: {"ok": True},
        )
    )
    surface = ToolSurface(registry)

    assert surface.execute_tool("provider.tool", {}, None)["ok"] is True
    assert surface.execute_tool("other.tool", {}, None)["error"]["code"] == "invalid_tool_name"


def test_argument_validation_errors_before_handler() -> None:
    calls = []
    surface = ToolSurface(_registry_with_echo(calls))

    cases = [
        (None, "arguments must be an object"),
        ({}, "missing required argument"),
        ({"message": "x", "extra": 1}, "unexpected argument"),
        ({"message": "x", "mode": "quiet"}, "must be one of"),
        ({"message": "x", "mode": None}, "must not be null"),
        ({"message": 123}, "must be string"),
    ]
    for arguments, expected in cases:
        result = surface.execute_tool("echo", arguments, None)
        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_arguments"
        assert expected in result["error"]["message"]

    assert calls == []


def test_optional_null_arguments_are_rejected_but_omitted_defaults_still_work() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="optional_params",
            description="Optional params",
            parameters=[
                ToolParameter(name="message", type="string", description="Message"),
                ToolParameter(name="count", type="integer", description="Count", required=False, default=1),
                ToolParameter(name="enabled", type="boolean", description="Enabled", required=False, default=True),
                ToolParameter(name="metadata", type="object", description="Metadata", required=False),
            ],
            handler=lambda message, count=1, enabled=True, metadata=None: calls.append(
                (message, count, enabled, metadata)
            )
            or {
                "message": message,
                "count": count,
                "enabled": enabled,
                "metadata": metadata,
            },
        )
    )
    surface = ToolSurface(registry)

    for key in ["count", "enabled", "metadata"]:
        result = surface.execute_tool("optional_params", {"message": "x", key: None}, None)
        assert result["ok"] is False
        assert result["error"]["code"] == "invalid_arguments"
        assert "must not be null" in result["error"]["message"]

    result = surface.execute_tool("optional_params", {"message": "x"}, None)
    assert result["ok"] is True
    assert result["result"] == {
        "message": "x",
        "count": 1,
        "enabled": True,
        "metadata": None,
    }
    assert calls == [("x", 1, True, None)]


def test_extra_arguments_allowed_when_handler_accepts_kwargs() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="kwargs_tool",
            description="Allows kwargs",
            parameters=[],
            handler=lambda **kwargs: kwargs,
        )
    )

    result = ToolSurface(registry).execute_tool("kwargs_tool", {"extra": 1}, None)
    descriptor = ToolSurface(registry).list_tools("public")[0]

    assert result["ok"] is True
    assert result["result"] == {"extra": 1}
    assert descriptor["parameters"]["additionalProperties"] is True


def test_stock_scope_violation_blocks_handler() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="quote",
            description="Quote",
            parameters=[ToolParameter(name="stock_code", type="string", description="Stock")],
            handler=lambda stock_code: calls.append(stock_code) or {"code": stock_code},
            policy=ToolPolicy.declared(
                read_only=True,
                permissions=["market_data:read"],
                scope_dimensions=["stock"],
            ),
        )
    )

    result = ToolSurface(registry).execute_tool(
        "quote",
        {"stock_code": "AAPL"},
        ToolAccessContext(stock_scope=StockScope(expected_stock_code="600519", allowed_stock_codes={"600519"})),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "stock_scope_violation"
    assert calls == []


def test_declared_stock_scope_requires_explicit_stock_context_before_handler() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="quote",
            description="Quote",
            parameters=[ToolParameter(name="stock_code", type="string", description="Stock")],
            handler=lambda stock_code: calls.append(stock_code) or {"code": stock_code},
            policy=ToolPolicy.declared(
                read_only=True,
                permissions=["market_data:read"],
                scope_dimensions=["stock"],
            ),
        )
    )

    result = ToolSurface(registry).execute_tool(
        "quote",
        {"stock_code": "AAPL"},
        None,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "stock_scope_violation"
    assert result["error"]["details"]["reason"] == "stock_scope_required"
    assert calls == []


def test_handler_error_is_structured_without_traceback() -> None:
    def _fail():
        raise RuntimeError("secret stack")

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="fail", description="Fail", parameters=[], handler=_fail))

    result = ToolSurface(registry).execute_tool("fail", {}, None)

    assert result["ok"] is False
    assert result["error"]["code"] == "handler_error"
    assert "Traceback" not in result["result_text"]
    assert "secret stack" not in result["result_text"]


def test_serialization_fallback_for_non_json_native_object() -> None:
    class Payload:
        def __init__(self) -> None:
            self.value = "ok"

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="payload", description="Payload", parameters=[], handler=lambda: Payload()))

    result = ToolSurface(registry).execute_tool("payload", {}, None)

    assert result["ok"] is True
    assert result["result"] == {"value": "ok"}
    assert json.loads(result["result_text"]) == {"value": "ok"}
    json.dumps(result)


def test_audit_and_diagnostics_are_redacted() -> None:
    plain_secret = "plainsecret1234567890"
    cookie_secret = "sessionid=abcdef1234567890"
    basic_auth_secret = "dXNlcjpwYXNzMTIzNDU2"
    proxy_auth_secret = "cHJveHk6c2VjcmV0MTIz"
    api_auth_secret = "plainauthsecret123456"
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="secret",
            description="Secret",
            parameters=[
                ToolParameter(name="message", type="string", description="Message"),
                ToolParameter(name="api_key", type="string", description="API key", required=False),
                ToolParameter(name="headers", type="object", description="Headers", required=False),
            ],
            handler=lambda message, api_key=None, headers=None: {
                "Authorization": "Bearer sk-secret-token-1234567890",
                "api_key": plain_secret,
                "token": plain_secret,
                "secret": plain_secret,
                "headers": {
                    "cookie": cookie_secret,
                    "set-cookie": cookie_secret,
                    "authorization": plain_secret,
                },
                "path": "/Users/massif/private/file.txt",
                "message": message * 50,
            },
        )
    )

    result = ToolSurface(registry).execute_tool(
        "secret",
        {
            "message": (
                "Authorization: Bearer sk-argument-token-1234567890 "
                f"Authorization: Basic {basic_auth_secret} "
                f"Proxy-Authorization: Basic {proxy_auth_secret} "
                f"authorization=ApiKey {api_auth_secret} "
                "/Users/massif/.env "
            ),
            "api_key": plain_secret,
            "headers": {
                "cookie": cookie_secret,
                "set-cookie": cookie_secret,
                "authorization": plain_secret,
            },
        },
        ToolAccessContext(audit_context={"secret": plain_secret}),
    )
    visible = json.dumps({"audit": result["audit"], "diagnostics": result["diagnostics"]}, ensure_ascii=False)

    assert "sk-secret-token-1234567890" not in visible
    assert "sk-argument-token-1234567890" not in visible
    assert basic_auth_secret not in visible
    assert proxy_auth_secret not in visible
    assert api_auth_secret not in visible
    assert plain_secret not in visible
    assert cookie_secret not in visible
    assert "/Users/massif/private" not in visible
    assert "/Users/massif/.env" not in visible
    assert "[REDACTED" in visible or "<truncated" in visible


def test_policy_unknown_does_not_break_registry_but_strict_validation_reports_issue() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="plain", description="Plain", parameters=[], handler=lambda: None))

    issues = registry.validate_tool_policies(strict=True)

    assert registry.validate_tool_policies(strict=False) == []
    assert issues
    assert issues[0]["code"] == "policy_unknown"


def test_strict_validation_reports_stock_scope_policy_mismatch() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="undeclared_stock",
            description="Stock param without policy scope.",
            parameters=[ToolParameter(name="stock_code", type="string", description="Stock")],
            handler=lambda stock_code: {"code": stock_code},
            policy=ToolPolicy.declared(read_only=True, permissions=["market_data:read"]),
        )
    )
    registry.register(
        ToolDefinition(
            name="missing_stock_param",
            description="Policy scope without stock_code param.",
            parameters=[ToolParameter(name="ticker", type="string", description="Ticker")],
            handler=lambda ticker: {"code": ticker},
            policy=ToolPolicy.declared(
                read_only=True,
                permissions=["market_data:read"],
                scope_dimensions=["stock"],
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="unsupported_market_scope",
            description="Unsupported market scope.",
            parameters=[ToolParameter(name="region", type="string", description="Region")],
            handler=lambda region: {"region": region},
            policy=ToolPolicy.declared(
                read_only=True,
                permissions=["market_data:read"],
                scope_dimensions=["market"],
            ),
        )
    )

    issue_codes = {issue["code"] for issue in registry.validate_tool_policies(strict=True)}
    non_strict_issue_codes = {issue["code"] for issue in registry.validate_tool_policies(strict=False)}

    assert "stock_scope_missing" in issue_codes
    assert "stock_scope_parameter_missing" in issue_codes
    assert "unsupported_scope_dimension" in issue_codes
    assert "stock_scope_missing" not in non_strict_issue_codes
    assert "stock_scope_parameter_missing" not in non_strict_issue_codes
    assert "unsupported_scope_dimension" not in non_strict_issue_codes


def test_tool_surface_stock_param_without_declared_scope_fails_closed() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="undeclared_stock",
            description="Stock param without policy scope.",
            parameters=[ToolParameter(name="stock_code", type="string", description="Stock")],
            handler=lambda stock_code: calls.append(stock_code) or {"code": stock_code},
            policy=ToolPolicy.declared(read_only=True, permissions=["market_data:read"]),
        )
    )

    result = ToolSurface(registry).execute_tool(
        "undeclared_stock",
        {"stock_code": "AAPL"},
        ToolAccessContext(stock_scope=StockScope(expected_stock_code="600519", allowed_stock_codes={"600519"})),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "scope_contract_violation"
    assert result["error"]["details"]["missing_scope_dimension"] == "stock"
    assert calls == []


def test_tool_surface_declared_stock_scope_without_stock_code_fails_closed() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="ticker_tool",
            description="Declares stock scope with ticker parameter.",
            parameters=[ToolParameter(name="ticker", type="string", description="Ticker")],
            handler=lambda ticker: calls.append(ticker) or {"code": ticker},
            policy=ToolPolicy.declared(
                read_only=True,
                permissions=["market_data:read"],
                scope_dimensions=["stock"],
            ),
        )
    )

    result = ToolSurface(registry).execute_tool(
        "ticker_tool",
        {"ticker": "AAPL"},
        ToolAccessContext(stock_scope=StockScope(expected_stock_code="600519", allowed_stock_codes={"600519"})),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "scope_contract_violation"
    assert result["error"]["details"]["missing_parameter"] == "stock_code"
    assert calls == []


def test_tool_surface_unsupported_scope_dimension_fails_closed() -> None:
    calls = []
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="market_tool",
            description="Declares unsupported market scope.",
            parameters=[ToolParameter(name="region", type="string", description="Region")],
            handler=lambda region: calls.append(region) or {"region": region},
            policy=ToolPolicy.declared(
                read_only=True,
                permissions=["market_data:read"],
                scope_dimensions=["market"],
            ),
        )
    )

    result = ToolSurface(registry).execute_tool(
        "market_tool",
        {"region": "us"},
        ToolAccessContext(market="cn"),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "scope_contract_violation"
    assert result["error"]["details"]["unsupported_scope_dimensions"] == ["market"]
    assert calls == []


def test_default_production_registry_has_supported_declared_policies() -> None:
    from src.agent.factory import get_tool_registry

    registry = get_tool_registry()

    assert registry.validate_tool_policies(strict=True) == []


def test_default_production_registry_only_exposes_bounded_tools_to_codex() -> None:
    from src.agent.factory import get_tool_registry

    safe_names = {
        item["name"]
        for item in ToolSurface(get_tool_registry()).list_tools(
            "public",
            cancellation_safe_only=True,
        )
    }

    assert safe_names == {
        "get_analysis_context",
        "get_skill_backtest_summary",
        "get_strategy_backtest_summary",
    }


def test_analysis_context_honors_cancellation_after_database_read(monkeypatch) -> None:
    from src.agent.tools import data_tools

    cancel_event = threading.Event()

    class _Database:
        def get_analysis_context(self, _stock_code):
            cancel_event.set()
            return {"code": "600519"}

    monkeypatch.setattr(data_tools, "_get_db", lambda: _Database())

    result = ToolSurface(_single_tool_registry(data_tools.get_analysis_context_tool)).execute_tool(
        "get_analysis_context",
        {"stock_code": "600519"},
        ToolAccessContext(
            stock_scope=StockScope(
                expected_stock_code="600519",
                allowed_stock_codes={"600519"},
            ),
            cancel_event=cancel_event,
        ),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "cancelled"


def test_backtest_summary_honors_cancellation_after_database_read(monkeypatch) -> None:
    from src.agent.tools import backtest_tools

    cancel_event = threading.Event()

    class _BacktestService:
        def get_summary(self, **_kwargs):
            cancel_event.set()
            return {"scope": "overall"}

    monkeypatch.setattr(backtest_tools, "_get_backtest_service", lambda: _BacktestService())

    result = ToolSurface(
        _single_tool_registry(backtest_tools.get_strategy_backtest_summary_tool)
    ).execute_tool(
        "get_strategy_backtest_summary",
        {},
        ToolAccessContext(cancel_event=cancel_event),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "cancelled"


def test_future_scope_context_fields_do_not_block_undeclared_tools() -> None:
    result = ToolSurface(_registry_with_echo()).execute_tool(
        "echo",
        {"message": "ok"},
        ToolAccessContext(
            market="us",
            time_range={"from": "2026-01-01", "to": "2026-01-31"},
            data_sources=["fixture"],
        ),
    )

    assert result["ok"] is True


def test_timeout_does_not_return_while_handler_is_still_running() -> None:
    finished = threading.Event()

    def slow_handler():
        time.sleep(0.4)
        finished.set()
        return {"done": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="slow",
            description="Slow",
            parameters=[],
            handler=slow_handler,
            policy=ToolPolicy.declared(read_only=True, cancellation_safe=True),
        )
    )

    started = time.time()
    result = ToolSurface(registry).execute_tool(
        "slow",
        {},
        ToolAccessContext(timeout_seconds=0.01),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "timeout"
    assert finished.is_set()
    assert time.time() - started >= 0.35


def test_max_result_bytes_truncates_public_payload_and_marks_diagnostics() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="large", description="Large", parameters=[], handler=lambda: {"text": "x" * 200}))

    result = ToolSurface(registry).execute_tool(
        "large",
        {},
        ToolAccessContext(max_result_bytes=20),
    )

    assert result["ok"] is True
    assert result["result"] is None
    assert result["diagnostics"]["result_truncated"] is True
    assert result["result_text"].endswith("<truncated>")
    assert len(result["result_text"].encode("utf-8")) <= 20


def test_max_result_bytes_does_not_return_raw_object_when_text_fits() -> None:
    class Payload:
        def __init__(self) -> None:
            self.value = "ok"
            self._private = "x" * 10000

    registry = ToolRegistry()
    registry.register(ToolDefinition(name="payload", description="Payload", parameters=[], handler=lambda: Payload()))

    result = ToolSurface(registry).execute_tool(
        "payload",
        {},
        ToolAccessContext(max_result_bytes=100),
    )

    assert result["ok"] is True
    assert result["result_text"] == '{"value": "ok"}'
    assert result["result"] == {"value": "ok"}
    assert result["diagnostics"]["result_truncated"] is False


def test_descriptors_include_explicit_empty_required_without_changing_openai_shape() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="empty", description="Empty", parameters=[], handler=lambda: None))

    surface = ToolSurface(registry)

    assert surface.list_tools("public")[0]["parameters"]["required"] == []
    assert surface.list_tools("public")[0]["parameters"]["additionalProperties"] is False
    assert surface.list_tools("mcp_descriptor")[0]["inputSchema"]["required"] == []
    assert surface.list_tools("mcp_descriptor")[0]["inputSchema"]["additionalProperties"] is False
    assert "required" not in registry.to_openai_tools()[0]["function"]["parameters"]
    assert "additionalProperties" not in registry.to_openai_tools()[0]["function"]["parameters"]


def test_max_result_bytes_caps_error_result_text() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(name="empty", description="Empty", parameters=[], handler=lambda: None))

    result = ToolSurface(registry).execute_tool(
        "empty",
        {"unexpected": "x" * 200},
        ToolAccessContext(max_result_bytes=16),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"
    assert result["diagnostics"]["result_truncated"] is True
    assert len(result["result_text"].encode("utf-8")) <= 16


def test_stock_scope_no_longer_imports_runner_for_normalization() -> None:
    source = Path("src/agent/stock_scope.py").read_text(encoding="utf-8")

    assert "from src.agent.runner import _normalize_tool_stock_code" not in source
