$ErrorActionPreference = 'Stop'

Write-Host '=== Daily Stock Analysis Desktop Build ==='

& "${PSScriptRoot}\build-backend.ps1"
& "${PSScriptRoot}\build-desktop.ps1"

Write-Host 'All builds completed.'
