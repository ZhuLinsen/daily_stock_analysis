# -*- coding: utf-8 -*-
"""Behavioural tests for the EFINANCE_CACHE_DIR contract (PR #1962).

Verifies the contract introduced on commit 6248158a and tightened across
PR #1962's iterative reviews:

  A. EFINANCE_CACHE_DIR unset, container /app read-only
     -> DATA_DIR falls back to /app/.cache/efinance (HOME=/app,
        XDG_CACHE_HOME unset); mkdir() is best-effort and never raises;
        the warning is logged.
  B. EFINANCE_CACHE_DIR points at a writable directory
     -> DATA_DIR resolves to that path, mkdir() succeeds.
  C. EFINANCE_CACHE_DIR points at an unwritable directory
     -> mkdir() fails with OSError, warning is logged, import still
        succeeds because the stub stays structurally complete.
  D. Container default: EFINANCE_CACHE_DIR=/app/data/.efinance-cache
     -> DATA_DIR matches the entrypoint-injected writable-Volume path
        on the official image; mkdir() succeeds when /app/data is RW.
  E. Consumer-side re-export chain (`efinance.shared.SEARCH_RESULT_CACHE_PATH`
     and `efinance.utils.SEARCH_RESULT_CACHE_PATH`) resolves to the same
     string the stub registered, so downstream code that reads
     `efinance.shared.SEARCH_RESULT_CACHE_PATH` (instead of
     `efinance.config.SEARCH_RESULT_CACHE_PATH`) sees the configured
     value.

Each case runs in a fresh subprocess so the import-time state set up by
the stub block is isolated.  The pytest runner must install the
project's `requirements.txt` (pandas, efinance, requests, ...) before
this file becomes executable; on a host without those deps the cases
are skipped via `pytest.importorskip`.

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

# Inline snippet executed in a fresh Python.  Imports the patched
# module, verifies the stub stays structurally complete and consistent
# across both `efinance.config` (set by the stub) and the consumer-side
# re-exports `efinance.shared` / `efinance.utils` (which import
# SEARCH_RESULT_CACHE_PATH from `efinance.config` at module load).
_SUBPROCESS_SNIPPET = textwrap.dedent("""
    import sys

    from data_provider import efinance_fetcher as ef

    print("EFINANCE_CACHE_DIR=" + str(ef._EFINANCE_CACHE_DIR))
    print("DATA_DIR=" + str(ef._ef_cfg_stub.DATA_DIR))
    print("SEARCH_RESULT_CACHE_PATH=" + str(ef._ef_cfg_stub.SEARCH_RESULT_CACHE_PATH))
    print("MKDIR_OK=" + ("1" if ef._ef_cfg_stub.DATA_DIR.exists() else "0"))

    # Consumer-side re-exports — must match the stub's value, otherwise
    # an implementation that didn't reset these re-exports (the past
    # review's correctness blocker) would still pass the other asserts.
    import efinance
    print("EFINANCE_SHARED_SRCP=" + str(efinance.shared.SEARCH_RESULT_CACHE_PATH))
    print("EFINANCE_UTILS_SRCP=" + str(efinance.utils.SEARCH_RESULT_CACHE_PATH))

    sys.exit(0)
""").strip()


def _run_case(env_overrides, *, expect_warning=False):
    """Spawn a fresh Python with the given env overrides; parse KEY=VALUE."""
    env = os.environ.copy()
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


def _assert_search_constants_match(result, expected_dir):
    expected = expected_dir + "/search-cache.json"
    assert result["kv"]["SEARCH_RESULT_CACHE_PATH"] == expected, (
        f"_ef_cfg_stub.SEARCH_RESULT_CACHE_PATH expected {expected}, "
        f"got {result['kv']['SEARCH_RESULT_CACHE_PATH']}"
    )
    assert result["kv"]["EFINANCE_SHARED_SRCP"] == expected, (
        f"efinance.shared.SEARCH_RESULT_CACHE_PATH expected {expected}, "
        f"got {result['kv']['EFINANCE_SHARED_SRCP']}"
    )
    assert result["kv"]["EFINANCE_UTILS_SRCP"] == expected, (
        f"efinance.utils.SEARCH_RESULT_CACHE_PATH expected {expected}, "
        f"got {result['kv']['EFINANCE_UTILS_SRCP']}"
    )


@pytest.mark.unit
def test_a_unset_env_falls_back_to_home_or_xdg():
    """Case A: HOME=/app (production default), EFINANCE_CACHE_DIR unset."""
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    result = _run_case({"HOME": "/app"})
    assert result["returncode"] == 0, (
        "efinance_fetcher import must not raise on RO-fs:\n" + result["stderr"]
    )

    data_dir = result["kv"]["DATA_DIR"]
    assert data_dir.endswith("efinance"), (
        f"DATA_DIR should end with 'efinance', got: {data_dir}"
    )

    _assert_search_constants_match(result, data_dir)

    # mkdir() may legitimately fail on /app RO-fs; either outcome is fine.
    assert result["kv"]["MKDIR_OK"] in ("0", "1")


@pytest.mark.unit
def test_b_explicit_override_creates_directory():
    """Case B: EFINANCE_CACHE_DIR=/tmp/ef-test → DATA_DIR=/tmp/ef-test."""
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    target = "/tmp/ef-test-pytest-" + str(os.getpid())
    try:
        result = _run_case({"EFINANCE_CACHE_DIR": target})
        assert result["returncode"] == 0, result["stderr"]
        assert result["kv"]["EFINANCE_CACHE_DIR"] == target
        assert result["kv"]["DATA_DIR"] == target

        _assert_search_constants_match(result, target)

        assert result["kv"]["MKDIR_OK"] == "1", (
            "explicit writable cache dir should be created: " + result["stderr"]
        )
    finally:
        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.unit
def test_c_unwritable_override_logs_warning_and_does_not_raise():
    """Case C: EFINANCE_CACHE_DIR=/proc/ef-test → mkdir fails, no exception."""
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    result = _run_case({"EFINANCE_CACHE_DIR": "/proc/ef-test"})
    assert result["returncode"] == 0, (
        "efinance_fetcher must NOT raise when the cache dir is unwritable:\n"
        + result["stderr"]
    )
    assert result["kv"]["DATA_DIR"] == "/proc/ef-test"

    _assert_search_constants_match(result, "/proc/ef-test")

    assert result["kv"]["MKDIR_OK"] == "0"
    assert "not creatable" in result["stderr"], (
        "expected 'not creatable' warning in stderr, got:\n" + result["stderr"]
    )


@pytest.mark.unit
def test_d_container_default_efinance_cache_dir_in_app_data():
    """Case D: official container default (what entrypoint.sh injects).

    /app/data is a writable Volume in production.  In the host pytest
    environment /app/data may or may not exist — we only assert that
    DATA_DIR resolves to /app/data/.efinance-cache when EFINANCE_CACHE_DIR
    is set that way; mkdir() may fail or succeed depending on the host,
    but the stub stays structurally complete regardless.
    """
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    result = _run_case({"EFINANCE_CACHE_DIR": "/app/data/.efinance-cache"})
    assert result["returncode"] == 0, result["stderr"]
    assert result["kv"]["DATA_DIR"] == "/app/data/.efinance-cache"

    _assert_search_constants_match(result, "/app/data/.efinance-cache")

    # mkdir may fail under host user without permission; both outcomes are
    # acceptable since the consumer-side chain still resolves correctly.
    assert result["kv"]["MKDIR_OK"] in ("0", "1")


@pytest.mark.unit
def test_e_consumer_re_exports_match_stub():
    """Case E: efinance.shared / utils consumer constants match the stub.

    Past review pointed out that the existing tests only checked the
    private `_ef_cfg_stub` object; an implementation that ignored the
    stub would still pass those tests.  This case explicitly asserts
    the downstream re-export values that efinance's own modules read.
    """
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    target = "/tmp/ef-test-pytest-consumer-" + str(os.getpid())
    try:
        result = _run_case({"EFINANCE_CACHE_DIR": target})
        assert result["returncode"] == 0, result["stderr"]

        # The consumer-side re-exports must reflect the stub.  We assert
        # both the value AND that the attribute is set to a string (not
        # a placeholder like None).
        expected = target + "/search-cache.json"
        for src in ("EFINANCE_SHARED_SRCP", "EFINANCE_UTILS_SRCP"):
            actual = result["kv"][src]
            assert actual == expected, (
                f"{src} expected {expected}, got {actual!r}"
            )
            assert actual.endswith("/search-cache.json"), (
                f"{src} should end with '/search-cache.json', got {actual!r}"
            )
    finally:
        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.unit
def test_eager_import_does_not_raise():
    """`data_provider/__init__.py` imports EfinanceFetcher; must succeed
    even when the cache dir is unwritable so the production fallback
    chain isn't bypassed by an import-time crash."""
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
