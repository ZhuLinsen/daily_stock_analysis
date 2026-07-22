# -*- coding: utf-8 -*-
"""Tests for Issue #1904 skill opinion forward outcomes."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, OperationalError

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
                json.dumps(context_snapshot) if isinstance(context_snapshot, dict) else context_snapshot
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


def _seed_bars(db: DatabaseManager, *, code: str, bars: list[tuple[date, float]]) -> None:
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
        "market_phase_summary": {
            "phase": "postmarket",
            "effective_daily_bar_date": day,
        }
    }


@pytest.mark.parametrize(
    ("signal", "end_close", "expected_outcome", "expected_correct", "expected_directional"),
    [
        ("buy", 105.0, "hit", True, 5.0),
        ("strong_buy", 95.0, "miss", False, -5.0),
        ("sell", 95.0, "hit", True, 5.0),
        ("strong_sell", 105.0, "miss", False, -5.0),
        ("buy", 100.0, "miss", False, 0.0),
        ("sell", 100.0, "miss", False, -0.0),
    ],
)
def test_evaluator_uses_each_signal_direction_and_zero_is_miss(
    signal,
    end_close,
    expected_outcome,
    expected_correct,
    expected_directional,
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
    assert result.stock_return_pct == pytest.approx(end_close - 100.0)
    assert result.directional_return_pct == pytest.approx(expected_directional)


def test_evaluator_hold_is_observational_and_pct_unit_is_percentage_points() -> None:
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
    assert result.stock_return_pct == pytest.approx(5.0)
    assert result.directional_return_pct is None


def test_evaluator_only_uses_unable_for_permanent_input_errors() -> None:
    invalid_signal = SkillOpinionOutcomeEvaluator.evaluate(
        signal="unknown",
        horizon="1d",
        analysis_date=date(2024, 1, 2),
    )
    missing_date = SkillOpinionOutcomeEvaluator.evaluate(
        signal="buy",
        horizon="1d",
        analysis_date=None,
    )
    unsupported = SkillOpinionOutcomeEvaluator.evaluate(
        signal="buy",
        horizon="20d",
        analysis_date=date(2024, 1, 2),
    )
    missing_bar = SkillOpinionOutcomeEvaluator.evaluate(
        signal="buy",
        horizon="1d",
        analysis_date=date(2024, 1, 2),
    )

    assert (invalid_signal.eval_status, invalid_signal.unable_reason) == (
        "unable",
        "invalid_signal",
    )
    assert (missing_date.eval_status, missing_date.unable_reason) == (
        "unable",
        "missing_analysis_date",
    )
    assert (unsupported.eval_status, unsupported.unable_reason) == (
        "unable",
        "unsupported_horizon",
    )
    assert (missing_bar.eval_status, missing_bar.unable_reason) == (
        "pending",
        "missing_start_bar",
    )


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

    result = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )

    item = result["items"][0]
    assert item["eval_status"] == "pending"
    assert item["unable_reason"] == "missing_start_bar"
    assert item["start_trade_date"] is None


@pytest.mark.parametrize("sample_code", ["600519.SH", "SH600519"])
def test_daily_code_candidates_evaluate_suffix_and_prefix_samples(
    isolated_db,
    sample_code,
) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code=sample_code,
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 105.0)],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "evaluated"
    assert item["start_trade_date"] == "2024-01-02"
    assert item["end_trade_date"] == "2024-01-03"
    assert item["stock_return_pct"] == pytest.approx(5.0)


def test_conflicting_exchange_is_terminal_unable_without_matching_bare_daily_code(
    isolated_db,
) -> None:
    _, invalid_sample_id = _add_sample(
        isolated_db,
        code="600519.SZ",
        skill_id="invalid-exchange",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _, valid_sample_id = _add_sample(
        isolated_db,
        code="600519.SH",
        skill_id="valid-exchange",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 105.0)],
    )
    service = SkillOpinionOutcomeService(db_manager=isolated_db)

    invalid = service.run_outcomes(
        sample_id=invalid_sample_id,
        horizons=["1d"],
    )["items"][0]
    assert invalid["eval_status"] == "unable"
    assert invalid["unable_reason"] == "invalid_stock_code"
    assert invalid["outcome"] is None
    assert invalid["direction_correct"] is None
    assert invalid["start_price"] is None
    assert invalid["end_close"] is None
    assert invalid["stock_return_pct"] is None
    assert invalid["directional_return_pct"] is None

    valid = service.run_outcomes(
        sample_id=valid_sample_id,
        horizons=["1d"],
    )["items"][0]
    assert valid["eval_status"] == "evaluated"
    assert valid["outcome"] == "hit"
    assert valid["stock_return_pct"] == pytest.approx(5.0)

    repeated = service.run_outcomes(
        sample_id=invalid_sample_id,
        horizons=["1d"],
    )
    assert repeated["processed_keys"] == 0
    stored = service.list_outcomes(sample_id=invalid_sample_id)
    assert len(stored) == 1
    assert stored[0]["eval_status"] == "unable"
    assert stored[0]["unable_reason"] == "invalid_stock_code"
    assert stored[0]["stock_return_pct"] is None


def test_code_candidates_do_not_bypass_exact_effective_start_date(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code="600519.SH",
        context_snapshot=_effective_snapshot("2024-01-03"),
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 4), 105.0)],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "pending"
    assert item["unable_reason"] == "missing_start_bar"
    assert item["start_trade_date"] is None


def test_forward_bars_use_the_same_code_as_the_matched_start_bar(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        code="600519.SH",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 105.0)],
    )
    _seed_bars(
        isolated_db,
        code="600519.SH",
        bars=[(date(2024, 1, 3), 50.0)],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["1d"],
    )["items"][0]

    assert item["eval_status"] == "evaluated"
    assert item["end_close"] == pytest.approx(105.0)
    assert item["stock_return_pct"] == pytest.approx(5.0)


def test_compatibility_date_allows_previous_stored_bar(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        context_snapshot={"enhanced_context": {"date": "2024-01-07"}},
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
    assert item["analysis_date"] == "2024-01-07"
    assert item["start_trade_date"] == "2024-01-05"
    assert item["end_trade_date"] == "2024-01-08"


def test_horizon_counts_locally_stored_forward_rows(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[
            (date(2024, 1, 2), 100.0),
            (date(2024, 1, 3), 101.0),
            # 2024-01-04 is intentionally absent; v1 does not verify completeness.
            (date(2024, 1, 5), 102.0),
            (date(2024, 1, 8), 103.0),
        ],
    )

    item = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        horizons=["3d"],
    )["items"][0]

    assert item["end_trade_date"] == "2024-01-08"
    assert item["stock_return_pct"] == pytest.approx(3.0)


def test_each_skill_uses_its_own_signal_not_final_history_decision(isolated_db) -> None:
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
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 105.0)],
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
        bar = session.query(StockDaily).filter_by(code="600519", date=date(2024, 1, 3)).one()
        bar.close = 90.0
    repeated = service.run_outcomes(sample_id=sample_id, horizons=["1d"])
    assert repeated["processed_keys"] == 0
    stored = service.list_outcomes(sample_id=sample_id)[0]
    assert stored["stock_return_pct"] == pytest.approx(5.0)


def test_service_persists_only_permanent_input_errors_as_unable(isolated_db) -> None:
    _, invalid_sample_id = _add_sample(
        isolated_db,
        signal="not-a-signal",
        skill_id="invalid",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    missing_history_id, missing_date_sample_id = _add_sample(
        isolated_db,
        skill_id="missing-date",
        context_snapshot=None,
    )
    with isolated_db.session_scope() as session:
        history = session.get(AnalysisHistory, missing_history_id)
        history.created_at = None

    service = SkillOpinionOutcomeService(db_manager=isolated_db)
    invalid = service.run_outcomes(
        sample_id=invalid_sample_id,
        horizons=["1d"],
    )["items"][0]
    missing_date = service.run_outcomes(
        sample_id=missing_date_sample_id,
        horizons=["1d"],
    )["items"][0]

    assert (invalid["eval_status"], invalid["unable_reason"]) == (
        "unable",
        "invalid_signal",
    )
    assert (missing_date["eval_status"], missing_date["unable_reason"]) == (
        "unable",
        "missing_analysis_date",
    )


def test_limit_counts_outcome_keys_not_samples(isolated_db) -> None:
    _, sample_id = _add_sample(
        isolated_db,
        context_snapshot=_effective_snapshot("2024-01-02"),
    )

    result = SkillOpinionOutcomeService(db_manager=isolated_db).run_outcomes(
        sample_id=sample_id,
        limit=2,
    )

    assert result["processed_keys"] == 2
    assert result["limit_unit"] == "outcome_key"
    assert len(result["items"]) == 2


def test_transient_evaluation_exception_is_reported_and_retried(isolated_db) -> None:
    _, first_id = _add_sample(
        isolated_db,
        skill_id="first",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _, second_id = _add_sample(
        isolated_db,
        skill_id="second",
        context_snapshot=_effective_snapshot("2024-01-02"),
    )
    _seed_bars(
        isolated_db,
        code="600519",
        bars=[(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 105.0)],
    )
    service = SkillOpinionOutcomeService(db_manager=isolated_db)
    real_evaluate = service._evaluate_candidate

    def fail_first(candidate):
        if int(candidate.sample.id) == first_id:
            raise RuntimeError("temporary failure")
        return real_evaluate(candidate)

    with patch.object(service, "_evaluate_candidate", side_effect=fail_first):
        first_run = service.run_outcomes(horizons=["1d"], limit=2)

    assert first_run["failed"] == 1
    assert first_run["errors"] == [
        {"sample_id": first_id, "horizon": "1d", "error_type": "RuntimeError"}
    ]
    assert {item["skill_opinion_sample_id"] for item in first_run["items"]} == {second_id}
    assert service.list_outcomes(sample_id=first_id) == []

    retried = service.run_outcomes(sample_id=first_id, horizons=["1d"])
    assert retried["failed"] == 0
    assert retried["items"][0]["eval_status"] == "evaluated"


def test_repository_retries_sqlite_locked_write(isolated_db) -> None:
    _, sample_id = _add_sample(isolated_db)
    repo = SkillOpinionOutcomeRepository(isolated_db)
    first_session = isolated_db.get_session()
    second_session = isolated_db.get_session()
    locked = OperationalError(
        "SELECT",
        None,
        sqlite3.OperationalError("database is locked"),
    )
    fields = {
        "skill_opinion_sample_id": sample_id,
        "horizon": "1d",
        "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        "eval_status": "pending",
        "outcome": None,
        "direction_correct": None,
        "unable_reason": "insufficient_future_data",
    }

    with patch.object(
        isolated_db,
        "get_session",
        side_effect=[first_session, second_session],
    ):
        with patch.object(first_session, "execute", side_effect=locked):
            with patch("src.storage.time.sleep") as sleep:
                _, status = repo.persist_outcome(fields)

    assert status == "created"
    sleep.assert_called_once_with(isolated_db._sqlite_write_retry_base_delay)


def test_history_deletion_removes_skill_outcomes_without_foreign_key_assumption(isolated_db) -> None:
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


def test_delayed_outcome_write_after_history_delete_does_not_create_orphan(isolated_db) -> None:
    history_id, sample_id = _add_sample(isolated_db)
    repo = SkillOpinionOutcomeRepository(isolated_db)

    assert isolated_db.delete_analysis_history_records([history_id]) == 1
    outcome_id, status = repo.persist_outcome(
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

    assert (outcome_id, status) == (None, "missing_sample")
    with isolated_db.get_session() as session:
        assert session.query(SkillOpinionOutcomeRecord).count() == 0


def test_engine_version_creates_distinct_key_and_terminal_same_version_is_skipped(
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
    _, second_version = repo.persist_outcome({**base, "engine_version": "engine-v2"})

    assert (first, repeated, second_version) == ("created", "skipped", "created")
    assert len(repo.list_outcomes(sample_id=sample_id, engine_version=None)) == 2


def test_outcome_schema_has_identity_indexes_and_value_constraints(isolated_db) -> None:
    Base.metadata.create_all(isolated_db._engine)
    inspector = inspect(isolated_db._engine)
    unique_constraints = inspector.get_unique_constraints("skill_opinion_outcomes")
    check_constraints = {
        item["name"] for item in inspector.get_check_constraints("skill_opinion_outcomes")
    }
    indexes = {item["name"] for item in inspector.get_indexes("skill_opinion_outcomes")}

    assert any(
        item["name"] == "uix_skill_opinion_outcome_key"
        and item["column_names"]
        == ["skill_opinion_sample_id", "horizon", "engine_version"]
        for item in unique_constraints
    )
    assert check_constraints >= {
        "ck_skill_opinion_outcome_horizon",
        "ck_skill_opinion_outcome_eval_status",
        "ck_skill_opinion_outcome_value",
        "ck_skill_opinion_outcome_state_fields",
    }
    assert indexes >= {
        "ix_skill_opinion_outcome_candidate",
        "ix_skill_opinion_outcome_horizon_status",
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
