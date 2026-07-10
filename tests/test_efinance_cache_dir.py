# -*- coding: utf-8 -*-
"""Behavioural tests for the `EFINANCE_CACHE_DIR` resolution contract.

The efinance data source uses an in-package cache directory that fails
on read-only filesystems (containers, system Python installs).  The
resolution contract under test:

  A. EFINANCE_CACHE_DIR unset, container /app read-only
     -> DATA_DIR falls back to /app/.cache/efinance (HOME=/app,
        XDG_CACHE_HOME unset); mkdir() is best-effort and never raises.
  B. EFINANCE_CACHE_DIR points at a writable directory
     -> DATA_DIR resolves to that path, mkdir() succeeds.
  C. EFINANCE_CACHE_DIR points at an unwritable directory
     -> mkdir() fails with OSError, the warning is logged, and the
        import still succeeds because the stub stays structurally
        complete.
  D. Container default: EFINANCE_CACHE_DIR=/app/data/.efinance-cache
     -> DATA_DIR matches the entrypoint-injected writable-Volume path.
  E. Consumer-side re-export chain
     (`efinance.shared.SEARCH_RESULT_CACHE_PATH` and
     `efinance.utils.SEARCH_RESULT_CACHE_PATH`) resolves to the same
     string the stub registered, so downstream code that reads
     either of those sees the configured value.
  F. Parent-attribute contract
     (`efinance.config.DATA_DIR` after `import efinance as ef`)
     resolves to the stub; the stub-block sets the attribute via
     `setattr(_ef, "config", _ef_cfg_stub)`.
  G. EfinanceFetcher instantiation under an unwritable cache directory
     does not raise at construction time; the data-source fallback
     chain is the contract for the runtime call path (out of scope
     here).

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
def test_import_order_efinance_first_then_data_provider_is_safe():
    """If `efinance` is imported first, our stub-block must back off
    instead of replacing the already-loaded module.

    This is the inverse-order case for the import-order contract
    documented at the top of `data_provider/efinance_fetcher.py`.  When
    `efinance` is already in `sys.modules` we must NOT inject a second
    `efinance.config` (which would mask the upstream-cached attribute
    and silently flip SEARCH_RESULT_CACHE_PATH), and we must NOT raise
    during `import data_provider`.
    """
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    script = textwrap.dedent("""
        import sys
        # Load efinance FIRST in a clean sys.modules.
        import efinance as ef
        sys.modules["__test__efinance_pre_loaded"] = "1"  # sentinel
        # Now load data_provider.
        from data_provider import efinance_fetcher as fetcher
        # data_provider.efinance_fetcher must NOT have replaced the
        # already-loaded efinance.config (which holds the upstream
        # module's data).
        cfg = ef.config
        from data_provider.efinance_fetcher import _ef_cfg_stub as stub
        same_id = cfg is stub
        print("EFINANCE_PRELOADED=1")
        print("STUB_IS_EFINANCE_CONFIG=" + ("1" if same_id else "0"))
        sys.exit(0)
    """).strip()

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "EFINANCE_CACHE_DIR": "", "XDG_CACHE_HOME": ""},
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        "importing data_provider after efinance must not raise:\n" + proc.stderr
    )
    kv = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k] = v
    assert kv.get("EFINANCE_PRELOADED") == "1"
    # Crucial: stub is NOT the active efinance.config when efinance was
    # loaded first; upstream retains control of its own cache dir.
    assert kv.get("STUB_IS_EFINANCE_CONFIG") == "0", (
        "stub must NOT replace a pre-loaded efinance.config (would mask "
        "the upstream-cached attribute): " + repr(proc.stdout)
    )


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


@pytest.mark.unit
def test_f_parent_attribute_contract():
    """`efinance.config.DATA_DIR` (parent attribute path) resolves to
    the stub registered by data_provider, so callers using
    `import efinance as ef; ef.config.X` see the configured cache
    directory.  This is the contract the PR body advertises; the
    earlier round did not satisfy it (efinance 0.5.x's __init__.py
    does not expose `.config`).
    """
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    target = "/tmp/ef-test-parent-attr-" + str(os.getpid())
    try:
        result = _run_case({"EFINANCE_CACHE_DIR": target})
        assert result["returncode"] == 0, result["stderr"]
        # The parent-attribute channel: `efinance.config.DATA_DIR`.
        assert result["kv"]["EFINANCE_CONFIG_PARENT_DATA_DIR"] == target, (
            f"efinance.config.DATA_DIR expected {target}, "
            f"got {result['kv'].get('EFINANCE_CONFIG_PARENT_DATA_DIR')!r}"
        )
        assert result["kv"]["EFINANCE_CONFIG_PARENT_SEARCH"] == target + "/search-cache.json", (
            f"efinance.config.SEARCH_RESULT_CACHE_PATH expected {target}/search-cache.json, "
            f"got {result['kv'].get('EFINANCE_CONFIG_PARENT_SEARCH')!r}"
        )
    finally:
        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.unit
def test_g_efinance_fetcher_instantiation_under_unwritable_cache():
    """Constructing `EfinanceFetcher()` under an unwritable cache dir
    must not raise.  The data-source fallback chain is the contract
    for the runtime call path itself; that integration is upstream's
    responsibility and is not asserted here.
    """
    pytest.importorskip("pandas")
    pytest.importorskip("efinance")

    script = textwrap.dedent("""
        from data_provider.efinance_fetcher import EfinanceFetcher
        e = EfinanceFetcher()
        print("CONSTRUCTED=" + type(e).__name__)
    """).strip()

    proc = subprocess.run(
        [sys.executable, "-c", script],
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
        "EfinanceFetcher() must construct under unwritable cache:\n"
        + proc.stderr
    )
    assert "CONSTRUCTED=EfinanceFetcher" in proc.stdout
