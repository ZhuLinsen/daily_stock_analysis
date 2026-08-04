# -*- coding: utf-8 -*-
"""Tests for Issue #1904 skill opinion forward outcomes."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from src.config import Config
from src.core.skill_opinion_outcome_evaluator import SkillOpinionOutcomeEvaluator
from src.repositories.skill_opinion_outcome_repo import SkillOpinionOutcomeRepository
from src.services.skill_opinion_outcome_service import (
    SKILL_OPINION_OUTCOME_ENGINE_VERSION,
    SkillOpinionOutcomeService,
)
from src.storage import (
    AnalysisHistory,
    Base,
    DatabaseManager,
    SkillOpinionOutcomeRecord,
    SkillOpinionSampleRecord,
    StockDaily,
)


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "skill_opinion_outcomes.db")
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


def _bar(day: date, close: float):
    return SimpleNamespace(date=day, close=close)


def _add_sample(
    db: DatabaseManager,
    *,
    signal: str = "buy",
    skill_id: str = "alpha",
    code: str = "600519",
    context_snapshot=None,
    created_at: datetime = datetime(2024, 1, 2, 18, 0, 0),
    operation_advice: str = "hold",
) -> tuple[int, int]:
    with db.session_scope() as session:
        history = AnalysisHistory(
            query_id=f"outcome-{skill_id}",
            code=code,
            report_type="simple",
            operation_advice=operation_advice,
            context_snapshot=(
                json.dumps(context_snapshot)
                if isinstance(context_snapshot, dict)
                else context_snapshot
            ),
            created_at=created_at,
        )
        session.add(history)
        session.flush()
        sample = SkillOpinionSampleRecord(
            analysis_history_id=history.id,
            stock_code=code,
            skill_id=skill_id,
            signal=signal,
            confidence=0.8,
            sample_schema_version="skill-opinion-sample-v1",
        )
        session.add(sample)
        session.flush()
        return int(history.id), int(sample.id)


def _seed_bars(
    db: DatabaseManager,
    *,
    code: str,
    bars: list[tuple[date, float]],
) -> None:
    with db.session_scope() as session:
        for day, close in bars:
            session.add(
                StockDaily(
                    code=code,
                    date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                )
            )


def _effective_snapshot(day: str) -> dict:
    return {
        "enhanced_context": {"date": day},
        "market_phase_summary": {
            "phase": "postmarket",
            "market": "cn",
            "effective_daily_bar_date": day,
        }
    }


def _stored_outcome(
    db: DatabaseManager,
    sample_id: int,
    horizon: str = "1d",
    engine_version: str = SKILL_OPINION_OUTCOME_ENGINE_VERSION,
):
    return SkillOpinionOutcomeRepository(db).get_outcome(
        sample_id=sample_id,
        horizon=horizon,
        engine_version=engine_version,
    )


@pytest.mark.parametrize(
    ("signal", "end_close", "expected_outcome", "expected_correct"),
    [
        ("buy", 105.0, "hit", True),
        ("strong_buy", 95.0, "miss", False),
        ("sell", 95.0, "hit", True),
        ("strong_sell", 105.0, "miss", False),
        ("buy", 100.0, "miss", False),
    ],
)
def test_evaluator_uses_sample_signal_and_zero_is_miss(
    signal,
    end_close,
    expected_outcome,
    expected_correct,
) -> None:
    result = SkillOpinionOutcomeEvaluator.evaluate(
        signal=signal,
        horizon="1d",
        analysis_date=date(2024, 1, 2),
        start_bar=_bar(date(2024, 1, 2), 100.0),
        forward_bars=[_bar(date(2024, 1, 3), end_close)],
    )

    assert result.eval_status == "evaluated"
    assert result.outcome == expected_outcome
    assert result.direction_correct is expected_correct


def test_evaluator_hold_is_observational() -> None:
    result = SkillOpinionOutcomeEvaluator.evaluate(
        signal="hold",
        horizon="1d",
        analysis_date=date(2024, 1, 2),
        start_bar=_bar(date(2024, 1, 2), 100.0),
        forward_bars=[_bar(date(2024, 1, 3), 105.0)],
    )

    assert result.eval_status == "observational"
    assert result.outcome == "observational"
    assert result.direction_correct is None
    assert result.directional_return_pct is None


def test_effective_daily_bar_date_requires_exact_start_bar(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        context_snapshot=_effective_snapshot("2024-01-03"),
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[
            (date(2024, 1, 2), 100.0),
            (date(2024, 1, 4), 105.0),
        ],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "pending"
    assert item["unable_reason"] == "missing_start_bar"
    assert item["start_trade_date"] is None


@pytest.mark.parametrize(
    ("phase_summary", "expected_reason"),
    [
        (
            {
                "phase": "postmarket",
                "market": "cn",
                "effective_daily_bar_date": "invalid",
            },
            "invalid_effective_daily_bar_date",
        ),
        (
            {
                "phase": "postmarket",
                "market": "cn",
                "effective_daily_bar_date": "2024-01-09",
            },
            "future_effective_daily_bar_date",
        ),
        (
            {
                "phase": "postmarket",
                "market": "cn",
                "effective_daily_bar_date": "2024-01-06",
            },
            "invalid_effective_daily_bar_date",
        ),
        (
            {"phase": "postmarket", "market": "us"},
            "invalid_market_phase_context",
        ),
        (
            {"phase": "unknown", "market": "cn"},
            "unresolvable_expected_start_date",
        ),
    ],
)
def test_permanently_invalid_start_metadata_is_terminal_unable(
    isolated_db,
    phase_summary,
    expected_reason,
) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code="600519.SH",
        context_snapshot={
            "enhanced_context": {"date": "2024-01-08"},
            "market_phase_summary": phase_summary,
        },
    )
    service = SkillOpinionOutcomeService(db_manager=isolated_db)

    item = service.run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "unable"
    assert item["unable_reason"] == expected_reason
    assert item["analysis_date"] == "2024-01-08"
    assert item["start_trade_date"] is None
    assert item["start_price"] is None
    assert service.run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["processed_keys"] == 0


def test_outcome_rebuilds_legacy_cn_snapshot_before_using_effective_date(
    isolated_db,
) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code="7203.T",
        context_snapshot={
            "enhanced_context": {"date": "2026-01-01"},
            "market_phase_summary": {
                "market": "cn",
                "phase": "postmarket",
                "market_local_time": "2026-01-01T10:00:00+08:00",
                "session_date": "2026-01-01",
                "effective_daily_bar_date": "2025-12-31",
                "is_trading_day": True,
                "is_market_open_now": False,
                "is_partial_bar": False,
                "trigger_source": "scheduled_job",
                "analysis_intent": "postmarket",
                "warnings": ["legacy_snapshot"],
            },
        },
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    _seed_bars(
        isolated_db,
        code="7203.T",
        bars=[
            (date(2025, 12, 30), 100.0),
            (date(2026, 1, 5), 105.0),
        ],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "evaluated"
    assert item["start_trade_date"] == "2025-12-30"
    assert item["end_trade_date"] == "2026-01-05"
    assert item["start_price"] == pytest.approx(100.0)
    assert item["end_close"] == pytest.approx(105.0)


def test_outcome_reuses_resolver_to_choose_newest_complete_equivalent_window(
    isolated_db,
) -> None:
    """Regression for the stale-first-candidate blocker raised on PR #2069."""

    _, sample_id = _add_sample(
        isolated_db,
        code="600519.SH",
        context_snapshot={
            "enhanced_context": {"date": "2024-01-07"},
            "market_phase_summary": {
                "phase": "non_trading",
                "market": "cn",
            },
        },
    )
    _seed_bars(
        isolated_db,
        code="600519.SH",
        bars=[(date(2024, 1, 2), 50.0)],
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[
            (date(2024, 1, 5), 100.0),
            (date(2024, 1, 8), 105.0),
        ],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "evaluated"
    assert item["start_trade_date"] == "2024-01-05"
    assert item["end_trade_date"] == "2024-01-08"
    assert item["start_price"] == pytest.approx(100.0)
    assert item["stock_return_pct"] == pytest.approx(5.0)


def test_outcome_rejects_all_stale_equivalent_windows(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code="600517.SH",
        context_snapshot={
            "enhanced_context": {"date": "2024-01-07"},
            "market_phase_summary": {
                "phase": "non_trading",
                "market": "cn",
                "effective_daily_bar_date": "2024-01-05",
            },
        },
    )
    _seed_bars(
        isolated_db,
        code="600517.SH",
        bars=[
            (date(2020, 1, 2), 50.0),
            (date(2024, 1, 8), 55.0),
        ],
    )
    _seed_bars(
        isolated_db,
        code="600517",
        bars=[
            (date(2021, 1, 4), 60.0),
            (date(2024, 1, 9), 65.0),
        ],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "pending"
    assert item["unable_reason"] == "missing_start_bar"
    assert item["analysis_date"] == "2024-01-07"
    assert item["start_trade_date"] is None
    assert item["end_trade_date"] is None
    assert item["start_price"] is None
    assert item["end_close"] is None
    assert item["stock_return_pct"] is None


def test_outcome_invalid_stock_code_fails_closed(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code="600519.SZ",
        context_snapshot=_effective_snapshot("2024-01-05"),
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "unable"
    assert item["unable_reason"] == "invalid_stock_code"
    assert item["start_trade_date"] is None
    assert item["start_price"] is None


def test_outcome_never_combines_start_and_forward_bars_across_code_shapes(
    isolated_db,
) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code="600519.SH",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _seed_bars(
        isolated_db,
        code="600519.SH",
        bars=[(date(2024, 1, 2), 100.0)],
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[(date(2024, 1, 3), 105.0)],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "pending"
    assert item["unable_reason"] == "insufficient_future_data"
    assert item["start_trade_date"] == "2024-01-02"
    assert item["end_trade_date"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"horizons": []},
        {"skill_id": "   "},
        {"stock_code": ""},
        {"limit": 0},
        {"limit": 1.5},
        {"limit": 501},
    ],
)
def test_explicit_empty_or_out_of_range_filters_fail_closed(
    isolated_db,
    kwargs,
) -> None:
    _, sample_id = _add_sample(isolated_db)
    service = SkillOpinionOutcomeService(db_manager=isolated_db)

    with pytest.raises(ValueError):
        service.run_outcomes(sample_id=sample_id, **kwargs)

    with isolated_db.get_session() as session:
        assert session.query(SkillOpinionOutcomeRecord).count() == 0


def test_each_skill_uses_its_own_signal_not_history_decision(isolated_db) -> None:
    history_id, buy_sample_id = _add_sample(
        isolated_db,
        signal="buy",
        skill_id="buyer",
        operation_advice="hold",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    with isolated_db.session_scope() as session:
        sell_sample = SkillOpinionSampleRecord(
            analysis_history_id=history_id,
            stock_code="600519",
            skill_id="seller",
            signal="sell",
            confidence=0.8,
            sample_schema_version="skill-opinion-sample-v1",
        )
        session.add(sell_sample)
        session.flush()
        sell_sample_id = int(sell_sample.id)
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[
            (date(2024, 1, 2), 100.0),
            (date(2024, 1, 3), 105.0),
        ],
    )

    result = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        analysis_history_id=history_id,
        horizons=["1d"],
        limit=2,
    )
    by_sample = {item["skill_opinion_sample_id"]: item for item in result["items"]}

    assert by_sample[buy_sample_id]["outcome"] == "hit"
    assert by_sample[sell_sample_id]["outcome"] == "miss"


def test_pending_is_retried_but_terminal_outcome_is_immutable(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _seed_bars(isolated_db, code="600519", bars=[(date(2024, 1, 2), 100.0)])
    service = SkillOpinionOutcomeService(db_manager=isolated_db)

    pending = service.run_outcomes(sample_id=sample_id, horizons=["1d"])["items"][0]
    assert pending["eval_status"] == "pending"

    _seed_bars(isolated_db, code="600519", bars=[(date(2024, 1, 3), 105.0)])
    evaluated = service.run_outcomes(sample_id=sample_id, horizons=["1d"])["items"][0]
    assert evaluated["eval_status"] == "evaluated"
    assert evaluated["stock_return_pct"] == pytest.approx(5.0)

    with isolated_db.session_scope() as session:
        bar = session.query(StockDaily).filter_by(
            code="600519",
            date=date(2024, 1, 3),
        ).one()
        bar.close = 90.0
    assert service.run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["processed_keys"] == 0
    assert _stored_outcome(isolated_db, sample_id).stock_return_pct == pytest.approx(5.0)


def test_old_pending_retry_is_not_starved_by_new_missing_candidates(
    isolated_db,
) -> None:
    _, pending_sample_id = _add_sample(isolated_db, skill_id="pending")
    _, missing_sample_id = _add_sample(isolated_db, skill_id="missing")
    repo = SkillOpinionOutcomeRepository(isolated_db)
    pending_fields = {
        "skill_opinion_sample_id": pending_sample_id,
        "horizon": "1d",
        "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        "eval_status": "pending",
        "outcome": None,
        "direction_correct": None,
        "unable_reason": "insufficient_future_data",
    }
    repo.persist_outcome(pending_fields)

    with isolated_db.session_scope() as session:
        pending_outcome = session.query(SkillOpinionOutcomeRecord).filter_by(
            skill_opinion_sample_id=pending_sample_id,
            horizon="1d",
            engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        ).one()
        pending_outcome.updated_at = datetime(2024, 1, 1, 12, 0, 0)
        session.get(SkillOpinionSampleRecord, missing_sample_id).created_at = datetime(
            2024, 1, 2, 12, 0, 0
        )

    first = repo.list_candidate_keys(
        horizons=["1d"],
        engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        limit=1,
    )
    assert [item.sample.id for item in first] == [pending_sample_id]

    repo.persist_outcome(pending_fields)
    second = repo.list_candidate_keys(
        horizons=["1d"],
        engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        limit=1,
    )
    assert [item.sample.id for item in second] == [missing_sample_id]


@pytest.mark.parametrize("existing_pending", [False, True])
def test_failed_candidate_attempt_rotates_behind_newer_missing_candidate(
    isolated_db,
    monkeypatch,
    existing_pending,
) -> None:
    _, failed_sample_id = _add_sample(isolated_db, skill_id="failed")
    _, missing_sample_id = _add_sample(isolated_db, skill_id="missing")
    repo = SkillOpinionOutcomeRepository(isolated_db)
    if existing_pending:
        repo.persist_outcome(
            {
                "skill_opinion_sample_id": failed_sample_id,
                "horizon": "1d",
                "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
                "eval_status": "pending",
                "outcome": None,
                "direction_correct": None,
                "unable_reason": "insufficient_future_data",
            }
        )

    with isolated_db.session_scope() as session:
        session.get(SkillOpinionSampleRecord, failed_sample_id).created_at = datetime(
            2024, 1, 1, 12, 0, 0
        )
        session.get(SkillOpinionSampleRecord, missing_sample_id).created_at = datetime(
            2024, 1, 2, 12, 0, 0
        )
        if existing_pending:
            session.query(SkillOpinionOutcomeRecord).filter_by(
                skill_opinion_sample_id=failed_sample_id,
                horizon="1d",
                engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
            ).one().updated_at = datetime(2024, 1, 1, 12, 0, 0)

    service = SkillOpinionOutcomeService(db_manager=isolated_db)

    def raise_transient_failure(_candidate):
        raise RuntimeError("transient evaluator failure")

    monkeypatch.setattr(
        service,
        "_evaluate_candidate",
        raise_transient_failure,
    )

    result = service.run_outcomes(horizons=["1d"], limit=1)

    assert result["failed"] == 1
    retry_marker = _stored_outcome(isolated_db, failed_sample_id)
    assert retry_marker is not None
    assert retry_marker.eval_status == "pending"
    next_candidates = repo.list_candidate_keys(
        horizons=["1d"],
        engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        limit=1,
    )
    assert [item.sample.id for item in next_candidates] == [missing_sample_id]


def test_history_deletion_removes_outcomes_before_samples(isolated_db) -> None:
    history_id, sample_id = _add_sample(isolated_db)
    repo = SkillOpinionOutcomeRepository(isolated_db)
    repo.persist_outcome(
        {
            "skill_opinion_sample_id": sample_id,
            "horizon": "1d",
            "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
            "eval_status": "pending",
            "outcome": None,
            "direction_correct": None,
            "unable_reason": "insufficient_future_data",
        }
    )

    assert isolated_db.delete_analysis_history_records([history_id]) == 1
    with isolated_db.get_session() as session:
        assert session.query(SkillOpinionOutcomeRecord).count() == 0
        assert session.query(SkillOpinionSampleRecord).count() == 0


def test_engine_version_is_part_of_identity_and_terminal_rows_are_immutable(
    isolated_db,
) -> None:
    _, sample_id = _add_sample(isolated_db)
    repo = SkillOpinionOutcomeRepository(isolated_db)
    base = {
        "skill_opinion_sample_id": sample_id,
        "horizon": "1d",
        "eval_status": "evaluated",
        "outcome": "hit",
        "direction_correct": True,
        "unable_reason": None,
        "stock_return_pct": 5.0,
        "directional_return_pct": 5.0,
    }

    _, first = repo.persist_outcome({**base, "engine_version": "engine-v1"})
    _, repeated = repo.persist_outcome(
        {
            **base,
            "engine_version": "engine-v1",
            "outcome": "miss",
            "direction_correct": False,
        }
    )
    _, second = repo.persist_outcome({**base, "engine_version": "engine-v2"})

    assert (first, repeated, second) == ("created", "skipped", "created")
    with isolated_db.get_session() as session:
        assert session.query(SkillOpinionOutcomeRecord).count() == 2


def test_outcome_schema_enforces_identity_and_state_values(isolated_db) -> None:
    Base.metadata.create_all(isolated_db._engine)
    inspector = inspect(isolated_db._engine)
    unique_constraints = inspector.get_unique_constraints("skill_opinion_outcomes")
    checks = {
        item["name"] for item in inspector.get_check_constraints("skill_opinion_outcomes")
    }

    assert any(
        item["name"] == "uix_skill_opinion_outcome_key"
        and item["column_names"]
        == ["skill_opinion_sample_id", "horizon", "engine_version"]
        for item in unique_constraints
    )
    assert checks >= {
        "ck_skill_opinion_outcome_horizon",
        "ck_skill_opinion_outcome_eval_status",
        "ck_skill_opinion_outcome_value",
        "ck_skill_opinion_outcome_state_fields",
    }

    _, sample_id = _add_sample(isolated_db)
    with pytest.raises(IntegrityError):
        with isolated_db.session_scope() as session:
            session.add(
                SkillOpinionOutcomeRecord(
                    skill_opinion_sample_id=sample_id,
                    horizon="20d",
                    engine_version="invalid",
                    eval_status="pending",
                )
            )
