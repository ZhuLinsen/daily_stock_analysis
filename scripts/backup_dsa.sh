#!/usr/bin/env bash
set -euo pipefail

cd /opt/daily_stock_analysis
mkdir -p backups

ts=$(date +%Y%m%d_%H%M%S)
tar --exclude='.venv' \
    --exclude='node_modules' \
    --exclude='apps/dsa-web/node_modules' \
    --exclude='backups' \
    --exclude='archive' \
    -czf "backups/dsa_backup_${ts}.tar.gz" \
    .env main.py data reports scripts

find backups -name 'dsa_backup_*.tar.gz' -type f -mtime +14 -delete

echo "Backup complete: backups/dsa_backup_${ts}.tar.gz"
