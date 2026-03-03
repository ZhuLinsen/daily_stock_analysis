$ErrorActionPreference = 'Stop'

Write-Host 'Building React UI (static assets)...'
Push-Location 'apps\dsa-web'
if (!(Test-Path 'node_modules')) {
  npm install
}
npm run build
Pop-Location

$pythonBin = $env:PYTHON_BIN
if ([string]::IsNullOrWhiteSpace($pythonBin)) {
  $pythonBin = 'python'
}

Write-Host "Using Python: $pythonBin"

function Test-PythonCode {
  param(
    [string]$Python,
    [string]$Code
  )

  try {
    & $Python -c $Code *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

Write-Host 'Building backend executable...'
if (-not (Test-PythonCode -Python $pythonBin -Code "import PyInstaller")) {
  & $pythonBin -m pip install pyinstaller
}

Write-Host 'Installing backend dependencies...'
& $pythonBin -m pip install -r requirements.txt

Write-Host 'Checking python-multipart availability...'
if (-not (Test-PythonCode -Python $pythonBin -Code "import multipart, multipart.multipart")) {
  throw 'python-multipart is not importable in the selected Python environment.'
}

if (Test-Path 'dist\backend') {
  Remove-Item -Recurse -Force 'dist\backend'
}
New-Item -ItemType Directory -Path 'dist\backend' | Out-Null

if (Test-Path 'dist\stock_analysis') {
  Remove-Item -Recurse -Force 'dist\stock_analysis'
}

if (Test-Path 'build\stock_analysis') {
  Remove-Item -Recurse -Force 'build\stock_analysis'
}

$hiddenImports = @(
  'multipart',
  'multipart.multipart',
  'json_repair',
  'api',
  'api.app',
  'api.deps',
  'api.v1',
  'api.v1.router',
  'api.v1.endpoints',
  'api.v1.endpoints.analysis',
  'api.v1.endpoints.history',
  'api.v1.endpoints.stocks',
  'api.v1.endpoints.health',
  'api.v1.schemas',
  'api.v1.schemas.analysis',
  'api.v1.schemas.history',
  'api.v1.schemas.stocks',
  'api.v1.schemas.common',
  'api.middlewares',
  'api.middlewares.error_handler',
  'src.services',
  'src.services.task_queue',
  'src.services.analysis_service',
  'src.services.history_service',
  'uvicorn.logging',
  'uvicorn.loops',
  'uvicorn.loops.auto',
  'uvicorn.protocols',
  'uvicorn.protocols.http',
  'uvicorn.protocols.http.auto',
  'uvicorn.protocols.websockets',
  'uvicorn.protocols.websockets.auto',
  'uvicorn.lifespan',
  'uvicorn.lifespan.on'
)
$hiddenImportArgs = $hiddenImports | ForEach-Object { "--hidden-import=$_" }

$pyInstallerArgs = @(
  '-m', 'PyInstaller',
  '--name', 'stock_analysis',
  '--onedir',
  '--noconfirm',
  '--noconsole',
  '--add-data', 'static;static',
  '--collect-data', 'litellm'
)
$pyInstallerArgs += $hiddenImportArgs
$pyInstallerArgs += 'main.py'

Write-Host "Running: $pythonBin $($pyInstallerArgs -join ' ')"
& $pythonBin @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE."
}

if (!(Test-Path 'dist\stock_analysis')) {
  throw 'PyInstaller finished but dist\stock_analysis was not generated.'
}

Copy-Item -Path 'dist\stock_analysis' -Destination 'dist\backend\stock_analysis' -Recurse -Force

Write-Host 'Backend build completed.'
