$ErrorActionPreference = 'Stop'

$devModeKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
$allowDev = 0
$allowTrusted = 0
if (Test-Path $devModeKey) {
  $props = Get-ItemProperty -Path $devModeKey -ErrorAction SilentlyContinue
  if ($null -ne $props) {
    $allowDev = $props.AllowDevelopmentWithoutDevLicense
    $allowTrusted = $props.AllowAllTrustedApps
  }
}

$skipDevModeCheck = ($env:DSA_SKIP_DEVMODE_CHECK -eq 'true') -or ($env:CI -eq 'true')
if (-not $skipDevModeCheck -and ($allowDev -ne 1) -and ($allowTrusted -ne 1)) {
  Write-Host 'Developer Mode is disabled. Enable it to allow symlink creation for electron-builder.'
  Write-Host 'Windows Settings -> Privacy & security -> For developers -> Developer Mode'
  throw 'Developer Mode required for electron-builder cache extraction.'
}

$env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'
$env:ELECTRON_BUILDER_ALLOW_UNRESOLVED_SYMLINKS = 'true'
$env:ELECTRON_BUILDER_CACHE = "${PSScriptRoot}\..\.electron-builder-cache"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendArtifact = Join-Path $repoRoot 'dist\backend\stock_analysis'

if (!(Test-Path $backendArtifact)) {
  throw "Backend artifact not found: $backendArtifact. Run scripts\build-backend.ps1 first."
}

Write-Host 'Building Electron desktop app...'
Push-Location (Join-Path $repoRoot 'apps\dsa-desktop')
if (!(Test-Path 'node_modules')) {
  npm install
}

Write-Host 'Stopping running app (if any)...'
Get-Process -Name "Daily Stock Analysis" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "stock_analysis" -ErrorAction SilentlyContinue | Stop-Process -Force

if (Test-Path 'dist\win-unpacked') {
  Write-Host 'Cleaning dist\win-unpacked...'
  Remove-Item -Recurse -Force 'dist\win-unpacked'
}

$appBuilderPath = 'node_modules\app-builder-bin\win\x64\app-builder.exe'
if (!(Test-Path $appBuilderPath)) {
  Write-Host 'app-builder.exe missing, reinstalling dependencies...'
  if (Test-Path 'node_modules') {
    Remove-Item -Recurse -Force 'node_modules'
  }
  npm install
}

npx electron-builder --win nsis
if ($LASTEXITCODE -ne 0) {
  throw 'Electron build failed.'
}
Pop-Location

Write-Host 'Desktop build completed.'
