# 虚拟交易员开机自启配置脚本（Windows 任务计划程序）
#
# 用法：
#   配置开机启动（默认）:  powershell -ExecutionPolicy Bypass -File scripts\setup_virtual_trader_task.ps1
#   移除任务:              powershell -ExecutionPolicy Bypass -File scripts\setup_virtual_trader_task.ps1 -Remove
#
# 说明：
# - 创建计划任务 "DSA Virtual Trader"，开机后延迟 1 分钟启动 `python main.py --virtual-trader` 常驻进程；
# - 进程内置每 30 分钟检查各市场（A/港/美）收盘状态，收盘后自动执行当日虚拟交易（幂等，重复触发不会重复成交）；
# - 需先在 .env 中设置 VIRTUAL_TRADER_ENABLED=true 并确认 python 在 PATH 中。

param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$TaskName = "DSA Virtual Trader"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "已移除计划任务 $TaskName"
    exit 0
}

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    Write-Error "未找到 python，请先安装并加入 PATH"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "main.py --virtual-trader" -WorkingDirectory $RepoRoot
# 开机后延迟 1 分钟启动，避开开机高峰；进程常驻自行调度
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT60S"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "DSA 虚拟交易员：每日收盘后按均值回归策略模拟买卖并复盘预测" -Force | Out-Null

Write-Host "已创建计划任务 $TaskName"
Write-Host "  启动命令: $pythonExe main.py --virtual-trader"
Write-Host "  工作目录: $RepoRoot"
Write-Host "提示：请确认 .env 中已设置 VIRTUAL_TRADER_ENABLED=true"
Write-Host "手动执行一次: schtasks /run /tn `"$TaskName`""
