# -*- coding: utf-8 -*-
"""Codex App Server JSONL transport for the experimental Agent backend.

The transport owns only protocol, process, permission-profile, and dynamic-tool
roundtrip concerns.  It never resolves or executes ``ToolRegistry`` directly;
all DSA tools are supplied through the Phase 6a :class:`ToolSurface` boundary.
"""

from __future__ import annotations

import json
import os
import queue
import re
import select
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from src.agent.codex_tool_process import MAX_TOOL_RESULT_BYTES, CodexToolProcessRunner
from src.agent.tool_surface import ToolSurface
from src.agent.tools.execution import ToolAccessContext, redact_diagnostic_value


MAX_STDOUT_FRAME_BYTES = 4 * 1024 * 1024
MAX_TURN_OUTPUT_BYTES = MAX_STDOUT_FRAME_BYTES
MAX_TURN_FRAME_COUNT = 4096
MAX_TURN_ITEM_COUNT = 1024
MAX_STDERR_BYTES = 64 * 1024
TOOL_WORKERS = 2
PERMISSION_PROFILE = "dsa_gate_a"

_BASE_CONFIG_OVERRIDES = (
    'default_permissions="dsa_gate_a"',
    'permissions.dsa_gate_a.description="DSA Agent read-only workspace"',
    'permissions.dsa_gate_a.filesystem={":minimal"="read",":workspace_roots"={"."="read"}}',
    "permissions.dsa_gate_a.network.enabled=false",
    "features.apps=false",
    "features.plugins=false",
)
_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

_APPROVAL_REQUESTS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "item/tool/requestUserInput",
    "mcpServer/elicitation/request",
    "applyPatchApproval",
    "execCommandApproval",
}
_AUTH_REQUESTS = {"account/chatgptAuthTokens/refresh"}
_RELEVANT_NOTIFICATIONS = {
    "item/completed",
    "thread/tokenUsage/updated",
    "turn/completed",
}
_ALLOWED_ENV_NAMES = {
    "CODEX_HOME",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TMPDIR",
    "USER",
}


def is_native_windows() -> bool:
    """Return whether the current process is running on native Windows."""
    return os.name == "nt"


def _process_group_alive(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class CodexAppServerError(RuntimeError):
    """Structured App Server transport failure."""

    def __init__(self, code: str, message: str, *, turn_started: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.turn_started = turn_started


@dataclass(frozen=True)
class ToolCallRecord:
    thread_id: str
    turn_id: str
    tool_name: str
    arguments: Any
    success: bool
    started_at: float
    finished_at: float


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    final_text: str
    usage: Optional[dict] = None
    model: str = ""


def normalize_token_usage_notification(params: dict) -> Optional[dict]:
    """Map the documented App Server per-turn usage payload to DSA telemetry keys."""
    token_usage = params.get("tokenUsage")
    last = token_usage.get("last") if isinstance(token_usage, dict) else None
    if not isinstance(last, dict):
        return None
    field_map = {
        "prompt_tokens": "inputTokens",
        "completion_tokens": "outputTokens",
        "total_tokens": "totalTokens",
        "cached_tokens": "cachedInputTokens",
    }
    usage: dict = {}
    for target, source in field_map.items():
        value = last.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[target] = value
    reasoning_tokens = last.get("reasoningOutputTokens")
    if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool) and reasoning_tokens >= 0:
        usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return usage if "total_tokens" in usage else None


def controlled_environment(source: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return the allowlisted environment inherited by Codex."""
    environment = os.environ if source is None else source
    return {name: environment[name] for name in _ALLOWED_ENV_NAMES if environment.get(name)}


def dynamic_tool_specs(surface: ToolSurface, names: Iterable[str]) -> list[dict]:
    """Convert ToolSurface MCP descriptors into App Server dynamic tools."""
    descriptors = {item["name"]: item for item in surface.list_tools("mcp_descriptor")}
    specs = []
    for name in names:
        descriptor = descriptors.get(name)
        if descriptor is None:
            raise CodexAppServerError("tool_not_found", f"DSA tool is not registered: {name}")
        specs.append(
            {
                "type": "function",
                "name": descriptor["name"],
                "description": descriptor["description"],
                "inputSchema": descriptor["inputSchema"],
            }
        )
    return specs


class CodexAppServerTransport:
    """Bidirectional JSONL client for one ephemeral App Server process."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        tool_surface: ToolSurface,
        tool_context: ToolAccessContext,
        request_timeout: float = 120.0,
        environment: Optional[Dict[str, str]] = None,
        tool_event_callback: Optional[Callable[[str, ToolCallRecord], None]] = None,
        deadline: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
        tool_runner: Optional[CodexToolProcessRunner] = None,
        max_tool_calls: int = 10,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self.command = list(command)
        self.tool_surface = tool_surface
        self.tool_context = tool_context
        self.request_timeout = request_timeout
        self.environment = controlled_environment(environment)
        self.tool_event_callback = tool_event_callback
        self.deadline = deadline
        self.cancel_event = cancel_event
        if max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be positive")
        self.max_tool_calls = max_tool_calls

        self.safe_cwd: Optional[Path] = None
        self.process: Optional[subprocess.Popen] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._tool_pool = ThreadPoolExecutor(max_workers=TOOL_WORKERS, thread_name_prefix="codex-agent-tool")
        self._tool_runner = tool_runner or CodexToolProcessRunner()
        self._process_lock = threading.Lock()
        self._writer_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._notification_condition = threading.Condition(self._state_lock)
        self._pending: Dict[int, queue.Queue] = {}
        self._next_id = 1
        self._fatal_error: Optional[CodexAppServerError] = None
        self._completed_turns: Dict[tuple[str, str], dict] = {}
        self._completed_answer_items: Dict[tuple[str, str], list[dict]] = {}
        self._turn_usage: Dict[tuple[str, str], dict] = {}
        self._tool_calls: list[ToolCallRecord] = []
        self._thread_tools: Dict[str, set[str]] = {}
        self._thread_metadata: Dict[str, dict] = {}
        self._stderr_parts: list[str] = []
        self._stderr_size = 0
        self._stdout_size = 0
        self._stdout_frame_count = 0
        self._completed_item_count = 0
        self._tool_call_count = 0
        self._closed = False

    def __enter__(self) -> "CodexAppServerTransport":
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @property
    def tool_calls(self) -> tuple[ToolCallRecord, ...]:
        with self._state_lock:
            return tuple(self._tool_calls)

    @property
    def stderr_preview(self) -> str:
        with self._state_lock:
            return redact_diagnostic_value("".join(self._stderr_parts), limit=2000)

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("transport already started")
        safe_path = Path(tempfile.mkdtemp(prefix="dsa-codex-app-server-"))
        safe_path.chmod(0o700)
        self.safe_cwd = safe_path
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=str(safe_path),
                env=self.environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
            )
        except Exception:
            shutil.rmtree(safe_path, ignore_errors=True)
            self.safe_cwd = None
            raise

        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="codex-app-server-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="codex-app-server-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {"name": "dsa-stock-analysis", "version": "phase-6"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.notify("initialized", {})
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close_error: Optional[CodexAppServerError] = None
        try:
            self._terminate_process()
        except CodexAppServerError as exc:
            close_error = exc
        tool_cleanup_ok = self._tool_runner.close()
        self._tool_pool.shutdown(wait=True, cancel_futures=True)
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2)
        if self.safe_cwd is not None:
            shutil.rmtree(self.safe_cwd, ignore_errors=True)
        if not tool_cleanup_ok:
            close_error = CodexAppServerError(
                "resource_cleanup_failed",
                "One or more DSA tool workers could not be fully reclaimed",
            )
        if close_error is not None:
            raise close_error

    def request(
        self,
        method: str,
        params: dict,
        timeout: Optional[float] = None,
        *,
        respect_cancellation: bool = True,
    ) -> dict:
        request_timeout = self.request_timeout if timeout is None else timeout
        deadline = time.monotonic() + request_timeout
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        response_queue: queue.Queue = queue.Queue(maxsize=1)
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = response_queue
        try:
            self._write_message(
                {"id": request_id, "method": method, "params": params},
                deadline=deadline,
                respect_cancellation=respect_cancellation,
            )
        except CodexAppServerError as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            if exc.code in {"cancelled", "timeout"}:
                self._terminate_process()
            if exc.code == "timeout":
                raise CodexAppServerError(
                    "timeout",
                    f"App Server request timed out: {method}",
                ) from exc
            if exc.code == "cancelled":
                raise CodexAppServerError(
                    "cancelled",
                    "App Server request was cancelled",
                ) from exc
            raise
        while True:
            self._raise_if_fatal()
            if (
                respect_cancellation
                and self.cancel_event is not None
                and self.cancel_event.is_set()
            ):
                with self._state_lock:
                    self._pending.pop(request_id, None)
                self._terminate_process()
                raise CodexAppServerError("cancelled", "App Server request was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._state_lock:
                    self._pending.pop(request_id, None)
                self._terminate_process()
                raise CodexAppServerError("timeout", f"App Server request timed out: {method}")
            try:
                message = response_queue.get(timeout=min(remaining, 0.1))
                break
            except queue.Empty:
                continue
        if "error" in message:
            error = message.get("error") or {}
            safe_message = redact_diagnostic_value(
                error.get("message", "App Server request failed"),
                limit=500,
            )
            raise CodexAppServerError("protocol_error", safe_message)
        result = message.get("result")
        if not isinstance(result, dict):
            raise CodexAppServerError(
                "protocol_error",
                f"App Server returned a non-object result for {method}",
            )
        return result

    def notify(self, method: str, params: dict) -> None:
        deadline = time.monotonic() + self.request_timeout
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        try:
            self._write_message(
                {"method": method, "params": params},
                deadline=deadline,
            )
        except CodexAppServerError as exc:
            if exc.code in {"cancelled", "timeout"}:
                self._terminate_process()
            raise

    def start_thread(
        self,
        *,
        tool_names: Sequence[str],
        base_instructions: str,
        developer_instructions: str,
    ) -> str:
        if self.safe_cwd is None:
            raise RuntimeError("transport not started")
        result = self.request(
            "thread/start",
            {
                "approvalPolicy": "never",
                "baseInstructions": base_instructions,
                "cwd": str(self.safe_cwd),
                "developerInstructions": developer_instructions,
                "dynamicTools": dynamic_tool_specs(self.tool_surface, tool_names),
                "environments": [],
                "ephemeral": True,
                "permissions": PERMISSION_PROFILE,
                "runtimeWorkspaceRoots": [str(self.safe_cwd)],
            },
        )
        thread = result.get("thread") or {}
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexAppServerError("protocol_error", "thread/start did not return a thread id")
        active_profile = result.get("activePermissionProfile") or {}
        if active_profile.get("id") != PERMISSION_PROFILE:
            raise CodexAppServerError(
                "permission_profile_mismatch",
                "App Server did not activate the DSA permission profile",
            )
        with self._state_lock:
            self._thread_tools[thread_id] = set(tool_names)
            self._thread_metadata[thread_id] = {
                "active_permission_profile": active_profile,
                "approval_policy": result.get("approvalPolicy"),
                "cwd_matches": result.get("cwd") == str(self.safe_cwd),
                "runtime_roots_match": result.get("runtimeWorkspaceRoots") == [str(self.safe_cwd)],
                "sandbox": result.get("sandbox"),
            }
        return thread_id

    def thread_metadata(self, thread_id: str) -> dict:
        with self._state_lock:
            return dict(self._thread_metadata.get(thread_id, {}))

    def inject_history(self, thread_id: str, messages: Sequence[dict]) -> None:
        items = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                raise ValueError("history messages must contain user/assistant string content")
            items.append(
                {
                    "type": "message",
                    "role": role,
                    "content": [
                        {
                            "type": "input_text" if role == "user" else "output_text",
                            "text": content,
                        }
                    ],
                }
            )
        if items:
            self.request("thread/inject_items", {"threadId": thread_id, "items": items})

    def run_turn(
        self,
        thread_id: str,
        text: str,
        timeout: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> TurnResult:
        result = self.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": text}],
                "approvalPolicy": "never",
                "environments": [],
                "permissions": PERMISSION_PROFILE,
            },
            timeout=timeout,
        )
        turn = result.get("turn") or {}
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise CodexAppServerError("protocol_error", "turn/start did not return a turn id")
        try:
            notification = self._wait_for_turn(
                thread_id,
                turn_id,
                self.request_timeout if timeout is None else timeout,
                cancel_event=cancel_event,
            )
        except CodexAppServerError as exc:
            raise CodexAppServerError(exc.code, str(exc), turn_started=True) from exc
        completed_turn = notification.get("params", {}).get("turn") or {}
        status = str(completed_turn.get("status", "unknown"))
        terminal_items = completed_turn.get("items", [])
        if not isinstance(terminal_items, list):
            raise CodexAppServerError(
                "protocol_error",
                "turn/completed returned a non-list items field",
                turn_started=True,
            )
        if len(terminal_items) > MAX_TURN_ITEM_COUNT:
            raise CodexAppServerError(
                "resource_limit_exceeded",
                "App Server exceeded the cumulative item budget",
                turn_started=True,
            )
        if status != "completed":
            error = completed_turn.get("error") or {}
            info = error.get("codexErrorInfo")
            if status == "interrupted":
                code = "cancelled"
            else:
                normalized_info = str(info or "").strip().casefold()
                code = "login_required" if normalized_info == "unauthorized" else "unknown_backend_error"
            message = redact_diagnostic_value(
                error.get("message", f"Turn ended with status {status}"),
                limit=500,
            )
            raise CodexAppServerError(code, message, turn_started=True)
        with self._state_lock:
            answer_items = list(self._completed_answer_items.get((thread_id, turn_id), []))
        final_items = [
            item
            for item in answer_items
            if item.get("phase") == "final_answer"
        ]
        if not final_items:
            final_items = [
                item
                for item in answer_items
                if item.get("phase") is None
            ]
        final_text = "".join(
            str(item.get("text", ""))
            for item in final_items
        ).strip()
        with self._state_lock:
            usage = self._turn_usage.get((thread_id, turn_id))
            self._completed_turns.pop((thread_id, turn_id), None)
            self._completed_answer_items.pop((thread_id, turn_id), None)
            self._turn_usage.pop((thread_id, turn_id), None)
        model = completed_turn.get("model") or notification.get("params", {}).get("model") or ""
        return TurnResult(
            turn_id=turn_id,
            final_text=final_text,
            usage=usage,
            model=str(model) if model else "",
        )

    def interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        """Interrupt one active turn using the documented App Server method."""
        self.request(
            "turn/interrupt",
            {"threadId": thread_id, "turnId": turn_id},
            timeout=min(self.request_timeout, 5.0),
            respect_cancellation=False,
        )

    def exec_sandboxed_command(self, command: Sequence[str], timeout: float = 10.0) -> dict:
        """Execute a fixed argv vector through App Server's own command sandbox."""
        if self.safe_cwd is None:
            raise RuntimeError("transport not started")
        if not command:
            raise ValueError("command must not be empty")
        return self.request(
            "command/exec",
            {
                "command": list(command),
                "cwd": str(self.safe_cwd),
                "env": {},
                "outputBytesCap": 4096,
                "permissionProfile": PERMISSION_PROFILE,
                "timeoutMs": max(1, int(timeout * 1000)),
                "tty": False,
            },
            timeout=timeout + 5,
        )

    def inspect_external_tool_isolation(self, thread_id: str) -> dict:
        """Prove that inherited Apps, plugins, and MCP capabilities are unavailable."""
        if self.safe_cwd is None:
            raise RuntimeError("transport not started")
        config_result = self.request(
            "config/read",
            {"cwd": str(self.safe_cwd), "includeLayers": False},
        )
        config = config_result.get("config")
        if not isinstance(config, dict):
            raise CodexAppServerError("protocol_error", "config/read did not return an effective config")
        features = config.get("features") or {}
        mcp_servers = config.get("mcp_servers") or {}
        if not isinstance(features, dict) or not isinstance(mcp_servers, dict):
            raise CodexAppServerError(
                "protocol_error",
                "config/read returned invalid feature or MCP configuration",
            )

        statuses = []
        cursor: Optional[str] = None
        seen_cursors = set()
        while True:
            params: dict = {"detail": "full", "limit": 100, "threadId": thread_id}
            if cursor is not None:
                params["cursor"] = cursor
            page = self.request("mcpServerStatus/list", params)
            data = page.get("data")
            if not isinstance(data, list):
                raise CodexAppServerError(
                    "protocol_error",
                    "mcpServerStatus/list did not return a server list",
                )
            statuses.extend(item for item in data if isinstance(item, dict))
            next_cursor = page.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or next_cursor in seen_cursors:
                raise CodexAppServerError(
                    "protocol_error",
                    "mcpServerStatus/list returned an invalid cursor",
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        configured_mcp_disabled = all(
            isinstance(value, dict) and value.get("enabled") is False
            for value in mcp_servers.values()
        )
        visible_capability_count = sum(
            len(status.get("tools") or {})
            + len(status.get("resources") or [])
            + len(status.get("resourceTemplates") or [])
            for status in statuses
        )
        apps_disabled = features.get("apps") is False
        plugins_disabled = features.get("plugins") is False
        return {
            "passed": (
                apps_disabled
                and plugins_disabled
                and configured_mcp_disabled
                and visible_capability_count == 0
            ),
            "apps_disabled": apps_disabled,
            "plugins_disabled": plugins_disabled,
            "configured_mcp_count": len(mcp_servers),
            "configured_mcp_disabled": configured_mcp_disabled,
            "visible_mcp_server_count": len(statuses),
            "visible_mcp_capability_count": visible_capability_count,
        }

    def _wait_for_turn(
        self,
        thread_id: str,
        turn_id: str,
        timeout: float,
        *,
        cancel_event: Optional[threading.Event],
    ) -> dict:
        deadline = time.monotonic() + timeout
        if self.deadline is not None:
            deadline = min(deadline, self.deadline)
        active_cancel_event = cancel_event or self.cancel_event
        while True:
            if active_cancel_event is not None and active_cancel_event.is_set():
                try:
                    self.interrupt_turn(thread_id, turn_id)
                finally:
                    raise CodexAppServerError("cancelled", "App Server turn was cancelled")
            with self._notification_condition:
                self._raise_if_fatal_locked()
                message = self._completed_turns.get((thread_id, turn_id))
                if message is not None:
                    return message
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_process()
                    raise CodexAppServerError("timeout", "App Server turn timed out")
                self._notification_condition.wait(timeout=min(remaining, 0.1))

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        stream = self.process.stdout
        while True:
            frame = stream.readline(MAX_STDOUT_FRAME_BYTES + 1)
            if not frame:
                if not self._closed and self._fatal_error is None:
                    self._set_fatal(
                        CodexAppServerError("protocol_error", "App Server stdout closed unexpectedly")
                    )
                return
            if len(frame) > MAX_STDOUT_FRAME_BYTES or not frame.endswith(b"\n"):
                self._set_fatal(
                    CodexAppServerError("output_too_large", "App Server JSON frame exceeded 4 MiB")
                )
                self._terminate_process()
                return
            with self._state_lock:
                self._stdout_size += len(frame)
                self._stdout_frame_count += 1
                over_budget = (
                    self._stdout_size > MAX_TURN_OUTPUT_BYTES
                    or self._stdout_frame_count > MAX_TURN_FRAME_COUNT
                )
            if over_budget:
                self._set_fatal(
                    CodexAppServerError(
                        "output_too_large",
                        "App Server exceeded the cumulative turn output budget",
                    )
                )
                self._terminate_process()
                return
            try:
                message = json.loads(frame)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._set_fatal(CodexAppServerError("protocol_error", "App Server emitted invalid JSON"))
                self._terminate_process()
                return
            if not isinstance(message, dict):
                self._set_fatal(
                    CodexAppServerError("protocol_error", "App Server emitted a non-object JSON frame")
                )
                self._terminate_process()
                return
            self._route_message(message)

    def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while True:
            chunk = self.process.stderr.readline(4096)
            if not chunk:
                return
            safe_line = redact_diagnostic_value(chunk.decode("utf-8", errors="replace"), limit=1024)
            encoded_size = len(safe_line.encode("utf-8"))
            with self._state_lock:
                remaining = MAX_STDERR_BYTES - self._stderr_size
                if remaining <= 0:
                    continue
                clipped = safe_line.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
                self._stderr_parts.append(clipped)
                self._stderr_size += min(encoded_size, remaining)

    def _route_message(self, message: dict) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if request_id is not None and isinstance(method, str):
            self._handle_server_request(message)
            return
        if request_id is not None:
            with self._state_lock:
                target = self._pending.pop(request_id, None)
            if target is not None:
                target.put(message)
            return
        if isinstance(method, str):
            if method not in _RELEVANT_NOTIFICATIONS:
                return
            with self._notification_condition:
                params = message.get("params") or {}
                thread_id = params.get("threadId")
                turn_id = params.get("turnId")
                if method == "item/completed" and isinstance(thread_id, str) and isinstance(turn_id, str):
                    item = params.get("item")
                    if isinstance(item, dict):
                        self._completed_item_count += 1
                        if self._completed_item_count > MAX_TURN_ITEM_COUNT:
                            self._fatal_error = CodexAppServerError(
                                "resource_limit_exceeded",
                                "App Server exceeded the cumulative item budget",
                                turn_started=True,
                            )
                            self._notification_condition.notify_all()
                            return
                        if (
                            item.get("type") == "agentMessage"
                            and item.get("phase") in (None, "final_answer")
                        ):
                            self._completed_answer_items.setdefault(
                                (thread_id, turn_id), []
                            ).append(item)
                elif method == "thread/tokenUsage/updated" and isinstance(thread_id, str) and isinstance(turn_id, str):
                    usage = normalize_token_usage_notification(params)
                    if usage is not None:
                        self._turn_usage[(thread_id, turn_id)] = usage
                elif method == "turn/completed" and isinstance(thread_id, str):
                    turn = params.get("turn") or {}
                    completed_turn_id = turn.get("id")
                    if isinstance(completed_turn_id, str):
                        self._completed_turns[(thread_id, completed_turn_id)] = message
                self._notification_condition.notify_all()

    def _handle_server_request(self, message: dict) -> None:
        method = message.get("method")
        if method == "item/tool/call":
            with self._state_lock:
                if self._tool_call_count >= self.max_tool_calls:
                    error = CodexAppServerError(
                        "resource_limit_exceeded",
                        "App Server exceeded the configured Agent tool-call budget",
                        turn_started=True,
                    )
                else:
                    self._tool_call_count += 1
                    error = None
            if error is not None:
                self._set_fatal(error)
                self._terminate_process()
                return
            self._tool_pool.submit(self._execute_tool_request, message)
            return
        if method in _APPROVAL_REQUESTS:
            error = CodexAppServerError(
                "approval_required",
                f"Unexpected App Server approval request: {method}",
            )
        elif method in _AUTH_REQUESTS:
            error = CodexAppServerError(
                "login_required",
                "App Server requested an unavailable token refresh",
            )
        else:
            error = CodexAppServerError("protocol_error", f"Unexpected App Server request: {method}")
        self._set_fatal(error)
        self._terminate_process()

    def _execute_tool_request(self, message: dict) -> None:
        params = message.get("params") or {}
        thread_id = str(params.get("threadId", ""))
        turn_id = str(params.get("turnId", ""))
        tool_name = str(params.get("tool", ""))
        arguments = params.get("arguments")
        started_at = time.monotonic()
        started_record = ToolCallRecord(
            thread_id=thread_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            started_at=started_at,
            finished_at=started_at,
        )
        if self.tool_event_callback is not None:
            self.tool_event_callback("start", started_record)
        with self._state_lock:
            allowed = tool_name in self._thread_tools.get(thread_id, set())
        if allowed:
            result = self._tool_runner.execute(tool_name, arguments, self.tool_context)
        else:
            result = {"ok": False, "result_text": json.dumps({"error": "tool_not_allowed"})}
        finished_at = time.monotonic()
        record = ToolCallRecord(
            thread_id=thread_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            success=bool(result.get("ok")),
            started_at=started_at,
            finished_at=finished_at,
        )
        with self._state_lock:
            self._tool_calls.append(record)
        if self.tool_event_callback is not None:
            self.tool_event_callback("done", record)
        error_code = (result.get("error") or {}).get("code")
        if error_code in {
            "output_too_large",
            "resource_cleanup_failed",
            "tool_roundtrip_failed",
        }:
            self._set_fatal(
                CodexAppServerError(
                    error_code,
                    "DSA tool process boundary failed",
                    turn_started=True,
                )
            )
            self._terminate_process()
            return
        try:
            deadline = self.deadline
            if deadline is None:
                deadline = time.monotonic() + self.request_timeout
            self._write_message(
                {
                    "id": message.get("id"),
                    "result": {
                        "contentItems": [
                            {"type": "inputText", "text": str(result.get("result_text", ""))}
                        ],
                        "success": bool(result.get("ok")),
                    },
                },
                deadline=deadline,
            )
        except CodexAppServerError as exc:
            if exc.code in {"cancelled", "timeout"}:
                self._set_fatal(exc)
                self._terminate_process()
            return

    def _write_message(
        self,
        message: dict,
        *,
        deadline: float,
        respect_cancellation: bool = True,
    ) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            self._raise_if_fatal()
            raise CodexAppServerError("protocol_error", "App Server process is not running")
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        while True:
            if (
                respect_cancellation
                and self.cancel_event is not None
                and self.cancel_event.is_set()
            ):
                raise CodexAppServerError("cancelled", "App Server request was cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAppServerError("timeout", "App Server stdin write timed out")
            if self._writer_lock.acquire(timeout=min(remaining, 0.1)):
                break
        try:
            file_descriptor = process.stdin.fileno()
            try:
                os.set_blocking(file_descriptor, False)
            except (BrokenPipeError, OSError) as exc:
                raise CodexAppServerError("protocol_error", "App Server stdin closed") from exc
            payload_view = memoryview(payload)
            bytes_written = 0
            while bytes_written < len(payload_view):
                self._raise_if_fatal()
                if (
                    respect_cancellation
                    and self.cancel_event is not None
                    and self.cancel_event.is_set()
                ):
                    raise CodexAppServerError("cancelled", "App Server request was cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexAppServerError("timeout", "App Server stdin write timed out")
                if process.poll() is not None:
                    self._raise_if_fatal()
                    raise CodexAppServerError("protocol_error", "App Server process is not running")
                try:
                    _, writable, _ = select.select(
                        [],
                        [file_descriptor],
                        [],
                        min(remaining, 0.1),
                    )
                except (OSError, ValueError) as exc:
                    raise CodexAppServerError("protocol_error", "App Server stdin closed") from exc
                if not writable:
                    continue
                try:
                    count = os.write(file_descriptor, payload_view[bytes_written:])
                except BlockingIOError:
                    continue
                except InterruptedError:
                    continue
                except (BrokenPipeError, OSError) as exc:
                    raise CodexAppServerError("protocol_error", "App Server stdin closed") from exc
                if count <= 0:
                    raise CodexAppServerError("protocol_error", "App Server stdin closed")
                bytes_written += count
        finally:
            self._writer_lock.release()

    def _set_fatal(self, error: CodexAppServerError) -> None:
        with self._notification_condition:
            if self._fatal_error is None:
                self._fatal_error = error
            self._notification_condition.notify_all()

    def _raise_if_fatal(self) -> None:
        with self._state_lock:
            self._raise_if_fatal_locked()

    def _raise_if_fatal_locked(self) -> None:
        if self._fatal_error is not None:
            raise self._fatal_error

    def _terminate_process(self) -> None:
        with self._process_lock:
            process = self.process
            if process is None:
                return
            process_group_id = process.pid
            process_alive = process.poll() is None
            group_alive = _process_group_alive(process_group_id)
            if not process_alive and not group_alive:
                return
            try:
                os.killpg(process_group_id, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                if process_alive:
                    process.terminate()
            term_deadline = time.monotonic() + 2
            if process_alive:
                try:
                    process.wait(timeout=max(0.0, term_deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    pass
            while _process_group_alive(process_group_id) and time.monotonic() < term_deadline:
                time.sleep(0.02)

            group_alive = _process_group_alive(process_group_id)
            if process.poll() is None or group_alive:
                try:
                    os.killpg(process_group_id, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    if process.poll() is None:
                        process.kill()
                kill_deadline = time.monotonic() + 2
                if process.poll() is None:
                    try:
                        process.wait(timeout=max(0.0, kill_deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        pass
                while _process_group_alive(process_group_id) and time.monotonic() < kill_deadline:
                    time.sleep(0.02)

            if process.poll() is None or _process_group_alive(process_group_id):
                raise CodexAppServerError(
                    "resource_cleanup_failed",
                    "Codex App Server process group could not be reclaimed",
                )


def resolve_command(executable: str = "codex") -> list[str]:
    """Resolve the fixed App Server argv and least-privilege overrides."""
    if is_native_windows():
        raise CodexAppServerError(
            "capability_unsupported",
            "Codex App Server Agent is not supported on native Windows in this phase",
        )
    resolved = shutil.which(executable)
    if resolved is None:
        raise CodexAppServerError("command_not_found", "Codex executable was not found")
    command = [resolved, "app-server", "--stdio"]
    for override in _BASE_CONFIG_OVERRIDES:
        command.extend(["-c", override])
    return command


def harden_command_against_configured_mcp(
    command: Sequence[str],
    *,
    timeout: float,
    deadline: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> list[str]:
    """Discover effective MCP config keys, then disable each via transient overrides."""
    empty_surface = ToolSurface.empty()
    with CodexAppServerTransport(
        command,
        tool_surface=empty_surface,
        tool_context=ToolAccessContext(),
        request_timeout=timeout,
        deadline=deadline,
        cancel_event=cancel_event,
    ) as client:
        assert client.safe_cwd is not None
        result = client.request("config/read", {"cwd": str(client.safe_cwd), "includeLayers": False})
        config = result.get("config")
        if not isinstance(config, dict):
            raise CodexAppServerError("protocol_error", "config/read did not return an effective config")
        mcp_servers = config.get("mcp_servers") or {}
        if not isinstance(mcp_servers, dict) or not all(isinstance(name, str) for name in mcp_servers):
            raise CodexAppServerError("protocol_error", "config/read returned invalid MCP configuration")

    hardened = list(command)
    for name in sorted(mcp_servers):
        if _TOML_BARE_KEY.fullmatch(name) is None:
            raise CodexAppServerError(
                "unsupported_mcp_name",
                "Configured MCP name cannot be safely expressed as a transient CLI override",
            )
        hardened.extend(["-c", f"mcp_servers.{name}.enabled=false"])
    return hardened


def build_hardened_command(
    *,
    timeout: float,
    executable: str = "codex",
    deadline: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> list[str]:
    """Build the fixed production argv with every configured MCP disabled."""
    return harden_command_against_configured_mcp(
        resolve_command(executable),
        timeout=timeout,
        deadline=deadline,
        cancel_event=cancel_event,
    )
