#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Daily Stock Analysis Desktop Build (macOS) ==="

bash "${SCRIPT_DIR}/build-backend-macos.sh"
bash "${SCRIPT_DIR}/build-desktop-macos.sh"

echo "All builds completed."
