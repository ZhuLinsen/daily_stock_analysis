# Contributing Guide

Thank you for your interest in contributing! All kinds of contributions are welcome.

## 🐛 Reporting Bugs

1. Search [Issues](https://github.com/ZhuLinsen/daily_stock_analysis/issues) first to check if it has already been reported.
2. Create a new Issue using the **Bug Report** template.
3. Provide detailed reproduction steps and environment information.

## 💡 Suggesting Features

1. Search Issues to make sure the suggestion hasn't already been raised.
2. Create a new Issue using the **Feature Request** template.
3. Describe your use case and expected behavior in detail.

## 🔧 Submitting Code

### Setting Up the Development Environment

```bash
# Clone the repository
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and fill in the required API keys
```

### Contribution Workflow

1. Fork this repository.
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'feat: add some feature'`
4. Push the branch: `git push origin feature/your-feature`
5. Open a Pull Request against `main`.

### Commit Message Convention

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     New feature
fix:      Bug fix
docs:     Documentation update
style:    Code formatting (no logic change)
refactor: Code refactoring
perf:     Performance improvement
test:     Test-related changes
chore:    Build / tooling changes
```

Examples:

```
feat: add DingTalk bot support
fix: handle 429 rate-limit with retry backoff
docs: update README deployment section
```

### Code Style

- Python code follows PEP 8 (line length: 120).
- Add docstrings to functions and classes.
- Add comments for non-obvious logic.
- Update relevant documentation when adding new features.

### CI Checks

After opening a PR, CI will automatically run the following PR checks:

| Check | Description | Required |
|-------|-------------|:--------:|
| `backend-gate` | `scripts/ci_gate.sh` — py_compile + flake8 critical errors + `./scripts/test.sh code` + `./scripts/test.sh yfinance` + offline pytest | ✅ |
| `docker-build` | Docker image build and key module import smoke test | ✅ |
| `web-gate` | `npm run lint` + `npm run build` (triggered when `apps/dsa-web/` changes) | ✅ (when triggered) |

Separately, the repository also has a non-blocking `network-smoke` workflow in `.github/workflows/network-smoke.yml`, but it is only triggered by `schedule` and `workflow_dispatch`, not by pull requests.

**Running checks locally:**

```bash
# Backend gate (recommended)
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh

# Frontend gate (only if you changed apps/dsa-web/)
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

### Documentation Sync Rule

When modifying a Chinese-language core document (e.g., `docs/full-guide.md`), your PR description **must state** whether the corresponding English document has been updated. If not updated, explain why.

## 📋 Priority Areas for Contribution

- 🔔 New notification channels (e.g., Slack, Matrix)
- 🤖 New AI model integrations
- 📊 New data source adapters
- 🐛 Bug fixes and performance improvements
- 📖 Documentation improvements and translations

## ❓ Questions

Feel free to:
- Open an Issue for discussion.
- Browse existing Issues and Discussions.

Thank you for contributing! 🎉
