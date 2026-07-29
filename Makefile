SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

# A-share / HK / US stock analysis — agent-discoverable entry points.
# Each target wraps an existing tool or shell script. No new tooling.
# See AGENTS.md §4 for the canonical command list this Makefile mirrors.

PIP       := python3 -m pip
PYTEST    := python3 -m pytest
FLAKE8    := python3 -m flake8
BLACK     := python3 -m black
ISORT     := python3 -m isort
BANDIT    := python3 -m bandit
PYCOMPILE := python3 -m py_compile
MAIN      := python3 main.py
SERVE     := python3 -m uvicorn server:app --reload --host 0.0.0.0 --port 8000

.PHONY: help install install-ci test test-unit lint format security syntax run serve web-install web-lint web-build ci clean

help: ## show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z_-]+:.*##/ { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## install runtime deps from requirements.txt
	$(PIP) install -r requirements.txt

install-ci: ## install runtime + test/lint deps (flake8, pytest)
	$(PIP) install -r requirements.txt
	$(PIP) install -r requirements-ci.txt

test: ## run offline test suite (pytest -m "not network")
	$(PYTEST) -m "not network"

test-unit: ## run unit-marked tests only
	$(PYTEST) -m unit

lint: ## run flake8 critical checks (E9,F63,F7,F82)
	$(FLAKE8) . --count --select=E9,F63,F7,F82 --show-source --statistics

syntax: ## py_compile the hot Python files (mirrors scripts/ci_gate.sh syntax_check)
	$(PYCOMPILE) main.py src/config.py src/auth.py src/analyzer.py src/notification.py
	$(PYCOMPILE) src/storage.py src/scheduler.py src/search_service.py
	$(PYCOMPILE) src/market_analyzer.py src/stock_analyzer.py
	$(PYCOMPILE) data_provider/*.py

format: ## black + isort in check mode (no writes)
	$(BLACK) --check --diff .
	$(ISORT) --check-only --diff .

security: ## bandit scan over repo (excludes tests; see setup.cfg [tool:bandit])
	$(BANDIT) -r . -c pyproject.toml

run: ## run the main analysis entry (python3 main.py)
	$(MAIN)

serve: ## run FastAPI dev server (uvicorn server:app --reload)
	$(SERVE)

web-install: ## install web frontend deps
	cd apps/dsa-web && npm ci

web-lint: ## web frontend lint
	cd apps/dsa-web && npm run lint

web-build: ## web frontend build
	cd apps/dsa-web && npm run build

ci: ## run scripts/ci_gate.sh (canonical CI gate)
	./scripts/ci_gate.sh

clean: ## remove __pycache__ and pytest cache
	find . -type d -name __pycache__ -not -path './node_modules/*' -not -path './.venv/*' -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
