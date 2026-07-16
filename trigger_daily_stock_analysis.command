#!/bin/zsh

set -euo pipefail

# Finder 双击 .command 时继承的 PATH 可能不包含 Homebrew 安装目录。
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"

REPOSITORY="${GITHUB_REPOSITORY:-liconquers/daily_stock_analysis}"
WORKFLOW="${GITHUB_WORKFLOW:-311211098}"
BRANCH="${GITHUB_BRANCH:-main}"
MODE="full"
MODE_SET="false"
FORCE_RUN="false"
DRY_RUN="false"
OPEN_ACTIONS="true"
RUNS_URL="https://github.com/${REPOSITORY}/actions"

usage() {
  cat <<'EOF'
用法：
  ./trigger_daily_stock_analysis.command [full|stocks-only|market-only] [选项]

选项：
  --force     跳过交易日检查，适合立即测试 Telegram 推送
  --dry-run   仅检查本机环境并显示将执行的命令，不触发云端任务
  --no-open   触发后不自动打开 GitHub Actions 页面
  -h, --help  显示帮助
EOF
}

fail() {
  print -u2 "❌ $1"
  if [[ "$OPEN_ACTIONS" == "true" ]] && command -v open >/dev/null 2>&1; then
    open "$RUNS_URL" >/dev/null 2>&1 || true
  fi
  exit "${2:-1}"
}

while (( $# > 0 )); do
  case "$1" in
    full|market-only|stocks-only)
      [[ "$MODE_SET" == "false" ]] || fail "只能指定一个运行模式。" 2
      MODE="$1"
      MODE_SET="true"
      ;;
    --force)
      FORCE_RUN="true"
      ;;
    --dry-run)
      DRY_RUN="true"
      ;;
    --no-open)
      OPEN_ACTIONS="false"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "不支持的参数: $1" 2
      ;;
  esac
  shift
done

case "$MODE" in
  full|market-only|stocks-only) ;;
  *) fail "不支持的运行模式: $MODE" 2 ;;
esac

GH_BIN="${GITHUB_CLI:-$(command -v gh 2>/dev/null || true)}"
[[ -n "$GH_BIN" && -x "$GH_BIN" ]] || fail "未找到 GitHub CLI。请先执行 brew install gh，再执行 gh auth login。"

"$GH_BIN" auth status --hostname github.com >/dev/null 2>&1 || fail "GitHub CLI 尚未登录。请先执行 gh auth login。"

print "GitHub CLI: $($GH_BIN --version | head -n 1)"
print "仓库: ${REPOSITORY}"
print "分支: ${BRANCH}"
print "模式: ${MODE}（强制运行: ${FORCE_RUN}）"

dispatch_args=(
  workflow run "$WORKFLOW"
  --repo "$REPOSITORY"
  --ref "$BRANCH"
  -f "mode=$MODE"
  -f "force_run=$FORCE_RUN"
)

if [[ "$DRY_RUN" == "true" ]]; then
  print "✅ 环境检查通过；dry-run 未触发云端任务。"
  print -r -- "将执行: $GH_BIN ${(q)dispatch_args}"
  exit 0
fi

# 记录触发前的最新运行，触发后据此定位本次新运行页面。
previous_run_url="$($GH_BIN run list \
  --repo "$REPOSITORY" \
  --workflow "$WORKFLOW" \
  --branch "$BRANCH" \
  --event workflow_dispatch \
  --limit 1 \
  --json url \
  --jq '.[0].url // ""' 2>/dev/null || true)"

print "正在触发 ${REPOSITORY} 的股票分析：mode=${MODE}, force_run=${FORCE_RUN}"
"$GH_BIN" "${dispatch_args[@]}" || fail "GitHub Actions 触发失败，请检查网络、仓库权限和工作流状态。"

run_url=""
for _ in {1..10}; do
  latest_run_url="$($GH_BIN run list \
    --repo "$REPOSITORY" \
    --workflow "$WORKFLOW" \
    --branch "$BRANCH" \
    --event workflow_dispatch \
    --limit 1 \
    --json url \
    --jq '.[0].url // ""' 2>/dev/null || true)"
  if [[ -n "$latest_run_url" && "$latest_run_url" != "$previous_run_url" ]]; then
    run_url="$latest_run_url"
    break
  fi
  sleep 1
done

print "已触发 GitHub Actions，分析完成后将按仓库配置推送到 Telegram。"
if [[ -n "$run_url" ]]; then
  print "本次运行: $run_url"
else
  run_url="$RUNS_URL"
  print "暂未取得本次运行链接，可在 Actions 页面查看队列状态。"
fi

if [[ "$OPEN_ACTIONS" == "true" ]] && command -v open >/dev/null 2>&1; then
  open "$run_url"
fi
