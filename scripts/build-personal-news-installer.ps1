param(
  [string]$ConfigPath = '',
  [switch]$SkipBackend,
  [switch]$SkipDesktop
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$previousBundleConfig = $env:DSA_BUNDLE_ENV_FILE

try {
  if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
    $resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
    $env:DSA_BUNDLE_ENV_FILE = $resolvedConfig
    Write-Host 'Using private personal-news configuration (values are not printed).'
  } else {
    $defaultPrivateConfig = Join-Path $repoRoot '.env.personal-news-bundle'
    if (Test-Path -LiteralPath $defaultPrivateConfig) {
      $env:DSA_BUNDLE_ENV_FILE = $defaultPrivateConfig
      Write-Host 'Using .env.personal-news-bundle (values are not printed).'
    } else {
      Write-Warning 'No private configuration found. The installer will contain empty credential fields.'
    }
  }

  Push-Location $repoRoot
  try {
    if (-not $SkipBackend) {
      & (Join-Path $PSScriptRoot 'build-backend.ps1')
    }
    if (-not $SkipDesktop) {
      & (Join-Path $PSScriptRoot 'build-desktop.ps1')
    }

    $desktopDist = Join-Path $repoRoot 'apps\dsa-desktop\dist'
    $installer = Get-ChildItem -LiteralPath $desktopDist -Filter 'daily-stock-analysis-windows-installer-*.exe' -File |
      Sort-Object LastWriteTimeUtc -Descending |
      Select-Object -First 1
    if ($null -eq $installer) {
      throw 'Windows installer was not generated.'
    }

    $releaseDir = Join-Path $repoRoot 'dist\personal-news-release'
    if (Test-Path -LiteralPath $releaseDir) {
      Remove-Item -LiteralPath $releaseDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $releaseDir | Out-Null
    Copy-Item -LiteralPath $installer.FullName -Destination $releaseDir

    $portableDir = Join-Path $desktopDist 'win-unpacked'
    if (-not (Test-Path -LiteralPath $portableDir)) {
      throw 'Portable win-unpacked directory was not generated.'
    }
    $portableZip = Join-Path $releaseDir 'personal-stock-news-windows-portable.zip'
    $sevenZip = Join-Path $repoRoot 'apps\dsa-desktop\node_modules\7zip-bin\win\x64\7za.exe'
    if (-not (Test-Path -LiteralPath $sevenZip)) {
      throw 'Bundled 7-Zip executable was not found.'
    }
    Push-Location $portableDir
    try {
      & $sevenZip 'a' '-tzip' '-mx=7' $portableZip '*'
      if ($LASTEXITCODE -ne 0) {
        throw "Portable ZIP creation failed with exit code $LASTEXITCODE."
      }
    } finally {
      Pop-Location
    }

    @(
      'Personal Stock News - Windows Setup',
      '',
      'Recommended: run daily-stock-analysis-windows-installer-*.exe and follow the wizard.',
      'The app starts after installation. Use the desktop shortcut next time.',
      'Portable: extract personal-stock-news-windows-portable.zip and run Daily Stock Analysis.exe.',
      'The bundled service configuration is filled automatically on first launch.',
      'Do not upload a credential-bearing package to public storage, releases, or public groups.'
    ) | Set-Content -LiteralPath (Join-Path $releaseDir 'README-INSTALL.txt') -Encoding utf8

    Write-Host "Personal-news release ready: $releaseDir"
    Get-ChildItem -LiteralPath $releaseDir -File | Select-Object Name, Length
  } finally {
    Pop-Location
  }
} finally {
  if ($null -eq $previousBundleConfig) {
    Remove-Item Env:DSA_BUNDLE_ENV_FILE -ErrorAction SilentlyContinue
  } else {
    $env:DSA_BUNDLE_ENV_FILE = $previousBundleConfig
  }
}
