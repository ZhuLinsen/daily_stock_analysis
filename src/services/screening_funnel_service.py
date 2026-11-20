# -*- coding: utf-8 -*-
"""Screening-to-Watchlist & Batch Analysis Funnel Service."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from data_provider.base import normalize_stock_code
from src.services.stock_list_parser import split_stock_list
from src.services.system_config_service import SystemConfigService
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)


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
        norm_code = normalize_stock_code(raw_code) or raw_code
        if not norm_code or norm_code in seen_codes:
            continue
        seen_codes.add(norm_code)
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
    config_data = svc.get_config(include_schema=False)
    config_version = str(config_data.get("config_version") or "")
    current_raw = ""
    for item in config_data.get("items", []):
        if item.get("key") == "STOCK_LIST":
            current_raw = str(item.get("value") or "")
            break

    existing_codes = split_stock_list(current_raw)
    existing_keys = {(normalize_stock_code(c) or c).upper() for c in existing_codes}

    added: List[str] = []
    already_present: List[str] = []
    updated_codes = list(existing_codes)

    for cand in extracted["candidates"]:
        code = str(cand["code"]).strip()
        key = (normalize_stock_code(code) or code).upper()
        if key in existing_keys:
            already_present.append(code)
            continue
        existing_keys.add(key)
        updated_codes.append(code)
        added.append(code)

    if added:
        svc.update(
            config_version=config_version,
            items=[{"key": "STOCK_LIST", "value": ",".join(updated_codes)}],
            mask_token="******",
            reload_now=True,
        )

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
                selection_source="screening_funnel",
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
        "ok": True,
        "run_id": extracted["run_id"],
        "submitted": submitted,
        "duplicates": duplicates,
        "failed": failed,
    }
