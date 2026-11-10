# -*- coding: utf-8 -*-
"""Weekly accuracy scorecard built from the auto-backtest summaries.

Sent once per ISO week (on Fridays) when ``BACKTEST_WEEKLY_REPORT_ENABLED`` is
true (the default). A marker file in ``data/`` prevents a second send when two
scheduled runs happen on the same Friday; on GitHub Actions ``data/`` persists
through the workflow cache.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

REPORT_WEEKDAY = 4  # Friday


def _fmt_pct(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.1f}%"


def build_weekly_report(
    overall: Optional[Dict[str, Any]],
    per_stock: Dict[str, Optional[Dict[str, Any]]],
    *,
    today: date,
) -> Optional[str]:
    """Render the scorecard as Markdown; ``None`` when nothing was evaluated yet."""
    if not overall or not overall.get("completed_count"):
        return None

    lines: List[str] = [
        f"# 🎯 Weekly accuracy report - {today.isoformat()}",
        "",
        "How past AI signals performed over the following trading days "
        f"(evaluation window: {overall.get('eval_window_days', '?')} days).",
        "",
        f"- **Signals evaluated:** {overall.get('completed_count')}",
        f"- **Direction accuracy:** {_fmt_pct(overall.get('direction_accuracy_pct'))}",
        f"- **Win rate:** {_fmt_pct(overall.get('win_rate_pct'))}",
        f"- **Avg stock return:** {_fmt_pct(overall.get('avg_stock_return_pct'))}",
        f"- **Avg return following the signals:** {_fmt_pct(overall.get('avg_simulated_return_pct'))}",
        "",
        "| Stock | Evaluated | Direction accuracy | Win rate |",
        "|---|---|---|---|",
    ]
    for code, summary in per_stock.items():
        if not summary or not summary.get("completed_count"):
            continue
        lines.append(
            f"| {code} | {summary.get('completed_count')} | "
            f"{_fmt_pct(summary.get('direction_accuracy_pct'))} | {_fmt_pct(summary.get('win_rate_pct'))} |"
        )
    lines += ["", "_Past accuracy does not guarantee future results. Not investment advice._"]
    return "\n".join(lines)


def _marker_path(data_dir: Path, today: date) -> Path:
    year, week, _ = today.isocalendar()
    return data_dir / f"weekly_report_sent_{year}-W{week:02d}"


def maybe_send_weekly_report(
    service: Any,
    stock_codes: Iterable[str],
    *,
    today: Optional[date] = None,
    data_dir: Optional[Path] = None,
    notifier: Any = None,
) -> bool:
    """Send the scorecard if today is report day and it was not sent this week."""
    if os.getenv("BACKTEST_WEEKLY_REPORT_ENABLED", "true").lower() != "true":
        return False
    today = today or date.today()
    if today.weekday() != REPORT_WEEKDAY:
        return False

    data_dir = data_dir or Path(os.getenv("DATABASE_PATH", "./data/stock_analysis.db")).parent
    marker = _marker_path(data_dir, today)
    if marker.exists():
        return False

    overall = service.get_summary(scope="overall", code=None)
    per_stock = {code: service.get_summary(scope="stock", code=code) for code in stock_codes}
    content = build_weekly_report(overall, per_stock, today=today)
    if content is None:
        logger.info("weekly accuracy report: no evaluated signals yet, skipped")
        return False

    if notifier is None:
        from src.notification import NotificationService

        notifier = NotificationService()
    if not notifier.is_available():
        return False
    sent = bool(notifier.send(content, route_type="report"))
    if sent:
        data_dir.mkdir(parents=True, exist_ok=True)
        marker.touch()
        logger.info("weekly accuracy report sent")
    return sent
