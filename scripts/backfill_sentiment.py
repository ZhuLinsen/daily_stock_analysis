"""Manually backfill A-share sentiment snapshots by trading date."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_config  # noqa: E402
from src.services.sentiment_backfill_service import (  # noqa: E402
    BackfillCalendarError, iter_backfill, iter_eastmoney_backfill,
)
from src.storage import DatabaseManager  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--source", choices=("csmar", "eastmoney"), default="eastmoney")
    parser.add_argument("--dry-run", action="store_true", help="compute without opening or writing the database")
    args = parser.parse_args(argv)

    config = get_config()
    source = None
    if args.source == "csmar":
        if not config.csmar_zip_path:
            parser.error("CSMAR_ZIP_PATH is not configured")
        source = Path(config.csmar_zip_path)
        if not source.is_file():
            parser.error("configured CSMAR_ZIP_PATH file does not exist")
    # Defer database initialization until the first valid snapshot is ready.
    session_factory = None if args.dry_run else lambda: DatabaseManager.get_instance().get_session()
    counts: Counter[str] = Counter()
    writes: Counter[str] = Counter()
    started = time.perf_counter()
    try:
        options = dict(start_date=args.start_date, end_date=args.end_date,
                       dry_run=args.dry_run, session_factory=session_factory)
        results = iter_eastmoney_backfill(**options) if args.source == "eastmoney" else iter_backfill(source, **options)
        for result in results:
            counts[result.status] += 1
            if result.save_action:
                writes[result.save_action] += 1
            print(json.dumps({
                "trade_date": result.trade_date.isoformat(),
                "status": result.status,
                "quality_status": result.quality_status,
                "save_action": result.save_action,
                "message": result.message,
            }, ensure_ascii=False), flush=True)
    except (BackfillCalendarError, ValueError) as exc:
        print(f"backfill aborted: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "summary": {key: counts[key] for key in
                    ("inserted", "unchanged", "partial", "dry-run", "conflict", "failed")},
        "writes": {key: writes[key] for key in ("inserted", "unchanged")},
        "seconds": round(time.perf_counter() - started, 2),
    }, ensure_ascii=False), flush=True)
    return 1 if counts["conflict"] or counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
