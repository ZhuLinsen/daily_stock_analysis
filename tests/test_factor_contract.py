# -*- coding: utf-8 -*-
"""Tests for the Issue #1902 P0 DSA internal factor contract."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.factor_contract import (
    FACTOR_CONTRACT_VERSION,
    FACTOR_SET_VERSION,
    CandidateFactorScore,
    CandidatePoolRun,
    FactorCategory,
    FactorDataQuality,
    FactorDefinition,
    FactorFieldStatus,
    FactorSnapshot,
)
from src.services.screening.factor_mapping import (
    factor_definitions,
    pick_to_factor_snapshot,
    screen_result_to_factor_snapshots,
    screen_result_to_pool_run,
)
from src.services.screening.models import Pick, ScreenResult
from src.services.screening.scorer import factor_score_columns


def _pick(**overrides: object) -> Pick:
    kwargs: dict[str, object] = {
        "rank": 1,
        "code": "600519",
        "name": "贵州茅台",
        "final_score": 72.5,
        "screen_score": 72.5,
    }
    kwargs.update(overrides)
    return Pick(**kwargs)  # type: ignore[arg-type]


def _screen_result(**overrides: object) -> ScreenResult:
    kwargs: dict[str, object] = {
        "strategy": "balanced_alpha",
        "market": "cn",
        # Real runs always carry the 12-hex run_id from pipeline.screen().
        "run_id": "a1b2c3d4e5f6",
    }
    kwargs.update(overrides)
    return ScreenResult(**kwargs)  # type: ignore[arg-type]


@pytest.mark.unit
def test_factor_definitions_cover_all_scorer_factors() -> None:
    definitions = factor_definitions()
    columns = factor_score_columns()

    assert {d.factor_id for d in definitions} == set(columns)
    assert len(definitions) == 9

    for definition in definitions:
        assert definition.definition
        assert definition.source == f"screening.scorer:{columns[definition.factor_id]}"
        assert definition.unit == "score_0_100"
        assert definition.factor_set_version == FACTOR_SET_VERSION
        assert definition.params == {}


@pytest.mark.unit
def test_snapshot_defaults_and_json_serialization_are_stable() -> None:
    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        name="贵州茅台",
        computed_at=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
    )

    dumped = snapshot.model_dump(mode="json")
    json.dumps(dumped, ensure_ascii=False)

    assert dumped["contract_version"] == FACTOR_CONTRACT_VERSION
    assert dumped["factor_set_version"] == FACTOR_SET_VERSION
    assert dumped["scores"] == {}
    assert dumped["screen_score"] is None
    assert dumped["rank"] is None
    assert dumped["source"] == "screening.pipeline"
    assert dumped["computed_at"] == "2026-11-14T09:30:00Z"
    assert dumped["quality"]["status"] == "available"
    assert dumped["quality"]["coverage"] is None
    assert dumped["quality"]["missing_rate"] is None


@pytest.mark.unit
def test_contract_version_literal_rejects_other_versions() -> None:
    with pytest.raises(ValidationError):
        FactorSnapshot(
            candidate_pool_run_id="a1b2c3d4e5f6",
            code="600519",
            contract_version="2.0",
        )

    with pytest.raises(ValidationError):
        CandidatePoolRun(
            run_id="a1b2c3d4e5f6",
            strategy="balanced_alpha",
            market="cn",
            contract_version="2.0",
        )

    snapshot = FactorSnapshot(candidate_pool_run_id="a1b2c3d4e5f6", code="600519")
    with pytest.raises(ValidationError):
        snapshot.contract_version = "2.0"
    with pytest.raises(ValidationError):
        snapshot.model_copy(update={"contract_version": "2.0"})

    pool_run = CandidatePoolRun(
        run_id="a1b2c3d4e5f6", strategy="balanced_alpha", market="cn"
    )
    with pytest.raises(ValidationError):
        pool_run.model_copy(update={"contract_version": "2.0"})

    copied = snapshot.model_copy(update={"name": "贵州茅台"})
    assert copied.contract_version == FACTOR_CONTRACT_VERSION
    assert copied.name == "贵州茅台"


@pytest.mark.unit
def test_candidate_factor_score_rejects_out_of_range_and_non_finite() -> None:
    for bad_value in (-1.0, 100.01, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            CandidateFactorScore(factor_id="value", value=bad_value)

    assert CandidateFactorScore(factor_id="value", value=0.0).value == 0.0
    assert CandidateFactorScore(factor_id="value", value=100.0).value == 100.0


@pytest.mark.unit
def test_pick_mapping_preserves_scores_weights_and_absent_factors() -> None:
    pick = _pick(
        factor_scores={
            "value": 80.5,
            "liquidity": 62.25,
            "momentum": 55.0,
            "reversal": 48.125,
            "activity": 71.0,
        }
    )

    snapshot = pick_to_factor_snapshot(
        pick,
        run_id="a1b2c3d4e5f6",
        effective_factor_weights={"value": 0.4, "liquidity": 0.0, "momentum": 0.2},
        computed_at=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
    )

    assert set(snapshot.scores) == {
        "value",
        "liquidity",
        "momentum",
        "reversal",
        "activity",
    }
    assert snapshot.scores["value"].value == 80.5
    assert snapshot.scores["value"].weight == 0.4
    assert snapshot.scores["liquidity"].weight == 0.0
    assert snapshot.scores["reversal"].weight is None
    assert snapshot.scores["activity"].weight is None
    assert snapshot.screen_score == 72.5
    assert snapshot.rank == 1
    assert snapshot.candidate_pool_run_id == "a1b2c3d4e5f6"
    assert snapshot.code == "600519"
    assert snapshot.quality.coverage == 5 / 9
    assert snapshot.quality.missing_rate == 1 - 5 / 9
    assert snapshot.quality.status == FactorFieldStatus.PARTIAL
    assert snapshot.quality.degradation_reason is not None
    for absent_id in ("size", "stability", "theme_heat", "topic_alignment"):
        assert absent_id in snapshot.quality.degradation_reason
    # Per-factor coverage is unknown at Pick level: never fabricated.
    assert snapshot.scores["value"].quality.coverage is None
    assert snapshot.scores["value"].quality.missing_rate is None


@pytest.mark.unit
def test_pick_mapping_does_not_mutate_pick() -> None:
    pick = _pick(factor_scores={"value": 80.5, "liquidity": 62.25})
    before = copy.deepcopy(pick)

    pick_to_factor_snapshot(pick, run_id="a1b2c3d4e5f6")

    assert pick == before


@pytest.mark.unit
def test_pick_mapping_empty_factor_scores_is_missing_not_zero() -> None:
    pick = _pick(factor_scores={})

    snapshot = pick_to_factor_snapshot(pick, run_id="a1b2c3d4e5f6")

    assert snapshot.scores == {}
    assert snapshot.quality.status == FactorFieldStatus.MISSING
    assert snapshot.quality.coverage == 0.0
    assert snapshot.quality.missing_rate == 1.0


@pytest.mark.unit
def test_pick_mapping_rejects_non_finite_factor_value() -> None:
    for bad_value in (float("nan"), float("inf")):
        pick = _pick(factor_scores={"value": bad_value})
        with pytest.raises(ValueError, match="non-finite"):
            pick_to_factor_snapshot(pick, run_id="a1b2c3d4e5f6")


@pytest.mark.unit
def test_pool_run_copies_screen_result_header_verbatim() -> None:
    result = _screen_result(
        strategy_version="1.1",
        strategy_category="framework",
        effective_factor_weights={"value": 0.4, "liquidity": 0.0, "momentum": 0.6},
        snapshot_count=5000,
        after_filter_count=120,
        picks=[_pick(), _pick(rank=2, code="000001", name="平安银行")],
        run_id="a1b2c3d4e5f6",
        ranking_mode="llm",
        degradation=["daily enrichment failed"],
        snapshot_source="akshare",
        source_errors=["provider timeout"],
        created_at="2026-11-14T09:30:00",
    )

    pool_run = screen_result_to_pool_run(result)

    assert pool_run.run_id == "a1b2c3d4e5f6"
    assert pool_run.strategy == "balanced_alpha"
    assert pool_run.strategy_version == "1.1"
    assert pool_run.strategy_category == "framework"
    assert pool_run.market == "cn"
    assert pool_run.effective_factor_weights == {
        "value": 0.4,
        "liquidity": 0.0,
        "momentum": 0.6,
    }
    assert pool_run.candidate_count == 2
    assert pool_run.snapshot_count == 5000
    assert pool_run.after_filter_count == 120
    assert pool_run.snapshot_source == "akshare"
    assert pool_run.source_errors == ["provider timeout"]
    assert pool_run.degradation == ["daily enrichment failed"]
    assert pool_run.ranking_mode == "llm"
    assert pool_run.contract_version == FACTOR_CONTRACT_VERSION
    assert pool_run.factor_set_version == FACTOR_SET_VERSION
    assert pool_run.created_at == datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc)


@pytest.mark.unit
def test_factor_set_version_bump_guard() -> None:
    assert isinstance(FACTOR_SET_VERSION, str)
    assert FACTOR_SET_VERSION

    for definition in factor_definitions():
        assert definition.factor_set_version == FACTOR_SET_VERSION


@pytest.mark.unit
def test_snapshot_to_safe_dict_redacts_nothing_and_round_trips() -> None:
    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        scores={
            "value": CandidateFactorScore(factor_id="value", value=80.5),
        },
        computed_at=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
    )

    assert snapshot.to_safe_dict() == snapshot.model_dump(mode="json")

    round_tripped = FactorSnapshot.model_validate(snapshot.model_dump(mode="json"))
    assert round_tripped == snapshot


@pytest.mark.unit
def test_unknown_factor_key_is_carried_with_warning() -> None:
    pick = _pick(
        factor_scores={
            "value": 80.0,
            "liquidity": 60.0,
            "momentum": 55.0,
            "reversal": 48.0,
            "activity": 71.0,
            "stability": 66.0,
            "size": 52.0,
            "theme_heat": 44.0,
            "topic_alignment": 39.0,
            "momentum_v2": 90.0,
        }
    )

    snapshot = pick_to_factor_snapshot(pick, run_id="a1b2c3d4e5f6")

    assert snapshot.scores["momentum_v2"].value == 90.0
    assert snapshot.quality.coverage == 1.0
    assert snapshot.quality.status == FactorFieldStatus.AVAILABLE
    assert any("momentum_v2" in warning for warning in snapshot.quality.warnings)
    assert snapshot.quality.degradation_reason is not None
    assert "momentum_v2" in snapshot.quality.degradation_reason


@pytest.mark.unit
def test_pool_run_timestamp_parses_offsets_and_falls_back_on_unparseable() -> None:
    offset_result = _screen_result(created_at="2026-11-14T17:30:00+08:00")
    assert screen_result_to_pool_run(offset_result).created_at == datetime(
        2026, 11, 14, 9, 30, tzinfo=timezone.utc
    )

    zulu_result = _screen_result(created_at="2026-11-14T09:30:00Z")
    assert screen_result_to_pool_run(zulu_result).created_at == datetime(
        2026, 11, 14, 9, 30, tzinfo=timezone.utc
    )

    unparseable_result = _screen_result(created_at="not-a-date")
    fallback_run = screen_result_to_pool_run(unparseable_result)
    fallback_created_at = fallback_run.created_at
    assert fallback_created_at.tzinfo is not None
    assert (
        abs((fallback_created_at - datetime.now(timezone.utc)).total_seconds()) < 60
    )
    # The fallback is recorded on the run envelope, not silent.
    assert fallback_run.degradation == [
        "unparseable created_at 'not-a-date': fell back to mapping time"
    ]

    degraded_result = _screen_result(
        created_at="not-a-date", degradation=["daily enrichment failed"]
    )
    degraded_run = screen_result_to_pool_run(degraded_result)
    assert degraded_run.degradation == [
        "daily enrichment failed",
        "unparseable created_at 'not-a-date': fell back to mapping time",
    ]


@pytest.mark.unit
def test_screen_result_to_factor_snapshots_shares_run_header() -> None:
    result = _screen_result(
        effective_factor_weights={"value": 0.5, "momentum": 0.5},
        picks=[
            _pick(factor_scores={"value": 80.0}),
            _pick(rank=2, code="000001", name="平安银行", factor_scores={"value": 40.0}),
        ],
        run_id="a1b2c3d4e5f6",
        created_at="2026-11-14T09:30:00",
    )

    snapshots = screen_result_to_factor_snapshots(result)

    assert [s.code for s in snapshots] == ["600519", "000001"]
    assert [s.rank for s in snapshots] == [1, 2]
    assert all(s.candidate_pool_run_id == "a1b2c3d4e5f6" for s in snapshots)
    assert all(
        s.computed_at == datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc)
        for s in snapshots
    )
    assert snapshots[0].scores["value"].weight == 0.5
    assert snapshots[1].scores["value"].value == 40.0


@pytest.mark.unit
def test_factor_field_status_and_category_vocabularies() -> None:
    for state in ("available", "missing", "partial", "fallback", "stale"):
        assert FactorFieldStatus(state).value == state

    with pytest.raises(ValueError):
        FactorFieldStatus("bad_status")

    with pytest.raises(ValidationError):
        FactorDataQuality(status="bad_status")

    categories = {d.category for d in factor_definitions()}
    assert categories == {
        FactorCategory.VALUATION,
        FactorCategory.LIQUIDITY,
        FactorCategory.TECHNICAL,
        FactorCategory.THEME,
    }
    by_id = {d.factor_id: d.category for d in factor_definitions()}
    assert by_id["value"] == FactorCategory.VALUATION
    assert by_id["size"] == FactorCategory.LIQUIDITY
    assert by_id["momentum"] == FactorCategory.TECHNICAL
    assert by_id["theme_heat"] == FactorCategory.THEME


@pytest.mark.unit
def test_snapshot_rank_is_carried_and_must_be_positive() -> None:
    pick = _pick(rank=3, factor_scores={"value": 80.0})
    snapshot = pick_to_factor_snapshot(pick, run_id="a1b2c3d4e5f6")
    assert snapshot.rank == 3

    # Unknown rank stays None; it is never 0.
    assert (
        FactorSnapshot(candidate_pool_run_id="a1b2c3d4e5f6", code="600519").rank
        is None
    )

    for bad_rank in (0, -1):
        with pytest.raises(ValidationError):
            FactorSnapshot(
                candidate_pool_run_id="a1b2c3d4e5f6",
                code="600519",
                rank=bad_rank,
            )


@pytest.mark.unit
def test_non_finite_floats_rejected_on_all_float_surfaces() -> None:
    for bad_value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            FactorSnapshot(
                candidate_pool_run_id="a1b2c3d4e5f6",
                code="600519",
                screen_score=bad_value,
            )
        with pytest.raises(ValidationError):
            CandidateFactorScore(factor_id="value", value=50.0, weight=bad_value)
        with pytest.raises(ValidationError):
            CandidatePoolRun(
                run_id="a1b2c3d4e5f6",
                strategy="balanced_alpha",
                market="cn",
                effective_factor_weights={"value": bad_value},
            )
        with pytest.raises(ValidationError):
            FactorDefinition(
                factor_id="value",
                name="Value",
                category=FactorCategory.VALUATION,
                unit="score_0_100",
                definition="PE/PB cross-sectional rank score.",
                source="screening.scorer:factor_value_score",
                params={"base": bad_value},
            )
        with pytest.raises(ValidationError):
            FactorDataQuality(coverage=bad_value)
        with pytest.raises(ValidationError):
            FactorDataQuality(missing_rate=bad_value)


@pytest.mark.unit
def test_snapshot_scores_keys_must_match_factor_ids() -> None:
    with pytest.raises(ValidationError):
        FactorSnapshot(
            candidate_pool_run_id="a1b2c3d4e5f6",
            code="600519",
            scores={
                "value": CandidateFactorScore(factor_id="momentum", value=80.0),
            },
        )

    # A consistent unknown key still passes: carry + warn is unaffected.
    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        scores={
            "momentum_v2": CandidateFactorScore(
                factor_id="momentum_v2", value=90.0
            ),
        },
    )
    assert snapshot.scores["momentum_v2"].value == 90.0


@pytest.mark.unit
def test_identifiers_must_be_non_empty_and_counts_non_negative() -> None:
    with pytest.raises(ValidationError):
        CandidatePoolRun(run_id="", strategy="balanced_alpha", market="cn")
    with pytest.raises(ValidationError):
        FactorSnapshot(candidate_pool_run_id="", code="600519")
    with pytest.raises(ValidationError):
        FactorSnapshot(candidate_pool_run_id="a1b2c3d4e5f6", code="")
    with pytest.raises(ValidationError):
        CandidateFactorScore(factor_id="", value=50.0)

    for field in ("candidate_count", "snapshot_count", "after_filter_count"):
        with pytest.raises(ValidationError):
            CandidatePoolRun(
                run_id="a1b2c3d4e5f6",
                strategy="balanced_alpha",
                market="cn",
                **{field: -1},
            )

    assert (
        CandidatePoolRun(
            run_id="a1b2c3d4e5f6",
            strategy="balanced_alpha",
            market="cn",
            candidate_count=0,
            snapshot_count=0,
            after_filter_count=0,
        ).candidate_count
        == 0
    )


@pytest.mark.unit
def test_pool_run_timestamp_accepts_date_only_as_utc_midnight() -> None:
    result = _screen_result(created_at="2026-11-15")

    pool_run = screen_result_to_pool_run(result)

    assert pool_run.created_at == datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)
    assert pool_run.degradation == []


@pytest.mark.unit
def test_json_round_trips_preserve_types_and_weights() -> None:
    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        name="贵州茅台",
        rank=1,
        scores={
            "value": CandidateFactorScore(
                factor_id="value", value=80.5, weight=0.0
            ),
            "momentum": CandidateFactorScore(
                factor_id="momentum", value=55.0, weight=None
            ),
        },
        screen_score=72.5,
        quality=FactorDataQuality(
            coverage=2 / 9,
            missing_rate=1 - 2 / 9,
            status=FactorFieldStatus.PARTIAL,
        ),
        computed_at=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
    )

    payload = snapshot.model_dump_json()
    assert '"computed_at":"2026-11-14T09:30:00Z"' in payload
    assert '"status":"partial"' in payload

    round_tripped = FactorSnapshot.model_validate_json(payload)
    assert round_tripped == snapshot
    assert round_tripped.scores["value"].weight == 0.0
    assert round_tripped.scores["momentum"].weight is None
    assert round_tripped.computed_at.tzinfo is not None

    pool_run = CandidatePoolRun(
        run_id="a1b2c3d4e5f6",
        strategy="balanced_alpha",
        market="cn",
        effective_factor_weights={"value": 0.4, "liquidity": 0.0},
        candidate_count=2,
        created_at=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
    )

    pool_payload = pool_run.model_dump_json()
    assert '"created_at":"2026-11-14T09:30:00Z"' in pool_payload

    round_tripped_run = CandidatePoolRun.model_validate_json(pool_payload)
    assert round_tripped_run == pool_run
    assert round_tripped_run.effective_factor_weights["liquidity"] == 0.0
    assert round_tripped_run.created_at.tzinfo is not None
