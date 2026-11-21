# -*- coding: utf-8 -*-
"""Thread-safety guard for ``py_mini_racer.MiniRacer``.

``mini-racer`` wheels ship V8 built with ``--single-threaded`` and a shared
PartitionAlloc / pointer-compression sandbox. Concurrent ``MiniRacer()``
isolate creation or JS evaluation across threads in one process triggers fatal
native V8 assertions (``address_pool_manager.cc(67)`` / ``partition_address_space.cc(243)``
``SIGTRAP`` on macOS/Windows, or ``SIGSEGV`` under Linux PKU), terminating the
process without raising a Python exception (see issue #2586, #63, PyMiniRacer#100).

This module idempotently serializes ``MiniRacer`` isolate creation and entry
methods behind a process-wide reentrant lock without eagerly importing or
instantiating V8 when ``py_mini_racer`` is unused.
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Callable, Optional

_MINI_RACER_LOCK = threading.RLock()
_PATCH_LOCK = threading.Lock()
_GUARDED_METHODS = ("__init__", "eval", "execute", "call")
_LOCKED_MARKER = "_dsa_mini_racer_locked"


def _is_fully_patched(mini_racer_cls: type) -> bool:
    for method_name in _GUARDED_METHODS:
        orig = getattr(mini_racer_cls, method_name, None)
        if callable(orig) and not getattr(orig, _LOCKED_MARKER, False):
            return False
    return True


def _make_locked_wrapper(
    orig: Callable[..., Any],
    active_lock: threading.RLock,
) -> Callable[..., Any]:
    def _locked(self: Any, *args: Any, **kwargs: Any) -> Any:
        with active_lock:
            return orig(self, *args, **kwargs)

    try:
        functools.wraps(orig)(_locked)
    except (AttributeError, TypeError):
        pass
    setattr(_locked, _LOCKED_MARKER, True)
    return _locked


def patch_mini_racer_class(
    mini_racer_cls: Any,
    lock: Optional[threading.RLock] = None,
) -> bool:
    """Wrap ``MiniRacer`` isolate entry methods with a reentrant lock.

    ``close`` and ``__del__`` are intentionally NOT wrapped: ``py_mini_racer``
    drives ``eval()`` via an internal background event-loop thread, so acquiring
    ``_MINI_RACER_LOCK`` inside GC finalization / ``close()`` could risk an
    ABBA lock inversion.

    Patching itself uses a dedicated ``_PATCH_LOCK`` (plus a lock-free fast
    path once already patched) rather than ``active_lock``, so repeat calls
    such as ``setup_env()`` from request middleware never block on an active
    background JS evaluation.
    """
    if not isinstance(mini_racer_cls, type):
        return False

    if _is_fully_patched(mini_racer_cls):
        return True

    active_lock = lock or _MINI_RACER_LOCK
    with _PATCH_LOCK:
        for method_name in _GUARDED_METHODS:
            orig = getattr(mini_racer_cls, method_name, None)
            if not callable(orig) or getattr(orig, _LOCKED_MARKER, False):
                continue
            setattr(
                mini_racer_cls,
                method_name,
                _make_locked_wrapper(orig, active_lock),
            )
    return True


def ensure_mini_racer_thread_safety() -> bool:
    """Idempotently guard ``py_mini_racer.MiniRacer`` against multi-thread races."""
    try:
        import py_mini_racer
    except Exception:
        return False

    return patch_mini_racer_class(getattr(py_mini_racer, "MiniRacer", None))
