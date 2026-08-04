# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Bounded near-score sampling for per-run screening variants."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from src.services.screening.models import Pick


@dataclass(frozen=True)
class SelectionVariant:
    picks: list[Pick]
    applied: bool = False
    pool_size: int = 0
    rotated_slots: int = 0


def apply_seeded_selection_variant(
    picks: list[Pick],
    *,
    max_output: int,
    seed: str,
    period: str,
    max_score_gap: float = 1.5,
    rotation_ratio: float = 1.0,
    analyzer_names: list[str] | None = None,
) -> SelectionVariant:
    """Sample output slots among candidates with comparable final scores.

    The leading half of the original Top-N and candidates that materially
    outperform the cutoff remain protected. The opaque client seed only affects
    the remaining near-score tail; hard filters, risk vetoes, score values, and
    portfolio penalties are never changed.

    Compatibility note: when the client does not provide a seed (empty string
    or None), preserve the original pick ordering and return a strict Top-N
    slice. This avoids silently applying the new code-based tie-breaker for
    legacy callers that expect previous stable ordering.
    """
    normalized_seed = str(seed or "").strip()

    # Respect the original ordering when no seed is provided. This preserves
    # backward compatibility for legacy clients that did not opt into rotation.
    output_count = min(max(int(max_output), 0), len(picks))
    if output_count == 0:
        return SelectionVariant(picks=[])
    if not normalized_seed or output_count < 2 or len(picks) <= output_count:
        # Preserve original order; just trim to requested output_count.
        return SelectionVariant(picks=_rerank(picks[:output_count]))

    # The upstream pipeline has already produced the authoritative final order.
    # Keep that order as the basis for the protected head and cutoff. In
    # particular, a code-based tie-break here would silently move equal-score
    # candidates across the original Top-N boundary before rotation starts.
    ordered = list(picks)
    output_count = min(max(int(max_output), 0), len(ordered))

    cutoff_score = float(ordered[output_count - 1].final_score)
    score_gap = max(float(max_score_gap), 0.0)
    minimum_score = cutoff_score - score_gap
    # Protect candidates whose lead over the original Top-N cutoff is larger
    # than the full allowed sampling gap.
    quality_protected = [
        pick
        for pick in ordered[:output_count]
        if float(pick.final_score) > cutoff_score + score_gap
    ]
    remaining_slots = output_count - len(quality_protected)
    requested_ratio = max(float(rotation_ratio), 0.0)
    if requested_ratio == 0.0:
        return SelectionVariant(picks=_rerank(ordered[:output_count]))
    # Rotation is a tail-only operation. Even when callers request ratio=1,
    # reserve the leading half of the original Top-N by limiting rotatable
    # positions to floor(N/2). This keeps rank 1 (and rank 2 for Top-3) stable.
    max_tail_slots = max(1, output_count // 2)
    rotation_slots = min(
        remaining_slots,
        max_tail_slots,
        max(1, int(round(output_count * requested_ratio))),
    )

    def _was_post_analyzed(pick: Pick) -> bool:
        # If analyzers were configured for this run, a pick must have explicit
        # non-skipped post-analysis results for all configured analyzers to be
        # eligible for near-cutoff rotation. This prevents promoting candidates
        # that never received the same L3 treatment as protected top picks.
        status_map = pick.post_analysis_status or {}
        if not analyzer_names:
            # No analyzers configured — fall back to legacy behavior: only
            # exclude picks explicitly marked as 'skipped'.
            return not any(status == "skipped" for status in status_map.values())

        # If analyzers were configured, require each configured analyzer to have
        # an explicit completed status recorded for this pick. Missing entries or
        # explicit 'not_requested' indicate the candidate did not receive the
        # same L3 treatment and must be excluded from near-cutoff rotation. This
        # prevents promoting candidates that never completed post-analysis.
        for analyzer in analyzer_names:
            s = status_map.get(analyzer)
            # Only allow picks that explicitly completed the analyzer run.
            if s != "completed":
                return False
        return True

    position_protected_count = remaining_slots - rotation_slots
    quality_protected_codes = {pick.code for pick in quality_protected}
    unprotected = [pick for pick in ordered if pick.code not in quality_protected_codes]
    position_protected = unprotected[:position_protected_count]
    position_protected_codes = {pick.code for pick in position_protected}
    protected = [*quality_protected, *position_protected]
    pool = [
        pick
        for pick in ordered
        if pick.code not in quality_protected_codes
        and pick.code not in position_protected_codes
        if float(pick.final_score) >= minimum_score
        and _was_post_analyzed(pick)
    ]
    if len(pool) <= rotation_slots:
        return SelectionVariant(
            picks=_rerank(ordered[:output_count]),
            pool_size=len(pool),
        )

    varied_pool = sorted(
        pool,
        key=lambda pick: _variant_key(
            normalized_seed,
            period,
            pick.code,
        ),
    )
    chosen_codes = {pick.code for pick in varied_pool[:rotation_slots]}
    chosen_tail = [pick for pick in pool if pick.code in chosen_codes]
    selected_code_set = {
        pick.code
        for pick in [*protected, *chosen_tail]
    }
    # Rotation changes membership only. Preserve the upstream relative order
    # for every selected candidate, including equal-score candidates.
    selected = [
        pick
        for pick in ordered
        if pick.code in selected_code_set
    ][:output_count]
    base_codes = [pick.code for pick in ordered[:output_count]]
    selected_codes = [pick.code for pick in selected]
    changed_count = len(set(selected_codes) - set(base_codes))
    return SelectionVariant(
        picks=_rerank(selected),
        applied=changed_count > 0,
        pool_size=len(pool),
        rotated_slots=changed_count,
    )


def _variant_key(seed: str, period: str, code: str) -> bytes:
    return hashlib.sha256(f"{seed}\0{period}\0{code}".encode("utf-8")).digest()


def _rerank(picks: list[Pick]) -> list[Pick]:
    for index, pick in enumerate(picks, start=1):
        pick.rank = index
    return picks
