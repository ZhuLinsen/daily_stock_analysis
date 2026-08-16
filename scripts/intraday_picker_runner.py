#!/usr/bin/env python3
"""Headless A-share intraday picker runner.

Runs independently of the Web/Electron UI. All trigger times are interpreted
in Asia/Shanghai regardless of the host OS timezone.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.intraday_picker.config import IntradayPickerConfig
from src.services.intraday_picker.runtime import build_intraday_picker

TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger("intraday_picker_runner")


def _now() -> datetime:
    return datetime.now(TZ)


def _parse_at(value: str | None, base: datetime | None = None) -> datetime:
    current = base or _now()
    if not value:
        return current
    hour, minute = [int(part) for part in value.split(":", 1)]
    return current.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _print_top(top) -> None:
    print("\n=== Intraday Top Candidates ===")
    for idx, item in enumerate(top, 1):
        rvol = "--" if item.metrics.rvol_time is None else f"{item.metrics.rvol_time:.2f}x"
        strategies = ",".join(hit.strategy_id for hit in item.strategy_hits)
        print(
            f"{idx:>2}. {item.stock_code} {item.stock_name:<10} "
            f"score={item.picker_score:5.1f} chg={item.change_pct:+6.2f}% "
            f"rvol={rvol} [{strategies}]"
        )


def run_once(orchestrator, when: datetime, *, dry_run: bool, force: bool):
    logger.info("[IntradayPicker] run start: %s", when.isoformat())
    top = orchestrator.run_preliminary(when, force=force, dry_run=dry_run)
    _print_top(top)
    return top


def finalize_with_wait(orchestrator, run_id: str, top, *, wait_seconds: int) -> None:
    if not top:
        return
    deadline = time.monotonic() + max(0, wait_seconds)
    final = []
    while True:
        now = _now()
        final = orchestrator.finalize(run_id, top, now)
        completed = sum(1 for item in final if item.dsa and item.dsa.status == "completed")
        if completed >= min(len(top), orchestrator.config.final_top_n):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(5)
    print("\n=== Final Top ===")
    for idx, item in enumerate(final, 1):
        dsa = "--" if not item.dsa or item.dsa.dsa_score is None else f"{item.dsa.dsa_score:.0f}"
        print(f"{idx:>2}. {item.candidate.stock_code} final={item.final_score:.1f} dsa={dsa}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Headless DSA intraday stock picker")
    parser.add_argument("--once", action="store_true", help="run one scan and exit")
    parser.add_argument("--at", help="override logical trigger time, HH:MM")
    parser.add_argument("--dry-run", action="store_true", help="do not notify or submit DSA tasks")
    parser.add_argument("--force", action="store_true", help="rerun an already persisted run id")
    parser.add_argument("--dsa-wait-seconds", type=int, default=120, help="wait for DSA results at the final trigger")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    config = IntradayPickerConfig.from_env()
    orchestrator = build_intraday_picker(config)

    if args.once:
        when = _parse_at(args.at)
        top = run_once(orchestrator, when, dry_run=args.dry_run, force=args.force)
        if not args.dry_run:
            finalize_with_wait(orchestrator, orchestrator.run_id(when), top, wait_seconds=args.dsa_wait_seconds)
        return 0

    if not config.enabled:
        logger.info("[IntradayPicker] disabled: set INTRADAY_PICKER_ENABLED=true to enable scheduled mode")
        return 0

    triggered: set[str] = set()
    start = _now().replace(hour=9, minute=25, second=0, microsecond=0)
    end = _now().replace(hour=10, minute=2, second=0, microsecond=0)
    if _now() > end:
        return 0
    while _now() < start:
        time.sleep(min(30, max(1, int((start - _now()).total_seconds()))))

    final_time = config.schedule_times[-1]
    while _now() <= end:
        now = _now()
        hhmm = now.strftime("%H:%M")
        for scheduled in config.schedule_times:
            key = f"{now.date().isoformat()}-{scheduled}"
            if scheduled == hhmm and key not in triggered:
                logical_time = _parse_at(scheduled, now)
                top = run_once(orchestrator, logical_time, dry_run=False, force=False)
                triggered.add(key)
                if scheduled == final_time:
                    finalize_with_wait(
                        orchestrator,
                        orchestrator.run_id(logical_time),
                        top,
                        wait_seconds=args.dsa_wait_seconds,
                    )
        time.sleep(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
