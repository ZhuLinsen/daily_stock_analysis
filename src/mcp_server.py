# -*- coding: utf-8 -*-
"""Read-only MCP stdio server over DSA's internal ``ToolSurface``.

Optional dependency: install ``mcp>=1.0.0,<2`` and run::

    python -m src.mcp_server
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import redirect_stdout
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.agent.factory import get_tool_registry
from src.agent.tool_surface import ToolSurface
from src.agent.tools.execution import (
    ToolAccessContext,
    redact_diagnostic_value,
    redact_external_tool_result,
)
from src.config import Config, get_config

# Portfolio and write/config tools stay closed on the read-only MCP surface.
_EXCLUDED_MCP_TOOL_NAMES = frozenset({"get_portfolio_snapshot"})
_EXCLUDED_MCP_PREFIXES = ("fxmacrodata_",)
_ALLOWED_REPORT_TYPES = frozenset({"simple", "detailed", "full", "brief"})

_ASYNC_TOOL_DESCRIPTORS: List[Dict[str, Any]] = [
    {
        "name": "resolve_stock",
        "description": "Resolve a Chinese/English stock name, ticker, or registered index into canonical code and asset type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Stock name or code (e.g. '贵州茅台', '600519', 'AAPL', 'hk00700', 'sh000016').",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "start_stock_analysis",
        "description": "Submit an async stock/index AI analysis task (notifications disabled by default). Returns task_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "Stock/index code or Chinese name.",
                },
                "report_type": {
                    "type": "string",
                    "description": "Report detail level: simple, detailed, full, or brief.",
                    "enum": ["simple", "detailed", "full", "brief"],
                },
                "force_refresh": {
                    "type": "boolean",
                    "description": "Bypass analysis cache and force fresh run.",
                },
            },
            "required": ["stock_code"],
        },
    },
    {
        "name": "get_analysis_status",
        "description": "Query the status and progress of an async analysis task submitted via start_stock_analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task identifier returned by start_stock_analysis.",
                }
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_latest_report",
        "description": "Fetch the latest persisted canonical analysis report for a stock/index from local history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "Stock/index code or Chinese name.",
                }
            },
            "required": ["stock_code"],
        },
    },
]


def _redact_structured_payload(payload: Any) -> Any:
    """Redact secrets across a structured JSON-compatible payload without truncation."""
    redacted_json = redact_external_tool_result(payload)
    try:
        return json.loads(redacted_json)
    except (TypeError, ValueError):
        return redacted_json


def _mcp_tool_result_is_error(result: Any) -> bool:
    """Map both adapter and wrapped tool failures to MCP ``isError``."""
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return True

    # ToolSurface deliberately wraps handler values in ``ok=True``. Several
    # existing read-only handlers signal a provider/business failure with an
    # inner ``{"error": ...}`` payload instead of raising, so the protocol
    # adapter must inspect the public result as well.
    nested_result = result.get("result")
    if isinstance(nested_result, dict):
        return nested_result.get("ok") is False or bool(nested_result.get("error"))
    return bool(result.get("error"))


def _configure_stderr_logging() -> None:
    """Route all Python logging to stderr so stdout stays dedicated to JSON-RPC."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(stream_handler)
    root.setLevel(logging.WARNING)


def resolve_stock_query(query: str) -> Dict[str, Any]:
    """Resolve stock/index code or Chinese name into canonical target metadata."""
    text = (query or "").strip()
    if not text:
        return {"ok": False, "error": "empty_query", "message": "query must be non-empty"}

    from src.services.name_to_code_resolver import resolve_name_to_code
    from src.services.stock_list_parser import ParseStatus, parse_analysis_target

    target = parse_analysis_target(text)
    if target.asset_type == ParseStatus.INDEX and target.canonical_id:
        return {
            "ok": True,
            "query": text,
            "stock_code": target.canonical_id,
            "canonical_id": target.canonical_id,
            "asset_type": "index",
            "stock_name": getattr(target.matched_index, "display_name", None),
        }
    if target.asset_type == ParseStatus.STOCK and target.canonical_id:
        return {
            "ok": True,
            "query": text,
            "stock_code": target.normalized_code or target.canonical_id,
            "canonical_id": target.canonical_id,
            "asset_type": "stock",
            "stock_name": None,
        }

    resolved = resolve_name_to_code(text)
    if resolved:
        resolved_target = parse_analysis_target(resolved)
        return {
            "ok": True,
            "query": text,
            "stock_code": resolved,
            "canonical_id": resolved_target.canonical_id or resolved,
            "asset_type": "index" if resolved_target.asset_type == ParseStatus.INDEX else "stock",
            "stock_name": text,
        }

    return {
        "ok": False,
        "query": text,
        "error": "unresolved_stock",
        "message": f"Could not resolve stock or index: {text}",
    }


def _resolve_analysis_target(query: str, resolved: Optional[Dict[str, Any]] = None) -> Any:
    """Return the parser target used to preserve index identity in the queue."""
    from src.services.stock_list_parser import parse_analysis_target

    target = parse_analysis_target(query)
    if getattr(target, "asset_type", None) == "index":
        return target
    if resolved and resolved.get("ok"):
        return parse_analysis_target(str(resolved.get("stock_code") or query))
    return target


def _build_stock_scope_for_code(stock_code: str) -> Any:
    try:
        from src.agent.stock_scope import StockIdentity, StockScope
        from src.services.stock_list_parser import default_index_registry

        registry = default_index_registry()
        identity = StockIdentity.from_code(stock_code, registry)
        return StockScope(
            expected_stock_code=identity.stock_code,
            allowed_stock_codes={identity.stock_code},
            mode="maintain",
            strict=True,
            identities=(identity,),
        )
    except Exception:
        return None


class McpReadOnlySurface:
    """Thin adapter exposing read-only DSA tools and async analysis helpers over MCP."""

    def __init__(
        self,
        config: Optional[Config] = None,
        *,
        include_macro: bool = False,
    ) -> None:
        self._config = config or get_config()
        self._include_macro = include_macro
        self._registry = get_tool_registry(self._config)
        self._surface = ToolSurface(self._registry)

    def _is_allowed_surface_tool(self, desc: Dict[str, Any]) -> bool:
        name = str(desc.get("name") or "")
        if not name or name in _EXCLUDED_MCP_TOOL_NAMES:
            return False
        if not self._include_macro and name.startswith(_EXCLUDED_MCP_PREFIXES):
            return False
        tool_def = self._registry.resolve(name)
        if tool_def is None or not getattr(tool_def.policy, "read_only", False):
            return False
        return True

    def list_tools(self) -> List[Dict[str, Any]]:
        descriptors = [
            desc
            for desc in self._surface.list_tools("mcp_descriptor")
            if self._is_allowed_surface_tool(desc)
        ]
        descriptors.extend(_ASYNC_TOOL_DESCRIPTORS)
        return descriptors

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        args = dict(arguments or {})
        try:
            if name == "resolve_stock":
                return resolve_stock_query(str(args.get("query") or ""))
            if name == "start_stock_analysis":
                return self._start_stock_analysis(args)
            if name == "get_analysis_status":
                return self._get_analysis_status(args)
            if name == "get_latest_report":
                return self._get_latest_report(args)

            allowed_names = {d["name"] for d in self.list_tools()}
            if name not in allowed_names:
                return {
                    "ok": False,
                    "error": "tool_not_allowed",
                    "message": f"Tool '{name}' is not available on the read-only MCP surface.",
                }

            stock_scope = None
            if isinstance(args.get("stock_code"), str) and args["stock_code"].strip():
                resolved = resolve_stock_query(args["stock_code"])
                if resolved.get("ok"):
                    args["stock_code"] = resolved["stock_code"]
                stock_scope = _build_stock_scope_for_code(str(args["stock_code"]))

            ctx = ToolAccessContext(
                stock_scope=stock_scope,
                redact_result=True,
                audit_context={"surface": "mcp_stdio"},
            )
            return self._surface.execute_tool(name, args, context=ctx)
        except Exception as exc:
            return {
                "ok": False,
                "error": "tool_execution_error",
                "message": str(redact_diagnostic_value(str(exc))),
            }

    def _start_stock_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raw_code = str(args.get("stock_code") or "").strip()
        if not raw_code:
            return {"ok": False, "error": "invalid_arguments", "message": "stock_code is required"}
        raw_report_type = args.get("report_type")
        if raw_report_type is None or str(raw_report_type).strip() == "":
            report_type = "detailed"
        else:
            report_type = str(raw_report_type).strip().lower()
            if report_type not in _ALLOWED_REPORT_TYPES:
                return {
                    "ok": False,
                    "error": "invalid_arguments",
                    "message": f"report_type must be one of {sorted(_ALLOWED_REPORT_TYPES)}",
                }
        force_refresh = bool(args.get("force_refresh", False))
        resolved = resolve_stock_query(raw_code)
        target_code = resolved["stock_code"] if resolved.get("ok") else raw_code
        analysis_target = _resolve_analysis_target(raw_code, resolved)

        from src.services.task_queue import get_task_queue

        queue = get_task_queue()
        accepted, duplicates = queue.submit_tasks_batch(
            [target_code],
            stock_name=resolved.get("stock_name") if resolved.get("ok") else None,
            original_query=raw_code,
            query_source="mcp",
            report_type=report_type,
            force_refresh=force_refresh,
            notify=False,
            analysis_targets=[analysis_target] if getattr(analysis_target, "asset_type", None) == "index" else None,
        )
        if duplicates:
            dup = duplicates[0]
            return {
                "ok": True,
                "duplicate": True,
                "task_id": dup.existing_task_id,
                "stock_code": target_code,
                "status": "pending",
                "notify": False,
            }
        if not accepted:
            return {
                "ok": False,
                "error": "submission_rejected",
                "message": f"Analysis task for '{target_code}' was not accepted.",
            }
        task = accepted[0]
        return {
            "ok": True,
            "task_id": task.task_id,
            "stock_code": task.stock_code,
            "status": task.status.value,
            "notify": False,
        }

    def _get_analysis_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(args.get("task_id") or "").strip()
        if not task_id:
            return {"ok": False, "error": "invalid_arguments", "message": "task_id is required"}

        from src.services.task_queue import get_task_queue

        task = get_task_queue().get_task(task_id)
        if task is None:
            return {"ok": False, "error": "not_found", "message": f"Task '{task_id}' not found"}
        redacted = _redact_structured_payload(task.to_dict())
        if isinstance(redacted, dict):
            return {"ok": True, **redacted}
        return {"ok": True, "task": redacted}

    def _get_latest_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raw_code = str(args.get("stock_code") or "").strip()
        if not raw_code:
            return {"ok": False, "error": "invalid_arguments", "message": "stock_code is required"}
        resolved = resolve_stock_query(raw_code)
        target_code = resolved["stock_code"] if resolved.get("ok") else raw_code

        from src.services.report_builder_service import get_latest_analysis_report_payload

        payload = get_latest_analysis_report_payload(target_code)
        if payload is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"No persisted report found for '{target_code}'",
            }
        return {"ok": True, "report": _redact_structured_payload(payload)}


def _import_mcp_sdk() -> Tuple[Any, Any, Any]:
    """Import optional ``mcp`` SDK lazily with actionable install guidance."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types
    except ImportError as exc:
        raise RuntimeError(
            "Optional dependency 'mcp' is required for the MCP stdio server. "
            "Install it with: pip install \"mcp>=1.0.0,<2\""
        ) from exc
    try:
        installed_version = package_version("mcp")
    except PackageNotFoundError:
        installed_version = ""
    if installed_version.split(".", 1)[0] == "2":
        raise RuntimeError(
            f"Installed MCP SDK {installed_version} is unsupported; "
            "install a 1.x release with: pip install \"mcp>=1.0.0,<2\""
        )
    return Server, stdio_server, types


def build_mcp_server(surface: McpReadOnlySurface) -> Tuple[Any, Any]:
    """Build a low-level MCP Server bound to ``surface``."""
    Server, _, types = _import_mcp_sdk()
    server = Server("daily-stock-analysis")

    @server.list_tools()
    async def handle_list_tools() -> List[Any]:
        return [
            types.Tool(
                name=desc["name"],
                description=desc.get("description") or "",
                inputSchema=desc.get("inputSchema") or {"type": "object", "properties": {}},
            )
            for desc in surface.list_tools()
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> Any:
        result = await asyncio.to_thread(surface.call_tool, name, arguments)
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, default=str),
                )
            ],
            isError=_mcp_tool_result_is_error(result),
        )

    return server, types


async def _serve_stdio_async(surface: McpReadOnlySurface) -> None:
    _, stdio_server, _ = _import_mcp_sdk()
    server, _ = build_mcp_server(surface)
    async with stdio_server() as (read_stream, write_stream):
        # stdio_server has already wrapped the underlying stdout buffer;
        # redirect text sys.stdout to stderr so stray print() calls in worker
        # threads cannot corrupt the JSON-RPC stream.
        prev_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        finally:
            sys.stdout = prev_stdout


def run_mcp_stdio_server(*, include_macro: bool = False) -> int:
    """Start the blocking read-only MCP stdio server."""
    os.environ.setdefault("TQDM_DISABLE", "1")
    _configure_stderr_logging()

    try:
        _import_mcp_sdk()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    with redirect_stdout(sys.stderr):
        surface = McpReadOnlySurface(include_macro=include_macro)
    asyncio.run(_serve_stdio_async(surface))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.mcp_server",
        description="Run Daily Stock Analysis read-only MCP stdio server (requires optional mcp>=1.0.0,<2).",
    )
    parser.add_argument(
        "--include-macro",
        action="store_true",
        help="Also expose optional fxmacrodata_* tools when available.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_mcp_stdio_server(include_macro=bool(args.include_macro))


if __name__ == "__main__":
    raise SystemExit(main())
