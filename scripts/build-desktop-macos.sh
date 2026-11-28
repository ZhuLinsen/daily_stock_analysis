#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export CSC_IDENTITY_AUTO_DISCOVERY="false"
export ELECTRON_BUILDER_CACHE="${ROOT_DIR}/.electron-builder-cache"

is_native_host_arch() {
  local host_arch target_arch
  host_arch="$(uname -m)"
  target_arch="${DSA_MAC_ARCH:-}"
  [[ -z "${target_arch}" ]] || [[ "${target_arch}" == "arm64" && "${host_arch}" == "arm64" ]] || [[ "${target_arch}" == "x64" && "${host_arch}" == "x86_64" ]]
}

verify_installed_dmg_app_launch() {
  local mounted_app="$1"
  if ! is_native_host_arch; then
    echo "Skipping installed DMG Electron launch smoke check for cross-arch build (host=$(uname -m), target=${DSA_MAC_ARCH:-})."
    return 0
  fi

  local smoke_root=""
  local installed_app=""
  local smoke_home=""
  local smoke_userdata=""
  local smoke_stdout=""
  local desktop_log=""
  local app_pid=""
  local status=1

  smoke_root="$(mktemp -d "${TMPDIR:-/tmp}/dsa-macos-launch-smoke.XXXXXX")"
  installed_app="${smoke_root}/Daily Stock Analysis.app"
  smoke_home="${smoke_root}/home"
  smoke_userdata="${smoke_root}/user-data"
  smoke_stdout="${smoke_root}/electron-stdout.log"
  desktop_log="${smoke_userdata}/logs/desktop.log"
  mkdir -p "${smoke_home}" "${smoke_userdata}"

  cleanup_launch_smoke() {
    if [[ -n "${app_pid}" ]] && kill -0 "${app_pid}" 2>/dev/null; then
      kill "${app_pid}" 2>/dev/null || true
      for _ in 1 2 3 4 5 6; do
        if ! kill -0 "${app_pid}" 2>/dev/null; then
          break
        fi
        sleep 0.5
      done
      if kill -0 "${app_pid}" 2>/dev/null; then
        kill -9 "${app_pid}" 2>/dev/null || true
      fi
      wait "${app_pid}" 2>/dev/null || true
    fi
    if [[ -n "${installed_app}" ]]; then
      pkill -9 -f "${installed_app}/Contents/" 2>/dev/null || true
    fi
    if [[ -n "${smoke_root}" ]] && [[ -d "${smoke_root}" ]]; then
      rm -rf "${smoke_root}" 2>/dev/null || true
    fi
  }

  echo "Installing mounted DMG app to temporary directory for end-to-end launch smoke check..."
  if ! ditto "${mounted_app}" "${installed_app}"; then
    echo "ERROR: failed to copy mounted DMG app for launch smoke check: ${mounted_app}" >&2
    cleanup_launch_smoke
    exit 1
  fi

  (
    unset GITHUB_ACTIONS
    export HOME="${smoke_home}"
    exec "${installed_app}/Contents/MacOS/Daily Stock Analysis" \
      --user-data-dir="${smoke_userdata}"
  ) >"${smoke_stdout}" 2>&1 &
  app_pid=$!

  local elapsed=0
  local max_wait_tenths=150
  while (( elapsed < max_wait_tenths )); do
    local combined=""
    if [[ -f "${smoke_stdout}" ]]; then
      combined+="$(cat "${smoke_stdout}" 2>/dev/null || true)"
    fi
    if [[ -f "${desktop_log}" ]]; then
      combined+=$'\n'"$(cat "${desktop_log}" 2>/dev/null || true)"
    fi

    if [[ "${combined}" == *"Backend ready in "* ]] && [[ "${combined}" == *"Main UI loaded in "* ]]; then
      echo "Installed DMG Electron launch smoke check passed (window + helpers + packaged backend health + main UI loaded)."
      status=0
      break
    fi

    if [[ "${combined}" == *"Startup failed while waiting for health:"* ]] || [[ "${combined}" == *"Backend launch failed:"* ]]; then
      echo "ERROR: packaged Electron app failed during backend startup/health check." >&2
      printf '%s\n' "${combined}" >&2
      cleanup_launch_smoke
      exit 1
    fi

    if ! kill -0 "${app_pid}" 2>/dev/null; then
      echo "ERROR: packaged Electron app exited prematurely before Main UI loaded." >&2
      printf '%s\n' "${combined}" >&2
      cleanup_launch_smoke
      exit 1
    fi

    sleep 0.5
    elapsed=$((elapsed + 1))
  done

  if [[ "${status}" -ne 0 ]]; then
    echo "ERROR: packaged Electron app did not complete backend health + Main UI load within 75s." >&2
    if [[ -f "${smoke_stdout}" ]]; then
      echo "--- electron stdout/stderr ---" >&2
      cat "${smoke_stdout}" >&2 || true
    fi
    if [[ -f "${desktop_log}" ]]; then
      echo "--- desktop.log ---" >&2
      cat "${desktop_log}" >&2 || true
    fi
    cleanup_launch_smoke
    exit 1
  fi

  cleanup_launch_smoke
}

verify_adhoc_signed_app() {
  local app_path="$1"
  local signature_details=""
  local assessment_output=""
  local smoke_output=""
  local backend_bin=""

  bash "${SCRIPT_DIR}/macos-signature-audit.sh" check "${app_path}"

  if ! signature_details="$(codesign -d --verbose=4 "${app_path}" 2>&1)"; then
    echo "ERROR: application bundle signature could not be read: ${app_path}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi
  if [[ "${signature_details}" == *"code object is not signed at all"* ]]; then
    echo "ERROR: expected an ad-hoc signed application bundle, but found unsigned binary: ${app_path}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi
  if [[ "${signature_details}" != *"Signature=adhoc"* ]] || [[ "${signature_details}" == *"Authority="* ]]; then
    echo "ERROR: expected a uniform ad-hoc signed application bundle, but found non-adhoc signature: ${app_path}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi

  if ! codesign --verify --deep --strict --verbose=4 "${app_path}" 2>&1; then
    echo "ERROR: application bundle failed deep strict code-signature verification: ${app_path}" >&2
    exit 1
  fi

  if is_native_host_arch; then
    if ! smoke_output="$(ELECTRON_RUN_AS_NODE=1 "${app_path}/Contents/MacOS/Daily Stock Analysis" -e "console.log('desktop-smoke:' + process.platform + ':' + process.arch)" 2>&1)"; then
      echo "ERROR: packaged Electron executable failed headless launch smoke check: ${app_path}" >&2
      echo "${smoke_output}" >&2
      exit 1
    fi
    echo "${smoke_output}"

    backend_bin="${app_path}/Contents/Resources/backend/stock_analysis/stock_analysis"
    if [[ ! -x "${backend_bin}" ]]; then
      echo "ERROR: packaged backend executable missing inside app bundle: ${backend_bin}" >&2
      exit 1
    fi
    if ! "${backend_bin}" --help >/dev/null 2>&1; then
      echo "ERROR: packaged backend executable inside app bundle failed --help smoke check: ${backend_bin}" >&2
      "${backend_bin}" --help || true
      exit 1
    fi
  else
    echo "Skipping native launch smoke checks for cross-arch build (host=$(uname -m), target=${DSA_MAC_ARCH:-})."
  fi

  if assessment_output="$(spctl --assess --type execute --verbose=4 "${app_path}" 2>&1)"; then
    echo "WARNING: Gatekeeper accepted an unnotarized ad-hoc signed application: ${app_path}"
    echo "${assessment_output}"
    return 0
  fi

  echo "${assessment_output}"
  if [[ "${assessment_output}" == *"code has no resources but signature indicates they must be present"* ]]; then
    echo "ERROR: Gatekeeper detected the broken-signature defect reported in issue #2075." >&2
    exit 1
  fi
  echo "WARNING: Gatekeeper rejection is expected because this build uses an ad-hoc signature without Apple Developer notarization."
}

verify_packaged_dmg() {
  local dmg_path="$1"
  local mount_dir=""
  local mounted_app=""
  local mounted=false

  mount_dir="$(mktemp -d "${TMPDIR:-/tmp}/dsa-macos-dmg.XXXXXX")"
  cleanup_mount() {
    if [[ "${mounted}" == "true" ]]; then
      hdiutil detach "${mount_dir}" >/dev/null || true
    fi
    rmdir "${mount_dir}" 2>/dev/null || true
  }
  trap cleanup_mount EXIT

  hdiutil attach "${dmg_path}" -nobrowse -readonly -mountpoint "${mount_dir}" >/dev/null
  mounted=true
  mounted_app="${mount_dir}/Daily Stock Analysis.app"
  if [[ ! -d "${mounted_app}" ]]; then
    echo "ERROR: application bundle not found in mounted DMG: ${mounted_app}"
    exit 1
  fi

  verify_adhoc_signed_app "${mounted_app}"
  verify_installed_dmg_app_launch "${mounted_app}"

  hdiutil detach "${mount_dir}" >/dev/null
  mounted=false
  rmdir "${mount_dir}"
  trap - EXIT
}

echo "Building Electron desktop app (macOS)..."

if [[ ! -d "${ROOT_DIR}/dist/backend/stock_analysis" ]]; then
  echo "Backend artifact not found: ${ROOT_DIR}/dist/backend/stock_analysis"
  echo "Run scripts/build-backend-macos.sh first."
  exit 1
fi

pushd "${ROOT_DIR}/apps/dsa-desktop" >/dev/null

package_lock_hash() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 package-lock.json | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum package-lock.json | awk '{print $1}'
  else
    echo "No SHA-256 checksum tool found. Install shasum or sha256sum." >&2
    exit 1
  fi
}

install_desktop_dependencies() {
  local reason="$1"

  echo "Installing desktop dependencies (${reason})..."
  npm install
  mkdir -p node_modules
  package_lock_hash > node_modules/.dsa-package-lock.sha256
}

ensure_desktop_dependencies() {
  local marker="node_modules/.dsa-package-lock.sha256"
  local reason=""

  if [[ ! -d node_modules ]]; then
    reason="node_modules missing"
  elif [[ ! -f "${marker}" ]]; then
    reason="package-lock marker missing"
  elif [[ "$(tr -d '[:space:]' < "${marker}")" != "$(package_lock_hash)" ]]; then
    reason="package-lock.json changed"
  elif [[ ! -d node_modules/electron-updater ]]; then
    reason="electron-updater missing"
  fi

  if [[ -n "${reason}" ]]; then
    install_desktop_dependencies "${reason}"
  else
    echo "Desktop dependencies are up to date."
  fi
}

ensure_desktop_dependencies

if compgen -G "dist/mac*" >/dev/null; then
  echo "Cleaning dist/mac*..."
  rm -rf dist/mac*
fi
if compgen -G "dist/*.dmg" >/dev/null; then
  echo "Cleaning stale dist/*.dmg..."
  rm -f dist/*.dmg
fi

MAC_ARCH="${DSA_MAC_ARCH:-}"
ARCH_ARGS=()
if [[ -n "${MAC_ARCH}" ]]; then
  case "${MAC_ARCH}" in
    x64|arm64)
      ARCH_ARGS+=("--${MAC_ARCH}")
      ;;
    *)
      echo "Unsupported DSA_MAC_ARCH: ${MAC_ARCH}. Use x64 or arm64."
      exit 1
      ;;
  esac
fi

echo "Building macOS target arch: ${MAC_ARCH:-default}"
if [[ ${#ARCH_ARGS[@]} -gt 0 ]]; then
  npx electron-builder --mac dmg "${ARCH_ARGS[@]}" --publish never
else
  npx electron-builder --mac dmg --publish never
fi

shopt -s nullglob
app_candidates=(dist/mac*/"Daily Stock Analysis.app")
dmg_candidates=(dist/*.dmg)
shopt -u nullglob

if [[ "${#app_candidates[@]}" -ne 1 ]]; then
  echo "ERROR: expected one unpacked macOS app, found ${#app_candidates[@]}."
  exit 1
fi
if [[ "${#dmg_candidates[@]}" -ne 1 ]]; then
  echo "ERROR: expected one macOS DMG, found ${#dmg_candidates[@]}."
  exit 1
fi

verify_adhoc_signed_app "${app_candidates[0]}"
verify_packaged_dmg "${dmg_candidates[0]}"

popd >/dev/null

echo "Desktop build completed."
