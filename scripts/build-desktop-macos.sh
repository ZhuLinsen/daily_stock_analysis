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
if [[ ! -d node_modules ]]; then
  npm install
fi

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
  npx electron-builder --mac dmg "${ARCH_ARGS[@]}"
else
  npx electron-builder --mac dmg
fi
popd >/dev/null

echo "Desktop build completed."
