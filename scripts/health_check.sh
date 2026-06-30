#!/usr/bin/env bash
set -u

APP_DIR="/opt/daily_stock_analysis"

echo "===== DSA Health Check ====="
date
echo

cd "$APP_DIR" || {
  echo "❌ 无法进入 $APP_DIR"
  exit 1
}

echo "【Git】"
git branch --show-current 2>/dev/null || true
git status --short 2>/dev/null || true
git log --oneline -5 2>/dev/null || true
echo

echo "【Service】"
systemctl is-active dsa || true
systemctl status dsa --no-pager -l | head -30 || true
echo

echo "【Config】"
if [ -f .env ]; then
  grep -E '^(STOCK_LIST|MARKET_REVIEW_ENABLED|MARKET_REVIEW_REGION|LITELLM_MODEL|OPENAI_MODEL)=' .env || true
else
  echo "⚠️ .env 不存在"
fi
echo

echo "【Cron】"
crontab -l 2>/dev/null | grep -E 'daily_stock_analysis|main.py|analyzer|dsa' || true
echo

echo "【Port】"
ss -lntp | grep -E ':8080|:8081|:8000|:5000' || true
echo

echo "【Latest reports】"
ls -lt reports 2>/dev/null | head -10 || true
echo

echo "【Latest logs】"
ls -lt logs 2>/dev/null | head -10 || true
echo

echo "【Recent errors】"
grep -RInE 'ERROR|Traceback|PermissionError|Exception' logs/*.log 2>/dev/null | tail -40 || true
echo

echo "===== Done ====="
