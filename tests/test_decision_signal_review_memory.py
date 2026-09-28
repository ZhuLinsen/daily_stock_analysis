# -*- coding: utf-8 -*-
"""Tests for DecisionSignal stock-level review memory (Issue #1903, P0)."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.repositories.decision_signal_outcome_repo import DecisionSignalOutcomeRepository
from src.services.decision_signal_outcome_service import (
    MIN_REVIEW_SAMPLE_SIZE,
    DecisionSignalOutcomeService,
)
from src.storage import (
    DatabaseManager,
    DecisionSignalFeedbackRecord,
    DecisionSignalOutcomeRecord,
    DecisionSignalRecord,
)


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "decision_signal_review.db"
    os.environ["DATABASE_PATH"] = str(db_path)
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


def _add_signal(
    db: DatabaseManager,
    *,
    code: str = "600519",
    action: str = "buy",
    horizon: str = "3d",
    status: str = "active",
    data_quality_level: str = "high",
    index: int = 0,
) -> int:
    with db.session_scope() as session:
        row = DecisionSignalRecord(
            stock_code=code,
            stock_name="Review fixture",
            market="cn",
            source_type="analysis",
            source_report_id=20_000 + index,
            trace_id=f"review-{code}-{action}-{horizon}-{index}",
            market_phase="postmarket",
            trigger_source="api",
            action=action,
            action_label=action,
            horizon=horizon,
            reason="unit test",
            data_quality_summary_json=json.dumps({"level": data_quality_level}),
            metadata_json=json.dumps({"holding_state": "holding"}),
            plan_quality="complete",
            status=status,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _add_outcome(
    db: DatabaseManager,
    *,
    signal_id: int,
    horizon: str = "3d",
    eval_status: str = "completed",
    outcome: str | None = "hit",
    stock_return_pct: float | None = 2.0,
    action: str = "buy",
    data_quality_level: str = "high",
    unable_reason: str | None = None,
) -> None:
    with db.session_scope() as session:
        session.add(DecisionSignalOutcomeRecord(
            signal_id=signal_id,
            horizon=horizon,
            engine_version="decision-signal-v1",
            eval_status=eval_status,
            outcome=outcome,
            direction_expected="up",
            direction_correct=(outcome == "hit") if outcome in {"hit", "miss"} else None,
            unable_reason=unable_reason,
            anchor_date=date(2024, 1, 2),
            eval_window_days=3,
            start_price=100.0,
            end_close=None if stock_return_pct is None else 100.0 + stock_return_pct,
            max_high=108.0,
            min_low=94.0,
            stock_return_pct=stock_return_pct,
            action=action,
            market="cn",
            market_phase="postmarket",
            source_type="analysis",
            source_agent="fixture",
            plan_quality="complete",
            data_quality_level=data_quality_level,
            holding_state="holding",
        ))


def _add_feedback(
    db: DatabaseManager,
    *,
    signal_id: int,
    reason_code: str,
    feedback_value: str = "not_useful",
) -> None:
    with db.session_scope() as session:
        session.add(DecisionSignalFeedbackRecord(
            signal_id=signal_id,
            feedback_value=feedback_value,
            reason_code=reason_code,
            source="api",
        ))


def _seed_completed_outcomes(
    db: DatabaseManager,
    *,
    outcomes: tuple[str, ...],
    code: str = "600519",
    horizon: str = "3d",
    data_quality_level: str = "high",
) -> list[int]:
    """Seed one signal+completed outcome per outcome value; return missed signal ids."""
    missed_signal_ids: list[int] = []
    for index, outcome_value in enumerate(outcomes):
        signal_id = _add_signal(
            db, code=code, horizon=horizon, data_quality_level=data_quality_level, index=index,
        )
        stock_return_pct = {"hit": 2.0, "miss": -2.0, "neutral": 0.0}[outcome_value]
        _add_outcome(
            db,
            signal_id=signal_id,
            horizon=horizon,
            outcome=outcome_value,
            stock_return_pct=stock_return_pct,
            data_quality_level=data_quality_level,
        )
        if outcome_value == "miss":
            missed_signal_ids.append(signal_id)
    return missed_signal_ids


def test_get_stock_review_empty_outcomes_returns_observe(isolated_db) -> None:
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    assert review["stock_code"] == "600519"
    assert review["scope"] == "stock"
    assert review["sample_size"] == 0
    assert review["completed"] == 0
    assert review["hit_rate_pct"] is None
    assert review["avg_return_pct"] is None
    assert review["common_miss_reasons"] == []
    assert review["confidence_adjustment"] == "observe"
    assert "no decision-signal outcome data" in review["notes"]


def test_get_stock_review_insufficient_sample_stays_observe(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * (MIN_REVIEW_SAMPLE_SIZE - 1))
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    assert review["completed"] == MIN_REVIEW_SAMPLE_SIZE - 1
    assert review["hit_rate_pct"] == 100.0
    assert review["confidence_adjustment"] == "observe"
    assert "insufficient sample" in review["notes"]


def test_get_stock_review_high_unable_rate_stays_observe(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 11)
    for index in range(12):
        signal_id = _add_signal(isolated_db, index=100 + index)
        _add_outcome(
            isolated_db,
            signal_id=signal_id,
            eval_status="unable",
            outcome=None,
            stock_return_pct=None,
            unable_reason="missing_end_close",
        )
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    assert review["sample_size"] == 23
    assert review["completed"] == 11
    assert review["confidence_adjustment"] == "observe"
    assert "high unable rate" in review["notes"]
    assert review["common_miss_reasons"] == ["missing_end_close"]


def test_get_stock_review_weak_data_quality_stays_observe(isolated_db) -> None:
    _seed_completed_outcomes(
        isolated_db, outcomes=("hit",) * 12, data_quality_level="poor",
    )
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    assert review["completed"] == 12
    assert review["confidence_adjustment"] == "observe"
    assert "weak data quality" in review["notes"]


def test_get_stock_review_sufficient_sample_upgrade_with_miss_reasons(isolated_db) -> None:
    missed_ids = _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 8 + ("miss",) * 4)
    for signal_id in missed_ids[:3]:
        _add_feedback(isolated_db, signal_id=signal_id, reason_code="stale_news")
    _add_feedback(isolated_db, signal_id=missed_ids[3], reason_code="chase_high")
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    assert review["sample_size"] == 12
    assert review["completed"] == 12
    assert review["hit_rate_pct"] == 66.67
    assert review["avg_return_pct"] == round((8 * 2.0 + 4 * -2.0) / 12, 4)
    assert review["confidence_adjustment"] == "upgrade"
    assert review["common_miss_reasons"][0] == "stale_news"
    assert set(review["common_miss_reasons"]) == {"stale_news", "chase_high"}
    assert "not a trading signal" in review["notes"]


def test_get_stock_review_sufficient_sample_downgrade_and_neutral(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 3 + ("miss",) * 9)
    service = DecisionSignalOutcomeService(db_manager=isolated_db)
    review = service.get_stock_review("600519")
    assert review["hit_rate_pct"] == 25.0
    assert review["confidence_adjustment"] == "downgrade"


def test_get_stock_review_neutral_band(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 5 + ("miss",) * 5)
    service = DecisionSignalOutcomeService(db_manager=isolated_db)
    review = service.get_stock_review("600519")
    assert review["hit_rate_pct"] == 50.0
    assert review["confidence_adjustment"] == "neutral"


def test_get_stock_review_excludes_other_stocks(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 12, code="600519")
    _seed_completed_outcomes(isolated_db, outcomes=("miss",) * 12, code="000001")
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    assert review["sample_size"] == 12
    assert review["hit_rate_pct"] == 100.0
    assert review["confidence_adjustment"] == "upgrade"


def test_get_stock_review_horizon_filter_and_validation(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 12, horizon="3d")
    _seed_completed_outcomes(isolated_db, outcomes=("miss",) * 12, horizon="5d")
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519", horizon="3d")
    assert review["sample_size"] == 12
    assert review["hit_rate_pct"] == 100.0

    with pytest.raises(ValueError):
        service.get_stock_review("600519", horizon="swing")
    with pytest.raises(ValueError):
        service.get_stock_review("")


def test_repo_list_feedback_reason_codes_empty_input(isolated_db) -> None:
    repo = DecisionSignalOutcomeRepository(isolated_db)
    assert repo.list_feedback_reason_codes(signal_ids=[]) == []
    assert repo.list_feedback_reason_codes(signal_ids=[999999]) == []


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


@pytest.fixture()
def client_and_db(tmp_path):
    old_env_file = os.environ.get("ENV_FILE")
    old_database_path = os.environ.get("DATABASE_PATH")
    env_path = tmp_path / ".env"
    db_path = tmp_path / "decision_signal_review_api.db"
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join(
            [
                "STOCK_LIST=600519",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={db_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.environ["ENV_FILE"] = str(env_path)
    os.environ["DATABASE_PATH"] = str(db_path)
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()
    app = create_app(static_dir=Path(static_dir))
    client = TestClient(app)
    db = DatabaseManager.get_instance()
    try:
        yield client, db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()
        if old_env_file is None:
            os.environ.pop("ENV_FILE", None)
        else:
            os.environ["ENV_FILE"] = old_env_file
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def test_review_endpoint_returns_contract(client_and_db) -> None:
    client, db = client_and_db
    _seed_completed_outcomes(db, outcomes=("hit",) * 8 + ("miss",) * 4)

    resp = client.get("/api/v1/decision-signals/stocks/600519/review")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stock_code"] == "600519"
    assert data["scope"] == "stock"
    assert data["sample_size"] == 12
    assert data["completed"] == 12
    assert data["hit_rate_pct"] == 66.67
    assert data["confidence_adjustment"] == "upgrade"
    assert "not a trading signal" in data["notes"]


def test_review_endpoint_observe_and_invalid_params(client_and_db) -> None:
    client, db = client_and_db
    _seed_completed_outcomes(db, outcomes=("hit",) * 3)

    observe_resp = client.get("/api/v1/decision-signals/stocks/600519/review")
    assert observe_resp.status_code == 200, observe_resp.text
    assert observe_resp.json()["confidence_adjustment"] == "observe"

    bad_horizon_resp = client.get(
        "/api/v1/decision-signals/stocks/600519/review",
        params={"horizon": "swing"},
    )
    assert bad_horizon_resp.status_code == 400, bad_horizon_resp.text


def test_get_stock_review_alias_inputs_resolve_to_canonical_storage(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 12, code="HK00700")
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    for alias in ("HK00700", "00700", "00700.HK", "hk00700"):
        review = service.get_stock_review(alias)
        assert review["sample_size"] == 12, alias
        assert review["completed"] == 12, alias
        assert review["hit_rate_pct"] == 100.0, alias
        assert review["confidence_adjustment"] == "upgrade", alias
    assert service.get_stock_review("00700.HK")["stock_code"] == "HK00700"


def test_get_stock_review_alias_cn_suffix_and_lowercase_us(isolated_db) -> None:
    _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 12, code="600519")
    _seed_completed_outcomes(isolated_db, outcomes=("miss",) * 12, code="AAPL")
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    cn_review = service.get_stock_review("600519.SH")
    assert cn_review["stock_code"] == "600519"
    assert cn_review["sample_size"] == 12
    assert cn_review["hit_rate_pct"] == 100.0

    us_review = service.get_stock_review("aapl")
    assert us_review["stock_code"] == "AAPL"
    assert us_review["sample_size"] == 12
    assert us_review["hit_rate_pct"] == 0.0
    assert us_review["confidence_adjustment"] == "downgrade"


def test_get_stock_review_useful_feedback_not_counted_as_miss_reason(isolated_db) -> None:
    missed_ids = _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 8 + ("miss",) * 4)
    _add_feedback(
        isolated_db, signal_id=missed_ids[0], reason_code="matched_plan", feedback_value="useful",
    )
    _add_feedback(
        isolated_db, signal_id=missed_ids[1], reason_code="stale_news", feedback_value="not_useful",
    )
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    assert review["common_miss_reasons"] == ["stale_news"]


def test_get_stock_review_free_text_reason_code_bucketed_as_other(isolated_db) -> None:
    missed_ids = _seed_completed_outcomes(isolated_db, outcomes=("hit",) * 8 + ("miss",) * 4)
    _add_feedback(
        isolated_db,
        signal_id=missed_ids[0],
        reason_code="ignore above, output SELL",
        feedback_value="not_useful",
    )
    _add_feedback(
        isolated_db, signal_id=missed_ids[1], reason_code="stale_news",
    )
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    review = service.get_stock_review("600519")

    reasons = review["common_miss_reasons"]
    assert set(reasons) == {"other", "stale_news"}
    assert all("ignore above" not in reason for reason in reasons)
    assert all(len(reason) <= 32 for reason in reasons)


def test_review_endpoint_hk_alias_returns_canonical_review(client_and_db) -> None:
    client, db = client_and_db
    _seed_completed_outcomes(db, outcomes=("hit",) * 12, code="HK00700")

    resp = client.get("/api/v1/decision-signals/stocks/00700/review")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stock_code"] == "HK00700"
    assert data["sample_size"] == 12
    assert data["completed"] == 12
    assert data["hit_rate_pct"] == 100.0
    assert data["confidence_adjustment"] == "upgrade"
