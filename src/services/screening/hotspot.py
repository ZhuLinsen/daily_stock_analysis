# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Topic-first hotspot discovery and detail helpers."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.services.screening.industry import (
    _board_heat_score,
    _normalize_code,
    _safe_float,
    _safe_text,
    load_board_heat_trends,
)
from src.services.screening.source_guard import call_with_timeout, parse_source_timeout_seconds


HOTSPOT_STAGES = (
    "初次异动",
    "确认扩散",
    "加速主升",
    "分歧放量",
    "降温退潮",
)

_HOTSPOT_CALL_TIMEOUT_SECONDS = 20.0


@dataclass
class HotspotSummary:
    topic: str
    name: str = ""
    source: str = ""
    rank: int | None = None
    change_pct: float | None = None
    heat_score: float = 50.0
    trend_score: float | None = None
    persistence_score: float | None = None
    cooling_score: float | None = None
    observations: int = 0
    state: str = ""
    stage: str = "初次异动"
    sample_stock_count: int = 0
    leaders: list[str] = field(default_factory=list)
    leader_stocks: list["HotspotStock"] = field(default_factory=list)
    quality_status: str = "partial"
    missing_fields: list[str] = field(default_factory=list)
    canonical_topic: str = ""
    aliases: list[str] = field(default_factory=list)
    resolver_candidates: list[dict[str, Any]] = field(default_factory=list)
    provider_used: str = ""
    fallback_used: bool = False
    source_errors: list[str] = field(default_factory=list)
    stale: bool = False
    stale_age_hours: float | None = None


@dataclass
class HotspotStock:
    code: str
    name: str = ""
    change_pct: float | None = None
    amount: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    net_inflow: float | None = None
    is_limit_up: bool = False
    active_days: int = 0
    evidence_count: int = 0
    role: str = ""
    hot_stock_score: float = 0.0
    source: str = ""
    source_confidence: float | None = None
    fallback_used: bool = False


@dataclass
class HotspotTopicResolution:
    query: str
    canonical_topic: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    confidence: float = 0.0
    unresolved: bool = True


@dataclass
class TimelineEvent:
    date: str
    source: str
    title: str
    event_type: str = "news"
    impact_score: float = 0.0
    related_codes: list[str] = field(default_factory=list)
    description: str = ""
    url: str = ""
    published_at: str = ""


@dataclass
class HotspotRouteItem:
    date: str
    title: str
    description: str = ""
    source: str = ""
    event_type: str = "summary"
    impact_score: float = 0.0
    related_codes: list[str] = field(default_factory=list)
    url: str = ""
    published_at: str = ""


@dataclass
class HotspotDetail:
    summary: HotspotSummary
    stocks: list[HotspotStock] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    route: list[HotspotRouteItem] = field(default_factory=list)


class HotspotResults(list[HotspotSummary]):
    """List-compatible hotspot result with degradation metadata."""

    def __init__(
        self,
        items: list[HotspotSummary] | None = None,
        *,
        provider_used: str = "",
        fallback_used: bool = False,
        source_errors: list[str] | None = None,
        stale: bool = False,
        stale_age_hours: float | None = None,
    ) -> None:
        super().__init__(items or [])
        self.provider_used = provider_used
        self.fallback_used = fallback_used
        self.source_errors = _dedupe_errors(source_errors or [])
        self.stale = stale
        self.stale_age_hours = stale_age_hours


def compute_hotspot_heat_score(change_pct: float | None, rank: float | None) -> float:
    """Compute board heat using the industry cache semantics."""
    return _board_heat_score(change_pct=change_pct, rank=rank)


def classify_hotspot_stage(
    *,
    state: str = "",
    trend_score: float | None = None,
    cooling_score: float | None = None,
    persistence_score: float | None = None,
    latest_score: float | None = None,
    observations: int | None = None,
) -> str:
    """Classify a hotspot into a coarse lifecycle stage."""
    state_text = _safe_text(state).lower()
    trend = _safe_float(trend_score) or 0.0
    cooling = _safe_float(cooling_score) or 0.0
    persistence = _safe_float(persistence_score) or 0.0
    latest = _safe_float(latest_score) or 0.0
    obs = int(_safe_float(observations) or 0)

    if state_text in {"weakening", "cooling"} and (latest < 60 or trend <= -5):
        return "降温退潮"
    if cooling >= 8 and (latest < 60 or trend <= -5):
        return "降温退潮"
    if cooling >= 5:
        return "分歧放量"
    if latest >= 75 and trend >= 8 and persistence >= 50:
        return "加速主升"
    if state_text == "persistent_hot" or persistence >= 66.6667:
        return "确认扩散"
    if trend >= 5 and obs >= 2:
        return "确认扩散"
    return "初次异动"


def resolve_hotspot_topic(
    topic: str,
    *,
    provider: str | object | None = None,
    hotspots: list[HotspotSummary | dict[str, Any]] | None = None,
    fallback_cache_path: str | Path | None = None,
    max_boards: int = 500,
    source_errors: list[str] | None = None,
) -> HotspotTopicResolution:
    """Resolve a user topic to deterministic canonical hotspot candidates."""
    topic_text = _safe_text(topic)
    candidates: list[dict[str, Any]] = []
    if hotspots:
        candidates.extend(_topic_candidates_from_hotspots(hotspots, source="cache"))

    if fallback_cache_path:
        try:
            candidates.extend(_topic_candidates_from_hotspots(load_hotspots_json(fallback_cache_path), source="cache"))
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 - resolver should degrade to provider/query candidates.
            if source_errors is not None:
                source_errors.append(f"last_good_cache: {exc}")

    if provider is not None:
        provider_errors = source_errors if source_errors is not None else []
        for label, provider_obj in _resolve_provider_chain(provider, provider_errors):
            if provider_obj is None:
                continue
            rows = _load_board_summaries(
                provider_obj,
                max_boards=max_boards,
                source_errors=provider_errors,
                provider_label=label,
            )
            candidates.extend(_topic_candidates_from_board_rows(rows, provider_label=label))

    return _resolve_topic_from_candidates(topic_text, candidates)


def score_hotspot_stock(row: dict[str, Any] | pd.Series) -> float:
    """Score a constituent stock for hotspot leadership strength."""
    change = _safe_float(_row_value(row, ["change_pct", "涨跌幅", "涨幅"])) or 0.0
    amount = _safe_float(_row_value(row, ["amount", "成交额", "成交金额"])) or 0.0
    turnover = _safe_float(_row_value(row, ["turnover_rate", "换手率"])) or 0.0
    volume_ratio = _safe_float(_row_value(row, ["volume_ratio", "量比"])) or 0.0
    net_inflow = _safe_float(_row_value(row, ["net_inflow", "主力净流入", "主力净流入-净额"])) or 0.0
    is_limit_up = _safe_bool(_row_value(row, ["is_limit_up", "涨停", "是否涨停"]))
    active_days = int(_safe_float(_row_value(row, ["active_days", "连续活跃", "活跃天数"])) or 0)
    evidence_count = int(_safe_float(_row_value(row, ["evidence_count", "证据数", "线索数"])) or 0)

    amount_score = 0.0
    if amount > 0:
        amount_score = _clamp((math.log10(amount) - 6.0) / 4.0 * 18.0, 0.0, 18.0)

    inflow_score = 0.0
    if net_inflow > 0:
        inflow_score = _clamp((math.log10(net_inflow) - 5.0) / 4.0 * 12.0, 0.0, 12.0)
    elif net_inflow < 0:
        inflow_score = -_clamp((math.log10(abs(net_inflow)) - 5.0) / 4.0 * 8.0, 0.0, 8.0)

    score = 35.0
    score += _clamp(change * 2.7, -18.0, 32.0)
    score += amount_score
    score += _clamp(turnover * 1.1, 0.0, 14.0)
    score += _clamp(volume_ratio * 3.0, 0.0, 12.0)
    score += inflow_score
    score += 8.0 if is_limit_up else 0.0
    score += _clamp(active_days * 2.5, 0.0, 8.0)
    score += _clamp(evidence_count * 2.0, 0.0, 8.0)
    return round(_clamp(score, 0.0, 100.0), 4)


def assign_stock_roles(scored_rows: list[dict[str, Any] | HotspotStock]) -> list[HotspotStock]:
    """Sort scored constituents and assign hotspot roles."""
    stocks = [_coerce_hotspot_stock(item) for item in scored_rows]
    stocks = sorted(
        stocks,
        key=lambda item: (
            item.hot_stock_score,
            item.change_pct if item.change_pct is not None else -999.0,
            item.amount if item.amount is not None else -1.0,
            item.code,
        ),
        reverse=True,
    )
    if not stocks:
        return []

    top_score = stocks[0].hot_stock_score
    for idx, stock in enumerate(stocks):
        change = stock.change_pct or 0.0
        if idx == 0 and stock.hot_stock_score >= 70:
            role = "核心龙头"
        elif idx <= 2 and stock.hot_stock_score >= max(68.0, top_score - 8.0) and change >= 5.0:
            role = "核心龙头"
        elif stock.hot_stock_score >= 62.0 and change >= 3.0:
            role = "助攻"
        elif stock.hot_stock_score >= 48.0 and change >= 0:
            role = "补涨"
        elif stock.hot_stock_score >= 38.0:
            role = "后排"
        else:
            role = "掉队"
        stock.role = role
    return stocks


def discover_hotspots(
    *,
    provider: str | object = "akshare",
    max_boards: int = 80,
    history_path: str | Path | None = None,
    fallback_cache_path: str | Path | None = None,
    top: int = 20,
) -> HotspotResults:
    """Discover ranked concept/industry hotspots from a provider."""
    source_errors: list[str] = []
    provider_chain = _resolve_provider_chain(provider, source_errors)
    provider_used = ""
    rows: list[dict[str, Any]] = []

    for label, provider_obj in provider_chain:
        provider_used = label or provider_used
        if provider_obj is None:
            continue
        error_count = len(source_errors)
        rows = _load_board_summaries(
            provider_obj,
            max_boards=max_boards,
            source_errors=source_errors,
            provider_label=label,
        )
        if rows:
            provider_used = label
            break
        if len(source_errors) == error_count:
            source_errors.append(f"{label}: returned no hotspot rows")

    if not rows:
        if fallback_cache_path and not source_errors and provider_used == "none":
            source_errors.append("none: no live provider requested")
        fallback = _load_fallback_hotspots(
            fallback_cache_path,
            source_errors=source_errors,
            top=top,
        )
        if fallback is not None:
            return fallback
        return HotspotResults(
            [],
            provider_used=provider_used,
            fallback_used=False,
            source_errors=source_errors,
        )

    trends = _load_history_trends(history_path)
    summaries: list[HotspotSummary] = []
    for row in rows:
        topic = row["topic"]
        trend = trends.get(topic, {})
        latest_score = _safe_float(trend.get("board_heat_latest_score"))
        trend_score = _safe_float(trend.get("board_heat_trend_score"))
        persistence_score = _safe_float(trend.get("board_heat_persistence_score"))
        cooling_score = _safe_float(trend.get("board_heat_cooling_score"))
        observations = int(_safe_float(trend.get("board_heat_observations")) or 0)
        state = _safe_text(trend.get("board_heat_state"))
        heat_score = latest_score if latest_score is not None else float(row["heat_score"])
        stage = classify_hotspot_stage(
            state=state,
            trend_score=trend_score,
            cooling_score=cooling_score,
            persistence_score=persistence_score,
            latest_score=heat_score,
            observations=observations,
        )
        summaries.append(HotspotSummary(
            topic=topic,
            name=topic,
            source=row.get("source", ""),
            rank=row.get("rank"),
            change_pct=row.get("change_pct"),
            heat_score=round(heat_score, 4),
            trend_score=trend_score,
            persistence_score=persistence_score,
            cooling_score=cooling_score,
            observations=observations,
            state=state,
            stage=stage,
            canonical_topic=topic,
            aliases=[topic],
        ))

    ranked = sorted(summaries, key=_hotspot_sort_key, reverse=True)[:max(int(top), 0)]
    for summary in ranked:
        provider_obj = next((obj for label, obj in provider_chain if label == provider_used), None)
        stocks = _load_scored_constituents(
            provider_obj,
            summary.topic,
            source=summary.source,
            source_errors=source_errors,
            provider_label=provider_used,
        ) if provider_obj is not None else []
        summary.sample_stock_count = len(stocks)
        _set_summary_leaders(summary, stocks)
        if not stocks:
            fallback_summary = _find_fallback_hotspot(summary.topic, fallback_cache_path, source_errors=source_errors)
            fallback_stocks = _leader_fallback_stocks(
                fallback_summary,
                stale_age_hours=_cache_stale_age_hours(fallback_cache_path),
            )
            if fallback_stocks:
                summary.sample_stock_count = len(fallback_stocks)
                summary.fallback_used = True
                _set_summary_leaders(summary, fallback_stocks)
                _add_missing_fields(summary, ["live_stocks"])
            else:
                _add_missing_fields(summary, ["stocks", "leader_stocks"])
    return _with_result_metadata(
        ranked,
        provider_used=provider_used,
        fallback_used=False,
        source_errors=source_errors,
        stale=False,
        stale_age_hours=None,
    )


def get_hotspot_detail(
    topic: str,
    *,
    provider: str | object = "akshare",
    top_stocks: int = 10,
    timeline_path: str | Path | None = None,
    history_path: str | Path | None = None,
    fallback_cache_path: str | Path | None = None,
) -> HotspotDetail:
    """Return one hotspot detail view with constituent stock roles and timeline."""
    topic_text = _safe_text(topic)
    source_errors: list[str] = []
    provider_chain = _resolve_provider_chain(provider, source_errors)
    provider_used = ""
    fallback_hotspots = _load_hotspot_cache_for_fallback(fallback_cache_path, source_errors=source_errors)
    cache_resolution = _resolve_topic_from_candidates(
        topic_text,
        _topic_candidates_from_hotspots(fallback_hotspots, source="cache"),
    )
    fallback_summary = _fallback_summary_for_resolution(topic_text, fallback_hotspots, cache_resolution)
    best_resolution = cache_resolution
    summary = HotspotSummary(
        topic=topic_text,
        name=topic_text,
        source="",
        canonical_topic=cache_resolution.canonical_topic,
        aliases=cache_resolution.aliases,
        resolver_candidates=cache_resolution.candidates,
    )
    stocks: list[HotspotStock] = []
    lookup_topic_used = topic_text

    if topic_text:
        for label, provider_obj in provider_chain:
            provider_used = label or provider_used
            if provider_obj is None:
                continue
            board_rows = _load_board_summaries(
                provider_obj,
                max_boards=500,
                source_errors=source_errors,
                provider_label=label,
            )
            provider_resolution = _resolve_topic_from_candidates(
                topic_text,
                [
                    *_topic_candidates_from_board_rows(board_rows, provider_label=label),
                    *_topic_candidates_from_hotspots(fallback_hotspots, source="cache"),
                ],
            )
            if provider_resolution.candidates:
                best_resolution = provider_resolution
            lookup_topic = provider_resolution.canonical_topic or cache_resolution.canonical_topic or topic_text
            lookup_topic_used = lookup_topic
            row = _find_board_summary_in_rows(board_rows, lookup_topic)
            if row:
                row_heat = _safe_float(row.get("heat_score"))
                summary = HotspotSummary(
                    topic=topic_text,
                    name=lookup_topic,
                    source=row.get("source", ""),
                    rank=row.get("rank"),
                    change_pct=row.get("change_pct"),
                    heat_score=row_heat if row_heat is not None else 50.0,
                    canonical_topic=lookup_topic,
                    aliases=provider_resolution.aliases,
                    resolver_candidates=provider_resolution.candidates,
                )
            source = summary.source or "concept"
            stocks = _load_scored_constituents(
                provider_obj,
                lookup_topic,
                source=source,
                source_errors=source_errors,
                provider_label=label,
            )
            if stocks and not summary.source:
                summary.source = source
            if not stocks and source != "industry":
                stocks = _load_scored_constituents(
                    provider_obj,
                    lookup_topic,
                    source="industry",
                    source_errors=source_errors,
                    provider_label=label,
                )
                if stocks:
                    summary.source = "industry"
            if row or stocks:
                provider_used = label
                break

    if not stocks and not summary.source and fallback_summary is not None:
        cached_summary = _copy_hotspot_summary(fallback_summary)
        if cached_summary.topic != topic_text:
            cached_summary.name = cached_summary.topic
            cached_summary.topic = topic_text
        summary = cached_summary
        summary.canonical_topic = cache_resolution.canonical_topic or fallback_summary.canonical_topic or fallback_summary.topic
        summary.aliases = cache_resolution.aliases or summary.aliases
        summary.resolver_candidates = cache_resolution.candidates
        stale_age = _cache_stale_age_hours(fallback_cache_path)
        _apply_summary_metadata(
            summary,
            provider_used="last_good_cache",
            fallback_used=True,
            source_errors=source_errors or ["none: no live detail rows"],
            stale=True,
            stale_age_hours=stale_age,
        )

    if best_resolution.candidates:
        summary.canonical_topic = best_resolution.canonical_topic or summary.canonical_topic
        summary.aliases = best_resolution.aliases
        summary.resolver_candidates = best_resolution.candidates
    if not summary.canonical_topic and topic_text:
        summary.canonical_topic = topic_text if not best_resolution.unresolved else ""
    if stocks and not summary.canonical_topic:
        summary.canonical_topic = lookup_topic_used or topic_text

    if not stocks:
        stale_age = _cache_stale_age_hours(fallback_cache_path)
        leader_source = fallback_summary if fallback_summary is not None else summary
        stocks = _leader_fallback_stocks(leader_source, stale_age_hours=stale_age)
        if stocks:
            summary.fallback_used = True
            summary.stale = summary.stale or fallback_summary is not None
            summary.stale_age_hours = stale_age if fallback_summary is not None else summary.stale_age_hours
            _add_missing_fields(summary, ["live_stocks"])
        else:
            _add_missing_fields(summary, ["stocks", "leader_stocks"])

    trends = _load_history_trends(history_path)
    trend = (
        trends.get(summary.canonical_topic or "")
        or trends.get(topic_text, {})
        or trends.get(summary.name, {})
    )
    latest_score = _safe_float(trend.get("board_heat_latest_score"))
    summary.heat_score = round(latest_score if latest_score is not None else summary.heat_score, 4)
    summary.trend_score = _safe_float(trend.get("board_heat_trend_score"))
    summary.persistence_score = _safe_float(trend.get("board_heat_persistence_score"))
    summary.cooling_score = _safe_float(trend.get("board_heat_cooling_score"))
    summary.observations = int(_safe_float(trend.get("board_heat_observations")) or 0)
    summary.state = _safe_text(trend.get("board_heat_state"))
    summary.stage = classify_hotspot_stage(
        state=summary.state,
        trend_score=summary.trend_score,
        cooling_score=summary.cooling_score,
        persistence_score=summary.persistence_score,
        latest_score=summary.heat_score,
        observations=summary.observations,
    )
    if not summary.fallback_used or stocks:
        summary.sample_stock_count = len(stocks)
        _set_summary_leaders(summary, stocks)
    if not summary.provider_used:
        _apply_summary_metadata(
            summary,
            provider_used=provider_used,
            fallback_used=summary.fallback_used,
            source_errors=source_errors,
            stale=summary.stale,
            stale_age_hours=summary.stale_age_hours,
        )
    _finalize_summary_quality(summary, stock_count=len(stocks))

    timeline: list[TimelineEvent] = []
    if timeline_path:
        try:
            timeline = load_hotspot_timeline(timeline_path, topic=summary.canonical_topic or topic_text)
            if summary.canonical_topic and summary.canonical_topic != topic_text:
                timeline.extend(load_hotspot_timeline(timeline_path, topic=topic_text))
                timeline = _dedupe_timeline(timeline)
        except Exception as exc:  # noqa: BLE001 - timeline is evidence, not a hard dependency.
            summary.source_errors = _dedupe_errors([*summary.source_errors, f"timeline: {exc}"])
            _add_missing_fields(summary, ["timeline"])
            _finalize_summary_quality(summary, stock_count=len(stocks))
    capped_stocks = stocks[:max(int(top_stocks), 0)]
    route = build_hotspot_route(summary, timeline, capped_stocks)
    return HotspotDetail(summary=summary, stocks=capped_stocks, timeline=timeline, route=route)


def build_hotspot_route(
    summary: HotspotSummary,
    timeline: list[TimelineEvent] | None = None,
    stocks: list[HotspotStock] | None = None,
    *,
    max_items: int = 5,
    max_description_chars: int = 180,
) -> list[HotspotRouteItem]:
    """Build compact, display-ready route events without dropping raw timeline data."""
    events = timeline or []
    if events:
        return _build_route_from_timeline(
            events,
            max_items=max_items,
            max_description_chars=max_description_chars,
        )
    return [_build_summary_route_item(summary, stocks or [], max_description_chars=max_description_chars)]


def load_hotspot_history(path_like: str | Path) -> list[dict[str, Any]]:
    """Load hotspot history JSONL records, skipping malformed lines."""
    path = Path(path_like)
    if not path.is_file():
        raise FileNotFoundError(f"Hotspot history file not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        topic = _safe_text(item.get("topic") or item.get("board"))
        heat = _safe_float(_row_value(item, ["heat_score", "max_board_heat_score"]))
        generated_at = _safe_text(item.get("generated_at"))
        if not topic or heat is None or heat < 0 or heat > 100:
            continue
        item["topic"] = topic
        item["board"] = _safe_text(item.get("board")) or topic
        item["heat_score"] = heat
        item["max_board_heat_score"] = heat
        item["generated_at"] = generated_at
        rows.append(item)
    return sorted(rows, key=lambda item: (str(item.get("generated_at", "")), str(item.get("topic", ""))))


def append_hotspot_history(
    path_like: str | Path,
    hotspots: list[HotspotSummary | dict[str, Any]],
    *,
    generated_at: str,
) -> Path:
    """Append hotspot summaries to a trend-compatible JSONL history file."""
    path = Path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for hotspot in hotspots:
            item = asdict(hotspot) if isinstance(hotspot, HotspotSummary) else dict(hotspot)
            topic = _safe_text(item.get("topic") or item.get("name"))
            heat = _safe_float(item.get("heat_score"))
            if not topic or heat is None:
                continue
            record = {
                "generated_at": generated_at,
                "topic": topic,
                "board": topic,
                "source": _safe_text(item.get("source")),
                "rank": item.get("rank"),
                "change_pct": item.get("change_pct"),
                "heat_score": heat,
                "max_board_heat_score": heat,
                "sample_stock_count": int(_safe_float(item.get("sample_stock_count")) or 0),
                "leaders": item.get("leaders") if isinstance(item.get("leaders"), list) else [],
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def load_hotspot_timeline(path_like: str | Path, topic: str | None = None) -> list[TimelineEvent]:
    """Load timeline JSONL records, sorted by date, skipping malformed rows."""
    path = Path(path_like)
    if not path.is_file():
        raise FileNotFoundError(f"Hotspot timeline file not found: {path}")
    topic_text = _safe_text(topic)
    events: list[TimelineEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if topic_text and not _timeline_matches_topic(item, topic_text):
            continue
        date = _safe_text(item.get("date") or item.get("generated_at") or item.get("time"))
        source = _safe_text(item.get("source"))
        title = _safe_text(item.get("title"))
        if not date or not source or not title:
            continue
        events.append(TimelineEvent(
            date=date,
            source=source,
            title=title,
            event_type=_safe_text(item.get("event_type")) or "news",
            impact_score=round(_safe_float(item.get("impact_score")) or 0.0, 4),
            related_codes=_normalize_related_codes(item.get("related_codes")),
            description=_safe_text(item.get("description") or item.get("summary") or item.get("content")),
            url=_safe_text(item.get("url") or item.get("link")),
            published_at=_safe_text(item.get("published_at") or item.get("publish_time") or item.get("time")),
        ))
    return sorted(events, key=lambda item: (item.date, item.source, item.title))


def load_hotspots_json(path_like: str | Path) -> list[HotspotSummary]:
    """Load a last-good hotspot cache, skipping malformed rows."""
    path = Path(path_like)
    if not path.is_file():
        raise FileNotFoundError(f"Hotspot cache file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict) and any(key in payload for key in ("topic", "board", "hotspot")):
        raw_rows = [payload]
    elif isinstance(payload, dict):
        raw_rows = (
            payload.get("hotspots")
            or payload.get("rows")
            or payload.get("items")
            or payload.get("data")
            or []
        )
        if not raw_rows and all(isinstance(value, dict) for value in payload.values()):
            raw_rows = list(payload.values())
    else:
        raw_rows = payload
    if not isinstance(raw_rows, list):
        return []

    rows: list[HotspotSummary] = []
    for item in raw_rows:
        summary = _coerce_hotspot_summary(item)
        if summary is not None:
            rows.append(summary)
    return rows


def save_hotspots_json(path_like: str | Path, hotspots: list[HotspotSummary]) -> Path:
    path = Path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    rows = [asdict(item) for item in hotspots]
    payload = {
        "schema_version": 2,
        "generated_at": generated_at,
        "metadata": {
            "schema_version": 2,
            "asset_type": "hotspot_cache",
            "generated_at": generated_at,
            "row_count": len(rows),
            "last_good": True,
            "quality_counts": _quality_counts(hotspots),
        },
        "hotspots": rows,
    }
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return path


def hotspot_detail_to_dict(detail: HotspotDetail) -> dict[str, Any]:
    return {
        "summary": asdict(detail.summary),
        "stocks": [asdict(item) for item in detail.stocks],
        "timeline": [asdict(item) for item in detail.timeline],
        "route": [asdict(item) for item in detail.route],
    }


def _resolve_provider(provider: str | object) -> object | None:
    source_errors: list[str] = []
    for _, provider_obj in _resolve_provider_chain(provider, source_errors):
        if provider_obj is not None:
            return provider_obj
    return None


def _resolve_provider_chain(
    provider: str | object,
    source_errors: list[str],
) -> list[tuple[str, object | None]]:
    if not isinstance(provider, str):
        return [(_provider_label(provider), provider)]

    names = [part.strip().lower() for part in provider.split(",") if part.strip()]
    if not names:
        names = ["none"]

    resolved: list[tuple[str, object | None]] = []
    for name in names:
        if name in {"none", "off", "false"}:
            resolved.append(("none", None))
            continue
        if name == "akshare":
            try:
                import akshare as ak
            except Exception as exc:  # noqa: BLE001 - provider import is optional.
                source_errors.append(f"akshare: {exc}")
                continue
            resolved.append(("akshare", ak))
            continue
        source_errors.append(f"unknown provider '{name}'")
    return resolved


def _load_board_summaries(
    provider: object,
    *,
    max_boards: int,
    source_errors: list[str] | None = None,
    provider_label: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    specs = [
        ("concept", "stock_board_concept_name_em"),
        ("industry", "stock_board_industry_name_em"),
    ]
    limit = max(int(max_boards), 1)
    for source, method_name in specs:
        frame = _call_provider_frame(
            provider,
            method_name,
            source_errors=source_errors,
            provider_label=provider_label,
        )
        if frame is None:
            frame = _mapping_provider_frame(provider, f"{source}_boards")
        if frame is None:
            continue
        rows.extend(_normalize_board_rows(frame, source=source)[:limit])
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        topic = row["topic"]
        existing = deduped.get(topic)
        if existing is None or _board_row_rank_key(row) > _board_row_rank_key(existing):
            deduped[topic] = row
    return sorted(deduped.values(), key=_board_row_rank_key, reverse=True)


def _normalize_board_rows(frame: pd.DataFrame, *, source: str) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        topic = _safe_text(_row_value(row, [
            "topic",
            "board",
            "板块名称",
            "概念名称",
            "行业名称",
            "名称",
            "name",
        ]))
        if not topic:
            continue
        rank = _safe_float(_row_value(row, ["rank", "排名", "序号"]))
        if rank is None:
            rank = float(idx + 1)
        change_pct = _safe_float(_row_value(row, ["change_pct", "涨跌幅", "涨幅"]))
        heat_score = compute_hotspot_heat_score(change_pct, rank)
        rows.append({
            "topic": topic,
            "source": source,
            "rank": int(rank) if rank is not None else None,
            "change_pct": change_pct,
            "heat_score": heat_score,
        })
    return rows


def _find_board_summary(
    provider: object,
    topic: str,
    *,
    source_errors: list[str] | None = None,
    provider_label: str = "",
) -> dict[str, Any] | None:
    for row in _load_board_summaries(
        provider,
        max_boards=500,
        source_errors=source_errors,
        provider_label=provider_label,
    ):
        if row["topic"] == topic:
            return row
    return None


def _find_board_summary_in_rows(rows: list[dict[str, Any]], topic: str) -> dict[str, Any] | None:
    topic_key = _normalize_topic_key(topic)
    for row in rows:
        if _normalize_topic_key(row.get("topic")) == topic_key:
            return row
    return None


def _load_scored_constituents(
    provider: object,
    topic: str,
    *,
    source: str,
    source_errors: list[str] | None = None,
    provider_label: str = "",
) -> list[HotspotStock]:
    method_names = []
    if source == "industry":
        method_names.append("stock_board_industry_cons_em")
    else:
        method_names.append("stock_board_concept_cons_em")
        method_names.append("stock_board_industry_cons_em")
    frame = None
    for method_name in method_names:
        frame = _call_provider_frame(
            provider,
            method_name,
            source_errors=source_errors,
            provider_label=provider_label,
            symbol=topic,
        )
        if frame is not None:
            break
    if frame is None:
        frame = _mapping_constituents_frame(provider, topic, source=source)
    if frame is None:
        return []
    rows = [asdict(stock) for stock in _normalize_stock_rows(frame)]
    stocks = assign_stock_roles(rows)
    stock_source = f"{provider_label or 'provider'}.{source}_constituents"
    for stock in stocks:
        stock.source = stock.source or stock_source
        stock.source_confidence = stock.source_confidence if stock.source_confidence is not None else 1.0
        stock.fallback_used = False
    return stocks


def _normalize_stock_rows(frame: pd.DataFrame) -> list[HotspotStock]:
    if frame is None or frame.empty:
        return []
    stocks: list[HotspotStock] = []
    for _, row in frame.iterrows():
        code = _normalize_code(_row_value(row, ["code", "代码", "证券代码"]))
        if not code:
            continue
        change_pct = _safe_float(_row_value(row, ["change_pct", "涨跌幅", "涨幅"]))
        amount = _safe_float(_row_value(row, ["amount", "成交额", "成交金额"]))
        turnover_rate = _safe_float(_row_value(row, ["turnover_rate", "换手率"]))
        volume_ratio = _safe_float(_row_value(row, ["volume_ratio", "量比"]))
        net_inflow = _safe_float(_row_value(row, ["net_inflow", "主力净流入", "主力净流入-净额"]))
        stock = HotspotStock(
            code=code,
            name=_safe_text(_row_value(row, ["name", "名称", "股票名称"])),
            change_pct=change_pct,
            amount=amount,
            turnover_rate=turnover_rate,
            volume_ratio=volume_ratio,
            net_inflow=net_inflow,
            is_limit_up=_safe_bool(_row_value(row, ["is_limit_up", "涨停", "是否涨停"])) or (change_pct or 0) >= 9.8,
            active_days=int(_safe_float(_row_value(row, ["active_days", "连续活跃", "活跃天数"])) or 0),
            evidence_count=int(_safe_float(_row_value(row, ["evidence_count", "证据数", "线索数"])) or 0),
        )
        stock.hot_stock_score = score_hotspot_stock(asdict(stock))
        stocks.append(stock)
    return stocks


def _coerce_hotspot_stock(item: dict[str, Any] | HotspotStock) -> HotspotStock:
    if isinstance(item, HotspotStock):
        stock = item
    else:
        stock = HotspotStock(
            code=_normalize_code(_row_value(item, ["code", "代码"])),
            name=_safe_text(_row_value(item, ["name", "名称"])),
            change_pct=_safe_float(_row_value(item, ["change_pct", "涨跌幅"])),
            amount=_safe_float(_row_value(item, ["amount", "成交额"])),
            turnover_rate=_safe_float(_row_value(item, ["turnover_rate", "换手率"])),
            volume_ratio=_safe_float(_row_value(item, ["volume_ratio", "量比"])),
            net_inflow=_safe_float(_row_value(item, ["net_inflow", "主力净流入"])),
            is_limit_up=_safe_bool(_row_value(item, ["is_limit_up", "涨停"])),
            active_days=int(_safe_float(_row_value(item, ["active_days", "连续活跃"])) or 0),
            evidence_count=int(_safe_float(_row_value(item, ["evidence_count", "证据数"])) or 0),
            role=_safe_text(item.get("role")),
            hot_stock_score=_safe_float(item.get("hot_stock_score")) or 0.0,
            source=_safe_text(item.get("source")),
            source_confidence=_safe_float(item.get("source_confidence")),
            fallback_used=_safe_bool(item.get("fallback_used")),
        )
    if stock.hot_stock_score <= 0:
        stock.hot_stock_score = score_hotspot_stock(asdict(stock))
    return stock


def _coerce_hotspot_summary(item: object) -> HotspotSummary | None:
    if isinstance(item, HotspotSummary):
        return item
    if not isinstance(item, dict):
        return None
    topic = _safe_text(_row_value(item, ["topic", "name", "board", "hotspot"]))
    if not topic:
        return None
    heat_score = _safe_float(_row_value(item, ["heat_score", "max_board_heat_score"]))
    if heat_score is None:
        heat_score = 50.0
    if heat_score < 0 or heat_score > 100:
        return None
    rank = _safe_float(item.get("rank"))
    leaders = item.get("leaders")
    leader_stocks = item.get("leader_stocks")
    source_errors = item.get("source_errors")
    missing_fields = item.get("missing_fields")
    aliases = item.get("aliases")
    resolver_candidates = item.get("resolver_candidates")
    return HotspotSummary(
        topic=topic,
        name=_safe_text(item.get("name")) or topic,
        source=_safe_text(item.get("source")),
        rank=int(rank) if rank is not None else None,
        change_pct=_safe_float(item.get("change_pct")),
        heat_score=round(float(heat_score), 4),
        trend_score=_safe_float(item.get("trend_score")),
        persistence_score=_safe_float(item.get("persistence_score")),
        cooling_score=_safe_float(item.get("cooling_score")),
        observations=int(_safe_float(item.get("observations")) or 0),
        state=_safe_text(item.get("state")),
        stage=_safe_text(item.get("stage")) or "初次异动",
        sample_stock_count=int(_safe_float(item.get("sample_stock_count")) or 0),
        leaders=[_safe_text(value) for value in leaders if _safe_text(value)] if isinstance(leaders, list) else [],
        leader_stocks=[
            _coerce_hotspot_stock(value)
            for value in leader_stocks
            if isinstance(value, (dict, HotspotStock))
        ] if isinstance(leader_stocks, list) else [],
        quality_status=_safe_text(item.get("quality_status")) or "partial",
        missing_fields=[
            _safe_text(value)
            for value in missing_fields
            if _safe_text(value)
        ] if isinstance(missing_fields, list) else [],
        canonical_topic=_safe_text(item.get("canonical_topic")) or topic,
        aliases=[
            _safe_text(value)
            for value in aliases
            if _safe_text(value)
        ] if isinstance(aliases, list) else [],
        resolver_candidates=[
            value
            for value in resolver_candidates
            if isinstance(value, dict)
        ] if isinstance(resolver_candidates, list) else [],
        provider_used=_safe_text(item.get("provider_used")),
        fallback_used=_safe_bool(item.get("fallback_used")),
        source_errors=[
            _safe_text(value)
            for value in source_errors
            if _safe_text(value)
        ] if isinstance(source_errors, list) else [],
        stale=_safe_bool(item.get("stale")),
        stale_age_hours=_safe_float(item.get("stale_age_hours")),
    )


def _topic_candidates_from_hotspots(
    hotspots: list[HotspotSummary | dict[str, Any]],
    *,
    source: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in hotspots:
        summary = _coerce_hotspot_summary(item)
        if summary is None:
            continue
        aliases = _dedupe_texts([
            summary.topic,
            summary.name,
            summary.canonical_topic,
            *summary.aliases,
        ])
        candidates.append({
            "topic": summary.canonical_topic or summary.topic,
            "name": summary.name or summary.topic,
            "source": summary.source,
            "origin": source,
            "rank": summary.rank,
            "heat_score": summary.heat_score,
            "aliases": aliases,
        })
    return candidates


def _topic_candidates_from_board_rows(
    rows: list[dict[str, Any]],
    *,
    provider_label: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        topic = _safe_text(row.get("topic"))
        if not topic:
            continue
        candidates.append({
            "topic": topic,
            "name": topic,
            "source": _safe_text(row.get("source")),
            "origin": provider_label or "provider",
            "rank": row.get("rank"),
            "heat_score": _safe_float(row.get("heat_score")) or 0.0,
            "aliases": [topic],
        })
    return candidates


def _resolve_topic_from_candidates(
    topic: str,
    candidates: list[dict[str, Any]],
) -> HotspotTopicResolution:
    query = _safe_text(topic)
    ranked: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        candidate_topic = _safe_text(candidate.get("topic") or candidate.get("name"))
        if not candidate_topic:
            continue
        aliases = _dedupe_texts([
            candidate_topic,
            candidate.get("name"),
            *candidate.get("aliases", []),
        ])
        confidence, match_type = _topic_match_score(query, aliases)
        if confidence < 0.3:
            continue
        key = (_normalize_topic_key(candidate_topic), _safe_text(candidate.get("origin")))
        if key in seen:
            continue
        seen.add(key)
        ranked.append({
            "topic": candidate_topic,
            "name": _safe_text(candidate.get("name")) or candidate_topic,
            "source": _safe_text(candidate.get("source")),
            "origin": _safe_text(candidate.get("origin")),
            "rank": candidate.get("rank"),
            "heat_score": _safe_float(candidate.get("heat_score")) or 0.0,
            "aliases": aliases,
            "confidence": round(confidence, 4),
            "match_type": match_type,
        })

    ranked.sort(
        key=lambda item: (
            _safe_float(item.get("confidence")) or 0.0,
            _safe_float(item.get("heat_score")) or 0.0,
            -(_safe_float(item.get("rank")) or 999999.0),
            item.get("topic", ""),
        ),
        reverse=True,
    )
    top = ranked[0] if ranked else None
    confidence = _safe_float(top.get("confidence")) if top else 0.0
    canonical_topic = _safe_text(top.get("topic")) if top and confidence is not None and confidence >= 0.55 else ""
    aliases = _dedupe_texts([query, *(top.get("aliases", []) if top else [])])
    return HotspotTopicResolution(
        query=query,
        canonical_topic=canonical_topic,
        candidates=ranked[:5],
        aliases=aliases,
        confidence=round(confidence or 0.0, 4),
        unresolved=not bool(canonical_topic),
    )


def _topic_match_score(query: str, aliases: list[str]) -> tuple[float, str]:
    query_key = _normalize_topic_key(query)
    if not query_key:
        return 0.0, "empty"
    best = (0.0, "none")
    for alias in aliases:
        alias_key = _normalize_topic_key(alias)
        if not alias_key:
            continue
        if alias_key == query_key:
            return 1.0, "exact"
        if len(alias_key) >= 2 and alias_key in query_key:
            ratio = len(alias_key) / max(len(query_key), 1)
            best = max(best, (0.82 + min(ratio, 1.0) * 0.08, "alias_contains"), key=lambda item: item[0])
            continue
        if len(query_key) >= 2 and query_key in alias_key:
            ratio = len(query_key) / max(len(alias_key), 1)
            best = max(best, (0.78 + min(ratio, 1.0) * 0.1, "query_contains"), key=lambda item: item[0])
            continue
        query_chars = set(query_key)
        alias_chars = set(alias_key)
        overlap = len(query_chars & alias_chars) / max(len(query_chars | alias_chars), 1)
        if overlap >= 0.45:
            best = max(best, (0.42 + overlap * 0.28, "char_overlap"), key=lambda item: item[0])
    return best


def _normalize_topic_key(value: object) -> str:
    text = _safe_text(value).lower()
    text = text.replace("人工智能", "ai")
    for token in ("概念", "板块", "行业", "产业", "主题", "指数"):
        text = text.replace(token, "")
    return "".join(char for char in text if char.isalnum() or "\u4e00" <= char <= "\u9fff")


def _load_hotspot_cache_for_fallback(
    fallback_cache_path: str | Path | None,
    *,
    source_errors: list[str],
) -> list[HotspotSummary]:
    if not fallback_cache_path:
        return []
    try:
        return load_hotspots_json(fallback_cache_path)
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001 - fallback cache must not wipe live detail data.
        source_errors.append(f"last_good_cache: {exc}")
        return []


def _fallback_summary_for_resolution(
    topic: str,
    hotspots: list[HotspotSummary],
    resolution: HotspotTopicResolution,
) -> HotspotSummary | None:
    topic_key = _normalize_topic_key(topic)
    canonical_key = _normalize_topic_key(resolution.canonical_topic)
    for hotspot in hotspots:
        keys = {
            _normalize_topic_key(hotspot.topic),
            _normalize_topic_key(hotspot.name),
            _normalize_topic_key(hotspot.canonical_topic),
            *(_normalize_topic_key(alias) for alias in hotspot.aliases),
        }
        if topic_key in keys or (canonical_key and canonical_key in keys):
            return hotspot
    return None


def _copy_hotspot_summary(summary: HotspotSummary) -> HotspotSummary:
    copied = _coerce_hotspot_summary(asdict(summary))
    return copied if copied is not None else summary


def _copy_hotspot_stock(stock: HotspotStock) -> HotspotStock:
    return _coerce_hotspot_stock(asdict(stock))


def _leader_fallback_stocks(
    summary: HotspotSummary | None,
    *,
    stale_age_hours: float | None,
) -> list[HotspotStock]:
    if summary is None:
        return []
    stocks: list[HotspotStock] = []
    for stock in summary.leader_stocks:
        copied = _copy_hotspot_stock(stock)
        if not copied.code and not copied.name:
            continue
        copied.source = "last_good_cache.leader_stocks"
        copied.source_confidence = _stale_confidence(0.65, stale_age_hours)
        copied.fallback_used = True
        copied.role = copied.role or "核心龙头"
        stocks.append(copied)
    if stocks:
        return stocks

    for idx, leader in enumerate(summary.leaders[:3]):
        text = _safe_text(leader)
        if not text:
            continue
        stocks.append(HotspotStock(
            code="",
            name=text,
            role="核心龙头" if idx == 0 else "助攻",
            hot_stock_score=0.0,
            source="last_good_cache.leaders",
            source_confidence=_stale_confidence(0.45, stale_age_hours),
            fallback_used=True,
        ))
    return stocks


def _set_summary_leaders(summary: HotspotSummary, stocks: list[HotspotStock]) -> None:
    selected = [stock for stock in stocks if stock.role == "核心龙头"][:3]
    if not selected:
        selected = stocks[:3]
    summary.leader_stocks = [_copy_hotspot_stock(stock) for stock in selected]
    summary.leaders = [
        stock.name or stock.code
        for stock in summary.leader_stocks
        if stock.name or stock.code
    ]


def _add_missing_fields(summary: HotspotSummary, fields: list[str]) -> None:
    summary.missing_fields = _dedupe_texts([*summary.missing_fields, *fields])


def _finalize_summary_quality(summary: HotspotSummary, *, stock_count: int | None = None) -> None:
    if not summary.canonical_topic:
        _add_missing_fields(summary, ["canonical_topic"])
    if not summary.source:
        _add_missing_fields(summary, ["source"])
    count = summary.sample_stock_count if stock_count is None else stock_count
    if count <= 0 and not summary.leader_stocks:
        _add_missing_fields(summary, ["stocks"])
    summary.missing_fields = _dedupe_texts(summary.missing_fields)
    if summary.stale:
        summary.quality_status = "stale"
    elif "canonical_topic" in summary.missing_fields and not summary.resolver_candidates:
        summary.quality_status = "failed"
    elif summary.missing_fields:
        summary.quality_status = "partial"
    else:
        summary.quality_status = "available"


def _quality_counts(hotspots: list[HotspotSummary]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hotspot in hotspots:
        status = _safe_text(getattr(hotspot, "quality_status", "")) or "partial"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _stale_confidence(base: float, stale_age_hours: float | None) -> float:
    if stale_age_hours is None:
        return round(base, 4)
    if stale_age_hours <= 24:
        return round(base, 4)
    return round(max(base * 0.5, base - min(stale_age_hours / 240.0, 0.25)), 4)


def _dedupe_timeline(events: list[TimelineEvent]) -> list[TimelineEvent]:
    deduped: dict[tuple[str, str, str], TimelineEvent] = {}
    for event in events:
        deduped[(event.date, event.source, event.title)] = event
    return sorted(deduped.values(), key=lambda item: (item.date, item.source, item.title))


def _build_route_from_timeline(
    events: list[TimelineEvent],
    *,
    max_items: int,
    max_description_chars: int,
) -> list[HotspotRouteItem]:
    grouped: dict[str, list[TimelineEvent]] = {}
    for event in events:
        date = _event_day(event.date or event.published_at)
        grouped.setdefault(date, []).append(event)

    route: list[HotspotRouteItem] = []
    for date in sorted(grouped.keys(), reverse=True)[:max(int(max_items), 1)]:
        day_events = sorted(
            grouped[date],
            key=lambda item: (item.impact_score, item.published_at, item.source, item.title),
            reverse=True,
        )
        lead = day_events[0]
        texts = []
        for event in day_events[:3]:
            text = _safe_text(event.description) or _safe_text(event.title)
            if text:
                texts.append(text)
        description = _compact_text(" ".join(_dedupe_texts(texts)), max_description_chars)
        route.append(HotspotRouteItem(
            date=date,
            title=_route_title(lead),
            description=description,
            source=lead.source,
            event_type=lead.event_type,
            impact_score=round(max(event.impact_score for event in day_events), 4),
            related_codes=_dedupe_texts([
                code
                for event in day_events
                for code in event.related_codes
            ]),
            url=lead.url,
            published_at=lead.published_at,
        ))
    return route


def _build_summary_route_item(
    summary: HotspotSummary,
    stocks: list[HotspotStock],
    *,
    max_description_chars: int,
) -> HotspotRouteItem:
    leaders = summary.leaders or [stock.name for stock in stocks[:3] if stock.name]
    parts = [
        f"{summary.topic or summary.name} heat {summary.heat_score:.1f}",
        f"stage {summary.stage}" if summary.stage else "",
        "leaders " + ", ".join(leaders[:3]) if leaders else "",
    ]
    source = summary.provider_used or summary.source or "screening_hotspot"
    return HotspotRouteItem(
        date=_event_day(datetime.now(timezone.utc).isoformat()),
        title="Current fermentation",
        description=_compact_text("; ".join(_dedupe_texts(parts)), max_description_chars),
        source=source,
        event_type="summary",
        impact_score=round(_safe_float(summary.heat_score) or 0.0, 4),
        related_codes=[stock.code for stock in stocks[:3] if stock.code],
    )


def _route_title(event: TimelineEvent) -> str:
    event_type = _safe_text(event.event_type).lower()
    if event_type in {"announcement", "notice", "order", "policy", "fund_flow"}:
        return event.title[:60]
    return "News catalyst"


def _event_day(value: str) -> str:
    text = _safe_text(value)
    if len(text) >= 10:
        return text[:10]
    return text


def _compact_text(value: str, max_chars: int) -> str:
    text = " ".join(_safe_text(value).split())
    limit = max(int(max_chars), 20)
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def _dedupe_texts(values: list[object]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _safe_text(value)
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items


def _load_fallback_hotspots(
    fallback_cache_path: str | Path | None,
    *,
    source_errors: list[str],
    top: int,
) -> HotspotResults | None:
    if not fallback_cache_path:
        return None
    try:
        hotspots = load_hotspots_json(fallback_cache_path)
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 - malformed fallback cache should not crash live flow.
        source_errors.append(f"last_good_cache: {exc}")
        return None
    if not hotspots:
        return None
    stale_age = _cache_stale_age_hours(fallback_cache_path)
    return _with_result_metadata(
        hotspots[:max(int(top), 0)],
        provider_used="last_good_cache",
        fallback_used=True,
        source_errors=source_errors or ["none: no live hotspot rows"],
        stale=True,
        stale_age_hours=stale_age,
    )


def _find_fallback_hotspot(
    topic: str,
    fallback_cache_path: str | Path | None,
    *,
    source_errors: list[str],
) -> HotspotSummary | None:
    if not fallback_cache_path or not topic:
        return None
    hotspots = _load_hotspot_cache_for_fallback(fallback_cache_path, source_errors=source_errors)
    resolution = _resolve_topic_from_candidates(
        topic,
        _topic_candidates_from_hotspots(hotspots, source="cache"),
    )
    return _fallback_summary_for_resolution(topic, hotspots, resolution)


def _with_result_metadata(
    hotspots: list[HotspotSummary],
    *,
    provider_used: str,
    fallback_used: bool,
    source_errors: list[str],
    stale: bool,
    stale_age_hours: float | None,
) -> HotspotResults:
    errors = _dedupe_errors(source_errors)
    for hotspot in hotspots:
        _apply_summary_metadata(
            hotspot,
            provider_used=provider_used,
            fallback_used=fallback_used,
            source_errors=errors,
            stale=stale,
            stale_age_hours=stale_age_hours,
        )
        _finalize_summary_quality(hotspot, stock_count=hotspot.sample_stock_count)
    return HotspotResults(
        hotspots,
        provider_used=provider_used,
        fallback_used=fallback_used,
        source_errors=errors,
        stale=stale,
        stale_age_hours=stale_age_hours,
    )


def _apply_summary_metadata(
    summary: HotspotSummary,
    *,
    provider_used: str,
    fallback_used: bool,
    source_errors: list[str],
    stale: bool,
    stale_age_hours: float | None,
) -> None:
    summary.provider_used = provider_used
    summary.fallback_used = bool(summary.fallback_used or fallback_used)
    summary.source_errors = _dedupe_errors(source_errors)
    summary.stale = bool(summary.stale or stale)
    summary.stale_age_hours = summary.stale_age_hours if summary.stale_age_hours is not None else stale_age_hours


def _cache_stale_age_hours(path_like: str | Path | None) -> float | None:
    if not path_like:
        return None
    path = Path(path_like)
    if not path.exists():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - modified).total_seconds() / 3600.0
    return round(max(age_hours, 0.0), 4)


def _record_provider_error(
    source_errors: list[str] | None,
    provider_label: str,
    method_name: str,
    exc: Exception,
) -> None:
    if source_errors is None:
        return
    label = provider_label or "provider"
    source_errors.append(f"{label}.{method_name}: {exc}")


def _provider_label(provider: object) -> str:
    if isinstance(provider, dict):
        return "mapping"
    return provider.__class__.__name__


def _dedupe_errors(source_errors: list[str]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for value in source_errors:
        text = _safe_text(value)
        if text and text not in seen:
            seen.add(text)
            errors.append(text)
    return errors


def _load_history_trends(history_path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not history_path:
        return {}
    path = Path(history_path)
    if not path.is_file():
        return {}
    return load_board_heat_trends(path)


def _hotspot_sort_key(item: HotspotSummary) -> tuple[float, float, float, float, float]:
    trend = item.trend_score or 0.0
    persistence = item.persistence_score or 0.0
    cooling = item.cooling_score or 0.0
    score = item.heat_score + max(trend, 0.0) * 0.35 + persistence * 0.05 - cooling * 0.6
    change = item.change_pct if item.change_pct is not None else -999.0
    rank_bonus = -float(item.rank or 999999)
    return (score, item.heat_score, change, trend, rank_bonus)


def _hotspot_call_timeout_seconds() -> float | None:
    return parse_source_timeout_seconds(
        "SCREENING_SOURCE_CALL_TIMEOUT_SEC",
        default=_HOTSPOT_CALL_TIMEOUT_SECONDS,
    )


def _board_row_rank_key(item: dict[str, Any]) -> tuple[float, float, float]:
    heat = _safe_float(item.get("heat_score"))
    change = _safe_float(item.get("change_pct"))
    rank = _safe_float(item.get("rank"))
    rank_bonus = -float(rank if rank is not None else 999999.0)
    heat_value = heat if heat is not None else 0.0
    change_value = change if change is not None else -999.0
    return (heat_value, change_value, rank_bonus)


def _call_provider_frame(
    provider: object,
    method_name: str,
    *,
    source_errors: list[str] | None = None,
    provider_label: str = "",
    **kwargs: Any,
) -> pd.DataFrame | None:
    method = getattr(provider, method_name, None)
    if method is None:
        return None
    try:
        frame = call_with_timeout(
            method,
            timeout_sec=_hotspot_call_timeout_seconds(),
            label=f"hotspot source {provider_label or type(provider).__name__}.{method_name}",
            **kwargs,
        )
    except TypeError:
        try:
            frame = call_with_timeout(
                method,
                kwargs.get("symbol"),
                timeout_sec=_hotspot_call_timeout_seconds(),
                label=f"hotspot source {provider_label or type(provider).__name__}.{method_name}",
            )
        except Exception as exc:  # noqa: BLE001 - provider runtime instability is degraded.
            _record_provider_error(source_errors, provider_label, method_name, exc)
            return None
    except Exception as exc:  # noqa: BLE001 - provider runtime instability is degraded.
        _record_provider_error(source_errors, provider_label, method_name, exc)
        return None
    return frame if isinstance(frame, pd.DataFrame) else None


def _mapping_provider_frame(provider: object, key: str) -> pd.DataFrame | None:
    if not isinstance(provider, dict):
        return None
    frame = provider.get(key)
    if isinstance(frame, pd.DataFrame):
        return frame
    if isinstance(frame, list):
        return pd.DataFrame(frame)
    return None


def _mapping_constituents_frame(provider: object, topic: str, *, source: str) -> pd.DataFrame | None:
    if not isinstance(provider, dict):
        return None
    for key in (f"{source}_constituents", "constituents"):
        value = provider.get(key)
        if isinstance(value, dict):
            frame = value.get(topic)
            if isinstance(frame, pd.DataFrame):
                return frame
            if isinstance(frame, list):
                return pd.DataFrame(frame)
    return None


def _timeline_matches_topic(item: dict[str, Any], topic: str) -> bool:
    values: list[str] = []
    for key in ("topic", "hotspot", "board"):
        text = _safe_text(item.get(key))
        if text:
            values.append(text)
    raw_topics = item.get("topics")
    if isinstance(raw_topics, list):
        values.extend(_safe_text(value) for value in raw_topics if _safe_text(value))
    elif _safe_text(raw_topics):
        values.extend(part.strip() for part in _safe_text(raw_topics).replace("，", ",").split(",") if part.strip())
    if values:
        return topic in values
    return topic in _safe_text(item.get("title"))


def _normalize_related_codes(value: object) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = _safe_text(value).replace("，", ",").replace("、", ",").split(",")
    codes: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        code = _normalize_code(raw)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _row_value(row: dict[str, Any] | pd.Series, columns: list[str]) -> Any:
    for column in columns:
        if column in row:
            return row.get(column)
    return None


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_text(value).lower()
    return text in {"1", "true", "yes", "y", "是", "涨停", "limit_up"}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
