#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <normalize|check> <artifact-path>" >&2
}

mode="${1:-}"
artifact_root="${2:-}"

if [[ "${mode}" != "normalize" ]] && [[ "${mode}" != "check" ]]; then
  usage
  exit 2
fi
if [[ -z "${artifact_root}" ]] || [[ ! -e "${artifact_root}" ]]; then
  echo "ERROR: macOS signature audit target does not exist: ${artifact_root:-<empty>}" >&2
  exit 2
fi
if ! command -v codesign >/dev/null 2>&1; then
  echo "ERROR: codesign is required for macOS signature auditing." >&2
  exit 2
fi
if ! command -v file >/dev/null 2>&1; then
  echo "ERROR: file is required for macOS signature auditing." >&2
  exit 2
fi

checked_count=0
signed_count=0
resigned_count=0

is_signable_bundle_dir() {
  local candidate="$1"
  case "${candidate}" in
    *.app|*.xpc)
      [[ -f "${candidate}/Contents/Info.plist" || -f "${candidate}/Info.plist" ]]
      ;;
    *.framework)
      # PyInstaller --onedir may place partial framework directories (for example
      # _internal/Python.framework without Versions/Current or Info.plist); sign
      # their Mach-O binaries as files and only codesign complete framework bundles.
      [[ -e "${candidate}/Versions/Current" || -f "${candidate}/Resources/Info.plist" || -f "${candidate}/Info.plist" ]]
      ;;
    *)
      return 1
      ;;
  esac
}

is_adhoc_signature() {
  local details="$1"
  [[ "${details}" == *"Signature=adhoc"* ]] && [[ "${details}" != *"Authority="* ]]
}

ad_hoc_sign_candidate() {
  local candidate="$1"
  local reason="$2"
  local signature_details=""

  echo "WARNING: applying ad-hoc signature (${reason}) to macOS artifact: ${candidate}"
  codesign --force --sign - --timestamp=none "${candidate}"
  resigned_count=$((resigned_count + 1))

  if ! signature_details="$(codesign -d --verbose=4 "${candidate}" 2>&1)"; then
    echo "ERROR: failed to read ad-hoc signature after signing: ${candidate}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi
  if ! is_adhoc_signature "${signature_details}"; then
    echo "ERROR: artifact signature is not ad-hoc after signing: ${candidate}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi
  if ! codesign --verify --strict --verbose=4 "${candidate}" >/dev/null 2>&1; then
    echo "ERROR: ad-hoc signature verification failed after signing: ${candidate}" >&2
    codesign --verify --strict --verbose=4 "${candidate}" || true
    exit 1
  fi
}

audit_candidate() {
  local candidate="$1"
  local signature_details=""

  checked_count=$((checked_count + 1))
  if ! signature_details="$(codesign -d --verbose=4 "${candidate}" 2>&1)"; then
    if [[ "${signature_details}" == *"code object is not signed at all"* ]]; then
      if [[ "${mode}" == "normalize" ]]; then
        ad_hoc_sign_candidate "${candidate}" "unsigned"
        signed_count=$((signed_count + 1))
        return 0
      fi
      echo "ERROR: unsigned macOS artifact (unsupported on Apple Silicon arm64): ${candidate}" >&2
      echo "${signature_details}" >&2
      exit 1
    fi
    if [[ "${mode}" == "normalize" ]]; then
      ad_hoc_sign_candidate "${candidate}" "unreadable signature"
      signed_count=$((signed_count + 1))
      return 0
    fi
    echo "ERROR: unreadable or invalid signature in macOS artifact: ${candidate}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi

  if codesign --verify --strict --verbose=4 "${candidate}" >/dev/null 2>&1; then
    if is_adhoc_signature "${signature_details}"; then
      signed_count=$((signed_count + 1))
      return 0
    fi
    if [[ "${mode}" == "normalize" ]]; then
      ad_hoc_sign_candidate "${candidate}" "non-adhoc signature"
      signed_count=$((signed_count + 1))
      return 0
    fi
    echo "ERROR: non-adhoc signature in macOS artifact (expected uniform ad-hoc signature): ${candidate}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi

  if [[ "${mode}" == "normalize" ]]; then
    ad_hoc_sign_candidate "${candidate}" "invalid signature"
    signed_count=$((signed_count + 1))
    return 0
  fi

  echo "ERROR: invalid signature in macOS artifact: ${candidate}" >&2
  codesign --verify --strict --verbose=4 "${candidate}" || true
  exit 1
}

while IFS= read -r -d '' candidate; do
  if [[ -d "${candidate}" ]]; then
    if is_signable_bundle_dir "${candidate}"; then
      audit_candidate "${candidate}"
    fi
  elif file -b "${candidate}" | grep -q "Mach-O"; then
    audit_candidate "${candidate}"
  fi
done < <(
  find "${artifact_root}" -depth \
    \( -type f -o -type d \( -name "*.app" -o -name "*.framework" -o -name "*.xpc" \) \) \
    -print0
)

echo "macOS signature audit complete: mode=${mode}, checked=${checked_count}, signed=${signed_count}, resigned=${resigned_count}"
