#!/bin/zsh

set -euo pipefail

REPOSITORY="${GITHUB_REPOSITORY:-liconquers/daily_stock_analysis}"
WORKFLOW="${GITHUB_WORKFLOW:-311211098}"
BRANCH="${GITHUB_BRANCH:-main}"
MODE="${1:-full}"
FORCE_RUN="false"
RUNS_URL="https://github.com/${REPOSITORY}/actions"

if [[ "${2:-}" == "--force" || "${1:-}" == "--force" ]]; then
  FORCE_RUN="true"
  [[ "$MODE" == "--force" ]] && MODE="full"
fi

case "$MODE" in
  full|market-only|stocks-only) ;;
  *)
    print -u2 "不支持的运行模式: $MODE"
    print -u2 "可用模式: full、market-only、stocks-only"
    exit 2
    ;;
esac

if ! command -v gh >/dev/null 2>&1; then
  print -u2 "未找到 GitHub CLI。请先安装并执行 gh auth login。"
  open "$RUNS_URL"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  print -u2 "GitHub CLI 尚未登录。请先执行 gh auth login。"
  open "$RUNS_URL"
  exit 1
fi

print "正在触发 ${REPOSITORY} 的股票分析：mode=${MODE}, force_run=${FORCE_RUN}"
gh workflow run "$WORKFLOW" \
  --repo "$REPOSITORY" \
  --ref "$BRANCH" \
  -f "mode=$MODE" \
  -f "force_run=$FORCE_RUN"

print "已触发 GitHub Actions，分析完成后将按仓库配置推送到 Telegram。"
open "$RUNS_URL"
