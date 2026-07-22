#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() {
  echo "$1"
}

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    PYTHON_BIN="python"
  fi
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python not found. Please install Python 3.10+ and retry."
  exit 1
fi

log "Building React UI (static assets)..."
pushd "${ROOT_DIR}/apps/dsa-web" >/dev/null
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build
popd >/dev/null

log "Verifying static asset references (source)..."
"${PYTHON_BIN}" "${SCRIPT_DIR}/check_static_assets.py" "${ROOT_DIR}/static"

log "Building backend executable..."
if ! "${PYTHON_BIN}" -m PyInstaller --version >/dev/null 2>&1; then
  "${PYTHON_BIN}" -m pip install pyinstaller
fi

log "Installing backend dependencies..."
"${PYTHON_BIN}" -m pip install -r "${ROOT_DIR}/requirements.txt"

log "Checking python-multipart availability..."
"${PYTHON_BIN}" -c "import multipart, multipart.multipart"

log "Checking AlphaSift adapter availability..."
"${PYTHON_BIN}" -c "import alphasift.dsa_adapter"

log "Checking Futu SDK availability..."
"${PYTHON_BIN}" -c "import futu"

log "Checking orjson availability..."
"${PYTHON_BIN}" -c "import orjson"

if [[ -d "${ROOT_DIR}/dist/backend" ]]; then
  rm -rf "${ROOT_DIR}/dist/backend"
fi
mkdir -p "${ROOT_DIR}/dist/backend"

if [[ -d "${ROOT_DIR}/dist/stock_analysis" ]]; then
  rm -rf "${ROOT_DIR}/dist/stock_analysis"
fi

if [[ -d "${ROOT_DIR}/build/stock_analysis" ]]; then
  rm -rf "${ROOT_DIR}/build/stock_analysis"
fi

hidden_imports=(
  "multipart"
  "multipart.multipart"
  "json_repair"
  "tiktoken"
  "tiktoken_ext"
  "tiktoken_ext.openai_public"
  "api"
  "api.app"
  "api.deps"
  "api.v1"
  "api.v1.router"
  "api.v1.endpoints"
  "api.v1.endpoints.analysis"
  "api.v1.endpoints.history"
  "api.v1.endpoints.stocks"
  "api.v1.endpoints.health"
  "api.v1.endpoints.alphasift"
  "api.v1.schemas"
  "api.v1.schemas.analysis"
  "api.v1.schemas.history"
  "api.v1.schemas.stocks"
  "api.v1.schemas.common"
  "api.middlewares"
  "api.middlewares.error_handler"
  "src.services"
  "src.services.task_queue"
  "src.services.analysis_service"
  "src.services.history_service"
  "src.services.alphasift_service"
  "alphasift"
  "alphasift.dsa_adapter"
  "orjson"
  "uvicorn.logging"
  "uvicorn.loops"
  "uvicorn.loops.auto"
  "uvicorn.protocols"
  "uvicorn.protocols.http"
  "uvicorn.protocols.http.auto"
  "uvicorn.protocols.websockets"
  "uvicorn.protocols.websockets.auto"
  "uvicorn.lifespan"
  "uvicorn.lifespan.on"
)

hidden_import_args=()
for module in "${hidden_imports[@]}"; do
  hidden_import_args+=("--hidden-import=${module}")
done

pushd "${ROOT_DIR}" >/dev/null
cmd=("${PYTHON_BIN}" -m PyInstaller --name stock_analysis --onedir --noconfirm --noconsole --add-data "static:static" --add-data "strategies:strategies" --collect-data litellm --collect-data tiktoken --collect-data akshare)
cmd+=("--collect-all" "alphasift")
cmd+=("--collect-all" "futu")
cmd+=("${hidden_import_args[@]}" "main.py")

echo "Running: ${cmd[*]}"
"${cmd[@]}"
popd >/dev/null

cp -R "${ROOT_DIR}/dist/stock_analysis" "${ROOT_DIR}/dist/backend/stock_analysis"

log "Verifying packaged runtime imports..."
packaged_root="${ROOT_DIR}/dist/backend/stock_analysis"

packaged_entry="${packaged_root}/stock_analysis"
if [[ ! -x "${packaged_entry}" ]]; then
  echo "ERROR: packaged backend entrypoint not found or not executable: ${packaged_entry}."
  exit 1
fi

# 先校验可执行文件可启动（不进入业务流程的参数），再检查冻结产物中的关键依赖。
if ! "${packaged_entry}" --help >/tmp/dsa-packaged-help.log 2>&1; then
  echo "ERROR: packaged backend help startup check failed."
  cat /tmp/dsa-packaged-help.log
  exit 1
fi

for module in alphasift.dsa_adapter futu orjson; do
  if DSA_PACKAGED_IMPORT_PROBE="${module}" "${packaged_entry}" >/tmp/dsa-packaged-import.log 2>&1; then
    cat /tmp/dsa-packaged-import.log
  else
    echo "ERROR: packaged backend artifact cannot import ${module}."
    cat /tmp/dsa-packaged-import.log
    exit 1
  fi
done

log "Verifying packaged AkShare calendar data..."
packaged_akshare_calendar="${packaged_root}/_internal/akshare/file_fold/calendar.json"
if [[ ! -f "${packaged_akshare_calendar}" ]]; then
  packaged_akshare_calendar="${packaged_root}/akshare/file_fold/calendar.json"
fi
if [[ ! -f "${packaged_akshare_calendar}" ]]; then
  echo "ERROR: packaged AkShare calendar data not found under ${packaged_root}."
  exit 1
fi

log "Verifying static asset references (packaged)..."
packaged_static="${ROOT_DIR}/dist/backend/stock_analysis/_internal/static"
if [[ ! -d "${packaged_static}" ]]; then
  packaged_static="${ROOT_DIR}/dist/backend/stock_analysis/static"
fi
if [[ -d "${packaged_static}" ]]; then
  "${PYTHON_BIN}" "${SCRIPT_DIR}/check_static_assets.py" "${packaged_static}"
else
  log "WARNING: could not locate packaged static directory under dist/backend/stock_analysis; skipping post-package check."
fi

log "Verifying packaged built-in strategies..."
source_strategy_count="$(find "${ROOT_DIR}/strategies" -maxdepth 1 -type f -name '*.yaml' | wc -l | tr -d '[:space:]')"
packaged_strategies="${ROOT_DIR}/dist/backend/stock_analysis/_internal/strategies"
if [[ ! -d "${packaged_strategies}" ]]; then
  packaged_strategies="${ROOT_DIR}/dist/backend/stock_analysis/strategies"
fi
if [[ ! -d "${packaged_strategies}" ]]; then
  echo "ERROR: packaged strategies directory not found under dist/backend/stock_analysis."
  exit 1
fi
packaged_strategy_count="$(find "${packaged_strategies}" -maxdepth 1 -type f -name '*.yaml' | wc -l | tr -d '[:space:]')"
if [[ "${packaged_strategy_count}" != "${source_strategy_count}" ]]; then
  echo "ERROR: packaged strategies count mismatch: expected ${source_strategy_count}, got ${packaged_strategy_count}."
  exit 1
fi

log "Backend build completed."
