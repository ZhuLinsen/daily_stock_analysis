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

Use the PR title to describe what changes when it lands. Explain who benefits, which entry points are affected and how you verified the result. Include screenshots for visible Web, desktop or report changes. GitHub generates release notes from merged PR titles and labels. Maintainers confirm the category and archive the release, so contributors can skip editing `docs/CHANGELOG.md`.

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

PRs that only change ordinary `docs/**`, non-governance Markdown, or `LICENSE` keep lightweight change detection, governance validation, and gate summarization, while skipping the three backend test shards, Docker, Web, and desktop packaging. Contract documentation, static API specifications, and Markdown fixtures read directly by offline tests still trigger backend tests. Governance assets such as `AGENTS.md`, `.github/instructions/**`, and `.agents/skills/**` are still validated by `ai-governance`; runtime-affecting text files such as configuration, dependency, and workflow files still run their corresponding full checks.

| Check | Description | Required |
|-------|-------------|:--------:|
| `backend-gate` | `scripts/ci_gate.sh` — py_compile + flake8 critical errors + `./scripts/test.sh code` + `./scripts/test.sh yfinance` + offline pytest | ✅ |
| `docker-build` | Docker image build and key module import smoke test | ✅ |
| `web-gate` | Path-based Web lint, build, tests and Playwright screenshots in the `web-ui-evidence-<head SHA>` artifact | ✅ (when triggered) |
| `pr-review` | Automatic PR triggering is temporarily paused. Maintainers can still run it by PR number through `workflow_dispatch`; it reads PR metadata and diff through the GitHub API and never checks out or executes fork PR code. | ❌ (advisory) |

Separately, the repository also has a non-blocking `network-smoke` workflow in `.github/workflows/network-smoke.yml`, but it is only triggered by `schedule` and `workflow_dispatch`, not by pull requests.

**Running checks locally:**

```bash
# Backend gate (recommended)
python -m pip install -r .github/requirements-ci.txt
./scripts/ci_gate.sh

# Frontend gate (only if you changed apps/dsa-web/)
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

### Documentation Sync Rule

When modifying a Chinese-language core document (e.g., `docs/full-guide.md`), your PR description **must state** whether the corresponding English document has been updated. If not updated, explain why.

## 📋 Product Direction & Priority Areas for Contribution

The project already has a complete end-to-end workflow and follows a **"do less, better"** principle: prioritize subtraction, simplicity, and core reliability over adding niche features, duplicate config templates, parallel entry points, or low-frequency toggles. **Before developing a substantial new feature, we recommend opening an Issue first to align on necessity and scope; regular bug fixes, UX improvements, and small focused enhancements can be submitted directly as PRs.**

Priority areas (ordered by priority; see [README](../README.md) for core entry points):

- 🐛 **Core bug fixes & reliability** (data ingestion, analysis quality, timeout/fallback isolation, notification delivery)
- ✨ **Simplification & subtraction** (streamlining config/UX, removing redundant paths, improving diagnostics)
- ⚡ **Performance & deterministic tests** (covering real risk paths)
- 📖 **Accurate, concise documentation** (aligned with executable code without duplicating guides)
- 🧩 **High-value core capabilities aligned in an Issue first** (clear, frequent user value without adding unnecessary complexity)

## ❓ Questions

Feel free to:
- Open an Issue for discussion.
- Browse existing Issues and Discussions.

Thank you for contributing! 🎉
