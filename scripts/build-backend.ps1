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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$requirementsPath = Join-Path $repoRoot 'requirements.txt'

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

function Install-PatchedLiteLLMFromGitHubSource {
  param(
    [string]$Python,
    [string]$Tag
  )

  $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "dsa-litellm-$Tag"
  $archivePath = Join-Path ([System.IO.Path]::GetTempPath()) "dsa-litellm-$Tag.zip"
  $extractRoot = Join-Path $tempRoot 'src'

  if (Test-Path $tempRoot) {
    Remove-Item -Recurse -Force $tempRoot
  }
  New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null

  $downloadUrl = "https://github.com/BerriAI/litellm/archive/refs/tags/$Tag.zip"
  Write-Host "Downloading patched LiteLLM source: $downloadUrl"
  Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath

  Expand-Archive -Path $archivePath -DestinationPath $extractRoot -Force
  $sourceDir = Get-ChildItem -Path $extractRoot -Directory | Select-Object -First 1
  if (-not $sourceDir) {
    throw "Unable to locate extracted LiteLLM source under $extractRoot."
  }

  $enterpriseDir = Join-Path $sourceDir.FullName 'enterprise'
  if (Test-Path $enterpriseDir) {
    # Work around Poetry wheel build failures on Windows when the upstream source archive
    # includes LiteLLM's optional enterprise package tree.
    Remove-Item -Recurse -Force $enterpriseDir
  }

  & $Python -m pip install $sourceDir.FullName
  if ($LASTEXITCODE -ne 0) {
    throw "Patched LiteLLM install failed with exit code $LASTEXITCODE."
  }
}

function Install-BackendDependencies {
  param(
    [string]$Python,
    [string]$RequirementsFile
  )

  $tempRequirements = Join-Path ([System.IO.Path]::GetTempPath()) 'dsa-desktop-backend-requirements.txt'
  $litellmTag = $null
  $filteredLines = foreach ($line in Get-Content $RequirementsFile) {
    if ($line -match '^\s*litellm\s*@\s*https://github\.com/BerriAI/litellm/archive/refs/tags/([^/\s]+)\.tar\.gz') {
      $litellmTag = $Matches[1]
      continue
    }
    $line
  }

  Set-Content -Path $tempRequirements -Value $filteredLines

  & $Python -m pip install -r $tempRequirements
  if ($LASTEXITCODE -ne 0) {
    throw "pip install -r $tempRequirements failed with exit code $LASTEXITCODE."
  }

  if ($litellmTag) {
    Install-PatchedLiteLLMFromGitHubSource -Python $Python -Tag $litellmTag
  }
}

Write-Host 'Building backend executable...'
if (-not (Test-PythonCode -Python $pythonBin -Code "import PyInstaller")) {
  & $pythonBin -m pip install pyinstaller
}

Write-Host 'Installing backend dependencies...'
Install-BackendDependencies -Python $pythonBin -RequirementsFile $requirementsPath

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
  '--collect-data', 'litellm',
  '--collect-data', 'tiktoken'
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
