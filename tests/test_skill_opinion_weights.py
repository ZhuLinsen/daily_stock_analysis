# -*- coding: utf-8 -*-
"""Behavior tests for conservative Skill Opinion outcome weights."""

from __future__ import annotations

import math
import os

import pytest

from src.agent.protocols import AgentOpinion
from src.agent.skills.aggregator import SkillAggregator
from src.config import Config
from src.services.skill_opinion_outcome_service import (
    SKILL_OPINION_OUTCOME_ENGINE_VERSION,
)
from src.services.skill_opinion_performance_service import (
    SkillOpinionPerformanceService,
)
from src.services.skill_opinion_weight_service import (
    SkillOpinionWeightService,
)
from src.storage import (
    AnalysisHistory,
    DatabaseManager,
    SkillOpinionOutcomeRecord,
    SkillOpinionSampleRecord,
)


class _FakePerformanceService:
    def __init__(self, buckets=None, *, error=None):
        self.buckets = list(buckets or [])
        self.error = error
        self.last_filters = None

    def get_stats(self, **filters):
        self.last_filters = filters
        if self.error is not None:
            raise self.error
        return {
            "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
            "minimum_evaluated_sample_size": 30,
            "buckets": self.buckets,
        }


def _bucket(
    *,
    skill_id="alpha",
    horizon="1d",
    engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
    evaluated=30,
    hit=18,
    miss=12,
    observational=0,
    unable=0,
    sample_sufficient=True,
):
    return {
        "skill_id": skill_id,
        "horizon": horizon,
        "engine_version": engine_version,
        "total": evaluated + observational + unable,
        "pending": 0,
        "evaluated": evaluated,
        "observational": observational,
        "unable": unable,
        "hit": hit,
        "miss": miss,
        "sample_sufficient": sample_sufficient,
        "sample_status": (
            "sufficient" if sample_sufficient else "observational"
        ),
        "hit_rate_pct": None,
        "miss_rate_pct": None,
        "avg_directional_return_pct": None,
        "unable_rate_pct": None,
    }


def _service(*buckets, error=None):
    return SkillOpinionWeightService(
        performance_service=_FakePerformanceService(
            buckets,
            error=error,
        )
    )


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(
        tmp_path / "skill_opinion_weights.db"
    )
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


def _add_real_hits(
    db: DatabaseManager,
    *,
    skill_id: str,
    count: int,
) -> None:
    with db.session_scope() as session:
        for index in range(count):
            history = AnalysisHistory(
                query_id=f"weight-{skill_id}-{index}",
                code="600519",
                report_type="simple",
                operation_advice="buy",
            )
            session.add(history)
            session.flush()
            sample = SkillOpinionSampleRecord(
                analysis_history_id=history.id,
                stock_code="600519",
                skill_id=skill_id,
                signal="buy",
                confidence=1.0,
                sample_schema_version="skill-opinion-sample-v1",
            )
            session.add(sample)
            session.flush()
            session.add(
                SkillOpinionOutcomeRecord(
                    skill_opinion_sample_id=sample.id,
                    horizon="1d",
                    engine_version=(
                        SKILL_OPINION_OUTCOME_ENGINE_VERSION
                    ),
                    eval_status="evaluated",
                    outcome="hit",
                    direction_correct=True,
                    directional_return_pct=1.0,
                )
            )


def test_weights_stay_neutral_without_independently_sufficient_bucket():
    service = _service(
        _bucket(
            evaluated=29,
            hit=29,
            miss=0,
            sample_sufficient=False,
        ),
        _bucket(skill_id="other", evaluated=100, hit=100, miss=0),
        _bucket(
            engine_version="skill-opinion-outcome-v999",
            evaluated=100,
            hit=100,
            miss=0,
        ),
    )

    assert service.compute_weights(["alpha", "missing"]) == {
        "alpha": 1.0,
        "missing": 1.0,
    }


def test_beta_prior_shrinks_minimum_sample_hit_rate_toward_neutral():
    service = _service(
        _bucket(evaluated=30, hit=30, miss=0),
    )

    weights = service.compute_weights(["alpha"])

    # Beta(15, 15) posterior = Beta(45, 15), so direction score = 0.5.
    assert weights["alpha"] == pytest.approx(1.2 ** 0.5)


def test_more_evidence_moves_posterior_closer_to_observed_hit_rate():
    service = _service(
        _bucket(
            skill_id="small",
            evaluated=30,
            hit=18,
            miss=12,
        ),
        _bucket(
            skill_id="large",
            evaluated=300,
            hit=180,
            miss=120,
        ),
    )

    weights = service.compute_weights(["small", "large"])

    # small: posterior=33/60, direction=0.1
    assert weights["small"] == pytest.approx(1.2 ** 0.1)
    # large: posterior=195/330, direction=2*(195/330)-1
    assert weights["large"] == pytest.approx(
        1.2 ** (2 * (195 / 330) - 1)
    )
    assert weights["large"] > weights["small"] > 1.0


def test_sufficient_horizons_use_evidence_weighted_model_average():
    service = _service(
        _bucket(
            horizon="1d",
            evaluated=30,
            hit=24,
            miss=6,
        ),
        _bucket(
            horizon="3d",
            evaluated=90,
            hit=45,
            miss=45,
        ),
        _bucket(
            horizon="5d",
            evaluated=29,
            hit=29,
            miss=0,
            sample_sufficient=False,
        ),
    )

    weights = service.compute_weights(["alpha"])

    # 1d: direction=0.3, strength=0.5.
    # 3d: direction=0.0, strength=0.75.
    # 5d is insufficient and cannot lend its samples to either bucket.
    combined_score = (0.3 * 0.5 + 0.0 * 0.75) / (0.5 + 0.75)
    assert weights["alpha"] == pytest.approx(1.2 ** combined_score)


def test_terminal_unable_rate_conservatively_reduces_factor():
    service = _service(
        _bucket(
            evaluated=30,
            hit=30,
            miss=0,
            unable=30,
        ),
    )

    weights = service.compute_weights(["alpha"])

    # direction=0.5, terminal unable rate=30/(30+30)=0.5,
    # bucket score=0.5-0.25*0.5=0.375.
    assert weights["alpha"] == pytest.approx(1.2 ** 0.375)
    assert 1.0 < weights["alpha"] < 1.2 ** 0.5


def test_extreme_negative_evidence_stays_at_multiplicative_lower_bound():
    service = _service(
        _bucket(
            evaluated=300,
            hit=0,
            miss=300,
            unable=300,
        ),
    )

    weights = service.compute_weights(["alpha"])

    assert weights["alpha"] == pytest.approx(1.0 / 1.2)


@pytest.mark.parametrize(
    "bucket",
    [
        _bucket(evaluated=30, hit=math.nan, miss=0),
        _bucket(evaluated=30, hit=31, miss=-1),
        _bucket(evaluated=30, hit=20, miss=10, unable=-1),
        _bucket(evaluated=30, hit=20, miss=9),
    ],
)
def test_malformed_bucket_fails_neutral(bucket):
    service = _service(bucket)

    assert service.compute_weights(["alpha"]) == {"alpha": 1.0}


def test_statistics_failure_fails_neutral():
    service = _service(error=RuntimeError("database unavailable"))

    assert service.compute_weights(["alpha"]) == {"alpha": 1.0}


def test_weight_query_is_restricted_to_requested_skills():
    performance_service = _FakePerformanceService(
        [_bucket(skill_id="alpha")]
    )
    service = SkillOpinionWeightService(
        performance_service=performance_service
    )

    service.compute_weights([" alpha ", "beta", "alpha"])

    assert performance_service.last_filters == {
        "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        "skill_ids": ["alpha", "beta"],
    }


def test_real_outcomes_flow_through_statistics_into_aggregator(
    isolated_db,
):
    _add_real_hits(isolated_db, skill_id="alpha", count=30)
    weight_service = SkillOpinionWeightService(
        performance_service=SkillOpinionPerformanceService(
            db_manager=isolated_db
        )
    )
    aggregator = SkillAggregator(weight_service=weight_service)

    result = aggregator.calculate(
        [
            AgentOpinion(
                agent_name="skill_alpha",
                signal="buy",
                confidence=1.0,
            ),
            AgentOpinion(
                agent_name="skill_without_samples",
                signal="sell",
                confidence=1.0,
            ),
        ]
    )

    assert result is not None
    assert result.weights == pytest.approx([1.2 ** 0.5, 1.0])
    assert result.weighted_score > 3.0
