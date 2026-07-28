# -*- coding: utf-8 -*-
"""Tests for read-only Skill Opinion Outcome performance statistics."""

from __future__ import annotations

import os
from itertools import count

import pytest

from src.config import Config
from src.repositories.skill_opinion_outcome_repo import (
    SkillOpinionOutcomeRepository,
)
from src.services.skill_opinion_performance_service import (
    SkillOpinionPerformanceService,
)
from src.services.skill_opinion_outcome_service import (
    SKILL_OPINION_OUTCOME_ENGINE_VERSION,
)
from src.storage import (
    AnalysisHistory,
    DatabaseManager,
    SkillOpinionOutcomeRecord,
    SkillOpinionSampleRecord,
)

_ROW_SEQUENCE = count(1)


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "skill_opinion_outcome_stats.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def _add_outcome(
    db: DatabaseManager,
    *,
    skill_id: str = "alpha",
    horizon: str = "1d",
    engine_version: str = SKILL_OPINION_OUTCOME_ENGINE_VERSION,
    eval_status: str,
    outcome: str | None = None,
    directional_return_pct: float | None = None,
) -> None:
    with db.session_scope() as session:
        history = AnalysisHistory(
            query_id=(
                f"stats-{skill_id}-{horizon}-{eval_status}-{next(_ROW_SEQUENCE)}"
            ),
            code="600519",
            report_type="simple",
            operation_advice="hold",
        )
        session.add(history)
        session.flush()
        sample = SkillOpinionSampleRecord(
            analysis_history_id=history.id,
            stock_code="600519",
            skill_id=skill_id,
            signal="buy" if eval_status != "observational" else "hold",
            confidence=0.8,
            sample_schema_version="skill-opinion-sample-v1",
        )
        session.add(sample)
        session.flush()
        session.add(
            SkillOpinionOutcomeRecord(
                skill_opinion_sample_id=sample.id,
                horizon=horizon,
                engine_version=engine_version,
                eval_status=eval_status,
                outcome=outcome,
                direction_correct=(
                    outcome == "hit" if eval_status == "evaluated" else None
                ),
                directional_return_pct=directional_return_pct,
                unable_reason=(
                    "invalid_metadata" if eval_status == "unable" else None
                ),
            )
        )


def test_repository_aggregates_raw_bucket_counts(isolated_db) -> None:
    _add_outcome(
        isolated_db,
        eval_status="evaluated",
        outcome="hit",
        directional_return_pct=5.0,
    )
    _add_outcome(
        isolated_db,
        eval_status="evaluated",
        outcome="miss",
        directional_return_pct=-2.0,
    )
    _add_outcome(isolated_db, eval_status="observational", outcome="observational")
    _add_outcome(isolated_db, eval_status="unable")
    _add_outcome(isolated_db, eval_status="pending")

    buckets = SkillOpinionOutcomeRepository(
        isolated_db
    ).list_performance_buckets(
        engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
    )

    assert len(buckets) == 1
    bucket = buckets[0]
    assert bucket.skill_id == "alpha"
    assert bucket.horizon == "1d"
    assert bucket.total == 5
    assert bucket.pending == 1
    assert bucket.evaluated == 2
    assert bucket.observational == 1
    assert bucket.unable == 1
    assert bucket.hit == 1
    assert bucket.miss == 1
    assert bucket.avg_directional_return_pct == pytest.approx(1.5)


def test_service_keeps_insufficient_bucket_observational(isolated_db) -> None:
    _add_outcome(
        isolated_db,
        eval_status="evaluated",
        outcome="hit",
        directional_return_pct=5.0,
    )
    _add_outcome(
        isolated_db,
        eval_status="evaluated",
        outcome="miss",
        directional_return_pct=-2.0,
    )
    _add_outcome(isolated_db, eval_status="observational", outcome="observational")
    _add_outcome(isolated_db, eval_status="unable")
    _add_outcome(isolated_db, eval_status="pending")

    stats = SkillOpinionPerformanceService(
        db_manager=isolated_db
    ).get_stats()

    assert stats["engine_version"] == SKILL_OPINION_OUTCOME_ENGINE_VERSION
    assert stats["minimum_evaluated_sample_size"] == 30
    assert len(stats["buckets"]) == 1
    bucket = stats["buckets"][0]
    assert bucket["total"] == 5
    assert bucket["evaluated"] == 2
    assert bucket["observational"] == 1
    assert bucket["unable"] == 1
    assert bucket["pending"] == 1
    assert bucket["hit"] == 1
    assert bucket["miss"] == 1
    assert bucket["sample_sufficient"] is False
    assert bucket["sample_status"] == "observational"
    assert bucket["hit_rate_pct"] is None
    assert bucket["miss_rate_pct"] is None
    assert bucket["avg_directional_return_pct"] is None
    assert bucket["unable_rate_pct"] is None


def test_service_unlocks_metrics_at_exact_sample_threshold(isolated_db) -> None:
    for _ in range(18):
        _add_outcome(
            isolated_db,
            eval_status="evaluated",
            outcome="hit",
            directional_return_pct=2.0,
        )
    for _ in range(12):
        _add_outcome(
            isolated_db,
            eval_status="evaluated",
            outcome="miss",
            directional_return_pct=-1.0,
        )
    _add_outcome(isolated_db, eval_status="observational", outcome="observational")
    _add_outcome(isolated_db, eval_status="unable")
    _add_outcome(isolated_db, eval_status="unable")
    _add_outcome(isolated_db, eval_status="pending")

    bucket = SkillOpinionPerformanceService(
        db_manager=isolated_db
    ).get_stats()["buckets"][0]

    assert bucket["total"] == 34
    assert bucket["evaluated"] == 30
    assert bucket["sample_sufficient"] is True
    assert bucket["sample_status"] == "sufficient"
    assert bucket["hit_rate_pct"] == 60.0
    assert bucket["miss_rate_pct"] == 40.0
    assert bucket["avg_directional_return_pct"] == 0.8
    assert bucket["unable_rate_pct"] == 6.06


def test_non_evaluated_rows_do_not_unlock_metrics(isolated_db) -> None:
    for _ in range(29):
        _add_outcome(
            isolated_db,
            eval_status="evaluated",
            outcome="hit",
            directional_return_pct=1.0,
        )
    for _ in range(5):
        _add_outcome(
            isolated_db,
            eval_status="observational",
            outcome="observational",
        )
        _add_outcome(isolated_db, eval_status="unable")
        _add_outcome(isolated_db, eval_status="pending")

    bucket = SkillOpinionPerformanceService(
        db_manager=isolated_db
    ).get_stats()["buckets"][0]

    assert bucket["total"] == 44
    assert bucket["evaluated"] == 29
    assert bucket["sample_sufficient"] is False
    assert bucket["sample_status"] == "observational"
    assert bucket["hit_rate_pct"] is None
    assert bucket["miss_rate_pct"] is None
    assert bucket["avg_directional_return_pct"] is None
    assert bucket["unable_rate_pct"] is None


def test_service_filters_exact_bucket_identity(isolated_db) -> None:
    _add_outcome(
        isolated_db,
        skill_id="alpha",
        horizon="1d",
        eval_status="evaluated",
        outcome="hit",
        directional_return_pct=1.0,
    )
    _add_outcome(
        isolated_db,
        skill_id="alpha",
        horizon="3d",
        eval_status="evaluated",
        outcome="miss",
        directional_return_pct=-1.0,
    )
    _add_outcome(
        isolated_db,
        skill_id="beta",
        horizon="3d",
        eval_status="evaluated",
        outcome="hit",
        directional_return_pct=2.0,
    )
    _add_outcome(
        isolated_db,
        skill_id="alpha",
        horizon="3d",
        engine_version="skill-opinion-outcome-v2",
        eval_status="evaluated",
        outcome="hit",
        directional_return_pct=3.0,
    )

    stats = SkillOpinionPerformanceService(
        db_manager=isolated_db
    ).get_stats(
        skill_id="alpha",
        horizons=["3d"],
        engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
    )

    assert len(stats["buckets"]) == 1
    bucket = stats["buckets"][0]
    assert bucket["skill_id"] == "alpha"
    assert bucket["horizon"] == "3d"
    assert bucket["engine_version"] == SKILL_OPINION_OUTCOME_ENGINE_VERSION
    assert bucket["evaluated"] == 1
    assert bucket["miss"] == 1


def test_sibling_buckets_cannot_combine_to_unlock_metrics(
    isolated_db,
) -> None:
    for skill_id, horizon, engine_version in [
        ("alpha", "1d", SKILL_OPINION_OUTCOME_ENGINE_VERSION),
        ("alpha", "3d", SKILL_OPINION_OUTCOME_ENGINE_VERSION),
        ("beta", "1d", SKILL_OPINION_OUTCOME_ENGINE_VERSION),
        ("alpha", "1d", "skill-opinion-outcome-v2"),
    ]:
        for _ in range(16):
            _add_outcome(
                isolated_db,
                skill_id=skill_id,
                horizon=horizon,
                engine_version=engine_version,
                eval_status="evaluated",
                outcome="hit",
                directional_return_pct=1.0,
            )

    service = SkillOpinionPerformanceService(db_manager=isolated_db)
    current_buckets = service.get_stats()["buckets"]
    future_buckets = service.get_stats(
        engine_version="skill-opinion-outcome-v2"
    )["buckets"]

    assert len(current_buckets) == 3
    assert all(bucket["evaluated"] == 16 for bucket in current_buckets)
    assert all(
        bucket["sample_sufficient"] is False
        for bucket in current_buckets
    )
    assert len(future_buckets) == 1
    assert future_buckets[0]["evaluated"] == 16
    assert future_buckets[0]["sample_sufficient"] is False


@pytest.mark.parametrize(
    "filters",
    [
        {"skill_id": "   "},
        {"horizons": []},
        {"horizons": ["2d"]},
        {"engine_version": "   "},
    ],
)
def test_service_rejects_invalid_filters(isolated_db, filters) -> None:
    with pytest.raises(ValueError):
        SkillOpinionPerformanceService(
            db_manager=isolated_db
        ).get_stats(**filters)


def test_service_orders_buckets_by_total_then_canonical_identity(
    isolated_db,
) -> None:
    for skill_id, horizon, repetitions in [
        ("zeta", "3d", 3),
        ("alpha", "10d", 2),
        ("alpha", "1d", 2),
        ("beta", "5d", 3),
    ]:
        for _ in range(repetitions):
            _add_outcome(
                isolated_db,
                skill_id=skill_id,
                horizon=horizon,
                eval_status="evaluated",
                outcome="hit",
                directional_return_pct=1.0,
            )

    buckets = SkillOpinionPerformanceService(
        db_manager=isolated_db
    ).get_stats()["buckets"]

    assert [
        (bucket["skill_id"], bucket["horizon"], bucket["total"])
        for bucket in buckets
    ] == [
        ("beta", "5d", 3),
        ("zeta", "3d", 3),
        ("alpha", "1d", 2),
        ("alpha", "10d", 2),
    ]


def test_service_returns_empty_buckets_for_valid_empty_filter(
    isolated_db,
) -> None:
    stats = SkillOpinionPerformanceService(
        db_manager=isolated_db
    ).get_stats(skill_id="missing")

    assert stats["buckets"] == []
