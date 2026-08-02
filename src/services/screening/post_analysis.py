# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Optional L3 post-ranking analyzers.

DSA is one analyzer backend. The pipeline can also use local scorecards or an
external HTTP scoring tool without making DSA part of the core selection path.
"""

from __future__ import annotations

from dataclasses import asdict

import requests

from src.services.screening.config import Config
from src.services.screening.dsa import analyze_picks_with_dsa, apply_dsa_overlay
from src.services.screening.models import Pick
from src.services.screening.normalize import (
    normalize_code,
    safe_float as _safe_float,
    safe_string_list as _safe_string_list,
)


def _normalize_code(value: object) -> str:
    # Pick codes and analyzer response code fields are structured, so
    # US tickers may pass through (see normalize_code docstring).
    return normalize_code(value, allow_ticker=True)

SUPPORTED_POST_ANALYZERS = {"dsa", "scorecard", "external_http"}
_DEFAULT_SCORECARD_PROFILE = {
    "value_quality_value_min": 75.0,
    "value_quality_stability_min": 65.0,
    "value_quality_bonus": 2.4,
    "capital_confirmed_momentum_min": 72.0,
    "capital_confirmed_activity_min": 65.0,
    "capital_confirmed_bonus": 1.8,
    "controlled_reversal_min": 75.0,
    "controlled_reversal_bonus": 1.2,
    "hot_money_activity_min": 90.0,
    "hot_money_stability_max": 45.0,
    "hot_money_penalty": 2.5,
    "volume_spike_ratio": 5.0,
    "volume_spike_penalty": 1.2,
    "high_llm_confidence": 0.75,
    "high_llm_confidence_bonus": 0.8,
    "low_llm_confidence": 0.40,
    "low_llm_confidence_penalty": 1.0,
    "catalyst_bonus": 0.5,
    "catalyst_bonus_cap": 1.5,
    "llm_risk_penalty": 0.8,
    "llm_risk_penalty_cap": 2.4,
    "score_delta_cap": 8.0,
}


def normalize_post_analyzers(analyzers: list[str] | str | None) -> list[str]:
    """Normalize comma-separated/repeated analyzer names."""
    if analyzers is None:
        return []
    raw_items: list[str]
    if isinstance(analyzers, str):
        raw_items = [analyzers]
    else:
        raw_items = list(analyzers)

    result: list[str] = []
    seen = set()
    for raw in raw_items:
        for item in str(raw).split(","):
            name = item.strip().lower()
            if not name or name in seen:
                continue
            if name not in SUPPORTED_POST_ANALYZERS:
                raise ValueError(
                    f"Unknown post analyzer '{name}'. "
                    f"Supported: {', '.join(sorted(SUPPORTED_POST_ANALYZERS))}"
                )
            seen.add(name)
            result.append(name)
    return result


def run_post_analyzers(
    picks: list[Pick],
    *,
    analyzer_names: list[str],
    run_id: str,
    config: Config,
    max_picks: int | None = None,
    scorecard_profile: dict[str, object] | None = None,
) -> tuple[list[Pick], list[str]]:
    """Run selected post analyzers and re-rank by final_score.

    ``max_picks`` is an operational cap for remote analyzers. The local
    scorecard is deterministic and inexpensive, so it evaluates the complete
    shortlisted pool. This keeps final scores comparable for every candidate
    that may enter bounded near-score rotation without expanding remote DSA or
    external HTTP work.
    """
    if not picks or not analyzer_names:
        return picks, []

    degradation: list[str] = []
    result = picks

    for analyzer in analyzer_names:
        if analyzer == "dsa":
            max_count = max_picks or config.post_analysis_max_picks
            result, messages = _run_dsa_analyzer(result, run_id=run_id, config=config, max_picks=max_count)
        elif analyzer == "scorecard":
            result, messages = _run_scorecard_analyzer(
                result,
                max_picks=len(result),
                profile=scorecard_profile,
            )
        elif analyzer == "external_http":
            max_count = max_picks or config.post_analysis_max_picks
            result, messages = _run_external_http_analyzer(result, run_id=run_id, config=config, max_picks=max_count)
        else:
            messages = [f"Unknown post analyzer skipped: {analyzer}"]
        degradation.extend(messages)
        # Every analyzer consumes the output of the previous one. Re-rank here,
        # rather than only after the whole chain, so a later capped remote
        # analyzer receives the candidates promoted by an earlier full-pool
        # scorecard. Python's stable sort preserves the prior order on ties.
        result.sort(key=lambda item: item.final_score, reverse=True)
        for i, pick in enumerate(result, start=1):
            pick.rank = i
    return result, degradation


def _run_dsa_analyzer(
    picks: list[Pick],
    *,
    run_id: str,
    config: Config,
    max_picks: int,
) -> tuple[list[Pick], list[str]]:
    if not config.dsa_api_url:
        raise ValueError("post analyzer 'dsa' requested but DSA_API_URL is not configured")

    attempted_count = min(max(int(max_picks), 0), len(picks))
    attempted_pick_ids = {id(pick) for pick in picks[:attempted_count]}
    before_scores = {pick.code: float(pick.final_score) for pick in picks}
    analyzed, degradation = analyze_picks_with_dsa(
        picks,
        run_id=run_id,
        api_url=config.dsa_api_url,
        report_type=config.dsa_report_type,
        max_picks=max_picks,
        timeout_sec=config.dsa_timeout_sec,
        force_refresh=config.dsa_force_refresh,
        notify=config.dsa_notify,
    )
    analyzed = apply_dsa_overlay(analyzed)
    for pick in analyzed:
        if id(pick) not in attempted_pick_ids:
            # The overlay can re-rank candidates, so the post-overlay list
            # position cannot identify which candidates crossed the remote cap.
            _record_post_result(pick, "dsa", status="skipped", summary="", score_delta=0.0)
            continue

        status = pick.deep_analysis_status
        summary = pick.deep_analysis_summary
        delta = round(float(pick.final_score) - before_scores.get(pick.code, float(pick.final_score)), 4)
        _record_post_result(
            pick,
            "dsa",
            status=status,
            summary=summary,
            score_delta=delta,
            payload=pick.deep_analysis_result or {},
            risk_flags=pick.deep_analysis_risk_flags,
            tags=["dsa"] if status == "completed" else [],
        )

    return analyzed, degradation


def _run_scorecard_analyzer(
    picks: list[Pick],
    *,
    max_picks: int,
    profile: dict[str, object] | None = None,
) -> tuple[list[Pick], list[str]]:
    for idx, pick in enumerate(picks):
        if idx >= max_picks:
            # Candidates beyond max_picks are explicitly marked as 'skipped'
            # so selection_variant can reliably exclude them from rotation.
            _record_post_result(pick, "scorecard", status="skipped", summary="", score_delta=0.0)
            continue
        delta, flags, tags, summary = _scorecard_delta(pick, profile=profile)
        pick.final_score = round(float(pick.final_score) + delta, 4)
        pick.risk_flags = _unique([*pick.risk_flags, *flags])
        _record_post_result(
            pick,
            "scorecard",
            status="completed",
            summary=summary,
            score_delta=delta,
            payload={"risk_flags": flags, "tags": tags},
            risk_flags=flags,
            tags=tags,
        )
    return picks, []


def _run_external_http_analyzer(
    picks: list[Pick],
    *,
    run_id: str,
    config: Config,
    max_picks: int,
) -> tuple[list[Pick], list[str]]:
    if not config.post_analyzer_url:
        raise ValueError("post analyzer 'external_http' requested but POST_ANALYZER_URL is not configured")

    attempted_count = min(max(int(max_picks), 0), len(picks))
    attempted_picks = picks[:attempted_count]
    candidates = [asdict(pick) for pick in attempted_picks]
    response = requests.post(
        config.post_analyzer_url,
        json={"run_id": run_id, "candidates": candidates},
        timeout=config.post_analyzer_timeout_sec,
    )
    response.raise_for_status()
    body = response.json()
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        items = body.get("ranked", [])
    else:
        items = []
    if not isinstance(items, list):
        raise ValueError("external_http analyzer response must be a list or contain ranked=list")

    # Only accept results for candidates sent in this request. A remote service
    # must not be able to mutate scores or risk flags for candidates beyond the
    # configured operational cap by returning an extra or stale code.
    by_code = {_normalize_code(pick.code): pick for pick in attempted_picks}
    completed_codes: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(item.get("code", ""))
        pick = by_code.get(code)
        if pick is None or code in completed_codes:
            continue
        delta = _safe_float(item.get("score_delta"), 0.0)
        summary = str(item.get("summary", "")).strip()
        risk_flags = _safe_string_list(item.get("risk_flags"))
        tags = _safe_string_list(item.get("tags"))
        pick.final_score = round(float(pick.final_score) + delta, 4)
        pick.risk_flags = _unique([*pick.risk_flags, *risk_flags])
        _record_post_result(
            pick,
            "external_http",
            status="completed",
            summary=summary,
            score_delta=delta,
            payload=item,
            risk_flags=risk_flags,
            tags=tags,
        )

        completed_codes.add(code)

    # A submitted candidate omitted from a syntactically valid response was
    # attempted but not analyzed. Record that explicitly instead of leaving a
    # missing status that downstream consumers cannot distinguish from an
    # analyzer that never ran.
    for pick in attempted_picks:
        if _normalize_code(pick.code) not in completed_codes:
            _record_post_result(
                pick,
                "external_http",
                status="failed",
                summary="",
                score_delta=0.0,
            )

    for pick in picks[attempted_count:]:
        _record_post_result(pick, "external_http", status="skipped", summary="", score_delta=0.0)
    return picks, []


def _scorecard_delta(
    pick: Pick,
    *,
    profile: dict[str, object] | None = None,
) -> tuple[float, list[str], list[str], str]:
    profile = _scorecard_profile(profile)
    factors = pick.factor_scores or {}
    value = float(factors.get("value", 50))
    stability = float(factors.get("stability", 50))
    momentum = float(factors.get("momentum", 50))
    activity = float(factors.get("activity", 50))
    reversal = float(factors.get("reversal", 50))

    delta = 0.0
    flags: list[str] = []
    tags: list[str] = []

    if value >= profile["value_quality_value_min"] and stability >= profile["value_quality_stability_min"]:
        delta += profile["value_quality_bonus"]
        tags.append("value_quality")
    if momentum >= profile["capital_confirmed_momentum_min"] and activity >= profile["capital_confirmed_activity_min"]:
        delta += profile["capital_confirmed_bonus"]
        tags.append("capital_confirmed")
    if reversal >= profile["controlled_reversal_min"] and pick.change_pct < 0:
        delta += profile["controlled_reversal_bonus"]
        tags.append("controlled_reversal")
    if activity >= profile["hot_money_activity_min"] and stability < profile["hot_money_stability_max"]:
        delta -= profile["hot_money_penalty"]
        flags.append("hot_money_instability")
    if pick.volume_ratio is not None and pick.volume_ratio >= profile["volume_spike_ratio"]:
        delta -= profile["volume_spike_penalty"]
        flags.append("volume_spike")
    if pick.llm_confidence is not None:
        if pick.llm_confidence >= profile["high_llm_confidence"]:
            delta += profile["high_llm_confidence_bonus"]
        elif pick.llm_confidence < profile["low_llm_confidence"]:
            delta -= profile["low_llm_confidence_penalty"]
            flags.append("low_llm_confidence")
    if pick.llm_catalysts:
        delta += min(len(pick.llm_catalysts) * profile["catalyst_bonus"], profile["catalyst_bonus_cap"])
    if pick.llm_risks:
        delta -= min(len(pick.llm_risks) * profile["llm_risk_penalty"], profile["llm_risk_penalty_cap"])
        flags.extend(pick.llm_risks)

    cap = max(float(profile["score_delta_cap"]), 0.0)
    delta = round(max(min(delta, cap), -cap), 4)
    summary = "本地后置评分: " + (
        "、".join(tags) if tags else "未发现额外加分项"
    )
    if flags:
        summary += f"；风险: {'、'.join(flags[:3])}"
    return delta, _unique(flags), _unique(tags), summary


def _scorecard_profile(profile: dict[str, object] | None) -> dict[str, float]:
    result = dict(_DEFAULT_SCORECARD_PROFILE)
    for key, value in (profile or {}).items():
        if key in result:
            result[key] = float(value)
    return result


def _record_post_result(
    pick: Pick,
    analyzer: str,
    *,
    status: str,
    summary: str,
    score_delta: float,
    payload: dict | None = None,
    risk_flags: list[str] | None = None,
    tags: list[str] | None = None,
) -> None:
    pick.post_analysis_status[analyzer] = status
    pick.post_analysis_summaries[analyzer] = summary
    pick.post_analysis_score_deltas[analyzer] = round(float(score_delta), 4)
    if payload is not None:
        pick.post_analysis_results[analyzer] = payload
    if risk_flags:
        pick.risk_flags = _unique([*pick.risk_flags, *risk_flags])
    if tags:
        pick.post_analysis_tags = _unique([*pick.post_analysis_tags, *tags])


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = str(item).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result
