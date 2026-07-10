#!/usr/bin/env bash
# Smoke test for the efinance cache-directory contract (PR #1962).
#
# Scope: this script is a **library-level fallback** smoke test, NOT an
# end-to-end entrypoint test.  `docker/entrypoint.sh` is NOT executed
# inside this podman container; we set `EFINANCE_CACHE_DIR` /
# `XDG_CACHE_HOME` explicitly to mirror the paths the entrypoint would
# inject, then verify the patched `data_provider/efinance_fetcher.py`
# resolves them correctly.  End-to-end entrypoint verification happens
# in the Quadlet/compose deployment, not here.
#
# Each case spawns a fresh podman container with `--read-only --tmpfs
# --user 1000:1000` (matching the production Quadlet rootfs posture),
# bind-mounts the working copy of `efinance_fetcher.py` plus a stub for
# `src.patches.eastmoney_patch` (image v3.12.0 predates that module),
# and probes the values efinance's downstream consumers actually read.
#
# Cases mirror the project's expected deployment paths:
#   A. container default (`/app/data/.efinance-cache`, set manually
#      here because the upstream entrypoint.sh is NOT executed in this
#      script; in production the entrypoint injects the same value)
#   B. explicit writable override (/tmp)
#   C. explicit unwritable override (/proc) → mkdir fail + warning logged
#   D. EFINANCE_CACHE_DIR unset, XDG_CACHE_HOME=/var/tmp → fallback path
#
# Exit code is non-zero on the first failing case.

set -uo pipefail

IMAGE="${IMAGE:-ghcr.io/zhulinsen/daily_stock_analysis:latest}"
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PATCHED_FILE="$REPO_ROOT/data_provider/efinance_fetcher.py"

if [[ ! -f "$PATCHED_FILE" ]]; then
  echo "error: efinance_fetcher.py not found at $PATCHED_FILE" >&2
  exit 2
fi

# Stub for `src.patches.eastmoney_patch` (image v3.12.0 predates the
# module; bind-mount it over /app/src/patches/ so the working copy of
# efinance_fetcher.py imports cleanly).
TESTSTUB_DIR="$(mktemp -d -t dsa-efinance-smoke.XXXXXX)"
trap 'rm -rf -- "$TESTSTUB_DIR"' EXIT
mkdir -p "$TESTSTUB_DIR/src/patches"
cat > "$TESTSTUB_DIR/src/patches/__init__.py" <<'PYSTUB'
PYSTUB
cat > "$TESTSTUB_DIR/src/patches/eastmoney_patch.py" <<'PYSTUB'
def eastmoney_patch():
    """No-op shim injected by scripts/check_efinance_cache_dir.sh.

    Image v3.12.0 predates the real `src.patches.eastmoney_patch` module;
    the working copy of `efinance_fetcher.py` imports it unconditionally.
    This stub satisfies the import without affecting test semantics.
    """
    return None
PYSTUB

read -r -d '' PY_PROBE <<'PY' || true
from data_provider import efinance_fetcher as ef

print("EFINANCE_CACHE_DIR=" + str(ef._EFINANCE_CACHE_DIR))
print("DATA_DIR=" + str(ef._ef_cfg_stub.DATA_DIR))
print("SEARCH_RESULT_CACHE_PATH=" + str(ef._ef_cfg_stub.SEARCH_RESULT_CACHE_PATH))
print("MKDIR_OK=" + ("1" if ef._ef_cfg_stub.DATA_DIR.exists() else "0"))

# Consumer-side re-exports.  efinance.shared / utils import
# SEARCH_RESULT_CACHE_PATH from efinance.config at module load, so they
# reflect the same string the stub registered above.
import efinance
print("EFINANCE_SHARED_SRCP=" + str(efinance.shared.SEARCH_RESULT_CACHE_PATH))
print("EFINANCE_UTILS_SRCP=" + str(efinance.utils.SEARCH_RESULT_CACHE_PATH))
PY

assert_kv() {
  local name="$1" actual="$2" expected="$3"
  if [[ "$actual" != "$expected" ]]; then
    echo "  FAIL: $name expected '$expected', got '$actual'" >&2
    return 1
  fi
  return 0
}

run_case() {
  local label="$1"             # A / B / C / D
  local case_cache_dir="$2"    # exact value of EFINANCE_CACHE_DIR ("" ⇒ unset)
  local case_xdg="$3"          # exact value of XDG_CACHE_HOME ("" ⇒ unset)
  local expect_data_dir="$4"   # expected ef.config.DATA_DIR
  local expect_mkdir="$5"      # "1" or "0" expected MKDIR_OK
  local expect_warning="$6"    # "1" if 'not creatable' warning expected on stderr

  echo "=== Case $label: EFINANCE_CACHE_DIR='${case_cache_dir:-<unset>}' XDG_CACHE_HOME='${case_xdg:-<unset>}' expect_DATA_DIR=$expect_data_dir ==="

  local env_args=(-e "HOME=/app")
  [[ -n "$case_cache_dir" ]] && env_args+=(-e "EFINANCE_CACHE_DIR=$case_cache_dir")
  [[ -n "$case_xdg" ]]       && env_args+=(--env "XDG_CACHE_HOME=$case_xdg")

  local tmp outF errF rc=0 prc out err
  tmp="$(mktemp -d)"
  outF="$tmp/out"; errF="$tmp/err"
  set +e
  podman run --rm \
    --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,exec \
    --security-opt=no-new-privileges \
    --user 1000:1000 \
    -v "$PATCHED_FILE:/app/data_provider/efinance_fetcher.py:ro" \
    -v "$TESTSTUB_DIR/src/patches:/app/src/patches:ro" \
    "${env_args[@]}" \
    "$IMAGE" \
    python -c "$PY_PROBE" \
    > "$outF" 2> "$errF"
  prc=$?
  set -e
  out="$(cat "$outF")"; err="$(cat "$errF")"
  rm -rf -- "$tmp"

  if (( prc != 0 )); then
    echo "  FAIL: podman exited $prc, stderr below" >&2
    echo "$err" >&2
    return 1
  fi

  local kv_data kv_search kv_shared kv_utils kv_mkdir
  kv_data=$(printf '%s\n' "$out" | grep -E '^DATA_DIR=' | head -1 | cut -d= -f2-)
  kv_search=$(printf '%s\n' "$out" | grep -E '^SEARCH_RESULT_CACHE_PATH=' | head -1 | cut -d= -f2-)
  kv_shared=$(printf '%s\n' "$out" | grep -E '^EFINANCE_SHARED_SRCP=' | head -1 | cut -d= -f2-)
  kv_utils=$(printf '%s\n'  "$out" | grep -E '^EFINANCE_UTILS_SRCP='  | head -1 | cut -d= -f2-)
  kv_mkdir=$(printf '%s\n'  "$out" | grep -E '^MKDIR_OK='             | head -1 | cut -d= -f2-)

  assert_kv "ef.config.DATA_DIR"                      "$kv_data"   "$expect_data_dir"      || rc=1
  assert_kv "_ef_cfg_stub.SEARCH_RESULT_CACHE_PATH"    "$kv_search" "$expect_data_dir/search-cache.json" || rc=1
  assert_kv "efinance.shared.SEARCH_RESULT_CACHE_PATH" "$kv_shared" "$expect_data_dir/search-cache.json" || rc=1
  assert_kv "efinance.utils.SEARCH_RESULT_CACHE_PATH"  "$kv_utils"  "$expect_data_dir/search-cache.json" || rc=1
  assert_kv "MKDIR_OK"                                 "$kv_mkdir"  "$expect_mkdir"        || rc=1
  if [[ "$expect_warning" == "1" ]] && ! grep -q 'not creatable' <<<"$err"; then
    echo "  FAIL: expected 'not creatable' warning in stderr, got:\n$err" >&2
    rc=1
  fi

  (( rc == 0 )) && echo "  PASS"
  return $rc
}

# Case A: container default — what `docker/entrypoint.sh` injects in
#   the official image (`EFINANCE_CACHE_DIR=/app/data/.efinance-cache`).
#   Note that the upstream image's entrypoint.sh is NOT run inside this
#   smoke container (we only set env + bind-mount files); we pass the
#   injected value directly to mirror it.  /app/data is a real writable
#   Volume in production; in this smoke run it's part of the read-only
#   rootfs, so mkdir() on it fails and the stub stays structurally
#   complete (warning logged, no ImportError).  This case therefore
#   exercises the entrypoint default path, NOT the library-only
#   fallback path — see case D for that.
# Case B: explicit writable /tmp override.
# Case C: explicit unwritable /proc override → mkdir fail + warning.
# Case D: library-level fallback path (entrypoint NOT active):
#   EFINANCE_CACHE_DIR unset, XDG_CACHE_HOME=/var/tmp →
#   DATA_DIR=/var/tmp/efinance, mkdir() succeeds.
run_case A "/app/data/.efinance-cache" ""    "/app/data/.efinance-cache" "0" "1" || exit 1
run_case B "/tmp/ef-smoke-test"          ""    "/tmp/ef-smoke-test"        "1" "0" || exit 1
run_case C "/proc/ef-test"               ""    "/proc/ef-test"             "0" "1" || exit 1
run_case D ""                            "/var/tmp" "/var/tmp/efinance"    "1" "0" || exit 1

echo
echo "smoke: all 4 cases passed"
