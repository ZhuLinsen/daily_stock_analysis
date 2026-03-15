#!/usr/bin/env bash

set -euo pipefail

echo "==> backend-gate: Python syntax check"
python -m py_compile main.py src/config.py src/auth.py src/analyzer.py src/notification.py
python -m py_compile src/storage.py src/scheduler.py src/search_service.py
python -m py_compile src/market_analyzer.py src/stock_analyzer.py
python -m py_compile data_provider/*.py

echo "==> backend-gate: flake8 critical checks"
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

echo "==> backend-gate: local deterministic checks"
./test.sh code
./test.sh yfinance

echo "==> backend-gate: offline test suite"
python -m pytest -m "not network"

echo "==> backend-gate: all checks passed"
