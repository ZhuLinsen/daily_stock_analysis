# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Optional DSA integration for L3 deep analysis."""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

import requests

from src.services.screening.models import Pick

logger = logging.getLogger(__name__)
_DEFAULT_ANALYZE_PATH = "/api/v1/analysis/analyze"
_ADVICE_SCORE_MAP = {
    "强烈买入": 10.0,
    "买入": 8.0,
    "增持": 5.0,
    "持有": 1.5,
    "中性": 0.0,
    "观望": -4.0,
    "减持": -8.0,
    "卖出": -12.0,
    "回避": -12.0,
}
_TREND_SCORE_MAP = {
    "看多": 4.0,
    "震荡": 0.0,
    "中性": 0.0,
    "看空": -6.0,
}


def analyze_picks_with_dsa(
    picks: list[Pick],
    *,
    run_id: str,
    api_url: str,
    report_type: str = "detailed",
    max_picks: int = 3,
    timeout_sec: float = 120.0,
    force_refresh: bool = False,
    notify: bool = False,
) -> tuple[list[Pick], list[str]]:
    """Run DSA deep analysis for up to ``max_picks`` candidates in place.

    This low-level helper only records attempted candidates. The post-analysis
    orchestrator records an explicit ``skipped`` status for candidates beyond
    the configured cap so downstream selection cannot treat them as analyzed.
    """
    if not api_url:
        raise ValueError("DSA_API_URL is required when deep_analysis=True")
    if max_picks <= 0:
        return picks, []

    analyze_count = min(max_picks, len(picks))
    degradation: list[str] = []
    endpoint = build_dsa_analyze_url(api_url)

    for idx, pick in enumerate(picks):
        if idx >= analyze_count:
            # The post-analysis orchestrator owns the explicit skipped status.
            continue

        try:
            result = call_dsa_analysis(
                endpoint,
                stock_code=pick.code,
                stock_name=pick.name,
                report_type=report_type,
                query_id=f"{run_id}-{pick.rank}-{pick.code}",
                timeout_sec=timeout_sec,
                force_refresh=force_refresh,
                notify=notify,
            )
            pick.deep_analysis_status = "completed"
            pick.deep_analysis_query_id = str(result.get("query_id", ""))
            pick.deep_analysis_result = result
            pick.deep_analysis_summary = extract_deep_analysis_summary(result)
            _attach_deep_analysis_fields(pick, result)
        except Exception as exc:
            logger.warning("DSA deep analysis failed for %s: %s", pick.code, exc)
            pick.deep_analysis_status = "failed"
            pick.deep_analysis_error = str(exc)
            degradation.append(f"DSA deep analysis failed for {pick.code}: {exc}")

    return picks, degradation


def build_dsa_analyze_url(api_url: str) -> str:
    """Accept a base URL or a full endpoint URL."""
    stripped = api_url.rstrip("/")
    parsed = urlparse(stripped)
    if parsed.path and parsed.path not in ("", "/"):
        return stripped
    return f"{stripped}{_DEFAULT_ANALYZE_PATH}"


def check_dsa_readiness(api_url: str, *, timeout_sec: float = 5.0) -> dict:
    """Best-effort DSA endpoint readiness probe for CLI/runtime diagnostics."""
    if not api_url:
        return {
            "available": False,
            "status": "missing_url",
            "endpoint": "",
            "http_status": None,
            "error": "DSA_API_URL is not configured",
        }

    endpoint = build_dsa_analyze_url(api_url)
    try:
        response = requests.get(endpoint, timeout=timeout_sec)
    except requests.RequestException as exc:
        return {
            "available": False,
            "status": "unreachable",
            "endpoint": endpoint,
            "http_status": None,
            "error": str(exc),
        }

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code in {200, 204, 405, 422}:
        status = "route_present"
        available = True
    elif status_code in {401, 403}:
        status = "unauthorized"
        available = False
    elif status_code == 404:
        status = "route_missing"
        available = False
    else:
        status = "unexpected_status"
        available = False

    return {
        "available": available,
        "status": status,
        "endpoint": endpoint,
        "http_status": status_code,
        "error": "" if available else _safe_str(getattr(response, "text", ""))[:280],
    }


def call_dsa_analysis(
    endpoint: str,
    *,
    stock_code: str,
    stock_name: str = "",
    report_type: str = "detailed",
    query_id: str = "",
    timeout_sec: float = 120.0,
    force_refresh: bool = False,
    notify: bool = False,
) -> dict:
    """Call the DSA sync analysis endpoint and return parsed JSON."""
    payload = {
        "stock_code": stock_code,
        "report_type": report_type,
        "force_refresh": force_refresh,
        "async_mode": False,
        "stock_name": stock_name or None,
        "original_query": stock_code,
        "selection_source": "import",
        "notify": notify,
    }
    if query_id:
        # The current DSA public API does not require query_id,
        # but we keep it in the payload for forward compatibility.
        payload["query_id"] = query_id

    response = requests.post(endpoint, json=payload, timeout=timeout_sec)
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError:
        return {"raw_text": response.text}
    if not isinstance(body, dict):
        return {"raw_result": body}
    return body


def extract_deep_analysis_summary(result: dict) -> str:
    """Best-effort extraction of a short summary from a DSA response."""
    if not isinstance(result, dict):
        return ""

    for key in ("summary", "analysis_summary", "conclusion", "message"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    report = result.get("report")
    if isinstance(report, dict):
        summary = report.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        if isinstance(summary, dict):
            for key in (
                "analysis_summary",
                "summary",
                "conclusion",
                "recommendation",
                "operation_advice",
                "signal_level",
            ):
                value = summary.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            rendered = json.dumps(summary, ensure_ascii=False)
            return rendered[:280]

    rendered = json.dumps(result, ensure_ascii=False)
    return rendered[:280]


def apply_dsa_overlay(picks: list[Pick]) -> list[Pick]:
    """Use DSA structured output as the final low-frequency risk/alpha overlay."""
    rescored: list[tuple[int, Pick]] = []
    for idx, pick in enumerate(picks):
        base_score = float(pick.final_score)
        if pick.deep_analysis_status == "completed":
            base_score += _compute_dsa_overlay_score(pick)
        pick.final_score = round(base_score, 4)
        rescored.append((idx, pick))

    rescored.sort(key=lambda item: (-item[1].final_score, item[0]))
    reranked = [pick for _, pick in rescored]
    for i, pick in enumerate(reranked, start=1):
        pick.rank = i
    return reranked


def _attach_deep_analysis_fields(pick: Pick, result: dict) -> None:
    summary = _extract_report_summary(result)
    trend = _extract_trend_result(result)

    pick.deep_analysis_signal_score = _safe_int(trend.get("signal_score"))
    pick.deep_analysis_sentiment_score = _safe_int(summary.get("sentiment_score"))
    pick.deep_analysis_operation_advice = _safe_str(summary.get("operation_advice"))
    pick.deep_analysis_trend_prediction = _safe_str(summary.get("trend_prediction"))
    pick.deep_analysis_risk_flags = _extract_risk_flags(trend)


def _compute_dsa_overlay_score(pick: Pick) -> float:
    score = 0.0

    if pick.deep_analysis_signal_score is not None:
        score += (pick.deep_analysis_signal_score - 50) * 0.20
    if pick.deep_analysis_sentiment_score is not None:
        score += (pick.deep_analysis_sentiment_score - 50) * 0.12

    advice = pick.deep_analysis_operation_advice.strip()
    score += _ADVICE_SCORE_MAP.get(advice, 0.0)

    trend = pick.deep_analysis_trend_prediction.strip()
    score += _TREND_SCORE_MAP.get(trend, 0.0)

    if pick.deep_analysis_risk_flags:
        score -= min(len(pick.deep_analysis_risk_flags) * 2.0, 6.0)

    return score


def _extract_report_summary(result: dict) -> dict:
    report = result.get("report")
    if not isinstance(report, dict):
        return {}
    summary = report.get("summary")
    return summary if isinstance(summary, dict) else {}


def _extract_trend_result(result: dict) -> dict:
    report = result.get("report")
    if not isinstance(report, dict):
        return {}
    details = report.get("details")
    if not isinstance(details, dict):
        return {}
    context_snapshot = details.get("context_snapshot")
    if not isinstance(context_snapshot, dict):
        return {}
    trend = context_snapshot.get("trend_result")
    return trend if isinstance(trend, dict) else {}


def _extract_risk_flags(trend_result: dict) -> list[str]:
    risks = trend_result.get("risk_factors")
    if not isinstance(risks, list):
        return []
    return [str(item).strip() for item in risks if str(item).strip()]


def _safe_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()
