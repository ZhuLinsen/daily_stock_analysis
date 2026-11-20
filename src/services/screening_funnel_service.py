# -*- coding: utf-8 -*-
"""Screening-to-Watchlist & Batch Analysis Funnel Service."""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional

from data_provider.base import normalize_stock_code
from src.services.stock_list_parser import parse_analysis_target, split_stock_list
from src.services.system_config_service import ConfigConflictError, SystemConfigService
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

_WATCHLIST_UPDATE_LOCK = threading.Lock()
_US_CLASS_HYPHEN_RE = re.compile(r"^([A-Za-z]{1,5})-([A-Za-z])$")


def _canonicalize_funnel_stock_code(raw_code: str) -> str:
    """Normalize screening candidate codes to watchlist/queue compatible form.

    - Registered index identities (e.g. ``sh000001``) keep their canonical id.
    - US class-share hyphen tickers (``BRK-B``) map to dot format (``BRK.B``) so
      they match ``api/v1/endpoints/stocks.py`` validation and removal.
    """
    raw = str(raw_code or "").strip()
    if not raw:
        return ""
    target = parse_analysis_target(raw)
    if target.asset_type == "index":
        return target.canonical_id
    hyphen_match = _US_CLASS_HYPHEN_RE.fullmatch(raw)
    if hyphen_match:
        return f"{hyphen_match.group(1).upper()}.{hyphen_match.group(2).upper()}"
    return normalize_stock_code(raw) or raw


def _watchlist_identity_key(code: str) -> str:
    """Distinguish registered indices (``index:sh000001``) from bare stocks."""
    raw = str(code or "").strip()
    target = parse_analysis_target(raw)
    if target.asset_type == "index":
        return f"index:{target.canonical_id.lower()}"
    return f"stock:{_canonicalize_funnel_stock_code(raw).upper()}"


def extract_screening_candidates(
    run_id: Optional[str] = None,
    *,
    top_n: int = 10,
    db_manager: Optional[DatabaseManager] = None,
) -> Dict[str, Any]:
    """Extract normalized top N candidates from a specific or latest persisted ``ScreeningRun``."""
    db = db_manager or DatabaseManager.get_instance()
    safe_n = max(1, min(int(top_n), 30))

    if run_id is not None:
        run_data = db.get_screening_run(str(run_id).strip())
        if run_data is None:
            raise LookupError(f"Screening run not found: {run_id}")
    else:
        recent = db.list_screening_runs(limit=1)
        if not recent:
            return {"run_id": None, "strategy": None, "market": None, "candidates": []}
        latest_id = str(recent[0].get("run_id") or "").strip()
        run_data = db.get_screening_run(latest_id) if latest_id else None
        if not run_data:
            return {"run_id": None, "strategy": None, "market": None, "candidates": []}

    result_block = run_data.get("result") if isinstance(run_data.get("result"), dict) else {}
    raw_rows = (
        result_block.get("results")
        or result_block.get("candidates")
        or result_block.get("items")
        or []
    )

    candidates: List[Dict[str, Any]] = []
    seen_codes: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        raw_code = str(row.get("code") or row.get("stock_code") or "").strip()
        norm_code = _canonicalize_funnel_stock_code(raw_code)
        identity = _watchlist_identity_key(norm_code) if norm_code else ""
        if not norm_code or identity in seen_codes:
            continue
        seen_codes.add(identity)
        candidates.append({
            "code": norm_code,
            "name": str(row.get("name") or row.get("stock_name") or norm_code),
            "score": row.get("score") or row.get("rank_score") or row.get("composite_score"),
            "price": row.get("price") or row.get("close"),
            "reason": str(row.get("reason") or row.get("rationale") or "")[:180],
        })
        if len(candidates) >= safe_n:
            break

    return {
        "run_id": run_data.get("run_id"),
        "strategy": run_data.get("strategy"),
        "market": run_data.get("market"),
        "candidates": candidates,
    }


def promote_screening_to_watchlist(
    run_id: str,
    *,
    top_n: int = 10,
    config_service: Optional[SystemConfigService] = None,
    db_manager: Optional[DatabaseManager] = None,
) -> Dict[str, Any]:
    """Idempotently append top screening candidates into persisted ``STOCK_LIST``."""
    extracted = extract_screening_candidates(run_id, top_n=top_n, db_manager=db_manager)
    svc = config_service or SystemConfigService()
    max_attempts = 4

    with _WATCHLIST_UPDATE_LOCK:
        for attempt in range(max_attempts):
            manager = getattr(svc, "_manager", None)
            version_before = (
                manager.get_config_version()
                if manager is not None and hasattr(manager, "get_config_version")
                else None
            )
            config_data = svc.get_config(include_schema=False)
            config_version = str(config_data.get("config_version") or "")
            # Reject torn reads where `.env` changed between reading values and version.
            if isinstance(version_before, str) and version_before and config_version != version_before:
                if attempt < max_attempts - 1:
                    continue
                raise ConfigConflictError(current_version=config_version)

            current_raw = ""
            for item in config_data.get("items", []):
                if item.get("key") == "STOCK_LIST":
                    current_raw = str(item.get("value") or "")
                    break

            # Mirror Config.refresh_stock_list() fallback when `.env` has blank STOCK_LIST=
            # but runtime container/process environment provides effective STOCK_LIST.
            if not current_raw.strip():
                current_raw = os.getenv("STOCK_LIST", "")

            existing_codes = split_stock_list(current_raw)
            existing_keys = {_watchlist_identity_key(c) for c in existing_codes}

            added: List[str] = []
            already_present: List[str] = []
            updated_codes = list(existing_codes)

            for cand in extracted["candidates"]:
                code = _canonicalize_funnel_stock_code(str(cand["code"]).strip())
                key = _watchlist_identity_key(code)
                if key in existing_keys:
                    already_present.append(code)
                    continue
                existing_keys.add(key)
                updated_codes.append(code)
                added.append(code)

            if added:
                try:
                    svc.update(
                        config_version=config_version,
                        items=[{"key": "STOCK_LIST", "value": ",".join(updated_codes)}],
                        mask_token="******",
                        reload_now=True,
                    )
                except ConfigConflictError:
                    if attempt < max_attempts - 1:
                        continue
                    raise

            return {
                "ok": True,
                "run_id": extracted["run_id"],
                "added": added,
                "already_present": already_present,
                "total_watchlist": len(updated_codes),
            }


def analyze_screening_candidates(
    run_id: str,
    *,
    top_n: int = 5,
    report_type: str = "detailed",
    task_queue: Optional[Any] = None,
    db_manager: Optional[DatabaseManager] = None,
) -> Dict[str, Any]:
    """Queue asynchronous AI analysis tasks for top N candidates of a persisted screening run."""
    from src.services.task_queue import DuplicateTaskError, get_task_queue

    safe_n = max(1, min(int(top_n), 10))
    extracted = extract_screening_candidates(run_id, top_n=safe_n, db_manager=db_manager)
    queue = task_queue or get_task_queue()

    submitted: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for cand in extracted["candidates"]:
        code = str(cand["code"])
        name = str(cand.get("name") or code)
        try:
            task = queue.submit_task(
                stock_code=code,
                stock_name=name,
                report_type=report_type,
                selection_source="import",
            )
            submitted.append({
                "code": code,
                "task_id": getattr(task, "task_id", None),
                "trace_id": getattr(task, "trace_id", None),
            })
        except DuplicateTaskError as exc:
            duplicates.append({"code": code, "message": str(exc)})
        except Exception as exc:
            failed.append({"code": code, "error": str(exc)})

    return {
        "ok": len(failed) == 0,
        "run_id": extracted["run_id"],
        "submitted": submitted,
        "duplicates": duplicates,
        "failed": failed,
    }
