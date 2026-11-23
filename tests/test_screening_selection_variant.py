"""Tests for bounded per-client screening result rotation."""

from __future__ import annotations

import copy

from src.services.screening.models import Pick
from src.services.screening.selection_variant import apply_seeded_selection_variant


def _picks() -> list[Pick]:
    scores = [90.0, 86.0, 84.0, 83.7, 83.3, 82.0, 80.0]
    return [
        Pick(
            rank=index,
            code=f"00000{index}",
            name=f"Stock {index}",
            screen_score=score,
            final_score=score,
            risk_flags=["kept-risk"] if index == 4 else [],
        )
        for index, score in enumerate(scores, start=1)
    ]


def test_selection_variant_without_seed_preserves_top_n() -> None:
    result = apply_seeded_selection_variant(
        _picks(),
        max_output=3,
        seed="",
        period="2026-08-01",
    )

    assert [pick.code for pick in result.picks] == ["000001", "000002", "000003"]
    assert result.applied is False


def test_selection_variant_without_seed_preserves_top_n_with_tie() -> None:
    """When the cutoff sits on a tie, legacy callers without a seed must get
    the original top-N slice (no code-based tie-breaker applied).
    """
    picks = [
        Pick(rank=1, code="A", name="A", screen_score=90.0, final_score=90.0),
        Pick(rank=2, code="B", name="B", screen_score=88.0, final_score=88.0),
        Pick(rank=3, code="C", name="C", screen_score=85.0, final_score=85.0),
        # Tie at cutoff between C and D — legacy behavior should keep C
        Pick(rank=4, code="D", name="D", screen_score=85.0, final_score=85.0),
        Pick(rank=5, code="E", name="E", screen_score=80.0, final_score=80.0),
    ]

    result = apply_seeded_selection_variant(
        picks,
        max_output=3,
        seed="",
        period="2026-08-01",
    )

    assert [pick.code for pick in result.picks] == ["A", "B", "C"]
    assert result.applied is False


def test_selection_variant_is_stable_for_same_seed_and_period() -> None:
    first = apply_seeded_selection_variant(
        copy.deepcopy(_picks()),
        max_output=3,
        seed="browser-a",
        period="2026-08-01",
    )
    second = apply_seeded_selection_variant(
        copy.deepcopy(_picks()),
        max_output=3,
        seed="browser-a",
        period="2026-08-01",
    )

    assert [pick.code for pick in first.picks] == [pick.code for pick in second.picks]
    assert [pick.rank for pick in first.picks] == [1, 2, 3]


def test_selection_variant_produces_multiple_bounded_client_variants() -> None:
    variants = {
        tuple(
            pick.code
            for pick in apply_seeded_selection_variant(
                copy.deepcopy(_picks()),
                max_output=3,
                seed=f"browser-{index}",
                period="2026-08-01",
            ).picks
        )
        for index in range(20)
    }

    assert len(variants) >= 2
    assert all(len(codes) == 3 for codes in variants)
    assert all(set(codes) <= {"000001", "000002", "000003", "000004", "000005"} for codes in variants)
    assert any("000003" not in codes for codes in variants)


def test_selection_variant_keeps_leading_picks_when_top_scores_are_close() -> None:
    close_picks = _picks()
    close_scores = [84.5, 84.4, 84.3, 84.2, 84.1, 80.0, 79.0]
    for pick, score in zip(close_picks, close_scores):
        pick.final_score = score
        pick.screen_score = score
    variants = [
        apply_seeded_selection_variant(
            copy.deepcopy(close_picks),
            max_output=3,
            seed="browser-a",
            period=f"2026-08-01:run-{index}",
        )
        for index in range(30)
    ]

    assert all([pick.code for pick in result.picks][:2] == ["000001", "000002"] for result in variants)
    assert len({tuple(pick.code for pick in result.picks) for result in variants}) >= 2
    assert all(
        all(pick.final_score >= 82.8 for pick in result.picks)
        for result in variants
    )


def test_selection_variant_zero_rotation_ratio_disables_rotation() -> None:
    result = apply_seeded_selection_variant(
        _picks(),
        max_output=3,
        seed="browser-a",
        period="2026-08-01",
        rotation_ratio=0.0,
    )

    assert [pick.code for pick in result.picks] == ["000001", "000002", "000003"]
    assert result.applied is False


def test_selection_variant_preserves_incoming_tie_order_for_seeded_runs() -> None:
    picks = [
        Pick(rank=1, code="B", name="B", screen_score=90.0, final_score=90.0),
        Pick(rank=2, code="C", name="C", screen_score=85.0, final_score=85.0),
        Pick(rank=3, code="D", name="D", screen_score=85.0, final_score=85.0),
        Pick(rank=4, code="A", name="A", screen_score=85.0, final_score=85.0),
    ]

    disabled = apply_seeded_selection_variant(
        copy.deepcopy(picks),
        max_output=3,
        seed="browser-a",
        period="2026-08-01",
        rotation_ratio=0.0,
    )
    variants = [
        apply_seeded_selection_variant(
            copy.deepcopy(picks),
            max_output=3,
            seed=f"browser-{index}",
            period="2026-08-01",
        )
        for index in range(20)
    ]

    assert [pick.code for pick in disabled.picks] == ["B", "C", "D"]
    assert disabled.applied is False
    assert all([pick.code for pick in result.picks][:2] == ["B", "C"] for result in variants)
    assert all("A" not in [pick.code for pick in result.picks][:2] for result in variants)


def test_selection_variant_protects_materially_superior_candidates() -> None:
    variants = [
        apply_seeded_selection_variant(
            copy.deepcopy(_picks()),
            max_output=3,
            seed="browser-a",
            period=f"2026-08-01:run-{index}",
        )
        for index in range(20)
    ]

    assert all([pick.code for pick in result.picks][:2] == ["000001", "000002"] for result in variants)


def test_selection_variant_keeps_scores_and_risk_metadata_unchanged() -> None:
    picks = _picks()
    original = {
        pick.code: (pick.final_score, list(pick.risk_flags))
        for pick in picks
    }

    result = apply_seeded_selection_variant(
        picks,
        max_output=5,
        seed="browser-risk-check",
        period="2026-08-01",
    )

    assert result.pool_size >= result.rotated_slots
    for pick in result.picks:
        assert (pick.final_score, pick.risk_flags) == original[pick.code]


def test_selection_variant_never_promotes_skipped_post_analysis() -> None:
    """Regression: rotation must not promote picks whose post_analysis status is 'skipped'."""
    picks = _picks()
    # Simulate post-analysis: first 3 completed, ranks 4-5 skipped
    for i, pick in enumerate(picks, start=1):
        if i <= 3:
            pick.post_analysis_status = {"scorecard": "completed"}
        elif i in (4, 5):
            pick.post_analysis_status = {"scorecard": "skipped"}
        else:
            pick.post_analysis_status = {}

    result = apply_seeded_selection_variant(
        picks,
        max_output=3,
        seed="browser-variation",
        period="2026-08-01",
        analyzer_names=["scorecard"],
    )

    # Ensure none of the final picks have 'skipped' for scorecard
    for pick in result.picks:
        assert pick.post_analysis_status.get("scorecard") != "skipped"


def test_selection_variant_excludes_unanalyzed_from_rotation() -> None:
    """Regression: candidates without explicit completed post-analysis must not
    be eligible for near-cutoff rotation when analyzers are configured.
    """
    picks = _picks()
    # Simulate post-analysis: first 3 completed, ranks 4-5 not requested (or missing)
    for i, pick in enumerate(picks, start=1):
        if i <= 3:
            pick.post_analysis_status = {"scorecard": "completed"}
        elif i in (4, 5):
            # Either missing entry or explicit not_requested should exclude them
            pick.post_analysis_status = {"scorecard": "not_requested"}
        else:
            pick.post_analysis_status = {}

    result = apply_seeded_selection_variant(
        picks,
        max_output=3,
        seed="browser-variation",
        period="2026-08-01",
        analyzer_names=["scorecard"],
    )

    # Since only first three completed the analyzer, rotation must not promote
    # unanalyzed candidates into the Top-3 — result should remain the original Top-3
    assert [pick.code for pick in result.picks] == ["000001", "000002", "000003"]
