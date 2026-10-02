# -*- coding: utf-8 -*-
"""Atomic occurrence claims for schedulers sharing the analysis SQLite file."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class ScheduledAnalysisSkipped(Exception):
    """The same scheduled workload was already claimed by another runner."""


def claim_scheduled_analysis(config: Any, args: Any, scheduled_for: datetime) -> bool:
    """Claim a prepared workload at its original due instant, not the poll time.

    Naive times use the process timezone, as the schedule library does. SQLite
    errors propagate: silently running without coordination would duplicate
    reports. Callers must execute exactly this snapshot without refreshing it.
    """
    portfolio = getattr(args, "portfolio", None)
    workload = {
        "stocks": [] if portfolio else sorted({
            str(code).strip().upper() for code in getattr(config, "stock_list", [])
        }),
        "portfolio": portfolio,
        "options": {
            key: bool(getattr(args, key, False))
            for key in ("no_notify", "no_market_review", "dry_run", "force_run", "single_notify")
        },
        "market_review_enabled": bool(getattr(config, "market_review_enabled", False)),
        "market_review_region": getattr(config, "market_review_region", "cn"),
        "report_language": getattr(config, "report_language", "zh"),
        "report_type": getattr(config, "report_type", "simple"),
    }
    workload_key = hashlib.sha256(
        json.dumps(workload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    occurrence = scheduled_for.astimezone(timezone.utc).isoformat()
    database_path = Path(getattr(config, "database_path", "./data/stock_analysis.db"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(database_path), timeout=10)) as connection:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS scheduled_analysis_claims ("
                "occurrence TEXT NOT NULL, workload TEXT NOT NULL, "
                "claimed_at REAL NOT NULL, PRIMARY KEY (occurrence, workload))"
            )
            cursor = connection.execute(
                "INSERT OR IGNORE INTO scheduled_analysis_claims "
                "(occurrence, workload, claimed_at) VALUES (?, ?, ?)",
                (occurrence, workload_key, time.time()),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "DELETE FROM scheduled_analysis_claims WHERE claimed_at < ?",
                (time.time() - 7 * 24 * 60 * 60,),
            )
    return True


def run_claimed_scheduled_analysis(
    config: Any, args: Any, scheduled_for: datetime, runner: Callable[[Any], Any],
) -> Any:
    """Freeze, claim and execute the same workload at the final execution boundary.

    Keep the claim after failures: notifications may already be partially sent.
    A human can retry through the ordinary manual entrypoints. Busy/rejected API
    dispatches never reach this boundary and therefore do not consume a claim.
    """
    snapshot = copy.copy(config)
    if not getattr(args, "portfolio", None):
        refresh = getattr(snapshot, "refresh_stock_list", None)
        if callable(refresh):
            refresh()
        snapshot.stock_list = list(getattr(snapshot, "stock_list", []))
    try:
        acquired = claim_scheduled_analysis(snapshot, args, scheduled_for)
    except Exception as exc:
        raise RuntimeError(f"scheduled occurrence claim failed: {exc}") from exc
    if not acquired:
        raise ScheduledAnalysisSkipped()
    return runner(snapshot)
