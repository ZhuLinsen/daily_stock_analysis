# -*- coding: utf-8 -*-
"""
===================================
Report Engine - Jinja2 Report Renderer
===================================

Renders reports from Jinja2 templates. Falls back to caller's logic on template
missing or render error. Template path is relative to project root.
Any expensive data preparation should be injected by the caller via extra_context.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.analyzer import AnalysisResult
from src.config import get_config
from src.report_language import (
    get_localized_stock_name,
    get_report_labels,
    get_signal_level,
    localize_chip_health,
    localize_operation_advice,
    localize_trend_prediction,
    normalize_report_language,
)

logger = logging.getLogger(__name__)


def _escape_md(text: str) -> str:
    """Escape markdown special chars (*ST etc)."""
    if not text:
        return ""
    return text.replace("*", "\\*").replace("_", "\\_")


def _clean_sniper_value(val: Any) -> str:
    """Format sniper point value for display (strip label prefixes)."""
    if val is None:
        return "N/A"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val).strip() if val else ""
    if not s or s == "N/A":
        return s or "N/A"
    prefixes = [
        "理想买入点：", "次优买入点：", "止损位：", "目标位：",
        "理想买入点:", "次优买入点:", "止损位:", "目标位:",
        "Ideal Entry:", "Secondary Entry:", "Stop Loss:", "Target:",
    ]
    for prefix in prefixes:
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def _resolve_templates_dir() -> Path:
    """Resolve template directory relative to project root."""
    config = get_config()
    base = Path(__file__).resolve().parent.parent.parent
    templates_dir = Path(config.report_templates_dir)
    if not templates_dir.is_absolute():
        return base / templates_dir
    return templates_dir


def render(
    platform: str,
    results: List[AnalysisResult],
    report_date: Optional[str] = None,
    summary_only: bool = False,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Render report using Jinja2 template.

    Args:
        platform: One of: markdown, wechat, brief
        results: List of AnalysisResult
        report_date: Report date string (default: today)
        summary_only: Whether to output summary only
        extra_context: Additional template context

    Returns:
        Rendered string, or None on error (caller should fallback).
    """
    from datetime import datetime

    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError:
        logger.warning("jinja2 not installed, report renderer disabled")
        return None

    if report_date is None:
        report_date = datetime.now().strftime("%Y-%m-%d")

    templates_dir = _resolve_templates_dir()
    template_name = f"report_{platform}.j2"
    template_path = templates_dir / template_name
    if not template_path.exists():
        logger.debug("Report template not found: %s", template_path)
        return None

    report_language = normalize_report_language(
        (extra_context or {}).get("report_language")
        or next(
            (getattr(result, "report_language", None) for result in results if getattr(result, "report_language", None)),
            None,
        )
        or getattr(get_config(), "report_language", "zh")
    )
    labels = get_report_labels(report_language)

    # Build template context with pre-computed signal levels (sorted by score)
    sorted_results = sorted(results, key=lambda x: x.sentiment_score, reverse=True)
    sorted_enriched = []
    for r in sorted_results:
        st, se, _ = get_signal_level(r.operation_advice, r.sentiment_score, report_language)
        rn = get_localized_stock_name(r.name, r.code, report_language)
        sorted_enriched.append({
            "result": r,
            "signal_text": st,
            "signal_emoji": se,
            "stock_name": _escape_md(rn),
            "localized_operation_advice": localize_operation_advice(r.operation_advice, report_language),
            "localized_trend_prediction": localize_trend_prediction(r.trend_prediction, report_language),
        })

    buy_count = sum(1 for r in results if getattr(r, "decision_type", "") == "buy")
    sell_count = sum(1 for r in results if getattr(r, "decision_type", "") == "sell")
    hold_count = sum(1 for r in results if getattr(r, "decision_type", "") in ("hold", ""))

    report_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def failed_checks(checklist: List[str]) -> List[str]:
        return [c for c in (checklist or []) if c.startswith("❌") or c.startswith("⚠️")]

    context: Dict[str, Any] = {
        "report_date": report_date,
        "report_timestamp": report_timestamp,
        "results": sorted_results,
        "enriched": sorted_enriched,  # Sorted by sentiment_score desc
        "summary_only": summary_only,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "hold_count": hold_count,
        "labels": labels,
        "report_language": report_language,
        "escape_md": _escape_md,
        "clean_sniper": _clean_sniper_value,
        "failed_checks": failed_checks,
        "history_by_code": {},
        "localize_operation_advice": localize_operation_advice,
        "localize_trend_prediction": localize_trend_prediction,
        "localize_chip_health": localize_chip_health,
    }
    if extra_context:
        safe_extra_context = dict(extra_context)
        safe_extra_context.pop("labels", None)
        safe_extra_context.pop("report_language", None)
        context.update(safe_extra_context)

    try:
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(default=False),
        )
        template = env.get_template(template_name)
        return template.render(**context)
    except Exception as e:
        logger.warning("Report render failed for %s: %s", template_name, e)
        return None
