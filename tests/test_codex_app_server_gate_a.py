# -*- coding: utf-8 -*-
"""Deterministic tests for the isolated Codex App Server Gate A harness."""

from __future__ import annotations

import json
import functools
import os
import sqlite3
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from scripts.codex_app_server_gate_a import (
    MAX_STDERR_BYTES,
    MAX_STDOUT_FRAME_BYTES,
    MAX_TOOL_RESULT_BYTES,
    PERMISSION_PROFILE,
    CodexAppServerTransport,
    GateAError,
    _calls_overlap,
    _controlled_environment,
    _harden_command_against_configured_mcp,
    _resolve_command,
)
from src.agent.tool_surface import ToolSurface
from src.agent.codex_tool_process import CodexToolProcessRunner
from src.agent.tools.execution import ToolAccessContext
from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolPolicy, ToolRegistry


_FAKE_APP_SERVER = r"""
import json
import sys
import time
import os
import signal
import subprocess

mode = sys.argv[1]
thread_counter = 0
turn_counter = 0
history_valid = False


def send(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        if mode == "slow-initialize":
            time.sleep(2)
        if mode == "oversized":
            sys.stdout.buffer.write(b"{" + b"x" * (4 * 1024 * 1024 + 1) + b"\n")
            sys.stdout.buffer.flush()
            time.sleep(2)
            continue
        sys.stderr.write("Authorization: Bearer secret-token-1234567890 /Users/massif/private/file\n")
        sys.stderr.flush()
        send({"id": request_id, "result": {"userAgent": "fake"}})
    elif method == "initialized":
        send({"method": "future/notification", "params": {"secret": "ignored"}})
    elif method == "test/spawn_and_exit":
        child = subprocess.Popen([
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)",
        ])
        with open(sys.argv[2], "w", encoding="utf-8") as marker:
            marker.write(str(child.pid))
        send({"id": request_id, "result": {"childPid": child.pid}})
        os._exit(17)
    elif method == "test/echo-size":
        send({"id": request_id, "result": {"size": len(message["params"]["payload"])}})
    elif method == "thread/start":
        thread_counter += 1
        thread_id = f"thread-{thread_counter}"
        cwd = message["params"]["cwd"]
        if message["params"]["permissions"] != "dsa_gate_a":
            send({"id": request_id, "error": {"message": "wrong permission request"}})
            continue
        active_profile = ":read-only" if mode == "wrong-profile" else "dsa_gate_a"
        send({
            "id": request_id,
            "result": {
                "activePermissionProfile": {"id": active_profile},
                "approvalPolicy": "never",
                "cwd": cwd,
                "runtimeWorkspaceRoots": [cwd],
                "sandbox": {"type": "readOnly", "networkAccess": False},
                "thread": {"id": thread_id},
            },
        })
    elif method == "config/read":
        mcp_servers = {
            "alpha-mcp": {"enabled": False},
            "node_repl": {"enabled": False},
        }
        if mode == "unsafe-mcp-name":
            mcp_servers = {"unsafe.mcp": {"enabled": True}}
        send({
            "id": request_id,
            "result": {
                "config": {
                    "features": {"apps": False, "plugins": False},
                    "mcp_servers": mcp_servers,
                },
                "origins": {},
            },
        })
    elif method == "mcpServerStatus/list":
        tools = {"bypass": {"name": "bypass", "inputSchema": {}}} if mode == "mcp-exposed" else {}
        send({
            "id": request_id,
            "result": {
                "data": [{
                    "name": "configured",
                    "authStatus": "unsupported",
                    "tools": tools,
                    "resources": [],
                    "resourceTemplates": [],
                }],
                "nextCursor": None,
            },
        })
    elif method == "thread/inject_items":
        items = message["params"]["items"]
        history_valid = (
            len(items) == 2
            and items[0]["role"] == "user"
            and items[0]["content"][0]["type"] == "input_text"
            and items[1]["role"] == "assistant"
            and items[1]["content"][0]["type"] == "output_text"
        )
        send({"id": request_id, "result": {}})
    elif method == "command/exec":
        params = message["params"]
        send({
            "id": request_id,
            "result": {
                "exitCode": 7,
                "stdout": json.dumps({
                    "command": params["command"],
                    "cwd": params["cwd"],
                    "permissionProfile": params["permissionProfile"],
                    "tty": params["tty"],
                }),
                "stderr": "blocked",
            },
        })
    elif method == "turn/start":
        if mode == "turn-start-error":
            send({"id": request_id, "error": {"message": "turn/start rejected"}})
            continue
        if message["params"]["permissions"] != "dsa_gate_a":
            send({"id": request_id, "error": {"message": "wrong turn permission"}})
            continue
        turn_counter += 1
        turn_id = f"turn-{turn_counter}"
        thread_id = message["params"]["threadId"]
        send({"id": request_id, "result": {"turn": {"id": turn_id, "items": [], "status": "inProgress"}}})
        if mode == "aggregate-output":
            for _ in range(6):
                send({
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "itemId": "a",
                        "delta": "x" * (1024 * 1024),
                    },
                })
            time.sleep(2)
            continue
        if mode == "tool-flood":
            for index in range(4):
                send({
                    "id": 800 + index,
                    "method": "item/tool/call",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "callId": str(index),
                        "tool": "probe",
                        "arguments": {"label": str(index)},
                    },
                })
            time.sleep(2)
            continue
        if mode == "item-flood":
            for index in range(1025):
                send({
                    "method": "item/completed",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": {"id": f"item-{index}", "type": "reasoning"},
                    },
                })
            time.sleep(2)
            continue
        if mode == "unknown":
            send({"id": 700, "method": "currentTime/read", "params": {}})
            time.sleep(2)
            continue
        if mode == "approval":
            send({"id": 701, "method": "item/commandExecution/requestApproval", "params": {}})
            time.sleep(2)
            continue
        if mode == "timeout":
            time.sleep(2)
            continue
        if mode == "history":
            text = "HISTORY_OK" if history_valid else "HISTORY_BAD"
            send({
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {"id": "a", "type": "agentMessage", "text": text, "phase": "final_answer"},
                },
            })
            send({
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "status": "completed",
                        "itemsView": "notLoaded",
                        "items": [],
                    },
                },
            })
            continue
        if mode == "unauthorized":
            send({
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "status": "failed",
                        "items": [],
                        "error": {
                            "codexErrorInfo": "Unauthorized",
                            "message": "Sign in required",
                        },
                    },
                },
            })
            continue
        if mode in {"commentary-only", "delta-only", "mixed-final", "legacy-none", "turn-items-only"}:
            if mode == "delta-only":
                send({
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "itemId": "delta",
                        "delta": "DELTA_MUST_NOT_BE_FINAL",
                    },
                })
            terminal_items = {
                "commentary-only": [
                    {"id": "commentary", "type": "agentMessage", "text": "COMMENTARY", "phase": "commentary"},
                ],
                "delta-only": [],
                "mixed-final": [
                    {"id": "commentary", "type": "agentMessage", "text": "COMMENTARY", "phase": "commentary"},
                    {"id": "legacy", "type": "agentMessage", "text": "LEGACY", "phase": None},
                    {"id": "final-1", "type": "agentMessage", "text": "FINAL_1", "phase": "final_answer"},
                    {"id": "final-2", "type": "agentMessage", "text": "|FINAL_2", "phase": "final_answer"},
                ],
                "legacy-none": [
                    {"id": "legacy-1", "type": "agentMessage", "text": "LEGACY_1", "phase": None},
                    {"id": "legacy-2", "type": "agentMessage", "text": "|LEGACY_2", "phase": None},
                ],
                "turn-items-only": [],
            }[mode]
            for item in terminal_items:
                send({
                    "method": "item/completed",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": item,
                    },
                })
            turn_items = []
            if mode == "turn-items-only":
                turn_items = [
                    {"id": "turn-only", "type": "agentMessage", "text": "TURN_ITEM", "phase": "final_answer"},
                ]
            send({
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "status": "completed",
                        "itemsView": "full" if turn_items else "notLoaded",
                        "items": turn_items,
                    },
                },
            })
            continue
        if mode == "blocking":
            send({
                "id": 800,
                "method": "item/tool/call",
                "params": {"threadId": thread_id, "turnId": turn_id, "callId": "a", "tool": "probe", "arguments": {"label": "alpha"}},
            })
            while True:
                response = json.loads(sys.stdin.readline())
                if response.get("method") == "turn/interrupt":
                    send({"id": response["id"], "result": {}})
                    send({
                        "method": "turn/completed",
                        "params": {
                            "threadId": thread_id,
                            "turn": {"id": turn_id, "status": "interrupted", "items": []},
                        },
                    })
                    break
                if response.get("id") == 800:
                    continue
            continue
        send({
            "id": 800,
            "method": "item/tool/call",
            "params": {"threadId": thread_id, "turnId": turn_id, "callId": "a", "tool": "probe", "arguments": {"label": "alpha"}},
        })
        send({
            "id": 801,
            "method": "item/tool/call",
            "params": {"threadId": thread_id, "turnId": turn_id, "callId": "b", "tool": "probe", "arguments": {"label": "beta"}},
        })
        results = {}
        while len(results) < 2:
            response = json.loads(sys.stdin.readline())
            results[response["id"]] = json.loads(response["result"]["contentItems"][0]["text"])["token"]
        text = results[800] + "|" + results[801]
        send({
            "method": "item/agentMessage/delta",
            "params": {"threadId": thread_id, "turnId": turn_id, "itemId": "a", "delta": text},
        })
        send({
            "method": "item/completed",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "item": {"id": "a", "type": "agentMessage", "text": text, "phase": "final_answer"},
            },
        })
        send({
            "method": "turn/completed",
            "params": {
                "threadId": thread_id,
                "turn": {
                    "id": turn_id,
                    "status": "completed",
                    "itemsView": "notLoaded",
                    "items": [],
                },
            },
        })
"""


def _probe_process_worker(tool_name: str, arguments: dict, _context: ToolAccessContext) -> dict:
    time.sleep(0.2)
    result = {"token": str(arguments["label"]).upper()}
    return {
        "ok": True,
        "tool_name": tool_name,
        "result": result,
        "result_text": json.dumps(result),
        "error": None,
        "audit": {},
        "diagnostics": {},
    }


def _output_too_large_process_worker(
    tool_name: str,
    _arguments: dict,
    _context: ToolAccessContext,
) -> dict:
    return {
        "ok": False,
        "tool_name": tool_name,
        "result_text": json.dumps({"error": "output_too_large"}),
        "error": {
            "code": "output_too_large",
            "message": "Tool result exceeded the IPC output limit.",
            "retriable": False,
            "details": {},
        },
    }


def _blocking_probe_process_worker(
    tool_name: str,
    arguments: dict,
    _context: ToolAccessContext,
    *,
    marker_path: str,
) -> dict:
    Path(marker_path).write_text(str(os.getpid()), encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "WITH RECURSIVE cnt(x) AS (VALUES(0) UNION ALL SELECT x + 1 FROM cnt WHERE x < 500000000) "
            "SELECT sum(x) FROM cnt"
        ).fetchone()
    finally:
        connection.close()
    return _probe_process_worker(tool_name, arguments, _context)


def _fake_command(tmp_path: Path, mode: str) -> list[str]:
    script = tmp_path / "fake_app_server.py"
    script.write_text(textwrap.dedent(_FAKE_APP_SERVER), encoding="utf-8")
    return [sys.executable, str(script), mode]


def _surface(timing: list[tuple[str, float, float]] | None = None) -> ToolSurface:
    calls = timing if timing is not None else []
    registry = ToolRegistry()

    def probe(label: str) -> dict:
        started = time.monotonic()
        time.sleep(0.2)
        finished = time.monotonic()
        calls.append((label, started, finished))
        return {"token": label.upper()}

    registry.register(
        ToolDefinition(
            name="probe",
            description="Probe",
            parameters=[ToolParameter(name="label", type="string", description="Label")],
            handler=probe,
            policy=ToolPolicy.declared(read_only=True),
        )
    )
    return ToolSurface(registry)


def _transport(tmp_path: Path, mode: str, *, timeout: float = 3.0) -> CodexAppServerTransport:
    return CodexAppServerTransport(
        _fake_command(tmp_path, mode),
        tool_surface=_surface(),
        tool_context=ToolAccessContext(max_result_bytes=MAX_TOOL_RESULT_BYTES),
        request_timeout=timeout,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
    )


def _blocked_stdin_transport(
    *,
    request_timeout: float,
    cancel_event: threading.Event | None = None,
) -> tuple[CodexAppServerTransport, subprocess.Popen]:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    client = CodexAppServerTransport(
        ["unused"],
        tool_surface=_surface(),
        tool_context=ToolAccessContext(),
        request_timeout=request_timeout,
        cancel_event=cancel_event,
    )
    client.process = process
    return client, process


def _run_blocked_request(client: CodexAppServerTransport, state: dict) -> None:
    try:
        client.request("test/blocked-write", {"payload": "x" * (2 * 1024 * 1024)})
    except GateAError as exc:
        state["code"] = exc.code


def _assert_blocked_write_finishes(
    *,
    expected_code: str,
    request_timeout: float,
    cancel_event: threading.Event | None = None,
    hold_writer_lock: bool = False,
) -> None:
    client, process = _blocked_stdin_transport(
        request_timeout=request_timeout,
        cancel_event=cancel_event,
    )
    state: dict = {}
    request_thread = threading.Thread(
        target=_run_blocked_request,
        args=(client, state),
        name=f"codex-blocked-write-{expected_code}",
    )
    if hold_writer_lock:
        client._writer_lock.acquire()
    try:
        request_thread.start()
        if cancel_event is not None:
            time.sleep(0.1)
            cancel_event.set()
        request_thread.join(timeout=1)

        assert request_thread.is_alive() is False
        assert state == {"code": expected_code}
        assert client._pending == {}
        assert process.poll() is not None
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
    finally:
        if hold_writer_lock:
            client._writer_lock.release()
        if request_thread.is_alive():
            client._terminate_process()
            request_thread.join(timeout=2)
        client.close()


def test_blocked_stdin_write_obeys_request_timeout() -> None:
    _assert_blocked_write_finishes(
        expected_code="timeout",
        request_timeout=0.2,
    )


def test_blocked_stdin_write_obeys_cancel_event() -> None:
    _assert_blocked_write_finishes(
        expected_code="cancelled",
        request_timeout=5,
        cancel_event=threading.Event(),
    )


@pytest.mark.parametrize(
    ("expected_code", "request_timeout", "should_cancel"),
    [
        ("timeout", 0.2, False),
        ("cancelled", 5, True),
    ],
)
def test_writer_lock_wait_obeys_request_boundary(
    expected_code: str,
    request_timeout: float,
    should_cancel: bool,
) -> None:
    _assert_blocked_write_finishes(
        expected_code=expected_code,
        request_timeout=request_timeout,
        cancel_event=threading.Event() if should_cancel else None,
        hold_writer_lock=True,
    )


def test_large_request_is_fully_written_across_pipe_capacity(tmp_path: Path) -> None:
    payload = "x" * (2 * 1024 * 1024)
    with _transport(tmp_path, "history", timeout=5) as client:
        result = client.request("test/echo-size", {"payload": payload})

    assert result == {"size": len(payload)}


def test_tool_result_write_timeout_is_published_before_cleanup(monkeypatch) -> None:
    client, process = _blocked_stdin_transport(request_timeout=5)
    client._thread_tools["thread-1"] = {"probe"}
    monkeypatch.setattr(
        client._tool_runner,
        "execute",
        lambda *_args, **_kwargs: {"ok": True, "result_text": "{}"},
    )

    def fail_write(*_args, **_kwargs) -> None:
        raise GateAError("timeout", "App Server stdin write timed out")

    monkeypatch.setattr(client, "_write_message", fail_write)
    try:
        client._execute_tool_request(
            {
                "id": 800,
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "tool": "probe",
                    "arguments": {"label": "alpha"},
                },
            }
        )

        with pytest.raises(GateAError) as exc_info:
            client._raise_if_fatal()
        assert exc_info.value.code == "timeout"
        assert process.poll() is not None
    finally:
        client.close()


def test_parallel_dynamic_tool_requests_roundtrip_and_transport_limits(tmp_path: Path) -> None:
    timing: list[tuple[str, float, float]] = []
    client = CodexAppServerTransport(
        _fake_command(tmp_path, "parallel"),
        tool_surface=_surface(timing),
        tool_context=ToolAccessContext(max_result_bytes=MAX_TOOL_RESULT_BYTES),
        request_timeout=3,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        tool_runner=CodexToolProcessRunner(worker=_probe_process_worker),
    )
    with client:
        assert client.safe_cwd is not None
        safe_cwd = client.safe_cwd
        assert stat.S_IMODE(safe_cwd.stat().st_mode) == 0o700
        thread_id = client.start_thread(tool_names=["probe"], base_instructions="DSA", developer_instructions="probe")
        isolation = client.inspect_external_tool_isolation(thread_id)
        result = client.run_turn(thread_id, "probe")
        calls = [call for call in client.tool_calls if call.turn_id == result.turn_id]

        assert result.final_text == "ALPHA|BETA"
        assert isolation == {
            "passed": True,
            "apps_disabled": True,
            "plugins_disabled": True,
            "configured_mcp_count": 2,
            "configured_mcp_disabled": True,
            "visible_mcp_server_count": 1,
            "visible_mcp_capability_count": 0,
        }
        assert len(calls) == 2
        assert _calls_overlap(calls)
        assert timing == []
        assert client._completed_turns == {}
        assert "secret-token-1234567890" not in client.stderr_preview
        assert "/Users/massif/private/file" not in client.stderr_preview
        assert len(client.stderr_preview.encode("utf-8")) <= MAX_STDERR_BYTES
        assert MAX_STDOUT_FRAME_BYTES == 4 * 1024 * 1024
        assert MAX_TOOL_RESULT_BYTES == 1024 * 1024
    assert not safe_cwd.exists()


def test_transport_cancel_reaps_blocking_tool_before_close_returns(tmp_path: Path) -> None:
    marker = tmp_path / "transport-blocking.marker"
    cancel_event = threading.Event()
    runner = CodexToolProcessRunner(
        worker=functools.partial(
            _blocking_probe_process_worker,
            marker_path=str(marker),
        )
    )
    baseline_threads = {thread.name for thread in threading.enumerate()}
    client = CodexAppServerTransport(
        _fake_command(tmp_path, "blocking"),
        tool_surface=_surface(),
        tool_context=ToolAccessContext(
            cancel_event=cancel_event,
            deadline=time.monotonic() + 30,
            max_result_bytes=MAX_TOOL_RESULT_BYTES,
        ),
        request_timeout=30,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        cancel_event=cancel_event,
        tool_runner=runner,
    )
    turn_state: dict = {}

    with client:
        thread_id = client.start_thread(
            tool_names=["probe"],
            base_instructions="DSA",
            developer_instructions="probe",
        )

        def run_turn() -> None:
            try:
                client.run_turn(thread_id, "probe", cancel_event=cancel_event)
            except GateAError as exc:
                turn_state["code"] = exc.code

        turn_thread = threading.Thread(target=run_turn, name="transport-cancel-turn")
        turn_thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.02)
        assert marker.exists()
        cancel_started = time.monotonic()
        cancel_event.set()
        turn_thread.join(timeout=3)
        assert turn_thread.is_alive() is False
        assert time.monotonic() - cancel_started < 1

    assert turn_state["code"] == "cancelled"
    records = runner.snapshot()
    assert len(records) == 1
    assert records[0]["termination_reason"] == "cancelled"
    assert records[0]["pid_alive_after"] is False
    time.sleep(0.1)
    remaining_threads = {thread.name for thread in threading.enumerate()} - baseline_threads
    assert not {name for name in remaining_threads if name.startswith("codex-")}


def test_history_injection_preserves_user_and_assistant_roles(tmp_path: Path) -> None:
    with _transport(tmp_path, "history") as client:
        thread_id = client.start_thread(tool_names=[], base_instructions="DSA", developer_instructions="roles")
        client.inject_history(
            thread_id,
            [
                {"role": "user", "content": "user message"},
                {"role": "assistant", "content": "assistant message"},
            ],
        )
        result = client.run_turn(thread_id, "recall")

    assert result.final_text == "HISTORY_OK"


@pytest.mark.parametrize(
    ("mode", "expected_text"),
    [
        ("commentary-only", ""),
        ("delta-only", ""),
        ("mixed-final", "FINAL_1|FINAL_2"),
        ("legacy-none", "LEGACY_1|LEGACY_2"),
        ("turn-items-only", ""),
    ],
)
def test_terminal_answer_uses_only_completed_item_events(
    tmp_path: Path,
    mode: str,
    expected_text: str,
) -> None:
    with _transport(tmp_path, mode) as client:
        thread_id = client.start_thread(
            tool_names=[],
            base_instructions="DSA",
            developer_instructions="terminal answer",
        )
        result = client.run_turn(thread_id, "answer")

    assert result.final_text == expected_text


def test_transport_overall_deadline_bounds_initialize(tmp_path: Path) -> None:
    started_at = time.monotonic()
    client = CodexAppServerTransport(
        _fake_command(tmp_path, "slow-initialize"),
        tool_surface=_surface(),
        tool_context=ToolAccessContext(),
        request_timeout=3,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        deadline=started_at + 0.2,
    )

    with pytest.raises(GateAError) as exc_info:
        client.start()

    assert exc_info.value.code == "timeout"
    assert exc_info.value.turn_started is False
    assert time.monotonic() - started_at < 1.0


def test_transport_cancellation_interrupts_initialize(tmp_path: Path) -> None:
    cancel_event = threading.Event()
    timer = threading.Timer(0.1, cancel_event.set)
    client = CodexAppServerTransport(
        _fake_command(tmp_path, "slow-initialize"),
        tool_surface=_surface(),
        tool_context=ToolAccessContext(),
        request_timeout=3,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        cancel_event=cancel_event,
    )
    timer.start()
    try:
        with pytest.raises(GateAError) as exc_info:
            client.start()
    finally:
        timer.cancel()

    assert exc_info.value.code == "cancelled"


def test_transport_reaps_process_group_after_leader_crash(tmp_path: Path) -> None:
    marker = tmp_path / "app-server-child.pid"
    command = _fake_command(tmp_path, "leader-crash") + [str(marker)]
    client = CodexAppServerTransport(
        command,
        tool_surface=_surface(),
        tool_context=ToolAccessContext(),
        request_timeout=3,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
    )
    client.start()
    response = client.request("test/spawn_and_exit", {})
    child_pid = int(response["childPid"])
    deadline = time.monotonic() + 1
    while client.process is not None and client.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)

    client.close()

    assert marker.read_text(encoding="utf-8") == str(child_pid)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_turn_start_rejection_is_not_counted_as_started(tmp_path: Path) -> None:
    with _transport(tmp_path, "turn-start-error") as client:
        thread_id = client.start_thread(
            tool_names=[],
            base_instructions="DSA",
            developer_instructions="turn start",
        )
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "trigger")

    assert exc_info.value.code == "protocol_error"
    assert exc_info.value.turn_started is False


def test_turn_completed_unauthorized_maps_to_login_required(tmp_path: Path) -> None:
    with _transport(tmp_path, "unauthorized") as client:
        thread_id = client.start_thread(
            tool_names=[],
            base_instructions="DSA",
            developer_instructions="login",
        )
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "trigger")

    assert exc_info.value.code == "login_required"
    assert exc_info.value.turn_started is True


def test_command_probe_uses_fixed_argv_and_gate_a_permission_profile(tmp_path: Path) -> None:
    with _transport(tmp_path, "command") as client:
        assert client.safe_cwd is not None
        result = client.exec_sandboxed_command(["/usr/bin/touch", "marker"])

    payload = json.loads(result["stdout"])
    assert result["exitCode"] == 7
    assert payload == {
        "command": ["/usr/bin/touch", "marker"],
        "cwd": str(client.safe_cwd),
        "permissionProfile": PERMISSION_PROFILE,
        "tty": False,
    }


def test_wrong_active_permission_profile_fails_closed(tmp_path: Path) -> None:
    with _transport(tmp_path, "wrong-profile") as client:
        with pytest.raises(GateAError) as exc_info:
            client.start_thread(tool_names=[], base_instructions="DSA", developer_instructions="profile")

    assert exc_info.value.code == "permission_profile_mismatch"


def test_exposed_mcp_capability_fails_allowlist_check(tmp_path: Path) -> None:
    with _transport(tmp_path, "mcp-exposed") as client:
        thread_id = client.start_thread(tool_names=[], base_instructions="DSA", developer_instructions="mcp")
        isolation = client.inspect_external_tool_isolation(thread_id)

    assert isolation["passed"] is False
    assert isolation["visible_mcp_capability_count"] == 1


def test_command_configuration_defines_profile_and_disables_inherited_tools(tmp_path: Path) -> None:
    command = _resolve_command(sys.executable)
    overrides = command[command.index("--stdio") + 1 :]

    assert 'default_permissions="dsa_gate_a"' in overrides
    assert 'permissions.dsa_gate_a.filesystem={":minimal"="read",":workspace_roots"={"."="read"}}' in overrides
    assert "permissions.dsa_gate_a.network.enabled=false" in overrides
    assert "features.apps=false" in overrides
    assert "features.plugins=false" in overrides
    assert "mcp_servers={}" not in overrides
    assert not any("sandbox_mode" in value for value in overrides)

    hardened = _harden_command_against_configured_mcp(
        _fake_command(tmp_path, "history"),
        timeout=3,
    )
    assert "mcp_servers.alpha-mcp.enabled=false" in hardened
    assert "mcp_servers.node_repl.enabled=false" in hardened
    assert not any('mcp_servers."' in value for value in hardened)

    with pytest.raises(GateAError) as exc_info:
        _harden_command_against_configured_mcp(
            _fake_command(tmp_path, "unsafe-mcp-name"),
            timeout=3,
        )
    assert exc_info.value.code == "unsupported_mcp_name"


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [("unknown", "protocol_error"), ("approval", "approval_required")],
)
def test_unexpected_server_requests_fail_closed(tmp_path: Path, mode: str, expected_code: str) -> None:
    with _transport(tmp_path, mode) as client:
        thread_id = client.start_thread(tool_names=[], base_instructions="DSA", developer_instructions="fail")
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "trigger")

    assert exc_info.value.code == expected_code


def test_oversized_stdout_frame_terminates_transport(tmp_path: Path) -> None:
    client = _transport(tmp_path, "oversized")
    with pytest.raises(GateAError) as exc_info:
        client.start()
    safe_cwd = client.safe_cwd
    client.close()

    assert exc_info.value.code == "output_too_large"
    assert safe_cwd is not None and not safe_cwd.exists()


def test_many_valid_frames_share_one_cumulative_output_budget(tmp_path: Path) -> None:
    client = _transport(tmp_path, "aggregate-output")
    with client:
        thread_id = client.start_thread(
            tool_names=["probe"],
            base_instructions="DSA",
            developer_instructions="probe",
        )
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "flood")

    assert exc_info.value.code == "output_too_large"


def test_tool_request_queue_is_bounded_by_agent_max_steps(tmp_path: Path) -> None:
    client = CodexAppServerTransport(
        _fake_command(tmp_path, "tool-flood"),
        tool_surface=_surface(),
        tool_context=ToolAccessContext(max_result_bytes=MAX_TOOL_RESULT_BYTES),
        request_timeout=3,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        tool_runner=CodexToolProcessRunner(worker=_probe_process_worker),
        max_tool_calls=3,
    )
    with client:
        thread_id = client.start_thread(
            tool_names=["probe"],
            base_instructions="DSA",
            developer_instructions="probe",
        )
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "flood")

    assert exc_info.value.code == "resource_limit_exceeded"


def test_tool_output_limit_is_a_terminal_turn_error(tmp_path: Path) -> None:
    client = CodexAppServerTransport(
        _fake_command(tmp_path, "blocking"),
        tool_surface=_surface(),
        tool_context=ToolAccessContext(max_result_bytes=MAX_TOOL_RESULT_BYTES),
        request_timeout=3,
        environment={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        tool_runner=CodexToolProcessRunner(worker=_output_too_large_process_worker),
    )
    with client:
        thread_id = client.start_thread(
            tool_names=["probe"],
            base_instructions="DSA",
            developer_instructions="probe",
        )
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "probe")

    assert exc_info.value.code == "output_too_large"


def test_completed_items_share_one_cumulative_turn_budget(tmp_path: Path) -> None:
    client = _transport(tmp_path, "item-flood")
    with client:
        thread_id = client.start_thread(
            tool_names=[],
            base_instructions="DSA",
            developer_instructions="item budget",
        )
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "flood")

    assert exc_info.value.code == "resource_limit_exceeded"


def test_turn_timeout_terminates_process_group(tmp_path: Path) -> None:
    with _transport(tmp_path, "timeout", timeout=0.25) as client:
        thread_id = client.start_thread(tool_names=[], base_instructions="DSA", developer_instructions="timeout")
        with pytest.raises(GateAError) as exc_info:
            client.run_turn(thread_id, "wait", timeout=0.25)
        assert client.process is not None
        assert client.process.poll() is not None

    assert exc_info.value.code == "timeout"
    assert exc_info.value.turn_started is True


def test_controlled_environment_does_not_inherit_application_secrets() -> None:
    environment = _controlled_environment(
        {
            "HOME": "/tmp/home",
            "PATH": "/usr/bin",
            "OPENAI_API_KEY": "secret",
            "DATABASE_URL": "postgres://secret",
            "GITHUB_TOKEN": "secret",
            "WEBHOOK_URL": "https://secret",
        }
    )

    assert environment == {"HOME": "/tmp/home", "PATH": "/usr/bin"}
    assert _controlled_environment({}) == {}
