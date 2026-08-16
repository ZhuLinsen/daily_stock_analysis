param(
    [string]$TaskName = "DSA-Intraday-Picker",
    [string]$StartTime = "09:24"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$Runner = Join-Path $RepoRoot "scripts\intraday_picker_runner.py"

if (-not (Test-Path $Runner)) {
    throw "intraday picker runner not found: $Runner"
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Runner`"" -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $StartTime
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null

Write-Host "Installed task: $TaskName"
Write-Host "Worker startup: weekdays $StartTime (host local time)"
Write-Host "Actual scan times are checked again by the runner in Asia/Shanghai."
