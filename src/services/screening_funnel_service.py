# -*- coding: utf-8 -*-
"""Screening-to-Watchlist & Batch Analysis Funnel Service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.services.stock_code_utils import is_code_like
from src.services.stock_list_parser import ParseStatus, parse_analysis_target, split_stock_list
from src.services.system_config_service import SystemConfigService
from src.services.watchlist_service import canonicalize_watchlist_code, edit_watchlist, watchlist_match_key
from src.storage import DatabaseManager


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

    result_block = run_data.get("result")
    if not isinstance(result_block, dict):
        result_block = {}
    raw_rows = next(
        (result_block[key] for key in ("candidates", "results", "items") if isinstance(result_block.get(key), list)),
        [],
    )

    candidates: List[Dict[str, Any]] = []
    seen_codes: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        raw_code = str(row.get("code") or row.get("stock_code") or "").strip()
        if split_stock_list(raw_code) != [raw_code]:
            continue
        norm_code = canonicalize_watchlist_code(raw_code)
        identity = watchlist_match_key(norm_code)
        if identity in seen_codes or (identity.startswith("stock:") and not is_code_like(norm_code)):
            continue
        seen_codes.add(identity)
        score = next((row[key] for key in ("score", "rank_score", "composite_score") if row.get(key) is not None), None)
        price = row.get("price")
        candidates.append({
            "code": norm_code,
            "name": str(row.get("name") or row.get("stock_name") or norm_code),
            "score": score,
            "price": row.get("close") if price is None else price,
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

    def append_candidates(codes: list[str]) -> tuple[list[str], list[str]]:
        existing_keys = {watchlist_match_key(code) for code in codes}
        added: list[str] = []
        already_present: list[str] = []

        for cand in extracted["candidates"]:
            code = cand["code"]
            key = watchlist_match_key(code)
            if key in existing_keys:
                already_present.append(code)
                continue
            existing_keys.add(key)
            codes.append(code)
            added.append(code)
        return added, already_present

    codes, (added, already_present) = edit_watchlist(svc, append_candidates)
    return {
        "ok": True,
        "run_id": extracted["run_id"],
        "added": added,
        "already_present": already_present,
        "total_watchlist": len(codes),
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
            target = parse_analysis_target(code)
            task = queue.submit_task(
                stock_code=code,
                stock_name=name,
                report_type=report_type,
                selection_source="import",
                analysis_target=target if target.asset_type == ParseStatus.INDEX else None,
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
