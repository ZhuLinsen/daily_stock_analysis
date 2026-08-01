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

Write-Host 'Verifying static asset references (source)...'
& $pythonBin "${PSScriptRoot}\check_static_assets.py" 'static'
if ($LASTEXITCODE -ne 0) {
  throw "Static asset sanity check failed for source static/. See GitHub #1064."
}

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
if ($LASTEXITCODE -ne 0) {
  throw "pip install -r requirements.txt failed with exit code $LASTEXITCODE."
}

Write-Host 'Checking python-multipart availability...'
if (-not (Test-PythonCode -Python $pythonBin -Code "import multipart, multipart.multipart")) {
  throw 'python-multipart is not importable in the selected Python environment.'
}

Write-Host 'Checking built-in screening engine availability...'
if (-not (Test-PythonCode -Python $pythonBin -Code "import src.services.screening.pipeline")) {
  throw 'src.services.screening.pipeline is not importable.'
}

Write-Host 'Checking Futu SDK availability...'
if (-not (Test-PythonCode -Python $pythonBin -Code "import futu")) {
  throw 'futu is not importable after installing requirements.'
}

Write-Host 'Checking orjson availability...'
if (-not (Test-PythonCode -Python $pythonBin -Code "import orjson")) {
  throw 'orjson is not importable after installing requirements.'
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
  'orjson',
  'tiktoken',
  'tiktoken_ext',
  'tiktoken_ext.openai_public',
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
  'api.v1.endpoints.screening',
  'src.services.screening',
  'src.services.screening.pipeline',
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
  'src.services.screening_service',
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
  '--add-data', 'strategies;strategies',
  '--collect-data', 'litellm',
  '--collect-data', 'tiktoken',
  '--collect-data', 'akshare',
  '--collect-all', 'src.services.screening',
  '--collect-all', 'futu'
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

Write-Host 'Verifying packaged runtime imports...'
$packagedEntry = Join-Path 'dist\backend\stock_analysis' 'stock_analysis.exe'
if (-not (Test-Path $packagedEntry)) {
  throw "Packaged backend entrypoint not found: $packagedEntry"
}
$previousProbe = $env:DSA_PACKAGED_IMPORT_PROBE
try {
  foreach ($module in @('src.services.screening.pipeline', 'futu', 'orjson')) {
    $env:DSA_PACKAGED_IMPORT_PROBE = $module
    $probeProcess = Start-Process -FilePath $packagedEntry -Wait -PassThru
    if ($probeProcess.ExitCode -ne 0) {
      throw "Packaged backend cannot import $module; probe exited with code $($probeProcess.ExitCode)."
    }
  }
} finally {
  if ($null -eq $previousProbe) {
    Remove-Item Env:DSA_PACKAGED_IMPORT_PROBE -ErrorAction SilentlyContinue
  } else {
    $env:DSA_PACKAGED_IMPORT_PROBE = $previousProbe
  }
}

Write-Host 'Verifying packaged AkShare calendar data...'
$packagedAkshareCalendar = Join-Path 'dist\backend\stock_analysis' '_internal\akshare\file_fold\calendar.json'
if (-not (Test-Path $packagedAkshareCalendar)) {
  $packagedAkshareCalendar = Join-Path 'dist\backend\stock_analysis' 'akshare\file_fold\calendar.json'
}
if (-not (Test-Path $packagedAkshareCalendar)) {
  throw 'Packaged AkShare calendar data not found under dist\backend\stock_analysis.'
}

Write-Host 'Verifying static asset references (packaged)...'
$packagedStatic = Join-Path 'dist\backend\stock_analysis' '_internal\static'
if (-not (Test-Path $packagedStatic)) {
  $packagedStatic = Join-Path 'dist\backend\stock_analysis' 'static'
}
if (Test-Path $packagedStatic) {
  & $pythonBin "${PSScriptRoot}\check_static_assets.py" $packagedStatic
  if ($LASTEXITCODE -ne 0) {
    throw "Static asset sanity check failed for packaged $packagedStatic. See GitHub #1064."
  }
} else {
  Write-Warning "Could not locate packaged static directory under dist\backend\stock_analysis; skipping post-package check."
}

Write-Host 'Verifying packaged built-in strategies...'
$sourceStrategyCount = @(Get-ChildItem -Path 'strategies' -Filter '*.yaml' -File).Count
$packagedStrategies = Join-Path 'dist\backend\stock_analysis' '_internal\strategies'
if (-not (Test-Path $packagedStrategies)) {
  $packagedStrategies = Join-Path 'dist\backend\stock_analysis' 'strategies'
}
if (-not (Test-Path $packagedStrategies)) {
  throw 'Packaged strategies directory not found under dist\backend\stock_analysis.'
}
$packagedStrategyCount = @(Get-ChildItem -Path $packagedStrategies -Filter '*.yaml' -File).Count
if ($packagedStrategyCount -ne $sourceStrategyCount) {
  throw "Packaged strategies count mismatch: expected $sourceStrategyCount, got $packagedStrategyCount."
}

Write-Host 'Verifying packaged screening strategies...'
$sourceScreeningStrategies = Join-Path 'src\services\screening' 'strategies'
$sourceScreeningStrategyCount = @(Get-ChildItem -Path $sourceScreeningStrategies -Filter '*.yaml' -File).Count
$packagedScreeningStrategies = Join-Path 'dist\backend\stock_analysis' '_internal\src\services\screening\strategies'
if (-not (Test-Path $packagedScreeningStrategies)) {
  $packagedScreeningStrategies = Join-Path 'dist\backend\stock_analysis' 'src\services\screening\strategies'
}
if (-not (Test-Path $packagedScreeningStrategies)) {
  throw 'Packaged screening strategies directory not found under dist\backend\stock_analysis.'
}
$packagedScreeningStrategyCount = @(Get-ChildItem -Path $packagedScreeningStrategies -Filter '*.yaml' -File).Count
if ($packagedScreeningStrategyCount -ne $sourceScreeningStrategyCount) {
  throw "Packaged screening strategies count mismatch: expected $sourceScreeningStrategyCount, got $packagedScreeningStrategyCount."
}

Write-Host 'Backend build completed.'
