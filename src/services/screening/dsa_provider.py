# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""DSA provider-context bridge.

This module consumes DSA-owned callables passed through ``context["dsa"]``.
It is intentionally best-effort: the screening engine can use richer DSA data when
available, but screening should continue when one provider is slow or broken.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from src.services.screening.models import Pick

logger = logging.getLogger(__name__)

DSA_PROVIDER_MAX_CANDIDATES = 5


def apply_dsa_provider_context(
    picks: list[Pick],
    context: dict[str, Any] | None,
    *,
    max_candidates: int | None = None,
) -> list[str]:
    """Attach DSA context to top candidates before LLM ranking."""
    provider = _extract_provider_context(context)
    if not picks or not provider:
        return []

    limit = min(len(picks), max(_resolve_max_candidates(provider, max_candidates), 0))
    if limit <= 0:
        return []

    enriched_count = 0
    errors: list[str] = []
    for pick in picks[:limit]:
        try:
            payload = _fetch_candidate_context(provider, pick)
            if not payload:
                continue
            normalized = _normalize_candidate_payload(payload, pick)
            if not normalized:
                continue
            pick.dsa_context = normalized["context"]
            pick.dsa_news = normalized["news"]
            pick.dsa_analysis_summary = normalized["summary"]
            if _is_enriched_context(pick.dsa_context, pick.dsa_news):
                enriched_count += 1
        except Exception as exc:  # noqa: BLE001 - external DSA providers are optional.
            message = f"{pick.code}: {exc}"
            errors.append(message)
            pick.dsa_context = {
                "enriched": False,
                "warnings": [message],
            }
            logger.warning("DSA provider context failed for %s: %s", pick.code, exc)

    notes = [f"DSA provider context applied {enriched_count} of {limit} candidates"]
    if errors:
        sample = " | ".join(errors[:5])
        suffix = f" | +{len(errors) - 5} more" if len(errors) > 5 else ""
        notes.append(f"DSA provider context row errors: {sample}{suffix}")
    return notes


def _resolve_max_candidates(provider: dict[str, Any], max_candidates: int | None) -> int:
    if max_candidates is not None:
        return max_candidates
    configured = provider.get("max_candidates")
    try:
        if configured is None or configured == "":
            raise ValueError
        return int(configured)
    except (TypeError, ValueError):
        return DSA_PROVIDER_MAX_CANDIDATES


def _extract_provider_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    provider = context.get("dsa")
    return provider if isinstance(provider, dict) else {}


def _fetch_candidate_context(provider: dict[str, Any], pick: Pick) -> dict[str, Any]:
    candidate_getter = provider.get("get_candidate_context")
    if callable(candidate_getter):
        payload = _call_candidate_getter(candidate_getter, pick)
        return payload if isinstance(payload, dict) else {}

    quote = _call_optional_provider(provider.get("get_realtime_quote"), pick.code)
    fundamentals = _call_optional_provider(provider.get("get_fundamental_context"), pick.code)
    news = _call_news_provider(provider.get("search_stock_news"), pick)
    return {
        "enriched": bool(quote or fundamentals or _news_results(news)),
        "quote": quote,
        "fundamentals": fundamentals,
        "news": news,
        "warnings": [],
    }


def _call_candidate_getter(getter: Callable[..., Any], pick: Pick) -> Any:
    try:
        return getter(pick.code, pick.name)
    except TypeError:
        return getter(pick.code)


def _call_optional_provider(provider: Any, stock_code: str) -> dict[str, Any]:
    if not callable(provider):
        return {}
    payload = provider(stock_code)
    return payload if isinstance(payload, dict) else {}


def _call_news_provider(provider: Any, pick: Pick) -> dict[str, Any]:
    if not callable(provider):
        return {"success": False, "results": []}
    try:
        payload = provider(pick.code, pick.name, max_results=3)
    except TypeError:
        try:
            payload = provider(pick.code, pick.name)
        except TypeError:
            payload = provider(pick.code)
    return payload if isinstance(payload, dict) else {"success": False, "results": []}


def _normalize_candidate_payload(payload: dict[str, Any], pick: Pick) -> dict[str, Any]:
    full_payload = payload
    context = payload.get("dsa_context") if isinstance(payload.get("dsa_context"), dict) else payload
    if not isinstance(context, dict):
        return {}

    news = payload.get("dsa_news")
    if not isinstance(news, list):
        news = _news_results(context.get("news"))
    news = [item for item in news if isinstance(item, dict)]

    summary = str(payload.get("dsa_analysis_summary") or "").strip()
    if not summary:
        summary = _build_dsa_summary(pick, context, news)

    normalized_context = dict(context)
    normalized_context.setdefault("enriched", _is_enriched_context(normalized_context, news))
    if full_payload is not context and "dsa_context" in full_payload:
        normalized_context.setdefault("source_payload", "dsa_candidate_context")
    return {
        "context": normalized_context,
        "news": news,
        "summary": summary,
    }


def _is_enriched_context(context: dict[str, Any], news: list[dict[str, Any]]) -> bool:
    return bool(
        context.get("enriched")
        or context.get("quote")
        or context.get("fundamentals")
        or news
    )


def _news_results(news_payload: Any) -> list[dict[str, Any]]:
    if isinstance(news_payload, dict) and isinstance(news_payload.get("results"), list):
        return [item for item in news_payload["results"] if isinstance(item, dict)]
    if isinstance(news_payload, list):
        return [item for item in news_payload if isinstance(item, dict)]
    return []


def _build_dsa_summary(pick: Pick, context: dict[str, Any], news: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    quote = context.get("quote") if isinstance(context.get("quote"), dict) else {}
    price = quote.get("price") if quote else pick.price
    change_pct = quote.get("change_pct") if quote else pick.change_pct
    if price not in (None, ""):
        text = f"DSA行情: 现价 {price}"
        if change_pct not in (None, ""):
            text += f", 涨跌幅 {change_pct}%"
        parts.append(text)

    fundamentals = context.get("fundamentals")
    coverage = fundamentals.get("coverage") if isinstance(fundamentals, dict) else {}
    if isinstance(coverage, dict):
        available = [
            str(key)
            for key, value in coverage.items()
            if str(value).lower() in {"available", "partial"}
        ]
        if available:
            parts.append(f"DSA基本面覆盖: {', '.join(available[:4])}")

    titles = [
        str(item.get("title") or "").strip()
        for item in news
        if isinstance(item.get("title"), str) and item.get("title")
    ]
    if titles:
        parts.append(f"DSA新闻: {'; '.join(titles[:2])}")
    return "; ".join(parts)
