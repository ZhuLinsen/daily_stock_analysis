from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github/workflows/00-daily-analysis.yml"
)


def test_daily_analysis_keeps_existing_evening_schedule() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "cron: '0 10 * * 1-5'" in workflow_text


def test_daily_analysis_adds_us_after_hours_close_schedule() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "cron: '30 1 * * 2-6'" in workflow_text
    assert '${{ github.event.schedule }}' in workflow_text


def test_us_after_hours_run_uses_dedicated_price_script() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'python scripts/send_us_postmarket_prices.py' in workflow_text
    assert 'if [ "$IS_US_POSTMARKET_RUN" = "true" ]; then' in workflow_text


def test_us_after_hours_run_sends_email_only() -> None:
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'export NOTIFICATION_REPORT_CHANNELS="email"' in workflow_text
