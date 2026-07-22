#!/usr/bin/env python3
"""Fail closed when an upstream merge breaks this fork's automation contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "00-daily-analysis.yml"
UPSTREAM_WORKFLOW = ROOT / ".github" / "workflows" / "upstream-sync.yml"


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")
    required_snippets = {
        "09:47 schedule": "cron: '42 1 * * 1-5'",
        "14:07 schedule": "cron: '2 6 * * 1-5'",
        "15:20 review schedule": "cron: '15 7 * * 1-5'",
        "scheduled stock mode": 'echo "RUN_MODE=stocks-only"',
        "scheduled market review mode": 'echo "RUN_MODE=market-only"',
        "dynamic candidate selector": "scripts/select_intraday_candidates.py",
        "candidate count default": "AUTO_SELECT_COUNT: ${{ vars.AUTO_SELECT_COUNT || '10' }}",
        "candidate amount default": "AUTO_SELECT_MIN_AMOUNT: ${{ vars.AUTO_SELECT_MIN_AMOUNT || '100000000' }}",
        "daily failure alert": "Telegram 失败告警",
    }
    missing = [label for label, snippet in required_snippets.items() if snippet not in text]
    required_files = [
        ROOT / "scripts" / "select_intraday_candidates.py",
        ROOT / "trigger_daily_stock_analysis.command",
        ROOT / ".github" / "dependabot.yml",
        ROOT / ".github" / "workflows" / "codeql.yml",
    ]
    missing.extend(str(path.relative_to(ROOT)) for path in required_files if not path.is_file())
    selector_text = (ROOT / "scripts" / "select_intraday_candidates.py").read_text(
        encoding="utf-8"
    )
    if "改用已配置自选股继续分析" not in selector_text:
        missing.append("configured-stock fallback")
    upstream_text = UPSTREAM_WORKFLOW.read_text(encoding="utf-8")
    upstream_required_snippets = {
        "upstream sync credential preflight": "Validate upstream sync credential",
        "upstream sync checkout outcome": "steps.checkout.outcome == 'failure'",
        "upstream sync detect outcome": "steps.detect.outcome == 'failure'",
        "upstream sync Telegram alert": "Send Telegram alert when automatic sync is blocked",
        "upstream sync maintenance issue": "Create a maintenance issue when automatic sync is blocked",
        "upstream sync recovery closure": "Close maintenance issue after recovery",
        "safe maintenance issue token": "GH_TOKEN: ${{ github.token }}",
    }
    missing.extend(
        label
        for label, snippet in upstream_required_snippets.items()
        if snippet not in upstream_text
    )
    if upstream_text.count("secrets.UPSTREAM_SYNC_TOKEN") < 2:
        missing.append("upstream sync workflow-capable token")
    if missing:
        raise SystemExit("Personal automation contract is incomplete: " + ", ".join(missing))
    print("Personal automation contract is intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
