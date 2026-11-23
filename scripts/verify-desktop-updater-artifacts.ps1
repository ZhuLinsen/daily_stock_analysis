param(
  [string]$DistDir = '',
  [string]$ReleaseTag = '',
  [string]$ReleaseAssetsDir = ''
)

$ErrorActionPreference = 'Stop'

function Resolve-ReleaseTag {
  param([string]$Tag)

  if (-not $Tag) {
    return '';
  }
  return $Tag.Trim();
}

function Normalize-SemverText {
  param([string]$VersionText)

  return ($VersionText -replace '^v', '').Trim();
}

if (-not $DistDir) {
  $DistDir = Join-Path $PSScriptRoot '..\apps\dsa-desktop\dist'
}

$resolvedDistDir = Resolve-Path $DistDir -ErrorAction SilentlyContinue
$distDirPath = ''
if ($resolvedDistDir) {
  $distDirPath = $resolvedDistDir.Path
}
if (-not $distDirPath) {
  Write-Host "[check] dist directory not found: $DistDir"
  Write-Host "[check] if build is not executed on this host, skip validation."
  exit 0
}

$packageJsonPath = Join-Path $PSScriptRoot '..\apps\dsa-desktop\package.json'
if (-not (Test-Path $packageJsonPath)) {
  throw "Package manifest missing: $packageJsonPath"
}

$packageMeta = Get-Content -Path $packageJsonPath -Raw | ConvertFrom-Json
$normalizedPackageVersion = Normalize-SemverText -VersionText $packageMeta.version
if (-not $normalizedPackageVersion) {
  throw "Cannot resolve package version from $packageJsonPath"
}

$normalizedReleaseTag = Normalize-SemverText -VersionText (Resolve-ReleaseTag -Tag $ReleaseTag)
if (-not $normalizedReleaseTag) {
  $normalizedReleaseTag = $normalizedPackageVersion
}

$latestPath = Join-Path $distDirPath 'latest.yml'
if (-not (Test-Path $latestPath)) {
  throw "latest.yml not found in dist: $distDirPath"
}

$ymlText = Get-Content -Path $latestPath -Raw
if ($ymlText -match 'version:\s*([\d][^\s\r\n]*)') {
  $normalizedLatestVersion = Normalize-SemverText -VersionText $matches[1]
} else {
  throw "latest.yml missing valid version field: $latestPath"
}

if ($normalizedLatestVersion -ne $normalizedReleaseTag) {
  throw "Version mismatch: latest.yml=$normalizedLatestVersion, expected=$normalizedReleaseTag"
}

$expectedInstallerFileName = "daily-stock-analysis-windows-installer-v$normalizedReleaseTag.exe"

if ($ymlText -match '(?m)^\s*path:\s*[''"]?([^''"\r\n]+)[''"]?\s*$') {
  $latestInstallerPath = $matches[1].Trim()
} else {
  throw "latest.yml appears invalid: missing path field."
}

if ($latestInstallerPath -ne $expectedInstallerFileName) {
  throw "latest.yml path ($latestInstallerPath) does not match expected installer $expectedInstallerFileName."
}

if ($ymlText -match '(?m)^\s*-\s*url:\s*[''"]?([^''"\r\n]+)[''"]?\s*$') {
  $latestInstallerUrl = $matches[1].Trim()
  if ($latestInstallerUrl -ne $expectedInstallerFileName) {
    throw "latest.yml file url ($latestInstallerUrl) does not match expected installer $expectedInstallerFileName."
  }
}

$setupFiles = Get-ChildItem -Path $distDirPath -Filter $expectedInstallerFileName -File -ErrorAction SilentlyContinue
if (-not $setupFiles) {
  throw "No expected NSIS installer found in dist: $expectedInstallerFileName"
}

$expectedBlockmapFileName = "$expectedInstallerFileName.blockmap"
$blockmapFiles = Get-ChildItem -Path $distDirPath -Filter $expectedBlockmapFileName -File -ErrorAction SilentlyContinue
if (-not $blockmapFiles) {
  throw "No matching blockmap found in dist: $expectedBlockmapFileName"
}

$installerFiles = @()
$releaseAssetsDirPath = ''
$releaseAssetsDirWasExplicit = -not [string]::IsNullOrWhiteSpace($ReleaseAssetsDir)

if ($releaseAssetsDirWasExplicit) {
  $resolvedReleaseAssetsDir = Resolve-Path $ReleaseAssetsDir -ErrorAction SilentlyContinue
  if ($resolvedReleaseAssetsDir) {
    $releaseAssetsDirPath = $resolvedReleaseAssetsDir.Path
  }
  if (-not $releaseAssetsDirPath) {
    throw "Release assets directory not found: $ReleaseAssetsDir"
  }
} elseif ((Split-Path -Path $distDirPath -Leaf) -eq 'release-assets') {
  $releaseAssetsDirPath = $distDirPath
} else {
  $defaultReleaseAssetsDir = Join-Path $distDirPath 'release-assets'
  $resolvedReleaseAssetsDir = Resolve-Path $defaultReleaseAssetsDir -ErrorAction SilentlyContinue
  if ($resolvedReleaseAssetsDir) {
    $releaseAssetsDirPath = $resolvedReleaseAssetsDir.Path
  }
}

if ($releaseAssetsDirPath) {
  $installerFiles = Get-ChildItem -Path $releaseAssetsDirPath -Filter $expectedInstallerFileName -File -ErrorAction SilentlyContinue
  if (-not $installerFiles) {
    throw "No expected Windows installer found in release assets: $expectedInstallerFileName"
  }
} else {
  Write-Host "[check] release attachment alias check skipped: run after release assets are prepared or pass -ReleaseAssetsDir."
}

Write-Host "[check] dist: $distDirPath"
Write-Host "[check] latest.yml version: $normalizedLatestVersion"
Write-Host "[check] expected release version: $normalizedReleaseTag"
Write-Host "[check] latest.yml installer path: $latestInstallerPath"
Write-Host "[check] NSIS installers:"
$setupFiles | ForEach-Object { Write-Host "[found] $($_.Name)" }
if ($installerFiles) {
  Write-Host "[check] release assets: $releaseAssetsDirPath"
  Write-Host "[check] installer aliases:"
  $installerFiles | ForEach-Object { Write-Host "[found] $($_.Name)" }
}
Write-Host "[check] blockmaps:"
$blockmapFiles | ForEach-Object { Write-Host "[found] $($_.Name)" }

$versionInTag = Normalize-SemverText -VersionText $ReleaseTag
if ($versionInTag -and $versionInTag -ne $normalizedReleaseTag) {
  Write-Host "[warn] input release tag ($versionInTag) differs from package version ($normalizedReleaseTag)."
}

Write-Host '[check] desktop updater metadata verification passed.'
exit 0
