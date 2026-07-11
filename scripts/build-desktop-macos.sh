#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export CSC_IDENTITY_AUTO_DISCOVERY="false"
export ELECTRON_BUILDER_CACHE="${ROOT_DIR}/.electron-builder-cache"

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
popd >/dev/null

echo "Desktop build completed."
