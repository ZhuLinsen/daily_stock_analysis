#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 6 Gate A feasibility harness for Codex App Server.

The harness imports the production transport and keeps only test probes and
security sentinels here.  Its ``gate_a_nonce`` tool is never part of the
production registry or Agent backend.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import io
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agent.codex_app_server_transport import (  # noqa: E402
    MAX_STDERR_BYTES,
    MAX_STDOUT_FRAME_BYTES,
    MAX_TOOL_RESULT_BYTES,
    PERMISSION_PROFILE,
    TOOL_WORKERS,
    CodexAppServerError,
    CodexAppServerTransport,
    ToolCallRecord,
    controlled_environment as _controlled_environment,
    harden_command_against_configured_mcp as _harden_command_against_configured_mcp,
    resolve_command as _resolve_command,
)
from src.agent.codex_tool_process import CodexToolProcessRunner  # noqa: E402
from src.agent.factory import get_tool_registry  # noqa: E402
from src.agent.stock_scope import StockScope  # noqa: E402
from src.agent.tool_surface import ToolSurface  # noqa: E402
from src.agent.tools.execution import ToolAccessContext, redact_diagnostic_value  # noqa: E402
from src.agent.tools.registry import (  # noqa: E402
    ToolDefinition,
    ToolParameter,
    ToolPolicy,
    ToolRegistry,
)


GateAError = CodexAppServerError


def _probe_descriptor_handler(label: str) -> dict:
    raise RuntimeError(f"Gate A descriptor handler must run in a child process: {label}")


def _gate_a_process_worker(
    tool_name: str,
    arguments: dict,
    context: ToolAccessContext,
    *,
    tokens: Dict[str, str],
) -> dict:
    if tool_name == "gate_a_nonce":
        time.sleep(0.5)
        result = {"label": arguments["label"], "token": tokens[arguments["label"]]}
        return {
            "ok": True,
            "tool_name": tool_name,
            "result": result,
            "result_text": json.dumps(result),
            "error": None,
            "audit": {},
            "diagnostics": {},
        }
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return ToolSurface(get_tool_registry()).execute_tool(tool_name, arguments, context)


def _build_probe_surface() -> ToolSurface:
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="gate_a_nonce",
            description="Return the hidden Gate A token for one requested label.",
            parameters=[
                ToolParameter(
                    name="label",
                    type="string",
                    description="Probe label",
                    enum=["alpha", "beta"],
                )
            ],
            handler=_probe_descriptor_handler,
            category="data",
            policy=ToolPolicy.declared(read_only=True, permissions=["gate_a:test"]),
        )
    )
    production_tool = get_tool_registry().resolve("get_analysis_context")
    if production_tool is None:
        raise GateAError("tool_not_found", "Production get_analysis_context tool is not registered")

    registry.register(production_tool)
    return ToolSurface(registry)


def _calls_overlap(calls: Sequence[ToolCallRecord]) -> bool:
    if len(calls) != 2:
        return False
    first, second = sorted(calls, key=lambda item: item.started_at)
    return second.started_at < first.finished_at


class _LoopbackSentinel:
    def __init__(self, token: str) -> None:
        self.token = token
        self.requested = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                owner.requested.set()
                body = owner.token.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="gate-a-loopback",
            daemon=True,
        )

    def __enter__(self) -> "_LoopbackSentinel":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/gate-a"


def run_gate_a(command: Sequence[str], *, timeout: float = 120.0) -> dict:
    nonce = secrets.token_hex(8)
    tokens = {"alpha": f"ALPHA_{nonce}", "beta": f"BETA_{nonce}"}
    reserved_stock_code = f"DSAGATEA{secrets.token_hex(6).upper()}"
    surface = _build_probe_surface()
    context = ToolAccessContext(
        stock_scope=StockScope(
            expected_stock_code=reserved_stock_code,
            allowed_stock_codes={reserved_stock_code},
        ),
        backend="codex_app_server_gate_a",
        session_id="gate-a",
        timeout_seconds=10,
        max_result_bytes=MAX_TOOL_RESULT_BYTES,
    )

    report: dict = {
        "gate": "phase_6_gate_a",
        "protocol": "codex_app_server_experimental_dynamic_tools",
        "checks": {},
        "feasible": False,
    }
    with CodexAppServerTransport(
        command,
        tool_surface=surface,
        tool_context=context,
        request_timeout=timeout,
        tool_runner=CodexToolProcessRunner(
            worker=functools.partial(_gate_a_process_worker, tokens=tokens)
        ),
    ) as client:
        common_base = (
            "You are the DSA stock-analysis Agent runtime. DSA instructions and DSA tools define your task; "
            "coding-agent defaults do not. Never modify files, request approval, or use unregistered tools."
        )

        tool_thread = client.start_thread(
            tool_names=["gate_a_nonce"],
            base_instructions=common_base,
            developer_instructions=(
                "Call gate_a_nonce exactly twice, once for alpha and once for beta. Issue both calls together. "
                "After both results return, answer with the two returned token values and no invented values."
            ),
        )
        report["checks"]["permission_profile_selection"] = {
            "passed": (
                client.thread_metadata(tool_thread)
                .get("active_permission_profile", {})
                .get("id")
                == PERMISSION_PROFILE
            ),
            "active_profile": client.thread_metadata(tool_thread).get("active_permission_profile"),
        }
        report["checks"]["external_tool_isolation"] = client.inspect_external_tool_isolation(tool_thread)
        tool_turn = client.run_turn(
            tool_thread,
            "Run the two-label DSA capability probe now. The hidden tokens are available only from the tool results.",
            timeout=timeout,
        )
        tool_calls = [call for call in client.tool_calls if call.turn_id == tool_turn.turn_id]
        tool_roundtrip = (
            {call.tool_name for call in tool_calls} == {"gate_a_nonce"}
            and len(tool_calls) == 2
            and all(call.success for call in tool_calls)
            and all(token in tool_turn.final_text for token in tokens.values())
        )
        report["checks"]["deterministic_tool_roundtrip"] = {
            "passed": tool_roundtrip,
            "structured_calls": len(tool_calls) == 2,
            "final_depends_on_both_results": all(token in tool_turn.final_text for token in tokens.values()),
            "overlapping_calls": _calls_overlap(tool_calls),
        }

        production_thread = client.start_thread(
            tool_names=["get_analysis_context"],
            base_instructions=common_base,
            developer_instructions=(
                "Use only get_analysis_context for the exact stock code in the user request, then report whether "
                "the DSA Tool Surface returned analysis context. Do not substitute another code."
            ),
        )
        production_turn = client.run_turn(
            production_thread,
            f"Check DSA analysis context for the reserved nonexistent stock code {reserved_stock_code}.",
            timeout=timeout,
        )
        production_calls = [call for call in client.tool_calls if call.turn_id == production_turn.turn_id]
        production_passed = (
            len(production_calls) == 1
            and production_calls[0].tool_name == "get_analysis_context"
            and production_calls[0].arguments == {"stock_code": reserved_stock_code}
            and production_calls[0].success
            and reserved_stock_code in production_turn.final_text
        )
        report["checks"]["production_tool_surface_roundtrip"] = {
            "passed": production_passed,
            "tool": "get_analysis_context",
            "reserved_nonexistent_scope": True,
            "user_data_requested": False,
        }

        history_user = f"HISTORY_USER_{secrets.token_hex(6)}"
        history_assistant = f"HISTORY_ASSISTANT_{secrets.token_hex(6)}"
        turn_one_token = f"TURN_ONE_{secrets.token_hex(6)}"
        history_thread = client.start_thread(
            tool_names=[],
            base_instructions=common_base,
            developer_instructions=(
                "Preserve user and assistant roles exactly. For recall questions, output only the requested tokens."
            ),
        )
        client.inject_history(
            history_thread,
            [
                {"role": "user", "content": f"Do not return this user-role token: {history_user}"},
                {"role": "assistant", "content": history_assistant},
            ],
        )
        client.run_turn(
            history_thread,
            f"Remember this first-turn token for the next turn: {turn_one_token}. Reply only ACK.",
            timeout=timeout,
        )
        history_turn = client.run_turn(
            history_thread,
            "Return the assistant-role history token and the first-turn token, separated by a vertical bar.",
            timeout=timeout,
        )
        history_passed = (
            history_assistant in history_turn.final_text
            and turn_one_token in history_turn.final_text
            and history_user not in history_turn.final_text
        )
        report["checks"]["history_and_instruction_fidelity"] = {
            "passed": history_passed,
            "assistant_role_preserved": history_assistant in history_turn.final_text,
            "user_role_not_flattened": history_user not in history_turn.final_text,
            "two_turn_replay": turn_one_token in history_turn.final_text,
            "dsa_instruction_applied": history_turn.final_text.count("|") == 1,
        }

        sentinel_token = f"OUTSIDE_{secrets.token_hex(12)}"
        network_token = f"NETWORK_{secrets.token_hex(12)}"
        sentinel_dir = Path(tempfile.mkdtemp(prefix="dsa-gate-a-outside-"))
        sentinel_file = sentinel_dir / "sentinel.txt"
        sentinel_file.write_text(sentinel_token, encoding="utf-8")
        sentinel_file.chmod(0o600)
        assert client.safe_cwd is not None
        workspace_token = f"WORKSPACE_{secrets.token_hex(12)}"
        workspace_file = client.safe_cwd / "readable.txt"
        workspace_file.write_text(workspace_token, encoding="utf-8")
        workspace_file.chmod(0o600)
        write_marker = client.safe_cwd / "gate_a_write_marker.txt"
        safe_cwd_is_private = (client.safe_cwd.stat().st_mode & 0o777) == 0o700
        try:
            with _LoopbackSentinel(network_token) as loopback:
                workspace_read_result = client.exec_sandboxed_command(["/bin/cat", str(workspace_file)])
                write_result = client.exec_sandboxed_command(["/usr/bin/touch", str(write_marker)])
                read_result = client.exec_sandboxed_command(["/bin/cat", str(sentinel_file)])
                network_result = client.exec_sandboxed_command(
                    ["/usr/bin/curl", "--max-time", "3", loopback.url],
                    timeout=8,
                )
                loopback_requested = loopback.requested.is_set()
            workspace_read_allowed = (
                workspace_read_result.get("exitCode") == 0
                and workspace_token in str(workspace_read_result.get("stdout", ""))
            )
            write_blocked = write_result.get("exitCode") != 0 and not write_marker.exists()
            outside_read_blocked = (
                read_result.get("exitCode") != 0
                and sentinel_token not in str(read_result.get("stdout", ""))
            )
            network_blocked = (
                network_result.get("exitCode") != 0
                and not loopback_requested
                and network_token not in str(network_result.get("stdout", ""))
            )
            security_passed = (
                safe_cwd_is_private
                and workspace_read_allowed
                and write_blocked
                and outside_read_blocked
                and network_blocked
            )
            report["checks"]["security_boundary"] = {
                "passed": security_passed,
                "permission_profile": PERMISSION_PROFILE,
                "approval_required": False,
                "safe_cwd": safe_cwd_is_private,
                "workspace_read_attempted": True,
                "workspace_read_exit_code": workspace_read_result.get("exitCode"),
                "workspace_read_allowed": workspace_read_allowed,
                "write_attempted": True,
                "write_exit_code": write_result.get("exitCode"),
                "write_blocked": write_blocked,
                "outside_read_attempted": True,
                "outside_read_exit_code": read_result.get("exitCode"),
                "outside_read_blocked": outside_read_blocked,
                "loopback_network_attempted": True,
                "loopback_network_exit_code": network_result.get("exitCode"),
                "loopback_network_blocked": network_blocked,
            }
        finally:
            shutil.rmtree(sentinel_dir, ignore_errors=True)

        report["transport"] = {
            "stdout_frame_limit_bytes": MAX_STDOUT_FRAME_BYTES,
            "stderr_limit_bytes": MAX_STDERR_BYTES,
            "tool_result_limit_bytes": MAX_TOOL_RESULT_BYTES,
            "tool_workers": TOOL_WORKERS,
            "stderr_preview": client.stderr_preview,
        }

    checks = report["checks"]
    report["feasible"] = all(check.get("passed") for check in checks.values())
    report["failed_checks"] = [name for name, check in checks.items() if not check.get("passed")]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 6 Codex App Server Gate A feasibility probes")
    parser.add_argument("--codex", default="codex", help="Codex executable name or path")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per request/turn timeout in seconds")
    args = parser.parse_args()
    try:
        base_command = _resolve_command(args.codex)
        command = _harden_command_against_configured_mcp(base_command, timeout=args.timeout)
        version = subprocess.run(
            [command[0], "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=_controlled_environment(),
        ).stdout.strip()
        report = run_gate_a(command, timeout=args.timeout)
        report["codex_version"] = version
    except GateAError as exc:
        report = {
            "gate": "phase_6_gate_a",
            "feasible": False,
            "fatal_error": {
                "code": exc.code,
                "message": redact_diagnostic_value(str(exc), limit=500),
            },
        }
    except (OSError, subprocess.SubprocessError) as exc:
        report = {
            "gate": "phase_6_gate_a",
            "feasible": False,
            "fatal_error": {
                "code": "unknown_backend_error",
                "message": redact_diagnostic_value(str(exc), limit=500),
            },
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("feasible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
