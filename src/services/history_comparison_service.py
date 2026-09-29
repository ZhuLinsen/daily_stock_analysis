# -*- coding: utf-8 -*-
"""
===================================
Report Engine - History Comparison Service
===================================

Fetches recent analysis signal changes per stock for report rendering.
Excludes current record via exclude_query_id.
"""

import logging
from typing import Any, Dict, List, Optional

from src.storage import DatabaseManager
from src.report_language import normalize_report_language
from src.schemas.decision_action import display_action_fields
from src.schemas.decision_scale import extract_decision_guardrail_reason
from src.utils.data_processing import parse_json_field

logger = logging.getLogger(__name__)


def _record_to_signal(
    record: Any,
    *,
    report_language: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Convert AnalysisHistory record to signal dict. Skip on parse error."""
    raw_result = parse_json_field(getattr(record, "raw_result", None))
    if not isinstance(raw_result, dict):
        raw_result = {}

    operation_advice = raw_result.get("operation_advice") or getattr(record, "operation_advice", None)
    explicit_action = raw_result.get("action")
    action_label = raw_result.get("action_label")
    resolved_report_language = normalize_report_language(
        report_language
        or raw_result.get("report_language")
        or getattr(record, "report_language", None)
    )
    action_fields = display_action_fields(
        operation_advice=operation_advice,
        explicit_action=explicit_action,
        action_label=action_label,
        report_type=getattr(record, "report_type", None),
        report_language=resolved_report_language,
        sentiment_score=getattr(record, "sentiment_score", None),
        guardrail_reason=extract_decision_guardrail_reason(raw_result),
    )

    try:
        return {
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "query_id": record.query_id,
            "sentiment_score": record.sentiment_score,
            "operation_advice": record.operation_advice,
            "action": action_fields["action"],
            "action_label": action_fields["action_label"],
            "trend_prediction": record.trend_prediction,
        }
    except Exception as e:
        logger.debug("Skip record for history comparison: %s", e)
        return None


def get_signal_changes(
    code: str,
    limit: int = 5,
    exclude_query_id: Optional[str] = None,
    *,
    report_language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get recent signal changes for a single stock.

    Args:
        code: Stock code
        limit: Max records to return
        exclude_query_id: Exclude record with this query_id (e.g. current run)

    Returns:
        List of signal dicts (created_at, sentiment_score, operation_advice, trend_prediction)
    """
    db = DatabaseManager.get_instance()
    records = db.get_analysis_history(
        code=code,
        days=90,
        limit=limit,
        exclude_query_id=exclude_query_id,
    )
    out = []
    for r in records:
        sig = _record_to_signal(r, report_language=report_language)
        if sig:
            out.append(sig)
    return out


def get_signal_changes_batch(
    codes: List[str],
    limit: int = 5,
    exclude_query_ids: Optional[Dict[str, str]] = None,
    *,
    report_language: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get recent signal changes for multiple stocks.

    Args:
        codes: Stock codes
        limit: Max records per stock
        exclude_query_ids: Map code -> query_id to exclude per stock

    Returns:
        Dict mapping code -> list of signal dicts
    """
    exclude_query_ids = exclude_query_ids or {}
    db = DatabaseManager.get_instance()
    result: Dict[str, List[Dict[str, Any]]] = {c: [] for c in codes}
    for code in codes:
        exclude = exclude_query_ids.get(code)
        records = db.get_analysis_history(
            code=code,
            days=90,
            limit=limit,
            exclude_query_id=exclude,
        )
        for r in records:
            sig = _record_to_signal(r, report_language=report_language)
            if sig:
                result[code].append(sig)
    return result
