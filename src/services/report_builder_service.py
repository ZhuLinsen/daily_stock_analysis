# -*- coding: utf-8 -*-
"""Shared analysis-report payload builder for REST API and read-only MCP."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from src.analysis_context_pack_overview import (
    extract_analysis_context_pack_overview,
    sanitize_context_snapshot_for_api,
)
from src.config import Config
from src.data.stock_index_loader import resolve_index_stock_code
from src.market_phase_summary import rebuild_market_phase_summary_for_stock_code
from src.report_language import get_localized_stock_name, normalize_report_language
from src.schemas.decision_action import build_action_fields
from src.services.analysis_service import asset_type_from_canonical_code
from src.services.empty_news import empty_news_disclosure_from_stored
from src.utils.data_processing import (
    extract_board_detail_fields,
    extract_fundamental_detail_fields,
    extract_market_structure_detail_field,
    extract_realtime_detail_fields,
    normalize_model_used,
    parse_json_field,
)

logger = logging.getLogger(__name__)


def display_stock_code_from_index(stock_code: Any) -> str:
    code = str(stock_code or "").strip()
    if not code:
        return code
    return resolve_index_stock_code(code) or code


def display_market_phase_summary(stock_code: Any, context_snapshot: Any) -> Any:
    return rebuild_market_phase_summary_for_stock_code(
        display_stock_code_from_index(stock_code),
        context_snapshot,
    )


def first_non_empty_report_value(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def extract_guardrail_reason(raw_result: Any) -> Optional[str]:
    if not isinstance(raw_result, dict):
        return None
    for reason in (
        raw_result.get("guardrail_reason"),
        raw_result.get("downgrade_reason"),
        raw_result.get("decision_score_guardrail_reason"),
    ):
        if reason is not None:
            text = str(reason).strip()
            if text:
                return text
    metadata = raw_result.get("metadata")
    if isinstance(metadata, dict):
        metadata_reason = metadata.get("guardrail_reason") or metadata.get("downgrade_reason")
        if metadata_reason is not None:
            text = str(metadata_reason).strip()
            if text:
                return text
    return None


def stringify_report_strategy_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _looks_like_raw_result_payload(candidate: Any) -> bool:
    return isinstance(candidate, dict) and (
        "analysis_summary" in candidate
        or "operation_advice" in candidate
        or "trend_prediction" in candidate
        or "sentiment_score" in candidate
        or "market_structure_context" in candidate
        or "model_used" in candidate
        or "dashboard" in candidate
        or "action" in candidate
    )


def load_sync_fundamental_sources(
    query_id: str,
    stock_code: str,
) -> Tuple[Optional[Any], Optional[Dict[str, Any]], Optional[Any]]:
    """Load persisted context_snapshot / fundamental / raw_result payloads (fail-open)."""
    try:
        from src.storage import DatabaseManager

        db = DatabaseManager.get_instance()
        records = db.get_analysis_history(query_id=query_id, code=stock_code, limit=1)
        context_snapshot = None
        raw_result_snapshot = None
        if records:
            latest_record = records[0]
            context_snapshot = parse_json_field(getattr(latest_record, "context_snapshot", None))
            raw_result_snapshot = parse_json_field(getattr(latest_record, "raw_result", None))

        fallback_fundamental = db.get_latest_fundamental_snapshot(
            query_id=query_id,
            code=stock_code,
        )
        return context_snapshot, fallback_fundamental, raw_result_snapshot
    except Exception as exc:
        logger.debug(
            "load sync fundamental sources failed (fail-open): query_id=%s stock_code=%s err=%s",
            query_id,
            stock_code,
            exc,
        )
        return None, None, None


def build_analysis_report_payload(
    report_data: Dict[str, Any],
    query_id: str,
    stock_code: str,
    stock_name: Optional[str] = None,
    context_snapshot: Optional[Any] = None,
    fallback_fundamental_payload: Optional[Dict[str, Any]] = None,
    fallback_raw_result_payload: Optional[Any] = None,
    record_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a canonical dict matching ``api.v1.schemas.history.AnalysisReport``."""
    meta_data = report_data.get("meta") if isinstance(report_data.get("meta"), dict) else {}
    summary_data = report_data.get("summary") if isinstance(report_data.get("summary"), dict) else {}
    strategy_data = report_data.get("strategy") if isinstance(report_data.get("strategy"), dict) else {}
    details_data = report_data.get("details") if isinstance(report_data.get("details"), dict) else {}

    ctx_dict = context_snapshot if isinstance(context_snapshot, dict) else {}
    raw_result_for_metadata = details_data.get("raw_result")
    if not isinstance(raw_result_for_metadata, dict) and isinstance(fallback_raw_result_payload, dict):
        if isinstance(fallback_raw_result_payload.get("raw_result"), dict):
            raw_result_for_metadata = fallback_raw_result_payload["raw_result"]
        elif _looks_like_raw_result_payload(fallback_raw_result_payload):
            raw_result_for_metadata = fallback_raw_result_payload
    report_language = normalize_report_language(
        meta_data.get("report_language")
        or ctx_dict.get("report_language")
        or (
            raw_result_for_metadata.get("report_language")
            if isinstance(raw_result_for_metadata, dict)
            else None
        )
        or getattr(Config.get_instance(), "report_language", "zh")
    )
    raw_stock_code = meta_data.get("stock_code", stock_code)
    display_stock_code = display_stock_code_from_index(raw_stock_code)
    localized_stock_name = get_localized_stock_name(
        meta_data.get("stock_name", stock_name),
        display_stock_code,
        report_language,
    )
    realtime_fields = extract_realtime_detail_fields(context_snapshot)
    current_price = meta_data.get("current_price")
    if current_price is None:
        current_price = realtime_fields.get("current_price")
    change_pct = meta_data.get("change_pct")
    if change_pct is None:
        change_pct = realtime_fields.get("change_pct")

    market_phase_summary = display_market_phase_summary(raw_stock_code, context_snapshot)
    if market_phase_summary is None:
        meta_phase_summary = meta_data.get("market_phase_summary")
        if meta_phase_summary is not None:
            market_phase_summary = display_market_phase_summary(
                raw_stock_code,
                {"market_phase_summary": meta_phase_summary},
            )

    resolved_id = meta_data.get("id", record_id)
    meta: Dict[str, Any] = {
        "id": resolved_id,
        "query_id": meta_data.get("query_id", query_id),
        "stock_code": display_stock_code,
        "stock_name": localized_stock_name,
        "report_type": meta_data.get("report_type", "detailed"),
        "report_language": report_language,
        "created_at": meta_data.get("created_at") or datetime.now().isoformat(),
        "current_price": current_price,
        "change_pct": change_pct,
        "model_used": normalize_model_used(meta_data.get("model_used")),
        "market_phase_summary": market_phase_summary,
        "asset_type": asset_type_from_canonical_code(raw_stock_code),
    }

    raw_result_data = details_data.get("raw_result")
    if not isinstance(raw_result_data, dict):
        raw_result_data = {}
        if isinstance(fallback_raw_result_payload, dict):
            if isinstance(fallback_raw_result_payload.get("raw_result"), dict):
                raw_result_data = fallback_raw_result_payload["raw_result"]
            elif _looks_like_raw_result_payload(fallback_raw_result_payload):
                raw_result_data = fallback_raw_result_payload
        if not raw_result_data and isinstance(details_data, dict):
            raw_result_data = details_data

    action_fields = build_action_fields(
        operation_advice=(
            raw_result_data.get("operation_advice")
            or details_data.get("operation_advice")
            or summary_data.get("operation_advice")
        ),
        explicit_action=(
            raw_result_data.get("action")
            or details_data.get("action")
            or summary_data.get("action")
        ),
        report_type=meta["report_type"],
        report_language=report_language,
        sentiment_score=first_non_empty_report_value(
            summary_data.get("sentiment_score"),
            raw_result_data.get("sentiment_score"),
            details_data.get("sentiment_score"),
        ),
        guardrail_reason=extract_guardrail_reason(raw_result_data),
        align_with_score=True,
    )

    summary: Dict[str, Any] = {
        "analysis_summary": summary_data.get("analysis_summary"),
        "operation_advice": summary_data.get("operation_advice"),
        "action": action_fields["action"],
        "action_label": action_fields["action_label"],
        "trend_prediction": summary_data.get("trend_prediction"),
        "sentiment_score": summary_data.get("sentiment_score"),
        "sentiment_label": summary_data.get("sentiment_label"),
    }

    strategy: Optional[Dict[str, Any]] = None
    if strategy_data:
        strategy = {
            "ideal_buy": stringify_report_strategy_value(strategy_data.get("ideal_buy")),
            "secondary_buy": stringify_report_strategy_value(strategy_data.get("secondary_buy")),
            "stop_loss": stringify_report_strategy_value(strategy_data.get("stop_loss")),
            "take_profit": stringify_report_strategy_value(strategy_data.get("take_profit")),
        }

    extracted_fundamental = extract_fundamental_detail_fields(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    extracted_boards = extract_board_detail_fields(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    market_structure = None
    for raw_candidate in (fallback_raw_result_payload, raw_result_data, details_data):
        if raw_candidate is None:
            continue
        market_structure = extract_market_structure_detail_field(
            context_snapshot,
            raw_candidate,
        )
        if market_structure is not None:
            break

    analysis_context_pack_overview = extract_analysis_context_pack_overview(context_snapshot)
    api_context_snapshot = sanitize_context_snapshot_for_api(context_snapshot)
    news_disclosure = empty_news_disclosure_from_stored(
        raw_result_data,
        context_snapshot,
        report_language,
    )
    if news_disclosure is None and isinstance(details_data, dict):
        news_disclosure = details_data.get("empty_news_disclosure")

    details: Optional[Dict[str, Any]] = None
    has_board_details = (
        bool(extracted_boards.get("belong_boards"))
        or extracted_boards.get("sector_rankings") is not None
        or extracted_boards.get("concept_rankings") is not None
    )
    if (
        details_data
        or any(extracted_fundamental.values())
        or has_board_details
        or market_structure is not None
        or context_snapshot is not None
        or analysis_context_pack_overview is not None
        or news_disclosure is not None
    ):
        concept_rankings = extracted_boards.get("concept_rankings")
        if concept_rankings is None and api_context_snapshot is not None:
            try:
                concept_rankings = extract_board_detail_fields(api_context_snapshot).get("concept_rankings")
            except Exception:
                concept_rankings = None
        if market_structure is None:
            try:
                market_structure = extract_market_structure_detail_field(
                    api_context_snapshot,
                    raw_result_data,
                )
            except Exception:
                market_structure = None
        details = {
            "news_content": details_data.get("news_summary") or details_data.get("news_content"),
            "empty_news_disclosure": news_disclosure,
            "raw_result": raw_result_data,
            "context_snapshot": api_context_snapshot,
            "analysis_context_pack_overview": analysis_context_pack_overview,
            "financial_report": extracted_fundamental.get("financial_report"),
            "dividend_metrics": extracted_fundamental.get("dividend_metrics"),
            "belong_boards": extracted_boards.get("belong_boards"),
            "sector_rankings": extracted_boards.get("sector_rankings"),
            "concept_rankings": concept_rankings,
            "market_structure": market_structure,
        }

    return {
        "meta": meta,
        "summary": summary,
        "strategy": strategy,
        "details": details,
        "structured_report": report_data.get("structured_report"),
    }


def get_latest_analysis_report_payload(stock_code: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest persisted analysis record for ``stock_code`` in canonical report shape."""
    from src.services.history_service import HistoryService
    from src.storage import DatabaseManager

    db = DatabaseManager.get_instance()
    history_service = HistoryService()
    candidates = history_service._history_code_filter_candidates(stock_code)
    records, _ = db.get_analysis_history_paginated(code=candidates, limit=1)
    if not records:
        return None
    record = records[0]
    record_id = getattr(record, "id", None)
    detail = history_service.get_history_detail_by_id(int(record_id)) if record_id is not None else None
    if isinstance(detail, dict):
        report_data = {
            "meta": {
                "id": detail.get("id"),
                "query_id": detail.get("query_id", ""),
                "stock_code": detail.get("storage_stock_code") or detail.get("stock_code", stock_code),
                "stock_name": detail.get("stock_name"),
                "report_type": detail.get("report_type", "detailed"),
                "created_at": detail.get("created_at"),
                "model_used": detail.get("model_used"),
            },
            "summary": {
                "analysis_summary": detail.get("analysis_summary"),
                "operation_advice": detail.get("operation_advice"),
                "action": detail.get("action"),
                "trend_prediction": detail.get("trend_prediction"),
                "sentiment_score": detail.get("sentiment_score"),
                "sentiment_label": detail.get("sentiment_label"),
            },
            "strategy": {
                "ideal_buy": detail.get("ideal_buy"),
                "secondary_buy": detail.get("secondary_buy"),
                "stop_loss": detail.get("stop_loss"),
                "take_profit": detail.get("take_profit"),
            },
            "details": {
                "news_content": detail.get("news_content"),
                "empty_news_disclosure": detail.get("empty_news_disclosure"),
                "raw_result": detail.get("raw_result"),
            },
        }
        storage_code = str(detail.get("storage_stock_code") or detail.get("stock_code") or stock_code)
        fallback_fundamental = db.get_latest_fundamental_snapshot(
            query_id=str(detail.get("query_id") or ""),
            code=storage_code,
        )
        return build_analysis_report_payload(
            report_data=report_data,
            query_id=str(detail.get("query_id") or ""),
            stock_code=storage_code,
            stock_name=detail.get("stock_name"),
            context_snapshot=detail.get("context_snapshot"),
            fallback_fundamental_payload=fallback_fundamental,
            fallback_raw_result_payload=detail.get("raw_result"),
            record_id=record_id,
        )

    raw_result = parse_json_field(getattr(record, "raw_result", None)) or {}
    context_snapshot = parse_json_field(getattr(record, "context_snapshot", None))
    created_iso = record.created_at.isoformat() if getattr(record, "created_at", None) else None
    fallback_fundamental = db.get_latest_fundamental_snapshot(
        query_id=getattr(record, "query_id", ""),
        code=getattr(record, "code", stock_code),
    )
    report_data = {
        "meta": {
            "id": record_id,
            "query_id": getattr(record, "query_id", ""),
            "stock_code": getattr(record, "code", stock_code),
            "stock_name": getattr(record, "name", None),
            "report_type": getattr(record, "report_type", "detailed"),
            "created_at": created_iso,
            "model_used": getattr(record, "model_used", None),
        },
        "summary": {
            "analysis_summary": getattr(record, "analysis_summary", None),
            "operation_advice": getattr(record, "operation_advice", None),
            "trend_prediction": getattr(record, "trend_prediction", None),
            "sentiment_score": getattr(record, "sentiment_score", None),
        },
        "strategy": {
            "ideal_buy": getattr(record, "ideal_buy", None),
            "secondary_buy": getattr(record, "secondary_buy", None),
            "stop_loss": getattr(record, "stop_loss", None),
            "take_profit": getattr(record, "take_profit", None),
        },
        "details": {
            "news_content": getattr(record, "news_content", None),
            "raw_result": raw_result,
        },
    }
    return build_analysis_report_payload(
        report_data=report_data,
        query_id=str(getattr(record, "query_id", "") or ""),
        stock_code=str(getattr(record, "code", stock_code)),
        stock_name=getattr(record, "name", None),
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental,
        fallback_raw_result_payload=raw_result,
        record_id=record_id,
    )
