# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Shared guardrails for unstable external data-source calls."""

from __future__ import annotations

import os
from queue import Queue
import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


_CALL_CANCEL_LOCAL = threading.local()


class _SourceCallContext:
    """Track timeout deadline and cancellation callbacks for a worker call."""

    def __init__(self, cancel_event: threading.Event, deadline: float | None) -> None:
        self.cancel_event = cancel_event
        self.deadline = deadline
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []

    def add_cancel_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            already_cancelled = self.cancel_event.is_set()
            if not already_cancelled:
                self._callbacks.append(callback)
        if already_cancelled:
            try:
                callback()
            except Exception:
                pass
            return lambda: None

        def _unregister() -> None:
            with self._lock:
                try:
                    self._callbacks.remove(callback)
                except ValueError:
                    pass

        return _unregister

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue


def _get_current_source_call_context() -> _SourceCallContext | None:
    return getattr(_CALL_CANCEL_LOCAL, "call_context", None)


def get_current_source_call_cancel_event() -> threading.Event | None:
    """Return the active worker cancellation event set on ``SourceCallTimeout``."""
    ctx = _get_current_source_call_context()
    return ctx.cancel_event if ctx is not None else None


def get_current_source_call_deadline() -> float | None:
    """Return the monotonic deadline for the active ``call_with_timeout`` worker."""
    ctx = _get_current_source_call_context()
    return ctx.deadline if ctx is not None else None


def register_source_call_cancel_callback(
    callback: Callable[[], None],
) -> Callable[[], None]:
    """Register a callback invoked immediately if the active call times out."""
    ctx = _get_current_source_call_context()
    if ctx is None:
        return lambda: None
    return ctx.add_cancel_callback(callback)


class SourceCallTimeout(TimeoutError):
    """Raised when a source wrapper exceeds the screening caller-side timeout."""


def parse_source_timeout_seconds(
    specific_env: str,
    *,
    default: float,
    fallback_env: str = "SCREENING_SOURCE_CALL_TIMEOUT_SEC",
) -> float | None:
    """Return a positive timeout, or ``None`` when timeout guarding is disabled."""
    raw = os.getenv(specific_env)
    if raw is None:
        raw = os.getenv(fallback_env)
    if raw is None:
        return float(default)
    cleaned = raw.strip().lower()
    if cleaned in {"", "0", "false", "off", "none", "disabled"}:
        return None
    timeout = float(cleaned)
    return timeout if timeout > 0 else None


def call_with_timeout(
    func: Callable[..., T],
    *args: Any,
    timeout_sec: float | None,
    label: str,
    **kwargs: Any,
) -> T:
    """Run ``func`` with a bounded wait for the caller.

    Python cannot force-stop a thread that is already blocked inside a third-party
    library. The worker is daemonized so the caller can fall back promptly and a
    finished CLI process is not kept alive by a stuck wrapper call.
    """
    if timeout_sec is None:
        return func(*args, **kwargs)

    result_queue: Queue[tuple[bool, object]] = Queue(maxsize=1)
    cancel_event = threading.Event()
    call_context = _SourceCallContext(
        cancel_event,
        time.monotonic() + float(timeout_sec),
    )

    def run() -> None:
        previous_context = getattr(_CALL_CANCEL_LOCAL, "call_context", None)
        _CALL_CANCEL_LOCAL.call_context = call_context
        try:
            result_queue.put((True, func(*args, **kwargs)))
        except BaseException as exc:  # noqa: BLE001 - propagate worker failures to caller.
            result_queue.put((False, exc))
        finally:
            _CALL_CANCEL_LOCAL.call_context = previous_context

    worker = threading.Thread(target=run, name=f"screening-source:{label}", daemon=True)
    worker.start()
    worker.join(float(timeout_sec))
    if worker.is_alive():
        call_context.cancel()
        raise SourceCallTimeout(f"{label} timed out after {float(timeout_sec):g}s")

    ok, payload = result_queue.get_nowait()
    if ok:
        return payload  # type: ignore[return-value]
    raise payload
