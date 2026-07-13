# -*- coding: utf-8 -*-
"""Tests for DecisionSignal P5 outcome service."""

from __future__ import annotations

import json
import os
from datetime import date, datetime

import pytest

from src.config import Config
from src.services.decision_signal_outcome_service import DecisionSignalOutcomeService
from src.storage import DatabaseManager, DecisionSignalOutcomeRecord, DecisionSignalRecord, StockDaily


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "decision_signal_outcome.db"
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
    market: str = "cn",
    action: str = "buy",
    horizon: str = "3d",
    session_date: str = "2024-01-02",
    status: str = "active",
) -> int:
    with db.session_scope() as session:
        row = DecisionSignalRecord(
            stock_code=code,
            stock_name="贵州茅台",
            market=market,
            source_type="analysis",
            source_report_id=1001,
            trace_id=f"trace-{market}-{code}-{action}-{horizon}-{session_date}",
            market_phase="postmarket",
            trigger_source="api",
            action=action,
            action_label=action,
            horizon=horizon,
            reason="unit test",
            data_quality_summary_json=json.dumps({"level": "good"}),
            metadata_json=json.dumps({
                "market_phase_summary": {"session_date": session_date},
                "holding_state": "holding",
            }),
            plan_quality="complete",
            status=status,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _seed_bars(
    db: DatabaseManager,
    *,
    code: str = "600519",
    anchor: date = date(2024, 1, 2),
    start_close: float = 100.0,
    closes: list[float],
) -> None:
    with db.session_scope() as session:
        session.add(StockDaily(code=code, date=anchor, open=start_close, high=start_close, low=start_close, close=start_close))
        for index, close in enumerate(closes, start=1):
            session.add(
                StockDaily(
                    code=code,
                    date=date(2024, 1, 2 + index),
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                )
            )


def _set_outcome_updated_at(
    db: DatabaseManager,
    *,
    signal_id: int,
    horizon: str,
    updated_at: datetime,
) -> None:
    with db.session_scope() as session:
        row = (
            session.query(DecisionSignalOutcomeRecord)
            .filter_by(signal_id=signal_id, horizon=horizon)
            .one()
        )
        row.created_at = updated_at
        row.updated_at = updated_at


def test_run_outcomes_evaluates_supported_horizons_and_stats(isolated_db) -> None:
    signal_id = _add_signal(isolated_db, action="buy", horizon="3d")
    _seed_bars(isolated_db, closes=[103, 104, 105, 106, 107, 108, 109, 110, 111, 112])
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    result = service.run_outcomes(signal_id=signal_id, horizons=["1d", "3d", "5d", "10d"])

    assert result["evaluated"] == 4
    assert result["created"] == 4
    assert result["skipped"] == 0
    by_horizon = {item["horizon"]: item for item in result["items"]}
    assert by_horizon["1d"]["outcome"] == "hit"
    assert by_horizon["3d"]["stock_return_pct"] == 5.0
    assert by_horizon["10d"]["eval_window_days"] == 10
    assert by_horizon["10d"]["holding_state"] == "holding"
    assert by_horizon["10d"]["data_quality_level"] == "good"

    stats = service.get_stats(horizons=["1d", "3d", "5d", "10d"])
    assert stats["total"] == 4
    assert stats["hit"] == 4
    assert stats["breakdowns"]["action"][0]["value"] == "buy"
    assert stats["breakdowns"]["holding_state"][0]["value"] == "holding"


def test_stats_default_statuses_exclude_archived(isolated_db) -> None:
    service = DecisionSignalOutcomeService(db_manager=isolated_db)
    signal_ids = [
        _add_signal(isolated_db, code="600519", status="active", horizon="1d"),
        _add_signal(isolated_db, code="000001", status="expired", horizon="1d"),
        _add_signal(isolated_db, code="000002", status="invalidated", horizon="1d"),
        _add_signal(isolated_db, code="000003", status="closed", horizon="1d"),
        _add_signal(isolated_db, code="000004", status="archived", horizon="1d"),
    ]
    for signal_id, code in zip(signal_ids, ["600519", "000001", "000002", "000003", "000004"]):
        _seed_bars(isolated_db, code=code, closes=[103.0])
        service.run_outcomes(signal_id=signal_id, horizons=["1d"])

    default_stats = service.get_stats(horizons=["1d"])
    archived_stats = service.get_stats(horizons=["1d"], statuses=["archived"])

    assert default_stats["statuses"] == ["active", "expired", "invalidated", "closed"]
    assert default_stats["total"] == 4
    assert default_stats["hit"] == 4
    assert archived_stats["statuses"] == ["archived"]
    assert archived_stats["total"] == 1


def test_stock_code_filter_uses_hk_aliases_without_widening_market_filter(isolated_db) -> None:
    hk_id = _add_signal(isolated_db, code="HK00700", market="hk", horizon="1d")
    cn_id = _add_signal(isolated_db, code="00700", market="cn", horizon="1d")
    _seed_bars(isolated_db, code="HK00700", closes=[104.0])
    _seed_bars(isolated_db, code="00700", closes=[102.0])
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    broad = service.run_outcomes(stock_code="00700", horizons=["1d"], limit=10)
    forced = service.run_outcomes(stock_code="00700", horizons=["1d"], force=True, limit=10)
    hk_only = service.run_outcomes(stock_code="00700", market="hk", horizons=["1d"], force=True, limit=10)

    assert {item["signal_id"] for item in broad["items"]} == {hk_id, cn_id}
    assert {item["signal_id"] for item in forced["items"]} == {hk_id, cn_id}
    assert [item["signal_id"] for item in hk_only["items"]] == [hk_id]
    assert hk_only["evaluated"] == 1


def test_not_up_uses_defensive_direction_not_down_direction(isolated_db) -> None:
    reduce_hit_id = _add_signal(isolated_db, code="600519", action="reduce", horizon="3d")
    reduce_miss_id = _add_signal(isolated_db, code="000001", action="reduce", horizon="3d")
    _seed_bars(isolated_db, code="600519", closes=[100.5, 101.0, 101.5])
    _seed_bars(isolated_db, code="000001", closes=[101.0, 102.0, 103.0])
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    hit = service.run_outcomes(signal_id=reduce_hit_id)["items"][0]
    miss = service.run_outcomes(signal_id=reduce_miss_id)["items"][0]

    assert hit["direction_expected"] == "not_up"
    assert hit["outcome"] == "hit"
    assert miss["direction_expected"] == "not_up"
    assert miss["outcome"] == "miss"


def test_unable_reasons_are_persisted_for_non_directional_and_unsupported_horizon(isolated_db) -> None:
    watch_id = _add_signal(isolated_db, action="watch", horizon="3d")
    intraday_buy_id = _add_signal(isolated_db, code="000001", action="buy", horizon="intraday")
    _seed_bars(isolated_db, code="600519", closes=[103, 104, 105])
    _seed_bars(isolated_db, code="000001", closes=[103, 104, 105])
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    watch = service.run_outcomes(signal_id=watch_id)["items"][0]
    intraday = service.run_outcomes(signal_id=intraday_buy_id)["items"][0]
    watch_skipped = service.run_outcomes(signal_id=watch_id)
    intraday_skipped = service.run_outcomes(signal_id=intraday_buy_id)

    assert watch["eval_status"] == "unable"
    assert watch["unable_reason"] == "non_directional_action"
    assert intraday["eval_status"] == "unable"
    assert intraday["unable_reason"] == "unsupported_horizon"
    assert watch_skipped["evaluated"] == 0
    assert watch_skipped["skipped"] == 1
    assert intraday_skipped["evaluated"] == 0
    assert intraday_skipped["skipped"] == 1


def test_missing_anchor_price_is_retried_after_data_arrives(isolated_db) -> None:
    signal_id = _add_signal(isolated_db, action="buy", horizon="3d", session_date="2024-01-03")
    with isolated_db.session_scope() as session:
        session.add(StockDaily(code="600519", date=date(2024, 1, 2), close=100.0, high=101.0, low=99.0))
        session.add(StockDaily(code="600519", date=date(2024, 1, 4), close=105.0, high=106.0, low=104.0))
        session.add(StockDaily(code="600519", date=date(2024, 1, 5), close=106.0, high=107.0, low=105.0))
        session.add(StockDaily(code="600519", date=date(2024, 1, 6), close=107.0, high=108.0, low=106.0))
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    item = service.run_outcomes(signal_id=signal_id)["items"][0]

    assert item["eval_status"] == "unable"
    assert item["unable_reason"] == "missing_anchor_price"
    assert item["anchor_date"] == "2024-01-03"

    with isolated_db.session_scope() as session:
        session.add(StockDaily(code="600519", date=date(2024, 1, 3), close=100.0, high=101.0, low=99.0))
    retried = service.run_outcomes(signal_id=signal_id)

    assert retried["evaluated"] == 1
    assert retried["updated"] == 1
    assert retried["skipped"] == 0
    assert retried["items"][0]["eval_status"] == "completed"
    assert retried["items"][0]["outcome"] == "hit"


def test_insufficient_forward_bars_and_force_idempotency(isolated_db) -> None:
    insufficient_id = _add_signal(isolated_db, action="buy", horizon="3d", session_date="2024-01-10")
    with isolated_db.session_scope() as session:
        session.add(StockDaily(code="600519", date=date(2024, 1, 10), close=100.0, high=101.0, low=99.0))
        session.add(StockDaily(code="600519", date=date(2024, 1, 11), close=103.0, high=104.0, low=102.0))
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    insufficient = service.run_outcomes(signal_id=insufficient_id)["items"][0]
    retried_still_unable = service.run_outcomes(signal_id=insufficient_id)

    assert insufficient["unable_reason"] == "insufficient_forward_bars"
    assert retried_still_unable["evaluated"] == 1
    assert retried_still_unable["updated"] == 1
    assert retried_still_unable["items"][0]["unable_reason"] == "insufficient_forward_bars"

    with isolated_db.session_scope() as session:
        session.add(StockDaily(code="600519", date=date(2024, 1, 12), close=104.0, high=105.0, low=103.0))
        session.add(StockDaily(code="600519", date=date(2024, 1, 13), close=105.0, high=106.0, low=104.0))
    retried_completed = service.run_outcomes(signal_id=insufficient_id)

    assert retried_completed["evaluated"] == 1
    assert retried_completed["updated"] == 1
    assert retried_completed["items"][0]["eval_status"] == "completed"
    assert retried_completed["items"][0]["stock_return_pct"] == 5.0

    complete_id = _add_signal(isolated_db, code="000001", action="buy", horizon="3d", session_date="2024-01-02")
    _seed_bars(isolated_db, code="000001", closes=[103, 104, 105])
    first = service.run_outcomes(signal_id=complete_id)["items"][0]
    repeated = service.run_outcomes(signal_id=complete_id)
    with isolated_db.session_scope() as session:
        row = session.query(StockDaily).filter_by(code="000001", date=date(2024, 1, 5)).one()
        row.close = 110.0
        row.high = 111.0
    forced = service.run_outcomes(signal_id=complete_id, force=True)["items"][0]

    assert first["stock_return_pct"] == 5.0
    assert repeated["evaluated"] == 0
    assert repeated["skipped"] == 1
    assert forced["stock_return_pct"] == 10.0


def test_batch_progresses_past_completed_outcomes(isolated_db) -> None:
    older_missing_id = _add_signal(isolated_db, code="000010", action="buy", horizon="1d")
    newer_completed_id = _add_signal(isolated_db, code="000011", action="buy", horizon="1d")
    _seed_bars(isolated_db, code="000011", closes=[103.0])
    service = DecisionSignalOutcomeService(db_manager=isolated_db)
    service.run_outcomes(signal_id=newer_completed_id, horizons=["1d"])
    _seed_bars(isolated_db, code="000010", closes=[104.0])

    result = service.run_outcomes(horizons=["1d"], limit=1)

    assert result["evaluated"] == 1
    assert result["created"] == 1
    assert result["skipped"] == 0
    assert result["items"][0]["signal_id"] == older_missing_id


def test_batch_prioritizes_missing_before_retryable_unable(isolated_db) -> None:
    older_missing_id = _add_signal(isolated_db, code="000020", action="buy", horizon="1d")
    newer_retryable_id = _add_signal(isolated_db, code="000021", action="buy", horizon="3d", session_date="2024-01-10")
    with isolated_db.session_scope() as session:
        session.add(StockDaily(code="000021", date=date(2024, 1, 10), close=100.0, high=101.0, low=99.0))
        session.add(StockDaily(code="000021", date=date(2024, 1, 11), close=103.0, high=104.0, low=102.0))
    service = DecisionSignalOutcomeService(db_manager=isolated_db)
    retryable = service.run_outcomes(signal_id=newer_retryable_id)["items"][0]
    _seed_bars(isolated_db, code="000020", closes=[104.0])

    first_batch = service.run_outcomes(limit=1)
    second_batch = service.run_outcomes(limit=1)

    assert retryable["unable_reason"] == "insufficient_forward_bars"
    assert first_batch["evaluated"] == 1
    assert first_batch["created"] == 1
    assert first_batch["items"][0]["signal_id"] == older_missing_id
    assert second_batch["evaluated"] == 1
    assert second_batch["updated"] == 1
    assert second_batch["items"][0]["signal_id"] == newer_retryable_id
    assert second_batch["items"][0]["unable_reason"] == "insufficient_forward_bars"


def test_batch_rotates_retryable_unable_by_oldest_retry_timestamp(isolated_db) -> None:
    oldest_retryable_id = _add_signal(
        isolated_db,
        code="000030",
        action="buy",
        horizon="3d",
        session_date="2024-01-10",
    )
    newer_retryable_id = _add_signal(
        isolated_db,
        code="000031",
        action="buy",
        horizon="3d",
        session_date="2024-01-10",
    )
    for code in ("000030", "000031"):
        with isolated_db.session_scope() as session:
            session.add(StockDaily(code=code, date=date(2024, 1, 10), close=100.0, high=101.0, low=99.0))
            session.add(StockDaily(code=code, date=date(2024, 1, 11), close=103.0, high=104.0, low=102.0))
    service = DecisionSignalOutcomeService(db_manager=isolated_db)
    service.run_outcomes(signal_id=oldest_retryable_id)
    service.run_outcomes(signal_id=newer_retryable_id)
    _set_outcome_updated_at(
        isolated_db,
        signal_id=oldest_retryable_id,
        horizon="3d",
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
    )
    _set_outcome_updated_at(
        isolated_db,
        signal_id=newer_retryable_id,
        horizon="3d",
        updated_at=datetime(2024, 1, 2, 12, 0, 0),
    )

    first_batch = service.run_outcomes(limit=1)
    second_batch = service.run_outcomes(limit=1)

    assert first_batch["updated"] == 1
    assert first_batch["items"][0]["signal_id"] == oldest_retryable_id
    assert second_batch["updated"] == 1
    assert second_batch["items"][0]["signal_id"] == newer_retryable_id


def test_batch_uses_oldest_retryable_horizon_timestamp_for_signal_order(isolated_db) -> None:
    multi_horizon_id = _add_signal(
        isolated_db,
        code="000040",
        action="buy",
        horizon="1d",
        session_date="2024-01-10",
    )
    newer_retryable_id = _add_signal(
        isolated_db,
        code="000041",
        action="buy",
        horizon="1d",
        session_date="2024-01-10",
    )
    for code in ("000040", "000041"):
        with isolated_db.session_scope() as session:
            session.add(StockDaily(code=code, date=date(2024, 1, 10), close=100.0, high=101.0, low=99.0))
    service = DecisionSignalOutcomeService(db_manager=isolated_db)
    service.run_outcomes(signal_id=multi_horizon_id, horizons=["1d", "3d"])
    service.run_outcomes(signal_id=newer_retryable_id, horizons=["1d", "3d"])
    _set_outcome_updated_at(
        isolated_db,
        signal_id=multi_horizon_id,
        horizon="1d",
        updated_at=datetime(2024, 1, 5, 12, 0, 0),
    )
    _set_outcome_updated_at(
        isolated_db,
        signal_id=multi_horizon_id,
        horizon="3d",
        updated_at=datetime(2024, 1, 1, 12, 0, 0),
    )
    _set_outcome_updated_at(
        isolated_db,
        signal_id=newer_retryable_id,
        horizon="1d",
        updated_at=datetime(2024, 1, 3, 12, 0, 0),
    )
    _set_outcome_updated_at(
        isolated_db,
        signal_id=newer_retryable_id,
        horizon="3d",
        updated_at=datetime(2024, 1, 4, 12, 0, 0),
    )

    result = service.run_outcomes(horizons=["1d", "3d"], limit=1)

    assert result["updated"] == 2
    assert {item["signal_id"] for item in result["items"]} == {multi_horizon_id}
