# -*- coding: utf-8 -*-
"""Pure mapping from screening results to the #1902 P0 factor contract.

Side-effect-free translation only: it never recomputes scores, never
reads the DataFrame, never touches the scorer, and never mutates its
inputs. Nothing calls these functions in P0; the mapping is exercised
by tests only, and P1 decides the single call site.

The factor inventory is spelled out statically below and guarded by
``test_factor_definitions_cover_all_scorer_factors``, which fails
when the scorer inventory changes — extending the inventory requires
a contract bump, not a silent drift.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timezone

from src.schemas.factor_contract import (
    FACTOR_SET_VERSION,
    CandidateFactorScore,
    CandidatePoolRun,
    FactorCategory,
    FactorDataQuality,
    FactorDefinition,
    FactorFieldStatus,
    FactorSnapshot,
    normalize_contract_timestamp,
)
from src.services.screening.models import Pick, ScreenResult


# (factor_id, name, category, definition, window, scorer column).
# Definitions summarise the matching ``_compute_*_score`` function in
# ``scorer.py``; ``window`` is the lookback the computation uses, or
# None when the score has no fixed lookback.
_FACTOR_DEFINITION_ROWS: tuple[
    tuple[str, str, FactorCategory, str, str | None, str], ...
] = (
    (
        "value",
        "Value",
        FactorCategory.VALUATION,
        "PE/PB cross-sectional rank score; lower valuation ranks higher, "
        "blended from a neutral 50 base.",
        None,
        "factor_value_score",
    ),
    (
        "liquidity",
        "Liquidity",
        FactorCategory.LIQUIDITY,
        "Log10 trading-amount cross-sectional rank score.",
        None,
        "factor_liquidity_score",
    ),
    (
        "momentum",
        "Momentum",
        FactorCategory.TECHNICAL,
        "Intraday change, 60-day trend, signal score and MACD status "
        "blended with chase and overheat penalties.",
        "60d",
        "factor_momentum_score",
    ),
    (
        "reversal",
        "Reversal",
        FactorCategory.TECHNICAL,
        "Mean-reversion score from intraday change distance to an ideal "
        "pullback, RSI status and 60-day change.",
        "60d",
        "factor_reversal_score",
    ),
    (
        "activity",
        "Activity",
        FactorCategory.TECHNICAL,
        "Trading-activity score from volume ratio and turnover rate "
        "distance to ideal levels.",
        None,
        "factor_activity_score",
    ),
    (
        "stability",
        "Stability",
        FactorCategory.TECHNICAL,
        "Penalty-based stability score from price change, turnover, "
        "volume, valuation, signal and 20-day risk measures.",
        "20d",
        "factor_stability_score",
    ),
    (
        "size",
        "Size",
        FactorCategory.LIQUIDITY,
        "Log10 total-market-value cross-sectional rank score.",
        None,
        "factor_size_score",
    ),
    (
        "theme_heat",
        "Theme Heat",
        FactorCategory.THEME,
        "Board/industry/concept heat score with trend, persistence and "
        "cooling adjustments.",
        None,
        "factor_theme_heat_score",
    ),
    (
        "topic_alignment",
        "Topic Alignment",
        FactorCategory.THEME,
        "Score of industry/concept label alignment with hotspot route "
        "summaries.",
        None,
        "factor_topic_alignment_score",
    ),
)

_KNOWN_FACTOR_IDS: frozenset[str] = frozenset(
    row[0] for row in _FACTOR_DEFINITION_ROWS
)


def factor_definitions(
    *,
    factor_set_version: str = FACTOR_SET_VERSION,
) -> list[FactorDefinition]:
    """Return the static factor definitions for one factor-set version."""
    return [
        FactorDefinition(
            factor_id=factor_id,  # type: ignore[arg-type]
            name=name,
            category=category,
            unit="score_0_100",
            definition=definition,
            source=f"screening.scorer:{column}",
            window=window,
            factor_set_version=factor_set_version,
        )
        for factor_id, name, category, definition, window, column in (
            _FACTOR_DEFINITION_ROWS
        )
    ]


def _is_ambiguous_local_time(value: datetime) -> bool:
    """Report whether a naive local wall time occurs twice (DST fold).

    The two folds resolve to different UTC instants; a naive string
    carries no fold, so the mapping cannot tell them apart. The same
    check also flags nonexistent gap times, which the platform maps
    by its default fold handling.
    """
    return value.replace(fold=0).astimezone(timezone.utc) != value.replace(
        fold=1
    ).astimezone(timezone.utc)


def _parse_run_timestamp(
    value: str, fallback: datetime
) -> tuple[datetime, bool, bool]:
    """Parse a ``ScreenResult.created_at`` ISO string to aware UTC.

    ``ScreenResult.created_at`` is an offset-aware local ISO string
    (``datetime.now().astimezone().isoformat()``); legacy naive
    values are read on the process-local clock — the same clock that
    produced them, with the deployment running ``TZ=Asia/Shanghai``
    — and converted to UTC; they are never just stamped ``Z``.
    Offset values are converted to UTC. Date-only strings parse to
    local midnight under the same rule. Unparseable values fall back
    to the mapping time instead of raising, so a malformed header
    never blocks the translation; the returned flags report whether
    the fallback was used and whether a naive value fell in a DST
    fold (mapped as the first occurrence), so callers can record
    either instead of failing silently.
    """
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return fallback, True, False
    ambiguous = parsed.tzinfo is None and _is_ambiguous_local_time(parsed)
    return normalize_contract_timestamp(parsed), False, ambiguous


def pick_to_factor_snapshot(
    pick: Pick,
    *,
    run_id: str,
    factor_set_version: str = FACTOR_SET_VERSION,
    effective_factor_weights: Mapping[str, float] | None = None,
    computed_at: datetime | None = None,
) -> FactorSnapshot:
    """Translate one ``Pick`` to a ``FactorSnapshot`` without mutation.

    Only entries present in ``pick.factor_scores`` become scores:
    absent factors are never synthesised as 0.0 or 50.0. Unknown
    factor ids are carried with a warning, never silently dropped.
    Non-finite values raise ``ValueError`` instead of entering the
    contract.
    """
    weights = effective_factor_weights if effective_factor_weights is not None else {}
    computed = (
        normalize_contract_timestamp(computed_at)
        if computed_at is not None
        else datetime.now(timezone.utc)
    )

    scores: dict[str, CandidateFactorScore] = {}
    unknown_ids: list[str] = []
    for factor_id, value in pick.factor_scores.items():
        if not math.isfinite(value):
            raise ValueError(
                f"non-finite factor score for {factor_id!r} "
                f"(code={pick.code!r}, run_id={run_id!r})"
            )
        if factor_id not in _KNOWN_FACTOR_IDS:
            unknown_ids.append(factor_id)
        scores[factor_id] = CandidateFactorScore(
            factor_id=factor_id,
            value=value,
            weight=weights.get(factor_id),
            computed_at=computed,
        )

    present_known = _KNOWN_FACTOR_IDS & scores.keys()
    absent_ids = sorted(_KNOWN_FACTOR_IDS - present_known)
    coverage = len(present_known) / len(_KNOWN_FACTOR_IDS)
    if not present_known:
        status = FactorFieldStatus.MISSING
    elif absent_ids:
        status = FactorFieldStatus.PARTIAL
    else:
        status = FactorFieldStatus.AVAILABLE

    notes: list[str] = []
    if absent_ids:
        notes.append(f"absent factors: {', '.join(absent_ids)}")
    if unknown_ids:
        notes.append(f"unknown factor keys carried: {', '.join(sorted(unknown_ids))}")

    quality = FactorDataQuality(
        coverage=coverage,
        missing_rate=1.0 - coverage,
        status=status,
        degradation_reason="; ".join(notes) if notes else None,
        warnings=notes,
    )

    return FactorSnapshot(
        candidate_pool_run_id=run_id,
        code=pick.code,
        name=pick.name,
        rank=pick.rank,
        factor_set_version=factor_set_version,
        scores=scores,
        screen_score=pick.screen_score,
        quality=quality,
        computed_at=computed,
    )


def screen_result_to_pool_run(
    result: ScreenResult,
    *,
    factor_set_version: str = FACTOR_SET_VERSION,
) -> CandidatePoolRun:
    """Translate a ``ScreenResult`` header to a ``CandidatePoolRun``.

    Header fields are copied verbatim, including explicit 0.0 weights
    (disabled is not missing). An unparseable ``created_at`` falls
    back to the mapping time and records a degradation entry, so the
    fallback is observable instead of silent.
    """
    created_at, fell_back, ambiguous = _parse_run_timestamp(
        result.created_at, datetime.now(timezone.utc)
    )
    degradation = list(result.degradation)
    if fell_back:
        degradation.append(
            f"unparseable created_at {result.created_at!r}: "
            "fell back to mapping time"
        )
    if ambiguous:
        degradation.append(
            f"ambiguous created_at {result.created_at!r}: DST fold, "
            "mapped as the first occurrence; run time may be one hour early"
        )
    return CandidatePoolRun(
        run_id=result.run_id,
        strategy=result.strategy,
        strategy_version=result.strategy_version,
        strategy_category=result.strategy_category,
        market=result.market,
        factor_set_version=factor_set_version,
        effective_factor_weights=dict(result.effective_factor_weights),
        candidate_count=len(result.picks),
        snapshot_count=result.snapshot_count,
        after_filter_count=result.after_filter_count,
        snapshot_source=result.snapshot_source,
        source_errors=list(result.source_errors),
        degradation=degradation,
        ranking_mode=result.ranking_mode,
        created_at=created_at,
    )


def screen_result_to_factor_snapshots(
    result: ScreenResult,
    *,
    factor_set_version: str = FACTOR_SET_VERSION,
) -> list[FactorSnapshot]:
    """Translate every pick of a run, sharing run id, weights and time."""
    computed, _, ambiguous = _parse_run_timestamp(
        result.created_at, datetime.now(timezone.utc)
    )
    snapshots = [
        pick_to_factor_snapshot(
            pick,
            run_id=result.run_id,
            factor_set_version=factor_set_version,
            effective_factor_weights=result.effective_factor_weights,
            computed_at=computed,
        )
        for pick in result.picks
    ]
    if ambiguous:
        # A naive created_at in a DST fold cannot be disambiguated
        # after the fact; record it on each snapshot instead of
        # silently stamping the first occurrence.
        for snapshot in snapshots:
            snapshot.quality.warnings.append(
                f"ambiguous created_at {result.created_at!r}: DST fold, "
                "mapped as the first occurrence; run time may be one hour early"
            )
    return snapshots
