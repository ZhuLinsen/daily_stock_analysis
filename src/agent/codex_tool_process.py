# -*- coding: utf-8 -*-
"""Process-owned execution boundary for Codex dynamic tool calls.

The App Server transport may use threads for protocol dispatch, but DSA tool
handlers run only in spawned child processes.  Cancellation and deadlines can
therefore end database work by terminating the process group that owns it.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from src.agent.tools.execution import ToolAccessContext


# Gate P observed cooperative TERM completion in under 25 ms.  The grace keeps
# normal interpreter cleanup possible without making user cancellation unbounded.
TOOL_PROCESS_TERM_GRACE_SECONDS = 0.5
TOOL_PROCESS_KILL_GRACE_SECONDS = 2.0
TOOL_PROCESS_NORMAL_EXIT_GRACE_SECONDS = 2.0
TOOL_PROCESS_POLL_SECONDS = 0.02

# ToolSurface limits external result text to 1 MiB.  IPC keeps the JSON metadata
# separate from raw UTF-8 result bytes so JSON escaping cannot change that limit.
MAX_TOOL_RESULT_BYTES = 1024 * 1024
MAX_TOOL_PROCESS_HEADER_BYTES = 64 * 1024
MAX_TOOL_PROCESS_FRAME_BYTES = 1 + 4 + MAX_TOOL_PROCESS_HEADER_BYTES + MAX_TOOL_RESULT_BYTES

ToolWorker = Callable[[str, dict, ToolAccessContext], dict]


class _ToolProcessOutputTooLarge(ValueError):
    pass


@dataclass
class _OwnedToolProcess:
    process: Any
    pid: int
    ready: bool = False
    termination_reason: Optional[str] = None
    isolation_valid: bool = True
    cleanup_complete: bool = False
    cleanup_ok: bool = False
    cleanup_lock: threading.Lock = field(default_factory=threading.Lock)


def _encode_json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _send_frame(connection: Any, payload: dict) -> None:
    encoded = _encode_json(payload)
    if len(encoded) > MAX_TOOL_PROCESS_HEADER_BYTES:
        raise ValueError("tool process metadata exceeded the IPC header limit")
    connection.send_bytes(b"J" + encoded)


def _send_result_frame(connection: Any, payload: dict) -> None:
    result_text = str(payload.get("result_text", ""))
    result_bytes = result_text.encode("utf-8")
    if len(result_bytes) > MAX_TOOL_RESULT_BYTES:
        raise _ToolProcessOutputTooLarge("tool result exceeded the IPC result limit")
    header = {
        "type": "result",
        "payload": {
            "ok": bool(payload.get("ok")),
            "tool_name": payload.get("tool_name"),
            "error": payload.get("error"),
        },
    }
    encoded_header = _encode_json(header)
    if len(encoded_header) > MAX_TOOL_PROCESS_HEADER_BYTES:
        raise ValueError("tool result metadata exceeded the IPC header limit")
    connection.send_bytes(
        b"R" + struct.pack("!I", len(encoded_header)) + encoded_header + result_bytes
    )


def _decode_frame(raw_frame: bytes) -> dict:
    if raw_frame.startswith(b"J"):
        frame = json.loads(raw_frame[1:])
    elif raw_frame.startswith(b"R") and len(raw_frame) >= 5:
        header_size = struct.unpack("!I", raw_frame[1:5])[0]
        if header_size > MAX_TOOL_PROCESS_HEADER_BYTES or 5 + header_size > len(raw_frame):
            raise ValueError("invalid tool result header length")
        frame = json.loads(raw_frame[5 : 5 + header_size])
        result_bytes = raw_frame[5 + header_size :]
        if len(result_bytes) > MAX_TOOL_RESULT_BYTES:
            raise ValueError("tool result exceeded the IPC result limit")
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("invalid tool result metadata")
        payload["result_text"] = result_bytes.decode("utf-8")
    else:
        raise ValueError("unknown tool process frame type")
    if not isinstance(frame, dict):
        raise ValueError("tool process frame must be an object")
    return frame


def _context_payload(context: ToolAccessContext) -> dict:
    stock_scope = context.stock_scope
    stock_payload = None
    if stock_scope is not None:
        stock_payload = {
            "expected_stock_code": str(getattr(stock_scope, "expected_stock_code", "") or ""),
            "allowed_stock_codes": sorted(
                str(code) for code in (getattr(stock_scope, "allowed_stock_codes", set()) or set())
            ),
            "mode": str(getattr(stock_scope, "mode", "maintain") or "maintain"),
        }
    return {
        "stock_scope": stock_payload,
        "market": context.market,
        "time_range": context.time_range,
        "data_sources": context.data_sources,
        "backend": context.backend,
        "session_id": context.session_id,
        "timeout_seconds": context.timeout_seconds,
        "deadline": context.deadline,
        "max_result_bytes": context.max_result_bytes,
        "redact_result": context.redact_result,
        "audit_context": context.audit_context,
    }


def _context_from_payload(payload: dict) -> ToolAccessContext:
    from src.agent.stock_scope import StockScope

    stock_payload = payload.get("stock_scope")
    stock_scope = None
    if isinstance(stock_payload, dict):
        stock_scope = StockScope(
            expected_stock_code=str(stock_payload.get("expected_stock_code") or ""),
            allowed_stock_codes={
                str(code) for code in (stock_payload.get("allowed_stock_codes") or [])
            },
            mode=str(stock_payload.get("mode") or "maintain"),
        )
    return ToolAccessContext(
        stock_scope=stock_scope,
        market=payload.get("market"),
        time_range=payload.get("time_range"),
        data_sources=payload.get("data_sources"),
        backend=payload.get("backend"),
        session_id=payload.get("session_id"),
        timeout_seconds=payload.get("timeout_seconds"),
        deadline=payload.get("deadline"),
        cancel_event=None,
        max_result_bytes=payload.get("max_result_bytes"),
        redact_result=bool(payload.get("redact_result")),
        audit_context=payload.get("audit_context") or {},
    )


def _execute_registered_tool(
    tool_name: str,
    arguments: dict,
    context: ToolAccessContext,
) -> dict:
    # Import only after the child owns a new process group.  This prevents the
    # worker from inheriting a cached registry or database connections.
    from src.agent.factory import get_tool_registry
    from src.agent.tool_surface import ToolSurface

    return ToolSurface(get_tool_registry()).execute_tool(tool_name, arguments, context)


def _tool_process_entry(
    connection: Any,
    request_json: str,
    worker: ToolWorker,
) -> None:
    try:
        os.setsid()
        if os.getpgrp() != os.getpid():
            raise RuntimeError("tool worker did not acquire its own process group")
        _send_frame(connection, {"type": "ready"})

        request = json.loads(request_json)
        result = worker(
            str(request["tool_name"]),
            request["arguments"],
            _context_from_payload(request["context"]),
        )
        if not isinstance(result, dict):
            raise TypeError("tool worker returned a non-object result")
        diagnostics = result.get("diagnostics") or {}
        if diagnostics.get("result_truncated") is True:
            result = _error_result(
                str(request["tool_name"]),
                "output_too_large",
                "Tool result exceeded the IPC output limit.",
            )
        # App Server consumes only the bounded text and success/error status.
        # Do not duplicate ToolSurface's public payload and diagnostics over IPC.
        wire_result = {
            "ok": bool(result.get("ok")),
            "tool_name": result.get("tool_name"),
            "result_text": str(result.get("result_text", "")),
            "error": result.get("error"),
        }
        _send_result_frame(connection, wire_result)
    except Exception as exc:
        try:
            _send_frame(
                connection,
                {
                    "type": "worker_error",
                    "error_type": type(exc).__name__,
                    "error_code": (
                        "output_too_large"
                        if isinstance(exc, _ToolProcessOutputTooLarge)
                        else "handler_error"
                    ),
                },
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_alive(process_group_id: int) -> bool:
    if process_group_id <= 0:
        return False
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _error_result(tool_name: str, code: str, message: str) -> dict:
    return {
        "ok": False,
        "tool_name": tool_name,
        "result": None,
        "result_text": json.dumps(
            {"error": message, "code": code, "retriable": False},
            ensure_ascii=False,
        ),
        "error": {
            "code": code,
            "message": message,
            "retriable": False,
            "details": {},
        },
    }


class CodexToolProcessRunner:
    """Own and reap every process used for one transport's DSA tool calls."""

    def __init__(self, *, worker: ToolWorker = _execute_registered_tool) -> None:
        self._worker = worker
        self._mp_context = mp.get_context("spawn")
        self._state_lock = threading.Lock()
        self._active: dict[int, _OwnedToolProcess] = {}
        self._records: list[dict] = []
        self._sequence = 0
        self._closing = False

    def execute(
        self,
        tool_name: str,
        arguments: Any,
        context: ToolAccessContext,
    ) -> dict:
        cancel_event = context.cancel_event
        if cancel_event is not None and cancel_event.is_set():
            return _error_result(tool_name, "cancelled", "Tool execution was cancelled.")
        if context.deadline is not None and time.monotonic() >= context.deadline:
            return _error_result(tool_name, "timeout", "Tool execution deadline was exceeded.")
        if not isinstance(arguments, dict):
            # Argument validation remains authoritative in ToolSurface.  Keeping
            # the original value here lets it return the existing error shape.
            serializable_arguments = arguments
        else:
            serializable_arguments = dict(arguments)
        try:
            request_json = json.dumps(
                {
                    "tool_name": tool_name,
                    "arguments": serializable_arguments,
                    "context": _context_payload(context),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return _error_result(
                tool_name,
                "tool_roundtrip_failed",
                "Tool request could not be serialized.",
            )

        receive_connection, send_connection = self._mp_context.Pipe(duplex=False)
        process = self._mp_context.Process(
            target=_tool_process_entry,
            args=(send_connection, request_json, self._worker),
            name=f"codex-tool-{tool_name}",
        )
        started_at = time.monotonic()
        with self._state_lock:
            if self._closing:
                receive_connection.close()
                send_connection.close()
                return _error_result(tool_name, "cancelled", "Tool transport is closing.")
            self._sequence += 1
            sequence = self._sequence
            try:
                process.start()
            except (OSError, RuntimeError):
                receive_connection.close()
                send_connection.close()
                return _error_result(
                    tool_name,
                    "tool_roundtrip_failed",
                    "Tool worker could not be started.",
                )
            send_connection.close()
            owner = _OwnedToolProcess(
                process=process,
                pid=int(process.pid),
            )
            self._active[sequence] = owner

        message: Optional[dict] = None
        termination_reason: Optional[str] = None
        cleanup_ok = True
        try:
            while True:
                if owner.termination_reason is not None:
                    termination_reason = owner.termination_reason
                    break
                if cancel_event is not None and cancel_event.is_set():
                    termination_reason = "cancelled"
                    break
                if context.deadline is not None and time.monotonic() >= context.deadline:
                    termination_reason = "timeout"
                    break
                if receive_connection.poll(TOOL_PROCESS_POLL_SECONDS):
                    try:
                        raw_frame = receive_connection.recv_bytes(MAX_TOOL_PROCESS_FRAME_BYTES)
                        frame = _decode_frame(raw_frame)
                    except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                        message = None
                        break
                    if not isinstance(frame, dict):
                        message = None
                        break
                    if frame.get("type") == "ready":
                        owner.ready = True
                        continue
                    message = frame
                    break
                if not process.is_alive():
                    while receive_connection.poll(0.1):
                        try:
                            raw_frame = receive_connection.recv_bytes(MAX_TOOL_PROCESS_FRAME_BYTES)
                            frame = _decode_frame(raw_frame)
                        except (EOFError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                            message = None
                            break
                        if not isinstance(frame, dict):
                            message = None
                            break
                        if frame.get("type") == "ready":
                            owner.ready = True
                            continue
                        message = frame
                        break
                    break

            if termination_reason is None and owner.termination_reason is not None:
                termination_reason = owner.termination_reason
            if termination_reason is not None:
                cleanup_ok = self._terminate(owner, termination_reason)
            else:
                process.join(timeout=TOOL_PROCESS_NORMAL_EXIT_GRACE_SECONDS)
                if process.is_alive():
                    cleanup_ok = self._terminate(owner, "resource_cleanup_failed")
                    termination_reason = "resource_cleanup_failed"
                elif owner.ready and _process_group_alive(owner.pid):
                    result_was_sent = isinstance(message, dict) and message.get("type") == "result"
                    cleanup_ok = self._terminate(
                        owner,
                        "resource_cleanup_failed" if result_was_sent else "handler_error",
                    )
                    if result_was_sent:
                        termination_reason = "resource_cleanup_failed"
        finally:
            finished_at = time.monotonic()
            with owner.cleanup_lock:
                exitcode = process.exitcode
                alive_after = process.is_alive()
                pid_alive_after = _pid_alive(owner.pid)
                process_group_alive_after = _process_group_alive(owner.pid)
                if not owner.cleanup_complete:
                    owner.cleanup_ok = (
                        not alive_after
                        and not process_group_alive_after
                        and owner.isolation_valid
                    )
                    owner.cleanup_complete = True
                if not alive_after:
                    process.close()
            cleanup_ok = cleanup_ok and owner.cleanup_ok
            record = {
                "sequence": sequence,
                "tool_name": tool_name,
                "pid": owner.pid,
                "started_at": started_at,
                "finished_at": finished_at,
                "elapsed_ms": round((finished_at - started_at) * 1000, 1),
                "ready": owner.ready,
                "termination_reason": termination_reason or owner.termination_reason,
                "exitcode": exitcode,
                "alive_after": alive_after,
                "pid_alive_after": pid_alive_after,
                "process_group_alive_after": process_group_alive_after,
                "isolation_valid": owner.isolation_valid,
            }
            receive_connection.close()
            with self._state_lock:
                self._active.pop(sequence, None)
                self._records.append(record)

        if not cleanup_ok or termination_reason == "resource_cleanup_failed":
            return _error_result(
                tool_name,
                "resource_cleanup_failed",
                "Tool worker resources could not be fully reclaimed.",
            )
        if termination_reason == "cancelled":
            return _error_result(tool_name, "cancelled", "Tool execution was cancelled.")
        if termination_reason == "timeout":
            return _error_result(tool_name, "timeout", "Tool execution deadline was exceeded.")
        if isinstance(message, dict) and message.get("type") == "result":
            payload = message.get("payload")
            if isinstance(payload, dict):
                return payload
            return _error_result(
                tool_name,
                "tool_roundtrip_failed",
                "Tool worker returned an invalid result.",
            )
        if isinstance(message, dict) and message.get("type") == "worker_error":
            error_code = str(message.get("error_code") or "handler_error")
            if error_code == "output_too_large":
                return _error_result(
                    tool_name,
                    "output_too_large",
                    "Tool result exceeded the IPC output limit.",
                )
            return _error_result(tool_name, "handler_error", "Tool handler failed.")
        return _error_result(tool_name, "handler_error", "Tool worker exited unexpectedly.")

    def close(self) -> bool:
        """Stop accepting calls and synchronously reap every owned worker."""
        with self._state_lock:
            self._closing = True
            active = tuple(self._active.values())
        cleanup_ok = True
        for owner in active:
            cleanup_ok = self._terminate(owner, "cancelled") and cleanup_ok
        return cleanup_ok

    def snapshot(self) -> tuple[dict, ...]:
        with self._state_lock:
            return tuple(dict(record) for record in self._records)

    @staticmethod
    def _terminate(owner: _OwnedToolProcess, reason: str) -> bool:
        with owner.cleanup_lock:
            if owner.cleanup_complete:
                return owner.cleanup_ok
            if owner.termination_reason is None:
                owner.termination_reason = reason
            process = owner.process
            process_alive = process.is_alive()

            try:
                owns_process_group = os.getpgid(owner.pid) == owner.pid
            except ProcessLookupError:
                owns_process_group = owner.ready and _process_group_alive(owner.pid)
            except PermissionError:
                owns_process_group = False

            if owns_process_group:
                try:
                    os.killpg(owner.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    owner.isolation_valid = False
                    if process_alive:
                        process.terminate()
            elif owner.ready and process_alive:
                # A consumed ready handshake proves the child claimed a new
                # group.  If the OS no longer confirms that invariant, never
                # risk signalling an unrelated process group.
                owner.isolation_valid = False
                process.terminate()
            elif process_alive:
                # Before the ready handshake no tool code has run and no child
                # process group is owned yet, so terminate only the exact PID.
                process.terminate()

            term_deadline = time.monotonic() + TOOL_PROCESS_TERM_GRACE_SECONDS
            process.join(
                timeout=max(0.0, term_deadline - time.monotonic()) if process_alive else 0
            )
            while owns_process_group and _process_group_alive(owner.pid) and time.monotonic() < term_deadline:
                time.sleep(TOOL_PROCESS_POLL_SECONDS)

            group_alive = owns_process_group and _process_group_alive(owner.pid)
            if process.is_alive() or group_alive:
                if group_alive and owner.isolation_valid:
                    try:
                        os.killpg(owner.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        owner.isolation_valid = False
                        if process.is_alive():
                            process.kill()
                elif process.is_alive():
                    process.kill()
                kill_deadline = time.monotonic() + TOOL_PROCESS_KILL_GRACE_SECONDS
                if process.is_alive():
                    process.join(timeout=max(0.0, kill_deadline - time.monotonic()))
                while group_alive and _process_group_alive(owner.pid) and time.monotonic() < kill_deadline:
                    time.sleep(TOOL_PROCESS_POLL_SECONDS)
                group_alive = owns_process_group and _process_group_alive(owner.pid)
            owner.cleanup_ok = (
                not process.is_alive() and not group_alive and owner.isolation_valid
            )
            owner.cleanup_complete = True
            return owner.cleanup_ok
