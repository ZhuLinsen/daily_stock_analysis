# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Shared guardrails for unstable external data-source calls."""

from __future__ import annotations

import os
from queue import Queue
import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")


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

    def run() -> None:
        try:
            result_queue.put((True, func(*args, **kwargs)))
        except BaseException as exc:  # noqa: BLE001 - propagate worker failures to caller.
            result_queue.put((False, exc))

    worker = threading.Thread(target=run, name=f"screening-source:{label}", daemon=True)
    worker.start()
    worker.join(float(timeout_sec))
    if worker.is_alive():
        raise SourceCallTimeout(f"{label} timed out after {float(timeout_sec):g}s")

    ok, payload = result_queue.get_nowait()
    if ok:
        return payload  # type: ignore[return-value]
    raise payload
