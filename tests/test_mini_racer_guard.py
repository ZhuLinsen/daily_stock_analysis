# -*- coding: utf-8 -*-
"""Regression tests for ``src.utils.mini_racer_guard``."""

from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.utils.mini_racer_guard import (
    ensure_mini_racer_thread_safety,
    patch_mini_racer_class,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_patch_mini_racer_class_serializes_concurrent_calls_and_allows_reentry() -> None:
    state_lock = threading.Lock()
    state = {"active": 0, "max_active": 0}

    class FakeMiniRacer:
        def __init__(self) -> None:
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                time.sleep(0.01)
                # Re-entrant call into guarded eval() while holding the init lock.
                self.eval("init")
            finally:
                with state_lock:
                    state["active"] -= 1

        def eval(self, code: str) -> str:
            return f"eval:{code}"

        def execute(self, expr: str) -> str:
            return self.eval(f"exec:{expr}")

        def call(self, fn: str, arg: int) -> str:
            return self.execute(f"{fn}({arg})")

    assert patch_mini_racer_class(FakeMiniRacer, lock=threading.RLock()) is True

    def worker(idx: int) -> str:
        mr = FakeMiniRacer()
        return mr.call("fn", idx)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(worker, range(12)))

    assert state["max_active"] == 1
    assert results == [f"eval:exec:fn({idx})" for idx in range(12)]


def test_patch_mini_racer_class_is_idempotent_and_skips_close() -> None:
    class FakeMiniRacer:
        def __init__(self) -> None:
            pass

        def eval(self, code: str) -> str:
            return code

        def close(self) -> None:
            pass

    lock = threading.RLock()
    assert patch_mini_racer_class(FakeMiniRacer, lock=lock) is True
    first_init = FakeMiniRacer.__init__
    first_eval = FakeMiniRacer.eval
    first_close = FakeMiniRacer.close

    assert patch_mini_racer_class(FakeMiniRacer, lock=lock) is True
    assert FakeMiniRacer.__init__ is first_init
    assert FakeMiniRacer.eval is first_eval
    assert FakeMiniRacer.close is first_close
    assert not getattr(FakeMiniRacer.close, "_dsa_mini_racer_locked", False)


def test_patch_mini_racer_class_does_not_block_while_eval_holds_runtime_lock() -> None:
    runtime_lock = threading.RLock()
    entered = threading.Event()
    release = threading.Event()

    class SlowMiniRacer:
        def __init__(self) -> None:
            pass

        def eval(self, code: str) -> str:
            entered.set()
            assert release.wait(timeout=5.0)
            return code

    class FreshMiniRacer:
        def eval(self, code: str) -> str:
            return code

    assert patch_mini_racer_class(SlowMiniRacer, lock=runtime_lock) is True

    eval_result: list[str] = []

    def run_slow_eval() -> None:
        eval_result.append(SlowMiniRacer().eval("slow"))

    worker = threading.Thread(target=run_slow_eval, daemon=True)
    worker.start()
    assert entered.wait(timeout=2.0)

    try:
        # Repeat patch call (e.g. setup_env() from FastAPI middleware) and
        # first-time patching must not block on an active eval holding runtime_lock.
        patch_done = threading.Event()
        patch_outcomes: list[bool] = []

        def run_patches() -> None:
            patch_outcomes.append(patch_mini_racer_class(SlowMiniRacer, lock=runtime_lock))
            patch_outcomes.append(patch_mini_racer_class(FreshMiniRacer, lock=runtime_lock))
            patch_done.set()

        patcher = threading.Thread(target=run_patches, daemon=True)
        patcher.start()
        assert patch_done.wait(timeout=1.0), "patch_mini_racer_class blocked on active eval lock"
        patcher.join(timeout=1.0)
        assert patch_outcomes == [True, True]
    finally:
        release.set()
        worker.join(timeout=2.0)

    assert eval_result == ["slow"]


def test_patch_mini_racer_class_rejects_non_type() -> None:
    assert patch_mini_racer_class(None) is False
    assert patch_mini_racer_class(lambda: None) is False
    assert patch_mini_racer_class(SimpleNamespace(MiniRacer=None)) is False


def test_ensure_mini_racer_thread_safety_fails_open_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "py_mini_racer", None)
    assert ensure_mini_racer_thread_safety() is False


def test_real_py_mini_racer_concurrent_initialization_in_subprocess() -> None:
    if importlib.util.find_spec("py_mini_racer") is None:
        pytest.skip("py_mini_racer is not installed in this environment")

    script = (
        "import concurrent.futures, json, py_mini_racer\n"
        "from src.utils.mini_racer_guard import ensure_mini_racer_thread_safety\n"
        "assert ensure_mini_racer_thread_safety() is True\n"
        "def work(i):\n"
        "    mr = py_mini_racer.MiniRacer()\n"
        "    try:\n"
        "        return mr.eval(f'{i} + 1')\n"
        "    finally:\n"
        "        close = getattr(mr, 'close', None)\n"
        "        if callable(close):\n"
        "            close()\n"
        "with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:\n"
        "    print(json.dumps(list(ex.map(work, range(12)))))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip()) == list(range(1, 13))
