#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export CSC_IDENTITY_AUTO_DISCOVERY="false"
export ELECTRON_BUILDER_CACHE="${ROOT_DIR}/.electron-builder-cache"

verify_expected_unsigned_app() {
  local app_path="$1"
  local signature_details=""
  local assessment_output=""

  bash "${SCRIPT_DIR}/macos-signature-audit.sh" check "${app_path}"

  if signature_details="$(codesign -d "${app_path}" 2>&1)"; then
    echo "ERROR: expected an unsigned application bundle, but a signature was found: ${app_path}"
    echo "${signature_details}" >&2
    exit 1
  fi
  if [[ "${signature_details}" != *"code object is not signed at all"* ]]; then
    echo "ERROR: application bundle has an unreadable or invalid signature: ${app_path}"
    echo "${signature_details}" >&2
    exit 1
  fi

  if assessment_output="$(spctl --assess --type execute --verbose=4 "${app_path}" 2>&1)"; then
    echo "WARNING: Gatekeeper accepted an explicitly unsigned application: ${app_path}"
    echo "${assessment_output}"
    return 0
  fi

  echo "${assessment_output}"
  if [[ "${assessment_output}" == *"code has no resources but signature indicates they must be present"* ]]; then
    echo "ERROR: Gatekeeper detected the broken-signature defect reported in issue #2075." >&2
    exit 1
  fi
  echo "WARNING: Gatekeeper rejection is expected because this build has no Apple Developer signature."
}

verify_unsigned_dmg() {
  local dmg_path="$1"
  local mount_dir=""
  local mounted_app=""
  local mounted=false

  mount_dir="$(mktemp -d "${TMPDIR:-/tmp}/dsa-unsigned-dmg.XXXXXX")"
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

  verify_expected_unsigned_app "${mounted_app}"

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

verify_expected_unsigned_app "${app_candidates[0]}"
verify_unsigned_dmg "${dmg_candidates[0]}"

popd >/dev/null

echo "Desktop build completed."
