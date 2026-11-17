# -*- coding: utf-8 -*-
"""Hot-top10 idempotency layer: per-day dedup marker with delivery-grade
write semantics. ``state_<YYYY-MM-DD>.json`` under ``<DATABASE_PATH dir>/
hot_top10/`` is written atomically ONLY after the report landed
(OR-COR-8c2d195e). Persistent write failure returns ``False`` so the caller
never counts the run as delivered and blocks same-day re-delivery (r1
closure blocker OR-COR-hot-top10-marker-write-failure)."""

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Tuple

logger = logging.getLogger(__name__)

STATE_DIR_NAME = "hot_top10"
MARKER_PREFIX = "state_"
MARKER_SCHEMA_VERSION = 3
MARKER_WRITE_ATTEMPTS = 3


def hot_top10_state_dir(config: Any) -> Path:
    return Path(getattr(config, "database_path", "./data/stock_analysis.db")).parent / STATE_DIR_NAME


def hot_top10_marker_path(config: Any, data_date: Any = None) -> Path:
    day = data_date or date.today().isoformat()
    return hot_top10_state_dir(config) / f"{MARKER_PREFIX}{day}.json"


def hot_top10_already_delivered_today(config: Any) -> Tuple[bool, str]:
    """``(skip, reason)`` for today's dedup gate; any problem fails open."""
    try:
        try:
            raw = hot_top10_marker_path(config).read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, "no hot-top10 marker file (first run of the day)"
        except OSError as exc:
            return False, f"hot-top10 marker unreadable, fail-open ({exc})"
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            return False, f"hot-top10 marker corrupt, fail-open ({exc})"
        valid_today = (
            isinstance(payload, dict)
            and payload.get("schema_version") == MARKER_SCHEMA_VERSION
            and payload.get("delivered") is True
            and str(payload.get("data_date") or "") == date.today().isoformat()
        )
        if not valid_today:
            return False, "hot-top10 marker unusable, fail-open"
        return True, "today's hot-top10 report already delivered"
    except Exception as exc:  # pragma: no cover - defensive fail-open
        return False, f"hot-top10 dedup gate error, fail-open: {exc}"


def record_hot_top10_marker(config: Any, *, llm_completed: bool, notification_status: str) -> bool:
    """Atomically record today's delivered marker; ``True`` on success.
    Persistent failure logs an ERROR (never silent) and returns ``False``."""
    payload = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "run_date": date.today().isoformat(),
        "data_date": date.today().isoformat(),
        "delivered": True,
        "llm_completed": bool(llm_completed),
        "notification_status": str(notification_status or "unknown"),
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
    }
    marker_path = hot_top10_marker_path(config)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    for attempt in range(1, MARKER_WRITE_ATTEMPTS + 1):
        tmp_path = marker_path.with_name(f"{marker_path.name}.{os.getpid()}.{attempt}.tmp")
        try:
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(body, encoding="utf-8")
            os.replace(tmp_path, marker_path)
            logger.info("[HotTop10] 已记录投递标记: %s", marker_path)
            return True
        except OSError as exc:
            logger.error("[HotTop10] 投递标记写入失败（第 %d/%d 次）: %s", attempt, MARKER_WRITE_ATTEMPTS, exc)
    logger.error("[HotTop10] 投递标记持续写入失败，本次不视为已交付：同日阻断重复推送")
    return False
