# -*- coding: utf-8 -*-
"""Hot-top10 idempotency layer: per-day dedup marker with delivery-grade
write semantics. ``state_<YYYY-MM-DD>.json`` under ``<DATABASE_PATH dir>/
hot_top10/`` is written atomically ONLY after the report landed
(OR-COR-8c2d195e). Persistent write failure returns ``False`` so the caller
never counts the run as delivered and blocks same-day re-delivery (r1
closure blocker OR-COR-hot-top10-marker-write-failure).

Day keying uses the CN market clock (Asia/Shanghai) via
``hot_top10_data_date()`` — never the host clock — so a host in another
timezone cannot book the previous trading day's list under its own local
date (OR-COR-3e7f490e).

When the primary marker location is unwritable (e.g. the data volume is
full), the marker falls back to the system temp directory, keyed per
deployment, and the dedup gate reads both — a same-day sequential process
restart therefore still sees the delivery instead of re-pushing
(OR-COR-hot-top10-marker-write-failure). If no location is writable the
delivery is genuinely unrecordable; the caller blocks in-process and logs
at ERROR."""

import hashlib
import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from src.services.hot_top10.datasource import hot_top10_data_date

logger = logging.getLogger(__name__)

STATE_DIR_NAME = "hot_top10"
MARKER_PREFIX = "state_"
FALLBACK_MARKER_PREFIX = "hot_top10_state_"
MARKER_SCHEMA_VERSION = 3
MARKER_WRITE_ATTEMPTS = 3
FALLBACK_MARKER_ATTEMPTS = 2


def hot_top10_state_dir(config: Any) -> Path:
    return Path(getattr(config, "database_path", "./data/stock_analysis.db")).parent / STATE_DIR_NAME


def hot_top10_marker_path(config: Any, data_date: Any = None) -> Path:
    day = data_date or hot_top10_data_date()
    return hot_top10_state_dir(config) / f"{MARKER_PREFIX}{day}.json"


def _deployment_key(config: Any) -> str:
    """Stable short key so deployments sharing one temp dir do not dedup
    against each other's markers."""
    try:
        raw = str(getattr(config, "database_path", "./data/stock_analysis.db"))
    except Exception:  # pragma: no cover - defensive
        raw = "unknown"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def fallback_marker_path(config: Any, data_date: Any = None) -> Path:
    """Temp-dir marker used only when the primary location is unwritable."""
    day = data_date or hot_top10_data_date()
    return (
        Path(tempfile.gettempdir())
        / f"{FALLBACK_MARKER_PREFIX}{day}_{_deployment_key(config)}.json"
    )


def _read_valid_marker(path: Path) -> Optional[str]:
    """Reason string when ``path`` holds today's valid delivered marker."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    valid_today = (
        isinstance(payload, dict)
        and payload.get("schema_version") == MARKER_SCHEMA_VERSION
        and payload.get("delivered") is True
        and str(payload.get("data_date") or "") == hot_top10_data_date()
    )
    if not valid_today:
        return None
    return f"today's hot-top10 report already delivered ({path})"


def hot_top10_already_delivered_today(config: Any) -> Tuple[bool, str]:
    """``(skip, reason)`` for today's dedup gate; any problem fails open.

    Checks the primary marker, then the temp-dir fallback written when the
    primary volume was unwritable — so a same-day restart after recovery
    still counts the earlier delivery (OR-COR-hot-top10-marker-write-failure).
    """
    try:
        fallback_reason = _read_valid_marker(fallback_marker_path(config))
        primary_path = hot_top10_marker_path(config)
        primary_reason = _read_valid_marker(primary_path)
        if primary_reason is not None:
            return True, primary_reason
        if fallback_reason is not None:
            return True, fallback_reason
        if not primary_path.exists():
            return False, "no hot-top10 marker file (first run of the day)"
        # A primary marker exists but is unusable: fail-open.
        return False, "hot-top10 marker unusable, fail-open"
    except Exception as exc:  # pragma: no cover - defensive fail-open
        return False, f"hot-top10 dedup gate error, fail-open: {exc}"


def record_hot_top10_marker(config: Any, *, llm_completed: bool, notification_status: str) -> bool:
    """Atomically record today's delivered marker; ``True`` on success.

    Tries the primary location, then the temp-dir fallback; only when BOTH
    are unwritable does it log an ERROR (never silent) and return ``False``.
    """
    payload = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "run_date": date.today().isoformat(),
        "data_date": hot_top10_data_date(),
        "delivered": True,
        "llm_completed": bool(llm_completed),
        "notification_status": str(notification_status or "unknown"),
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    for is_primary, marker_path, attempts in (
        (True, hot_top10_marker_path(config), MARKER_WRITE_ATTEMPTS),
        (False, fallback_marker_path(config), FALLBACK_MARKER_ATTEMPTS),
    ):
        for attempt in range(1, attempts + 1):
            tmp_path = marker_path.with_name(f"{marker_path.name}.{os.getpid()}.{attempt}.tmp")
            try:
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path.write_text(body, encoding="utf-8")
                os.replace(tmp_path, marker_path)
                if is_primary:
                    logger.info("[HotTop10] 已记录投递标记: %s", marker_path)
                else:
                    logger.warning(
                        "[HotTop10] 主位置不可写，投递标记已记录到回退位置: %s", marker_path
                    )
                return True
            except OSError as exc:
                logger.error(
                    "[HotTop10] 投递标记写入失败（%s 第 %d/%d 次）: %s",
                    marker_path, attempt, attempts, exc,
                )
    logger.error("[HotTop10] 投递标记持续写入失败，本次不视为已交付：同日阻断重复推送")
    return False
