# -*- coding: utf-8 -*-
"""Daily dedup marker for the schedule-mode startup-immediate analysis run.

The marker records the last successful full analysis run (date + scope +
stock-list fingerprint) so that ``python main.py --schedule`` can skip the
``SCHEDULE_RUN_IMMEDIATELY`` run when today's full analysis already happened
(e.g. the container restarted later the same day). Manual/explicit paths and
the daily scheduled invocation never consult the gate.

Design rules (see docs/CHANGELOG.md):

- Fail-open first: a missing, corrupt, unreadable or unknown-schema marker
  always lets the run through ("never miss a run" outranks "never re-run").
- Both the gate and the writer compute the fingerprint from
  ``config.stock_list`` (the persisted watchlist, no network dependency);
  the trading-day/position-filtered ``stock_codes`` are recorded for
  observability only and never participate in the decision.
- Market-review completeness is recorded for observability but does NOT
  gate the dedup decision: otherwise a persistently failing review would
  resurrect the very restart-loop bug this gate fixes. The daily scheduled
  run covers review backfill.
- scope=subset runs never overwrite today's existing full marker.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, List, Optional

logger = logging.getLogger(__name__)

MARKER_FILE_NAME = "analysis_run_state.json"
MARKER_SCHEMA_VERSION = 1
_SCOPE_FULL = "full"
_SCOPE_SUBSET = "subset"


@dataclass
class StartupRunDecision:
    """Result of the startup dedup gate (fail-open always yields skip=False)."""

    skip: bool
    reason: str


def analysis_run_marker_path(config: Any) -> Path:
    """Marker location next to the SQLite database (data/ in deployments)."""
    database_path = getattr(config, "database_path", "./data/stock_analysis.db")
    return Path(database_path).parent / MARKER_FILE_NAME


def compute_stock_list_fingerprint(codes: Optional[Iterable[Any]]) -> str:
    """Stable fingerprint of the watchlist: sorted unique codes, sha256[0:16].

    An empty/absent list hashes the empty string so pure-portfolio
    deployments still produce a consistent fingerprint on both sides.
    """
    normalized = sorted(
        {
            str(code).strip()
            for code in (codes or [])
            if str(code or "").strip()
        }
    )
    payload = ",".join(normalized)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _read_marker_payload(marker_path: Path) -> tuple[Optional[dict], str]:
    """Single marker read+parse point: returns ``(payload, reason)``.

    ``payload`` is ``None`` and ``reason`` is a machine-readable detail string
    for every failure branch: "missing" / "unreadable" / "corrupt" /
    "not-object". The user-facing Chinese warnings stay here so both callers
    log identically.
    """
    try:
        raw = marker_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        logger.warning("读取分析运行标记失败（视为无标记）: %s", exc)
        return None, f"unreadable ({exc})"
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("分析运行标记损坏（视为无标记）: %s", exc)
        return None, f"corrupt ({exc})"
    if not isinstance(payload, dict):
        logger.warning("分析运行标记内容不是 JSON 对象（视为无标记）")
        return None, "not-object"
    return payload, "ok"


def _load_marker(marker_path: Path) -> Optional[dict]:
    """Best-effort marker read: returns None when missing/corrupt/unreadable."""
    return _read_marker_payload(marker_path)[0]


def should_skip_startup_immediate_run(config: Any) -> StartupRunDecision:
    """Decide whether the startup-immediate schedule run may be skipped.

    Dedup key: today's local date + scope == "full" + stock-list fingerprint
    computed from ``config.stock_list``. Any error is fail-open (execute).
    """
    try:
        if not getattr(config, "schedule_startup_dedup", True):
            return StartupRunDecision(
                skip=False,
                reason="startup dedup kill switch disabled",
            )

        marker_path = analysis_run_marker_path(config)
        payload, marker_detail = _read_marker_payload(marker_path)
        if payload is None:
            if marker_detail == "missing":
                return StartupRunDecision(
                    skip=False,
                    reason="no analysis run marker file (first run of the day)",
                )
            return StartupRunDecision(
                skip=False,
                reason=f"analysis run marker {marker_detail}, fail-open",
            )

        schema_version = payload.get("schema_version")
        if schema_version != MARKER_SCHEMA_VERSION:
            return StartupRunDecision(
                skip=False,
                reason=(
                    "unknown analysis run marker schema version "
                    f"{schema_version!r}, fail-open"
                ),
            )

        marker_run_date = str(payload.get("run_date") or "")
        today = date.today().isoformat()
        if marker_run_date != today:
            return StartupRunDecision(
                skip=False,
                reason=(
                    f"marker run_date {marker_run_date!r} is not today ({today})"
                ),
            )

        if payload.get("scope") != _SCOPE_FULL:
            return StartupRunDecision(
                skip=False,
                reason=(
                    f"marker scope {payload.get('scope')!r} is not "
                    f"{_SCOPE_FULL!r}"
                ),
            )

        marker_fingerprint = str(payload.get("stock_list_fingerprint") or "")
        current_fingerprint = compute_stock_list_fingerprint(
            getattr(config, "stock_list", None)
        )
        if marker_fingerprint != current_fingerprint:
            return StartupRunDecision(
                skip=False,
                reason=(
                    "stock list changed: marker fingerprint "
                    f"{marker_fingerprint} != current {current_fingerprint}"
                ),
            )

        return StartupRunDecision(
            skip=True,
            reason=(
                "today's full analysis already recorded "
                f"(run_date={marker_run_date}, "
                f"fingerprint={marker_fingerprint})"
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive fail-open
        return StartupRunDecision(
            skip=False,
            reason=f"startup dedup gate error, fail-open: {exc}",
        )


def record_analysis_run_marker(
    config: Any,
    *,
    scope: str,
    stock_codes: Optional[Iterable[Any]],
    market_review_requested: bool,
    market_review_completed: Optional[bool],
    dry_run: bool = False,
    args: Any = None,
) -> None:
    """Persist a run marker on a successful analysis.

    Writes atomically (tmp file + ``os.replace``). A subset run never
    overwrites today's existing full marker. Any error is logged and
    swallowed: marker bookkeeping must never break an analysis run.
    """
    try:
        if args is not None and getattr(args, "dry_run", False):
            dry_run = True

        marker_path = analysis_run_marker_path(config)
        normalized_scope = (
            _SCOPE_FULL if scope == _SCOPE_FULL else _SCOPE_SUBSET
        )

        if normalized_scope == _SCOPE_SUBSET and not dry_run:
            existing = _load_marker(marker_path)
            if (
                existing is not None
                and existing.get("scope") == _SCOPE_FULL
                and existing.get("run_date") == date.today().isoformat()
            ):
                logger.info(
                    "当日已有全量分析记录，subset 运行不覆盖当日 full 标记: %s",
                    marker_path,
                )
                return

        payload = {
            "schema_version": MARKER_SCHEMA_VERSION,
            "run_date": date.today().isoformat(),
            "scope": normalized_scope,
            "stock_list_fingerprint": compute_stock_list_fingerprint(
                getattr(config, "stock_list", None)
            ),
            "stock_codes": [str(code) for code in (stock_codes or [])],
            "market_review": {
                "requested": bool(market_review_requested),
                "completed": market_review_completed,
            },
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(),
        }

        if dry_run:
            logger.info("dry-run 模式不写入分析运行标记: %s", marker_path)
            return

        marker_path.parent.mkdir(parents=True, exist_ok=True)
        # pid-suffixed tmp name: two analyzer processes writing concurrently
        # must never interleave into the same tmp file (os.replace stays atomic).
        tmp_path = marker_path.with_name(
            f"{marker_path.name}.{os.getpid()}.tmp"
        )
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, marker_path)
        logger.info(
            "已记录分析运行标记（%s）: %s", normalized_scope, marker_path
        )
    except Exception as exc:
        logger.warning("写入分析运行标记失败（忽略，不影响分析结果）: %s", exc)
