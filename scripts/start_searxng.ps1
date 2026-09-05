<#
.SYNOPSIS
  幂等启动自建 SearXNG（Docker 容器）并做健康检查，自愈新闻搜索链路。

.DESCRIPTION
  - 若 Docker Desktop 未运行，先自动拉起并等待 daemon 就绪。
  - 若 SearXNG 容器不存在则创建（挂载 d:\searxng 配置、8888->8080、
    restart=unless-stopped）；若存在但停止则直接启动。
  - 最后轮询 http://localhost:8888/search?format=json 确认服务可响应。

  退出码: 0 = 服务可用; 1 = 环境缺 Docker; 2 = 超时后仍不可用。

.PARAMETER Port
  SearXNG 对外端口（默认 8888，需与 .env 中 SEARXNG_BASE_URLS 一致）。

.PARAMETER ConfigDir
  SearXNG settings.yml 所在目录（默认 d:\searxng，需在 settings.yml
  search.formats 中启用 json）。

.PARAMETER WaitSeconds
  Docker daemon 与健康检查的总等待上限（秒，默认 180）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/start_searxng.ps1
#>
param(
    [int]$Port = 8888,
    [string]$ConfigDir = "d:\searxng",
    [int]$WaitSeconds = 180
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "[searxng] $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "[searxng] $msg" -ForegroundColor Green }
function Write-Fail($msg){ Write-Host "[searxng] $msg" -ForegroundColor Red }

# ---------- 1. Docker CLI 可用性 ----------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Fail "未找到 docker 命令，请先安装 Docker Desktop：https://www.docker.com/products/docker-desktop/"
    exit 1
}

# ---------- 2. Docker daemon 就绪（必要时拉起 Docker Desktop） ----------
$daemonReady = $false
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { $daemonReady = $true; break }
    if (-not $dockerLaunched) {
        $dockerLaunched = $true
        $candidates = @(
            Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe",
            Join-Path ${env:ProgramFiles(x86)} "Docker\Docker\Docker Desktop.exe"
        )
        $exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($exe) {
            Write-Step "Docker Desktop 未运行，正在启动: $exe"
            Start-Process -FilePath $exe | Out-Null
        } else {
            Write-Step "未找到 Docker Desktop 可执行文件，请手动启动后重试"
        }
    }
    Start-Sleep -Seconds 3
}
if (-not $daemonReady) {
    Write-Fail "等待 Docker daemon 就绪超时（${WaitSeconds}s）。请确认 Docker Desktop 已启动。"
    exit 2
}
Write-OK "Docker daemon 就绪"

# ---------- 3. 确保 SearXNG 容器存在并运行（幂等） ----------
$container = docker ps -a --filter "name=^/searxng$" --format "{{.Names}}" 2>$null
if ([string]::IsNullOrWhiteSpace($container)) {
    Write-Step "创建 SearXNG 容器（镜像 searxng/searxng:latest, ${Port}:8080, 挂载 $ConfigDir）"
    docker pull searxng/searxng:latest *> $null
    docker run -d --name searxng --restart unless-stopped -p "${Port}:8080" -v "${ConfigDir}:/etc/searxng" searxng/searxng:latest
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "SearXNG 容器创建失败（exit=$LASTEXITCODE）"
        exit 2
    }
} elseif ($(docker inspect -f "{{.State.Status}}" searxng 2>$null) -ne "running") {
    Write-Step "SearXNG 容器存在但已停止，正在启动: $(docker start searxng)"
}

# ---------- 4. 健康检查：8888 JSON 接口 ----------
$escapedQuery = [uri]::EscapeDataString("test")
$checkUrl = "http://localhost:${Port}/search?q=${escapedQuery}&format=json&pageno=1"
$ok = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri $checkUrl -TimeoutSec 10 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        # 容器刚起时 8888 尚未监听，继续等待
    }
    Start-Sleep -Seconds 4
}
if (-not $ok) {
    Write-Fail "健康检查超时：$checkUrl 不可达。请确认 settings.yml 已启用 format: json，且 $ConfigDir 挂载正确。"
    exit 2
}
Write-OK "SearXNG 自愈完成，服务可用：http://localhost:${Port} （.env 中 SEARXNG_BASE_URLS 应包含该地址）"
exit 0