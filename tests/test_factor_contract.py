# -*- coding: utf-8 -*-
"""Tests for the Issue #1902 P0 DSA internal factor contract."""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from collections.abc import Iterator
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
    FactorScoreMap,
    FactorSnapshot,
    FiniteFloatMap,
    normalize_contract_timestamp,
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


def _set_local_timezone(tz_name: str) -> str | None:
    """Point the process-local clock at ``tz_name``; return the previous TZ."""
    previous_tz = os.environ.get("TZ")
    os.environ["TZ"] = tz_name
    time.tzset()
    return previous_tz


def _restore_local_timezone(previous_tz: str | None) -> None:
    if previous_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous_tz
    time.tzset()


@pytest.fixture
def shanghai_local_time() -> Iterator[None]:
    """Run the test with the process-local clock on Asia/Shanghai.

    ``ScreenResult.created_at`` is produced by ``datetime.now()`` on the
    deployment clock (``TZ=Asia/Shanghai`` in docker-compose), so legacy
    naive timestamps must be read on that clock, not on UTC.
    """
    if sys.platform == "win32":
        pytest.skip("time.tzset() is unavailable on Windows")
    previous_tz = _set_local_timezone("Asia/Shanghai")
    yield
    _restore_local_timezone(previous_tz)


@pytest.fixture
def utc_local_time() -> Iterator[None]:
    """Run the test with the process-local clock on UTC."""
    if sys.platform == "win32":
        pytest.skip("time.tzset() is unavailable on Windows")
    previous_tz = _set_local_timezone("UTC")
    yield
    _restore_local_timezone(previous_tz)


@pytest.fixture
def new_york_local_time() -> Iterator[None]:
    """Run the test with the process-local clock on America/New_York.

    Unlike Shanghai and UTC, New York observes daylight saving time,
    so the local offset depends on the input date: UTC-04:00 in July,
    UTC-05:00 in November.
    """
    if sys.platform == "win32":
        pytest.skip("time.tzset() is unavailable on Windows")
    previous_tz = _set_local_timezone("America/New_York")
    yield
    _restore_local_timezone(previous_tz)


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
def test_pool_run_copies_screen_result_header_verbatim(
    shanghai_local_time: Iterator[None],
) -> None:
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
    # Naive input is local wall time: 09:30 in Shanghai is 01:30 UTC.
    assert pool_run.created_at == datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)


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
def test_naive_created_at_converts_from_local_time(
    shanghai_local_time: Iterator[None],
) -> None:
    """Reviewer scenario (OR-COR-771315a2 / OR-COR-37f2deeb).

    ``created_at`` ``2026-11-14T00:30:00`` is Shanghai wall time, so the
    run, the snapshot and the single-factor timestamps must all read
    2026-11-13T16:30:00Z — never 2026-11-14T00:30:00Z.
    """
    result = _screen_result(
        created_at="2026-11-14T00:30:00",
        picks=[_pick(factor_scores={"value": 80.0})],
        run_id="a1b2c3d4e5f6",
    )
    expected = datetime(2026, 11, 13, 16, 30, tzinfo=timezone.utc)

    assert screen_result_to_pool_run(result).created_at == expected
    snapshots = screen_result_to_factor_snapshots(result)
    assert len(snapshots) == 1
    assert snapshots[0].computed_at == expected
    assert snapshots[0].scores["value"].computed_at == expected


@pytest.mark.unit
def test_naive_created_at_under_utc_keeps_wall_time(
    utc_local_time: Iterator[None],
) -> None:
    """The naive rule follows the process-local clock, not a fixed zone."""
    result = _screen_result(created_at="2026-11-14T09:30:00")
    assert screen_result_to_pool_run(result).created_at == datetime(
        2026, 11, 14, 9, 30, tzinfo=timezone.utc
    )


@pytest.mark.unit
def test_screen_result_created_at_carries_offset() -> None:
    """Regression for OR-COR-7534d627: the run timestamp must keep its
    UTC offset, or two runs in a DST fold hour are indistinguishable."""
    created_at = ScreenResult(
        strategy="balanced_alpha", market="cn", run_id="a1b2c3d4e5f6"
    ).created_at
    parsed = datetime.fromisoformat(created_at)
    assert parsed.tzinfo is not None


@pytest.mark.unit
def test_dst_fold_offset_runs_map_to_distinct_utc(
    new_york_local_time: Iterator[None],
) -> None:
    """Regression for OR-COR-7534d627: the 2026-11-01 fold hour in
    America/New_York repeats 01:30 twice — the first run is 05:30Z
    (EDT, -04:00) and the second is 06:30Z (EST, -05:00)."""
    first = _screen_result(
        created_at="2026-11-01T01:30:00-04:00",
        picks=[_pick(factor_scores={"value": 80.0})],
        run_id="a1b2c3d4e5f6",
    )
    second = _screen_result(
        created_at="2026-11-01T01:30:00-05:00",
        picks=[_pick(factor_scores={"value": 80.0})],
        run_id="a1b2c3d4e5f6",
    )
    first_utc = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    second_utc = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)

    assert screen_result_to_pool_run(first).created_at == first_utc
    assert screen_result_to_pool_run(second).created_at == second_utc
    assert screen_result_to_factor_snapshots(first)[0].computed_at == first_utc
    assert screen_result_to_factor_snapshots(second)[0].computed_at == second_utc


@pytest.mark.unit
def test_ambiguous_naive_created_at_is_recorded(
    new_york_local_time: Iterator[None],
) -> None:
    """A legacy naive created_at in the fold hour cannot be
    disambiguated after the fact: it maps as the first occurrence
    and the ambiguity is recorded instead of silently stamped."""
    result = _screen_result(
        created_at="2026-11-01T01:30:00",
        picks=[_pick(factor_scores={"value": 80.0})],
        run_id="a1b2c3d4e5f6",
    )
    pool_run = screen_result_to_pool_run(result)
    assert pool_run.created_at == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)
    assert any("ambiguous created_at" in entry for entry in pool_run.degradation)
    snapshots = screen_result_to_factor_snapshots(result)
    assert any(
        "ambiguous created_at" in warning
        for warning in snapshots[0].quality.warnings
    )


@pytest.mark.unit
def test_pick_snapshot_normalizes_naive_computed_at(
    shanghai_local_time: Iterator[None],
) -> None:
    """An explicit naive ``computed_at`` is local wall time, not UTC."""
    pick = _pick(factor_scores={"value": 80.0})
    snapshot = pick_to_factor_snapshot(
        pick,
        run_id="a1b2c3d4e5f6",
        computed_at=datetime(2026, 11, 14, 9, 30),
    )
    expected = datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)
    assert snapshot.computed_at == expected
    assert snapshot.scores["value"].computed_at == expected


@pytest.mark.unit
def test_contract_schema_normalizes_naive_timestamps(
    shanghai_local_time: Iterator[None],
) -> None:
    """The schema backstop: naive datetimes serialize as aware UTC."""
    assert normalize_contract_timestamp(
        datetime(2026, 11, 14, 9, 30)
    ) == datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)
    assert normalize_contract_timestamp(
        datetime(2026, 11, 14, 17, 30, tzinfo=timezone.utc)
    ) == datetime(2026, 11, 14, 17, 30, tzinfo=timezone.utc)

    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        computed_at=datetime(2026, 11, 14, 9, 30),
    )
    assert snapshot.computed_at == datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)
    assert '"computed_at":"2026-11-14T01:30:00Z"' in snapshot.model_dump_json()

    pool_run = CandidatePoolRun(
        run_id="a1b2c3d4e5f6",
        strategy="balanced_alpha",
        market="cn",
        created_at=datetime(2026, 11, 14, 9, 30),
    )
    assert pool_run.created_at == datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)
    assert '"created_at":"2026-11-14T01:30:00Z"' in pool_run.model_dump_json()


@pytest.mark.unit
def test_dst_crossing_date_converts_with_input_date_offset(
    new_york_local_time: Iterator[None],
) -> None:
    """Cross-DST regression (OR-COR-4d68c9ab).

    ``created_at`` ``2026-07-14T00:30:00`` is New York daylight time
    (UTC-04:00), so it must read 2026-07-14T04:30:00Z even when the
    mapping runs in November standard time — never 05:30Z. The
    offset follows the input date, not the execution date, through
    all three mapping entry points.
    """
    result = _screen_result(
        created_at="2026-07-14T00:30:00",
        picks=[_pick(factor_scores={"value": 80.0})],
        run_id="a1b2c3d4e5f6",
    )
    expected = datetime(2026, 7, 14, 4, 30, tzinfo=timezone.utc)

    assert screen_result_to_pool_run(result).created_at == expected
    snapshots = screen_result_to_factor_snapshots(result)
    assert len(snapshots) == 1
    assert snapshots[0].computed_at == expected
    assert snapshots[0].scores["value"].computed_at == expected

    # Third entry point: explicit naive computed_at on a Pick.
    pick_snapshot = pick_to_factor_snapshot(
        _pick(factor_scores={"value": 80.0}),
        run_id="a1b2c3d4e5f6",
        computed_at=datetime(2026, 7, 14, 0, 30),
    )
    assert pick_snapshot.computed_at == expected
    assert pick_snapshot.scores["value"].computed_at == expected


@pytest.mark.unit
def test_standard_time_date_uses_standard_offset(
    new_york_local_time: Iterator[None],
) -> None:
    """A November date converts with the standard-time offset."""
    result = _screen_result(created_at="2026-11-14T00:30:00")
    assert screen_result_to_pool_run(result).created_at == datetime(
        2026, 11, 14, 5, 30, tzinfo=timezone.utc
    )


@pytest.mark.unit
def test_contract_schema_normalizes_dst_crossing_timestamps(
    new_york_local_time: Iterator[None],
) -> None:
    """Schema backstop resolves the offset per the input date.

    All three timestamp fields — per-factor ``computed_at``,
    snapshot ``computed_at``, run ``created_at`` — must convert a
    July wall time with the daylight offset, not today's offset.
    """
    assert normalize_contract_timestamp(
        datetime(2026, 7, 14, 0, 30)
    ) == datetime(2026, 7, 14, 4, 30, tzinfo=timezone.utc)

    score = CandidateFactorScore(
        factor_id="value", value=80.0, computed_at=datetime(2026, 7, 14, 0, 30)
    )
    assert score.computed_at == datetime(2026, 7, 14, 4, 30, tzinfo=timezone.utc)

    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        computed_at=datetime(2026, 7, 14, 0, 30),
    )
    assert snapshot.computed_at == datetime(2026, 7, 14, 4, 30, tzinfo=timezone.utc)
    assert '"computed_at":"2026-07-14T04:30:00Z"' in snapshot.model_dump_json()

    pool_run = CandidatePoolRun(
        run_id="a1b2c3d4e5f6",
        strategy="balanced_alpha",
        market="cn",
        created_at=datetime(2026, 7, 14, 0, 30),
    )
    assert pool_run.created_at == datetime(2026, 7, 14, 4, 30, tzinfo=timezone.utc)
    assert '"created_at":"2026-07-14T04:30:00Z"' in pool_run.model_dump_json()


@pytest.mark.unit
def test_screen_result_to_factor_snapshots_shares_run_header(
    shanghai_local_time: Iterator[None],
) -> None:
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
    # Naive input is local wall time: 09:30 in Shanghai is 01:30 UTC.
    assert all(
        s.computed_at == datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)
        for s in snapshots
    )
    assert all(
        score.computed_at == datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc)
        for s in snapshots
        for score in s.scores.values()
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
def test_in_place_non_finite_writes_are_rejected_on_float_dicts() -> None:
    """Regression for OR-COR-57d4e9b1: an in-place non-finite write
    into effective_factor_weights or params must fail —
    allow_inf_nan=False only bites at field validation, so a plain
    dict accepted the write and the dumped JSON exported the entry
    as null, which the same contract then refused to read back."""
    run = screen_result_to_pool_run(
        _screen_result(effective_factor_weights={"value": 1.0})
    )
    definition = factor_definitions()[0]
    assert isinstance(run.effective_factor_weights, FiniteFloatMap)
    assert isinstance(definition.params, FiniteFloatMap)

    for bad_value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="non-finite"):
            run.effective_factor_weights["value"] = bad_value
        with pytest.raises(ValueError, match="non-finite"):
            definition.params["base"] = bad_value
    assert run.effective_factor_weights == {"value": 1.0}
    assert definition.params == {}
    CandidatePoolRun.model_validate_json(run.model_dump_json())
    FactorDefinition.model_validate_json(definition.model_dump_json())

    # The same guard applies to the other mutating dict writes.
    with pytest.raises(ValueError, match="non-finite"):
        run.effective_factor_weights.update({"value": float("nan")})
    assert run.effective_factor_weights == {"value": 1.0}
    CandidatePoolRun.model_validate_json(run.model_dump_json())


@pytest.mark.unit
def test_omitted_float_dicts_still_get_the_validating_map() -> None:
    """Regression for OR-COR-57d4e9b1 (omitted path): a run or
    definition built — or JSON-read — with the float dict omitted
    must still guard in-place writes. The default used to skip
    field validation, so both omitted paths returned a plain dict."""
    omitted_run = CandidatePoolRun(
        run_id="a1b2c3d4e5f6", strategy="balanced_alpha", market="cn"
    )
    omitted_definition = FactorDefinition(
        factor_id="value",
        name="Value",
        category=FactorCategory.VALUATION,
        unit="score_0_100",
        definition="PE/PB cross-sectional rank score.",
        source="screening.scorer:factor_value_score",
    )
    from_json_run = CandidatePoolRun.model_validate_json(
        json.dumps(
            {
                "run_id": "a1b2c3d4e5f6",
                "strategy": "balanced_alpha",
                "market": "cn",
            }
        )
    )
    from_json_definition = FactorDefinition.model_validate_json(
        json.dumps(
            {
                "factor_id": "value",
                "name": "Value",
                "category": "valuation",
                "unit": "score_0_100",
                "definition": "PE/PB cross-sectional rank score.",
                "source": "screening.scorer:factor_value_score",
            }
        )
    )
    for mapping in (
        omitted_run.effective_factor_weights,
        from_json_run.effective_factor_weights,
        omitted_definition.params,
        from_json_definition.params,
    ):
        assert isinstance(mapping, FiniteFloatMap)
        assert mapping == {}
        with pytest.raises(ValueError, match="non-finite"):
            mapping["value"] = float("nan")
        assert mapping == {}
    CandidatePoolRun.model_validate_json(omitted_run.model_dump_json())
    FactorDefinition.model_validate_json(
        omitted_definition.model_dump_json()
    )


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
def test_snapshot_scores_assignment_rejection_keeps_original() -> None:
    """Regression for OR-COR-8c18c172: a rejected scores assignment
    must leave the snapshot untouched — previously the invalid key
    stayed in place and the dumped snapshot failed its own JSON
    round-trip."""
    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        scores={"value": CandidateFactorScore(factor_id="value", value=80.0)},
    )
    with pytest.raises(ValidationError):
        snapshot.scores = {
            "momentum": CandidateFactorScore(factor_id="value", value=80.0)
        }
    assert list(snapshot.scores) == ["value"]
    assert snapshot.scores["value"].factor_id == "value"
    FactorSnapshot.model_validate_json(snapshot.model_dump_json())


@pytest.mark.unit
def test_snapshot_nested_factor_id_assignment_is_rejected() -> None:
    """Regression for OR-COR-2f8b65a1: mutating a nested score's
    factor_id must fail — the scores dict is keyed by factor_id and
    the field validator only runs on construction or whole
    replacement, so a silent nested reassignment desynced the key
    from the id and the dumped snapshot failed its own JSON
    round-trip."""
    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        scores={"value": CandidateFactorScore(factor_id="value", value=80.0)},
    )
    with pytest.raises(ValidationError):
        snapshot.scores["value"].factor_id = "momentum"
    assert snapshot.scores["value"].factor_id == "value"
    FactorSnapshot.model_validate_json(snapshot.model_dump_json())


@pytest.mark.unit
def test_snapshot_scores_item_assignment_is_rejected() -> None:
    """Regression for OR-COR-2f8b65a1 (second half): replacing a
    scores entry in place must fail — freezing the score fixed direct
    ``factor_id`` edits, but ``snapshot.scores[key] = other`` never
    ran the field validator, so a mismatched entry desynced the key
    from the id and the dumped snapshot failed its own JSON
    round-trip."""
    snapshot = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
        scores={
            "value": CandidateFactorScore(factor_id="value", value=80.0),
            "momentum": CandidateFactorScore(
                factor_id="momentum", value=70.0
            ),
        },
    )
    with pytest.raises(ValueError, match="does not match factor_id"):
        snapshot.scores["value"] = snapshot.scores["momentum"]
    assert list(snapshot.scores) == ["value", "momentum"]
    assert snapshot.scores["value"].factor_id == "value"
    FactorSnapshot.model_validate_json(snapshot.model_dump_json())

    # The same guard applies to the other mutating dict writes.
    with pytest.raises(ValueError, match="does not match factor_id"):
        snapshot.scores.update(
            {"value": CandidateFactorScore(factor_id="momentum", value=70.0)}
        )
    assert snapshot.scores["value"].factor_id == "value"
    FactorSnapshot.model_validate_json(snapshot.model_dump_json())


@pytest.mark.unit
def test_snapshot_omitted_scores_still_gets_the_validating_map() -> None:
    """Regression for OR-COR-2f8b65a1 (third form): a snapshot built
    — or JSON-read — with ``scores`` omitted must still guard
    in-place writes. The default used to skip field validation, so
    both omitted paths returned a plain dict and a mismatched
    ``snapshot.scores[key] = score`` desynced the key from the id
    while the dumped snapshot failed its own JSON round-trip."""
    omitted = FactorSnapshot(
        candidate_pool_run_id="a1b2c3d4e5f6",
        code="600519",
    )
    from_json = FactorSnapshot.model_validate_json(
        json.dumps(
            {"candidate_pool_run_id": "a1b2c3d4e5f6", "code": "600519"}
        )
    )
    for snapshot in (omitted, from_json):
        assert isinstance(snapshot.scores, FactorScoreMap)
        assert snapshot.scores == {}
        with pytest.raises(ValueError, match="does not match factor_id"):
            snapshot.scores["value"] = CandidateFactorScore(
                factor_id="momentum", value=70.0
            )
        assert list(snapshot.scores) == []
        FactorSnapshot.model_validate_json(snapshot.model_dump_json())


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
def test_pool_run_timestamp_accepts_date_only_as_local_midnight(
    shanghai_local_time: Iterator[None],
) -> None:
    result = _screen_result(created_at="2026-11-15")

    pool_run = screen_result_to_pool_run(result)

    # Date-only means local midnight: 2026-11-15 00:00 in Shanghai is
    # 2026-11-14 16:00 UTC, not midnight UTC.
    assert pool_run.created_at == datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
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
