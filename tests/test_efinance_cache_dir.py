# -*- coding: utf-8 -*-
"""Behavioural tests for the EFINANCE_CACHE_DIR contract added in PR #1962.

These tests verify the three failure modes the maintainer review raised on
commit 6248158a:

  A. EFINANCE_CACHE_DIR unset on a read-only filesystem
     -> stub falls back to $XDG_CACHE_HOME/efinance or ~/.cache/efinance;
        mkdir() is best-effort and never raises.
  B. EFINANCE_CACHE_DIR points at a writable directory
     -> DATA_DIR resolves to that path, SEARCH_RESULT_CACHE_PATH joins it,
        mkdir() succeeds.
  C. EFINANCE_CACHE_DIR points at an unwritable path
     -> mkdir() fails with OSError, the failure is logged as a warning, and
        the import still succeeds because the stub stays structurally
        complete (`DATA_DIR` + `SEARCH_RESULT_CACHE_PATH` always set).
  D. Eager-import path used by `data_provider/__init__.py`
     -> `import data_provider` does not raise even when the cache dir is
        unwritable, so the production fallback chain still works.

Each case runs in a fresh subprocess so the import-time state set up by the
stub block is isolated.  pytest must install the project's
`requirements.txt` (pandas, efinance, requests, ...) before this file
becomes executable; on a host without those deps the cases are skipped via
`pytest.importorskip`.

Run with::

    pytest -m unit tests/test_efinance_cache_dir.py

Marked ``unit`` so CI's ``-m "not network"`` gate includes it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Inline snippet executed in a fresh Python.  Imports only the patched
# module (which transitively pulls pandas, requests, ...) and prints four
# structured ``KEY=VALUE`` lines plus MKDIR_OK.  Returning a non-zero exit
# status surfaces a crash as a test failure rather than a silent skip.
_SUBPROCESS_SNIPPET = textwrap.dedent("""
    import logging
    import sys

    logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

    from data_provider import efinance_fetcher as ef

    print("EFINANCE_CACHE_DIR=" + str(ef._EFINANCE_CACHE_DIR))
    print("DATA_DIR=" + str(ef._ef_cfg_stub.DATA_DIR))
    print("SEARCH_RESULT_CACHE_PATH=" + str(ef._ef_cfg_stub.SEARCH_RESULT_CACHE_PATH))
    print("MKDIR_OK=" + ("1" if ef._ef_cfg_stub.DATA_DIR.exists() else "0"))
    sys.exit(0)
""").strip()


def _run_case(env_overrides):
    """Spawn a fresh Python with the given env overrides; parse KEY=VALUE."""
    env = os.environ.copy()
    # Strip the override we're testing so each case starts clean.
    env.pop("EFINANCE_CACHE_DIR", None)
    env["XDG_CACHE_HOME"] = ""  # force the ~/.cache/efinance fallback
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    proc = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SNIPPET],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(REPO_ROOT),
    )
    kv = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k] = v
    return {
        "returncode": proc.returncode,
        "stderr": proc.stderr,
        "stdout": proc.stdout,
        "kv": kv,
    }


@pytest.mark.unit
def test_unset_env_falls_back_to_xdg_or_home():
    """Case A: HOME=/app (production default), EFINANCE_CACHE_DIR unset."""
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    result = _run_case({"HOME": "/app"})
    assert result["returncode"] == 0, (
        "efinance_fetcher import must not raise on RO-fs:\n" + result["stderr"]
    )

    # DATA_DIR falls back to /app/.cache/efinance (HOME=/app, XDG unset).
    data_dir = result["kv"]["DATA_DIR"]
    assert data_dir.endswith("efinance"), (
        f"DATA_DIR should end with 'efinance', got: {data_dir}"
    )
    # SEARCH_RESULT_CACHE_PATH is always DATA_DIR/search-cache.json.
    assert result["kv"]["SEARCH_RESULT_CACHE_PATH"] == data_dir + "/search-cache.json"
    # mkdir() may legitimately fail on /app RO-fs; either outcome is fine.
    assert result["kv"]["MKDIR_OK"] in ("0", "1")


@pytest.mark.unit
def test_explicit_override_creates_directory():
    """Case B: EFINANCE_CACHE_DIR=/tmp/ef-test → DATA_DIR=/tmp/ef-test."""
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    target = "/tmp/ef-test-pytest-" + str(os.getpid())
    try:
        result = _run_case({"EFINANCE_CACHE_DIR": target})
        assert result["returncode"] == 0, result["stderr"]
        assert result["kv"]["EFINANCE_CACHE_DIR"] == target
        assert result["kv"]["DATA_DIR"] == target
        assert result["kv"]["SEARCH_RESULT_CACHE_PATH"] == target + "/search-cache.json"
        assert result["kv"]["MKDIR_OK"] == "1", (
            "explicit writable cache dir should be created: " + result["stderr"]
        )
    finally:
        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.unit
def test_unwritable_override_logs_warning_and_does_not_raise():
    """Case C: EFINANCE_CACHE_DIR=/proc/ef-test → mkdir fails, no exception."""
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    result = _run_case({"EFINANCE_CACHE_DIR": "/proc/ef-test"})
    assert result["returncode"] == 0, (
        "efinance_fetcher must NOT raise when the cache dir is unwritable:\n"
        + result["stderr"]
    )
    # Stub is still structurally complete; DATA_DIR echoes the requested path.
    assert result["kv"]["DATA_DIR"] == "/proc/ef-test"
    assert result["kv"]["SEARCH_RESULT_CACHE_PATH"] == "/proc/ef-test/search-cache.json"
    assert result["kv"]["MKDIR_OK"] == "0"
    # The failure was surfaced as a warning so operators can see it.
    assert "not creatable" in result["stderr"], (
        "expected 'not creatable' warning in stderr, got:\n" + result["stderr"]
    )


@pytest.mark.unit
def test_eager_import_does_not_raise():
    """Case D: data_provider/__init__.py imports EfinanceFetcher; must succeed."""
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    proc = subprocess.run(
        [sys.executable, "-c", "import data_provider; print('OK')"],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "EFINANCE_CACHE_DIR": "/proc/ef-test",
            "HOME": "/app",
            "XDG_CACHE_HOME": "",
        },
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        "eager `import data_provider` must not raise when cache dir is unwritable:\n"
        + proc.stderr
    )
    assert "OK" in proc.stdout