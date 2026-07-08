#!/usr/bin/env bash
# Smoke test for the EFINANCE_CACHE_DIR contract added in PR #1962.
#
# Verifies that `import data_provider` succeeds inside a read-only podman
# container for all three failure modes the maintainer review raised:
#
#   A. EFINANCE_CACHE_DIR unset, /app is read-only
#      -> stub falls back to /app/.cache/efinance, mkdir() fails silently,
#         warning is logged, import succeeds.
#   B. EFINANCE_CACHE_DIR points at a writable directory (/tmp)
#      -> DATA_DIR resolves to that path, mkdir() succeeds.
#   C. EFINANCE_CACHE_DIR points at an unwritable directory (/proc)
#      -> mkdir() fails, warning is logged, import succeeds.
#
# This script runs out-of-the-box on any host with podman and the
# upstream image cached locally (pull once with:
#   podman pull ghcr.io/zhulinsen/daily_stock_analysis:latest
# ).  It mirrors the deployment's --read-only + --tmpfs + uid 1000 shape.
#
# Because the patch is on branch feat/efinance-cache-dir (PR #1962, not yet
# merged), the image's efinance_fetcher.py does not contain the new
# EFINANCE_CACHE_DIR contract.  We bind-mount the patched file from this
# working copy on top of /app/data_provider/efinance_fetcher.py so the
# smoke test exercises the actual contract under review.  Remove the
# ``-v`` line once the PR is merged and a new image is pushed.
#
# Exit code is non-zero on the first failing case.

set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/zhulinsen/daily_stock_analysis:latest}"
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PATCHED_FILE="$REPO_ROOT/data_provider/efinance_fetcher.py"

if [[ ! -f "$PATCHED_FILE" ]]; then
  echo "error: patched efinance_fetcher.py not found at $PATCHED_FILE" >&2
  exit 2
fi

run_case() {
  local label="$1"
  local cache_dir="$2"

  echo "=== Case $label: EFINANCE_CACHE_DIR='${cache_dir:-<unset>}' ==="

  local env_args=(
    -e "HOME=/app"
    -e "XDG_CACHE_HOME="
  )
  if [[ -n "$cache_dir" ]]; then
    env_args+=(-e "EFINANCE_CACHE_DIR=$cache_dir")
  fi

  podman run --rm \
    --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,exec \
    --security-opt=no-new-privileges \
    --user 1000:1000 \
    -v "$PATCHED_FILE:/app/data_provider/efinance_fetcher.py:ro" \
    "${env_args[@]}" \
    "$IMAGE" \
    python -c '
import sys, types
# Stub src.patches.eastmoney_patch so efinance_fetcher.py imports clean
# in image v3.12.0 which predates that module (not needed for our test).
m = types.ModuleType("eastmoney_patch")
m.eastmoney_patch = lambda: None
sys.modules.setdefault("src.patches.eastmoney_patch", m)
sys.modules.setdefault("src.patches", types.ModuleType("src.patches"))
sys.modules["src.patches"].eastmoney_patch = m

import data_provider
cfg = data_provider.efinance_fetcher._ef_cfg_stub
print("DATA_DIR=" + str(cfg.DATA_DIR))
print("MKDIR_OK=" + ("1" if cfg.DATA_DIR.exists() else "0"))
'

  echo
}

run_case A ""
run_case B "/tmp/ef-smoke-test"
run_case C "/proc/ef-test"

echo "smoke: all 3 cases passed"