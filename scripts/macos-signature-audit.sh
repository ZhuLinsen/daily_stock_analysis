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
removed_count=0

remove_broken_signature() {
  local candidate="$1"
  local signature_details=""

  echo "WARNING: removing invalid signature from unsigned macOS artifact: ${candidate}"
  codesign --remove-signature "${candidate}"
  removed_count=$((removed_count + 1))

  signature_details="$(codesign -d "${candidate}" 2>&1 || true)"
  if [[ "${signature_details}" != *"code object is not signed at all"* ]]; then
    echo "ERROR: failed to remove invalid signature: ${candidate}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi
}

audit_candidate() {
  local candidate="$1"
  local signature_details=""

  checked_count=$((checked_count + 1))
  if ! signature_details="$(codesign -d "${candidate}" 2>&1)"; then
    if [[ "${signature_details}" == *"code object is not signed at all"* ]]; then
      return 0
    fi
    if [[ "${mode}" == "normalize" ]]; then
      remove_broken_signature "${candidate}"
      return 0
    fi
    echo "ERROR: unreadable or invalid signature in macOS artifact: ${candidate}" >&2
    echo "${signature_details}" >&2
    exit 1
  fi

  signed_count=$((signed_count + 1))
  if codesign --verify --strict --verbose=4 "${candidate}" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "${mode}" == "normalize" ]]; then
    remove_broken_signature "${candidate}"
    return 0
  fi

  echo "ERROR: invalid signature in macOS artifact: ${candidate}" >&2
  codesign --verify --strict --verbose=4 "${candidate}" || true
  exit 1
}

while IFS= read -r -d '' candidate; do
  if [[ -d "${candidate}" ]]; then
    audit_candidate "${candidate}"
  elif file -b "${candidate}" | grep -q "Mach-O"; then
    audit_candidate "${candidate}"
  fi
done < <(
  find "${artifact_root}" -depth \
    \( -type f -o -type d \( -name "*.app" -o -name "*.framework" -o -name "*.xpc" \) \) \
    -print0
)

echo "macOS signature audit complete: mode=${mode}, checked=${checked_count}, signed=${signed_count}, removed=${removed_count}"
