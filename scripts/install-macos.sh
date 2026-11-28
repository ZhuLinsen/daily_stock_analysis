#!/usr/bin/env bash
set -euo pipefail

REPO="ZhuLinsen/daily_stock_analysis"
APP_NAME="Daily Stock Analysis"
APP_BUNDLE="${APP_NAME}.app"
INSTALL_DIR="/Applications"
REQUESTED_VERSION=""
REQUESTED_ARCH=""
NO_OPEN=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: install-macos.sh [options]

Download, SHA-256 verify, and install the official macOS Desktop DMG from GitHub Releases.
Downloading via curl avoids browser com.apple.quarantine prompts and auto-selects arm64 vs x64.

Options:
  --version <tag>   Install a specific release tag (for example v3.36.0; default: latest)
  --arch <arch>     Force target architecture: arm64 or x64 (default: auto-detect)
  --dir <path>      Destination directory for the .app bundle (default: /Applications)
  --no-open         Do not launch the app after installation
  --dry-run         Resolve release metadata and print the install plan without downloading
  -h, --help        Show this help message
EOF
}

log() {
  echo "[dsa-install] $*"
}

die() {
  echo "[dsa-install] ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      [[ $# -ge 2 ]] || die "--version requires a value"
      REQUESTED_VERSION="$2"
      shift 2
      ;;
    --version=*)
      REQUESTED_VERSION="${1#*=}"
      shift
      ;;
    --arch)
      [[ $# -ge 2 ]] || die "--arch requires a value (arm64 or x64)"
      REQUESTED_ARCH="$2"
      shift 2
      ;;
    --arch=*)
      REQUESTED_ARCH="${1#*=}"
      shift
      ;;
    --dir)
      [[ $# -ge 2 ]] || die "--dir requires a directory path"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --dir=*)
      INSTALL_DIR="${1#*=}"
      shift
      ;;
    --no-open)
      NO_OPEN=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[dsa-install] ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ensure_macos() {
  local os_name
  os_name="$(uname -s)"
  if [[ "${os_name}" != "Darwin" ]]; then
    die "This installer only supports macOS (detected: ${os_name})."
  fi
}

detect_arch() {
  if [[ -n "${REQUESTED_ARCH}" ]]; then
    case "${REQUESTED_ARCH}" in
      arm64|x64)
        echo "${REQUESTED_ARCH}"
        return 0
        ;;
      *)
        die "Unsupported --arch '${REQUESTED_ARCH}'. Use arm64 or x64."
        ;;
    esac
  fi

  local machine translated
  machine="$(uname -m)"
  case "${machine}" in
    arm64|aarch64)
      echo "arm64"
      ;;
    x86_64)
      translated="$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)"
      if [[ "${translated}" == "1" ]]; then
        echo "[dsa-install] Detected Rosetta 2 on Apple Silicon; selecting native arm64 build." >&2
        echo "arm64"
      else
        echo "x64"
      fi
      ;;
    *)
      die "Unsupported macOS architecture: ${machine}"
      ;;
  esac
}

resolve_release_tag() {
  local tag=""
  if [[ -n "${REQUESTED_VERSION}" ]]; then
    tag="v${REQUESTED_VERSION#v}"
  else
    command -v curl >/dev/null 2>&1 || die "curl is required."
    local api_url="https://api.github.com/repos/${REPO}/releases/latest"
    local release_json=""
    release_json="$(curl -fsSL --retry 3 --connect-timeout 15 \
      -H "Accept: application/vnd.github+json" \
      -H "User-Agent: daily-stock-analysis-macos-installer" \
      "${api_url}")" || die "Failed to query latest GitHub Release from ${api_url}."

    tag="$(printf '%s' "${release_json}" \
      | grep -oE '"tag_name"[[:space:]]*:[[:space:]]*"[^"]+"' \
      | head -n 1 \
      | sed -E 's/.*"([^"]+)"$/\1/')"
    [[ -n "${tag}" ]] || die "Could not parse tag_name from GitHub Release API response."
  fi

  if [[ ! "${tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
    die "Invalid release tag format: ${tag}"
  fi
  echo "${tag}"
}

extract_expected_sha256() {
  local sums_file="$1"
  local target_name="$2"
  awk -v target="${target_name}" '
    {
      gsub(/\r$/, "", $0)
      hash = $1
      sub(/^[^[:space:]]+[[:space:]]+/, "", $0)
      sub(/^\*/, "", $0)
      if ($0 == target) {
        print tolower(hash)
        exit
      }
    }
  ' "${sums_file}"
}

ensure_macos
TARGET_ARCH="$(detect_arch)"
RELEASE_TAG="$(resolve_release_tag)"
DMG_NAME="daily-stock-analysis-macos-${TARGET_ARCH}-${RELEASE_TAG}.dmg"
RELEASE_BASE_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}"
DMG_URL="${RELEASE_BASE_URL}/${DMG_NAME}"
SUMS_URL="${RELEASE_BASE_URL}/SHA256SUMS.txt"
TARGET_APP="${INSTALL_DIR}/${APP_BUNDLE}"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "Dry run summary:"
  echo "  Release tag:  ${RELEASE_TAG}"
  echo "  Architecture: ${TARGET_ARCH}"
  echo "  DMG URL:      ${DMG_URL}"
  echo "  SHA256 URL:   ${SUMS_URL}"
  echo "  Target path:  ${TARGET_APP}"
  exit 0
fi

for tool in curl shasum hdiutil ditto mktemp; do
  command -v "${tool}" >/dev/null 2>&1 || die "Required macOS tool not found: ${tool}"
done

if command -v pgrep >/dev/null 2>&1 && pgrep -x "${APP_NAME}" >/dev/null 2>&1; then
  die "${APP_NAME} is currently running. Please quit the app first and re-run this installer."
fi

if [[ ! -d "${INSTALL_DIR}" ]]; then
  mkdir -p "${INSTALL_DIR}" || die "Cannot create install directory: ${INSTALL_DIR}"
fi
if [[ ! -w "${INSTALL_DIR}" ]]; then
  die "Install directory is not writable: ${INSTALL_DIR}. Re-run with --dir \"\$HOME/Applications\" or run with sudo."
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dsa-macos-install.XXXXXX")"
MOUNT_DIR="${WORK_DIR}/mount"
mkdir -p "${MOUNT_DIR}"
MOUNTED=0
STAGING_APP=""

cleanup() {
  if [[ "${MOUNTED}" -eq 1 ]]; then
    hdiutil detach "${MOUNT_DIR}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${STAGING_APP}" ]] && [[ -d "${STAGING_APP}" ]]; then
    rm -rf "${STAGING_APP}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${WORK_DIR}" ]] && [[ -d "${WORK_DIR}" ]]; then
    rm -rf "${WORK_DIR}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

SUMS_PATH="${WORK_DIR}/SHA256SUMS.txt"
DMG_PATH="${WORK_DIR}/${DMG_NAME}"

log "Installing ${APP_NAME} ${RELEASE_TAG} (${TARGET_ARCH}) into ${INSTALL_DIR}"
log "Downloading checksum manifest..."
curl -fsSL --retry 3 --connect-timeout 15 -o "${SUMS_PATH}" "${SUMS_URL}" \
  || die "Failed to download ${SUMS_URL}"

EXPECTED_SHA="$(extract_expected_sha256 "${SUMS_PATH}" "${DMG_NAME}")"
if [[ ! "${EXPECTED_SHA}" =~ ^[0-9a-f]{64}$ ]]; then
  die "No valid SHA-256 entry for ${DMG_NAME} found in SHA256SUMS.txt"
fi

log "Downloading ${DMG_NAME}..."
curl -fSL --retry 3 --connect-timeout 15 -o "${DMG_PATH}" "${DMG_URL}" \
  || die "Failed to download ${DMG_URL}"

log "Verifying SHA-256 checksum..."
ACTUAL_SHA="$(shasum -a 256 "${DMG_PATH}" | awk '{print tolower($1)}')"
if [[ "${ACTUAL_SHA}" != "${EXPECTED_SHA}" ]]; then
  die "SHA-256 mismatch for ${DMG_NAME} (expected ${EXPECTED_SHA}, got ${ACTUAL_SHA})"
fi
log "SHA-256 verified: ${ACTUAL_SHA}"

log "Mounting DMG..."
hdiutil attach "${DMG_PATH}" -nobrowse -readonly -mountpoint "${MOUNT_DIR}" >/dev/null
MOUNTED=1

MOUNTED_APP="${MOUNT_DIR}/${APP_BUNDLE}"
[[ -d "${MOUNTED_APP}" ]] || die "Application bundle not found inside DMG: ${MOUNTED_APP}"

STAGING_APP="${INSTALL_DIR}/.${APP_BUNDLE}.installing.$$"
BACKUP_APP="${INSTALL_DIR}/.${APP_BUNDLE}.previous.$$"

log "Copying ${APP_BUNDLE} to ${INSTALL_DIR}..."
rm -rf "${STAGING_APP}" "${BACKUP_APP}"
ditto "${MOUNTED_APP}" "${STAGING_APP}"
[[ -e "${STAGING_APP}/Contents/MacOS/${APP_NAME}" ]] \
  || die "Staged application bundle is missing main executable: ${STAGING_APP}/Contents/MacOS/${APP_NAME}"

if [[ -e "${TARGET_APP}" ]]; then
  mv "${TARGET_APP}" "${BACKUP_APP}"
fi
if ! mv "${STAGING_APP}" "${TARGET_APP}"; then
  if [[ -e "${BACKUP_APP}" ]]; then
    mv "${BACKUP_APP}" "${TARGET_APP}" || true
  fi
  die "Failed to finalize installation at ${TARGET_APP}"
fi
STAGING_APP=""
rm -rf "${BACKUP_APP}"

if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "${TARGET_APP}" 2>/dev/null || true
fi

hdiutil detach "${MOUNT_DIR}" >/dev/null 2>&1 || true
MOUNTED=0

log "Installed successfully: ${TARGET_APP}"
if [[ "${NO_OPEN}" -eq 0 ]] && command -v open >/dev/null 2>&1; then
  log "Launching ${APP_NAME}..."
  open "${TARGET_APP}"
fi
