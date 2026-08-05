#!/usr/bin/env bash

set -euo pipefail

syntax_check() {
  echo "==> backend-gate: Python syntax check"
  python -m py_compile main.py src/config.py src/auth.py src/analyzer.py src/notification.py
  python -m py_compile src/storage.py src/scheduler.py src/search_service.py
  python -m py_compile src/market_analyzer.py src/stock_analyzer.py
  python -m py_compile data_provider/*.py
}

flake8_checks() {
  echo "==> backend-gate: flake8 critical checks"
  flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
}

deterministic_checks() {
  echo "==> backend-gate: local deterministic checks"
  ./scripts/test.sh code
  ./scripts/test.sh yfinance
}

offline_test_suite() {
  echo "==> backend-gate: offline test suite"
  # ``--timeout=120`` hard-fails any single test that runs longer than two
  # minutes (issue #2131: backend-gate previously hung indefinitely around
  # AlphaSift hotspot cases without leaving any traceback). ``-o
  # timeout_method=thread`` makes pytest-timeout use a watcher thread that
  # is reliable even when the test has swallowed Ctrl-C / signal handling
  # (yfinance, AlphaSift). ``-o faulthandler_timeout=300`` dumps all
  # thread + interpreter stacks to stderr after five minutes of total
  # test silence, giving us a post-mortem root cause for any future
  # CI hang instead of ``backend-gate`` being silently cancelled by the
  # workflow timeout.
  pytest_args=(
    -m "not network"
    --timeout=120 -o timeout_method=thread
    -o faulthandler_timeout=300
    --durations=30 --durations-min=0.5
  )

  if [[ -n "${PYTEST_SPLITS:-}" || -n "${PYTEST_GROUP:-}" ]]; then
    if [[ ! "${PYTEST_SPLITS:-}" =~ ^[1-9][0-9]*$ ]] \
      || [[ ! "${PYTEST_GROUP:-}" =~ ^[1-9][0-9]*$ ]] \
      || (( PYTEST_GROUP > PYTEST_SPLITS )); then
      echo "PYTEST_SPLITS and PYTEST_GROUP must be positive integers with group <= splits." >&2
      exit 2
    fi
    if [[ ! -f .github/ci-test-durations.json ]]; then
      echo "Missing .github/ci-test-durations.json required for balanced CI shards." >&2
      exit 2
    fi
    echo "==> backend-gate: pytest shard ${PYTEST_GROUP}/${PYTEST_SPLITS}"
    python scripts/ci_test_shard.py \
      --splits "${PYTEST_SPLITS}" \
      --group "${PYTEST_GROUP}" \
      --first-shard-overhead "${PYTEST_FIRST_SHARD_OVERHEAD:-0}" \
      -- "${pytest_args[@]}"
    return
  fi

  python -m pytest "${pytest_args[@]}"
}

run_all() {
  syntax_check
  flake8_checks
  deterministic_checks
  offline_test_suite
  echo "==> backend-gate: all checks passed"
}

phase="${1:-all}"

case "$phase" in
  all)
    run_all
    ;;
  syntax)
    syntax_check
    ;;
  flake8)
    flake8_checks
    ;;
  deterministic)
    deterministic_checks
    ;;
  offline-tests)
    offline_test_suite
    ;;
  *)
    echo "Usage: $0 [all|syntax|flake8|deterministic|offline-tests]" >&2
    exit 2
    ;;
esac
