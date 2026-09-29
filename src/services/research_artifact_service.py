# -*- coding: utf-8 -*-
"""Build structured research artifacts from existing analysis reports."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from api.v1.schemas.research_artifact import ResearchArtifact


_BULLISH_ACTIONS = {"buy", "add"}
_BEARISH_ACTIONS = {"reduce", "sell", "avoid"}
_NEUTRAL_ACTIONS = {"hold", "watch"}


def build_research_artifact(
    report: Any,
    *,
    evidence_items: Optional[Iterable[Dict[str, Any]]] = None,
    invalidation_conditions: Optional[Iterable[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a ResearchArtifact-compatible dict without mutating the source report."""
    meta = _section(report, "meta")
    summary = _section(report, "summary")
    strategy = _section(report, "strategy")
    details = _section(report, "details")
    context_overview = _value(details, "analysis_context_pack_overview")
    source_report_id = _as_int(_value(meta, "id"))
    query_id = _as_text(_value(meta, "query_id"))
    stock_code = _as_text(_value(meta, "stock_code")) or "UNKNOWN"
    artifact_id = (
        f"report:{source_report_id}"
        if source_report_id is not None
        else f"report:{stock_code}:{query_id}" if query_id else f"report:{stock_code}"
    )

    evidence = _build_evidence(details, context_overview)
    if evidence_items is not None:
        evidence.extend(dict(item) for item in evidence_items)

    invalidations = _build_invalidation_conditions(summary, strategy, details, context_overview)
    if invalidation_conditions is not None:
        invalidations.extend(dict(item) for item in invalidation_conditions)
    if not invalidations:
        invalidations.append(_manual_reassessment_condition())

    payload = {
        "artifact_id": artifact_id,
        "source_report_id": source_report_id,
        "source_query_id": query_id or None,
        "created_at": _as_text(_value(meta, "created_at")) or None,
        "subject": {
            "stock_code": stock_code,
            "stock_name": _as_text(_value(meta, "stock_name")) or None,
            "market": _subject_market(meta, context_overview),
        },
        "thesis": _build_thesis(summary),
        "evidence": evidence,
        "invalidation_conditions": invalidations,
        "next_actions": _build_next_actions(summary, invalidations),
        "data_quality": _build_data_quality(context_overview, evidence),
        "metadata": {
            "source": "analysis_report",
            **dict(metadata or {}),
        },
    }
    return ResearchArtifact.model_validate(payload).model_dump(exclude_none=True)


def _build_thesis(summary: Any) -> Dict[str, Any]:
    action = _as_text(_value(summary, "action")) or None
    action_label = _as_text(_value(summary, "action_label")) or _as_text(_value(summary, "operation_advice")) or None
    score = _as_int(_value(summary, "sentiment_score"))
    analysis_summary = _as_text(_value(summary, "analysis_summary"))
    trend_prediction = _as_text(_value(summary, "trend_prediction"))
    operation_advice = _as_text(_value(summary, "operation_advice"))
    reasons = [value for value in [analysis_summary, trend_prediction] if value]
    risks = []
    if action == "alert":
        risks.append(operation_advice or "Report action is alert")
    return {
        "direction": _direction_from_action_or_score(action, score),
        "summary": analysis_summary or trend_prediction or operation_advice,
        "score": score,
        "confidence": _score_to_confidence(score),
        "action": action,
        "action_label": action_label,
        "reasons": reasons,
        "risks": risks,
    }


def _build_evidence(details: Any, context_overview: Any) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    blocks = _value(context_overview, "blocks") or []
    for index, block in enumerate(blocks):
        key = _as_text(_value(block, "key")) or f"context_{index + 1}"
        status = _as_text(_value(block, "status"))
        evidence.append({
            "id": f"context:{key}",
            "source_type": "analysis_context",
            "title": _as_text(_value(block, "label")) or key,
            "source": _as_text(_value(block, "source")) or None,
            "freshness": _freshness_from_status(status),
            "quality_level": _quality_from_status(status),
            "metadata": {
                "status": status,
                "warnings": _value(block, "warnings") or [],
                "missing_reasons": _value(block, "missing_reasons") or [],
            },
        })

    if _value(details, "news_content") or _value(details, "empty_news_disclosure"):
        has_news_content = bool(_value(details, "news_content"))
        evidence.append({
            "id": "news:summary",
            "source_type": "news",
            "title": "News summary",
            "summary": _as_text(_value(details, "empty_news_disclosure"))
            or _compact(_as_text(_value(details, "news_content"))),
            "freshness": "unknown",
            "quality_level": "usable" if has_news_content else "limited",
            "metadata": {"status": "available" if has_news_content else "missing"},
        })

    if _value(details, "financial_report"):
        evidence.append({
            "id": "fundamental:financial_report",
            "source_type": "fundamental",
            "title": "Financial report",
            "freshness": "unknown",
            "quality_level": "usable",
        })

    if _value(details, "dividend_metrics"):
        evidence.append({
            "id": "fundamental:dividend_metrics",
            "source_type": "fundamental",
            "title": "Dividend metrics",
            "freshness": "unknown",
            "quality_level": "usable",
        })

    market_structure = _value(details, "market_structure")
    if market_structure:
        status = _as_text(_value(market_structure, "status"))
        evidence.append({
            "id": "market:structure",
            "source_type": "market_structure",
            "title": "Market structure",
            "freshness": _freshness_from_status(status),
            "quality_level": _quality_from_status(status),
            "metadata": {"status": status},
        })

    return evidence


def _build_invalidation_conditions(
    summary: Any,
    strategy: Any,
    details: Any,
    context_overview: Any,
) -> List[Dict[str, Any]]:
    conditions: List[Dict[str, Any]] = []
    stop_loss = _as_text(_value(strategy, "stop_loss"))
    if stop_loss:
        conditions.append({
            "id": "price:stop_loss",
            "category": "price",
            "description": f"Price breaks the report stop-loss area: {stop_loss}",
            "trigger": stop_loss,
            "severity": "critical",
            "metric": "price",
            "threshold": stop_loss,
        })

    take_profit = _as_text(_value(strategy, "take_profit"))
    if take_profit:
        conditions.append({
            "id": "price:take_profit_review",
            "category": "price",
            "description": f"Price reaches the take-profit area and requires reassessment: {take_profit}",
            "trigger": take_profit,
            "severity": "watch",
            "metric": "price",
            "threshold": take_profit,
        })

    limitations = _quality_limitations(context_overview)
    if limitations:
        conditions.append({
            "id": "data_quality:limitations",
            "category": "data_quality",
            "description": "Input data quality limitations require reassessment when fresh data is available.",
            "trigger": "; ".join(limitations[:3]),
            "severity": "warning",
            "metadata": {"limitations": limitations},
        })

    disclosure = _as_text(_value(details, "empty_news_disclosure"))
    if disclosure:
        conditions.append({
            "id": "evidence:news_missing",
            "category": "evidence",
            "description": "News evidence was unavailable or empty during report generation.",
            "trigger": disclosure,
            "severity": "watch",
        })

    thesis_text = _as_text(_value(summary, "analysis_summary")) or _as_text(_value(summary, "trend_prediction"))
    if thesis_text and not conditions:
        conditions.append(_manual_reassessment_condition())

    return conditions


def _manual_reassessment_condition() -> Dict[str, Any]:
    return {
        "id": "manual:thesis_reassessment",
        "category": "manual",
        "description": "Reassess when price action, news, fundamentals, or market phase conflicts with the thesis.",
        "severity": "warning",
    }


def _build_next_actions(summary: Any, invalidations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    action = _as_text(_value(summary, "action")) or "watch"
    label = _as_text(_value(summary, "action_label")) or _as_text(_value(summary, "operation_advice")) or action
    next_actions = [{
        "action": action,
        "label": label,
        "reason": _as_text(_value(summary, "analysis_summary")) or None,
    }]
    if invalidations:
        next_actions.append({
            "action": "monitor_invalidation",
            "label": "Monitor invalidation",
            "reason": invalidations[0]["description"],
            "metadata": {"condition_id": invalidations[0]["id"]},
        })
    return next_actions


def _build_data_quality(context_overview: Any, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    data_quality = _value(context_overview, "data_quality")
    counts = _value(context_overview, "counts")
    missing_blocks = [
        _as_text(_value(block, "key"))
        for block in (_value(context_overview, "blocks") or [])
        if _as_text(_value(block, "status")) in {"missing", "fetch_failed", "not_supported"}
    ]
    return {
        "level": _as_text(_value(data_quality, "level")) or _infer_quality_level(evidence),
        "overall_score": _as_int(_value(data_quality, "overall_score")),
        "source_count": sum(1 for item in evidence if _evidence_has_usable_source(item)),
        "stale_count": sum(1 for item in evidence if item.get("freshness") == "stale"),
        "missing_blocks": [block for block in missing_blocks if block],
        "limitations": _quality_limitations(context_overview),
        "metadata": {"counts": counts} if counts else {},
    }


def _quality_limitations(context_overview: Any) -> List[str]:
    data_quality = _value(context_overview, "data_quality")
    limitations = _value(data_quality, "limitations") or []
    return [_as_text(item) for item in limitations if _as_text(item)]


def _direction_from_action_or_score(action: Optional[str], score: Optional[int]) -> str:
    if action in _BULLISH_ACTIONS:
        return "bullish"
    if action in _BEARISH_ACTIONS:
        return "bearish"
    if action in _NEUTRAL_ACTIONS:
        return "neutral"
    if score is not None:
        if score >= 65:
            return "bullish"
        if score <= 35:
            return "bearish"
        return "neutral"
    return "unknown"


def _score_to_confidence(score: Optional[int]) -> Optional[float]:
    if score is None:
        return None
    bounded = max(0, min(100, score))
    return round(abs(bounded - 50) / 50, 2)


def _freshness_from_status(status: str) -> str:
    if status in {"available", "fallback", "partial", "estimated", "ok"}:
        return "fresh"
    if status == "stale":
        return "stale"
    return "unknown"


def _quality_from_status(status: str) -> str:
    if status in {"available", "ok"}:
        return "good"
    if status in {"fallback", "estimated"}:
        return "usable"
    if status in {"partial", "stale"}:
        return "limited"
    if status in {"missing", "fetch_failed"}:
        return "poor"
    return "unknown"


def _evidence_has_usable_source(item: Dict[str, Any]) -> bool:
    metadata = item.get("metadata")
    status = _as_text(metadata.get("status")) if isinstance(metadata, dict) else ""
    return status not in {"missing", "fetch_failed", "not_supported", "unavailable", "unknown"}


def _infer_quality_level(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "unknown"
    levels = {str(item.get("quality_level") or "unknown") for item in evidence}
    if "poor" in levels:
        return "poor"
    if "limited" in levels:
        return "limited"
    if "usable" in levels:
        return "usable"
    if levels == {"good"}:
        return "good"
    return "unknown"


def _subject_market(meta: Any, context_overview: Any) -> Optional[str]:
    market = _value(_value(context_overview, "subject"), "market")
    return _as_text(market) or _as_text(_value(meta, "market")) or None


def _section(report: Any, key: str) -> Any:
    return _value(report, key) or {}


def _value(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        if key in source:
            return source[key]
        camel_key = _snake_to_camel(key)
        return source.get(camel_key)
    if hasattr(source, key):
        return getattr(source, key)
    return getattr(source, _snake_to_camel(key), None)


def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _compact(value: str, limit: int = 180) -> str:
    text = _as_text(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
