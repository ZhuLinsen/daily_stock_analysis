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
    decision_profile: str | None = None,
    profile_source: str | None = None,
    metadata_data_quality: str | None = None,
    data_quality_summary_json: str | None = '{"level": "good"}',
) -> int:
    metadata = {
        "market_phase_summary": {"session_date": session_date},
        "holding_state": "holding",
    }
    if profile_source is not None:
        metadata["profile_source"] = profile_source
    if metadata_data_quality is not None:
        metadata["data_quality_level"] = metadata_data_quality
    with db.session_scope() as session:
        row = DecisionSignalRecord(
            stock_code=code,
            stock_name="贵州茅台",
            market=market,
            source_type="analysis",
            source_report_id=1001,
            trace_id=f"trace-{market}-{code}-{action}-{horizon}-{session_date}",
            decision_profile=decision_profile,
            market_phase="postmarket",
            trigger_source="api",
            action=action,
            action_label=action,
            horizon=horizon,
            reason="unit test",
            data_quality_summary_json=data_quality_summary_json,
            metadata_json=json.dumps(metadata),
            plan_quality="complete",
            status=status,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _seed_calibration_outcomes(
    db: DatabaseManager,
    *,
    count: int,
    decision_profile: str | None,
    action: str,
    horizon: str,
    market_phase: str,
    data_quality_level: str,
    profile_source: str | None,
    outcomes: tuple[str, ...] = ("hit",),
) -> None:
    with db.session_scope() as session:
        for index in range(count):
            outcome_value = outcomes[index % len(outcomes)]
            signal = DecisionSignalRecord(
                stock_code=f"T{index:05d}",
                stock_name="Calibration fixture",
                market="cn",
                source_type="analysis",
                source_report_id=10_000 + index,
                trace_id=f"calibration-{decision_profile}-{action}-{horizon}-{profile_source}-{index}",
                decision_profile=decision_profile,
                market_phase=market_phase,
                trigger_source="api",
                action=action,
                action_label=action,
                horizon=horizon,
                reason="deterministic calibration boundary fixture",
                data_quality_summary_json=json.dumps({"level": data_quality_level}),
                metadata_json=json.dumps({"profile_source": profile_source}) if profile_source is not None else None,
                plan_quality="complete",
                status="active",
            )
            session.add(signal)
            session.flush()
            stock_return_pct = {"hit": 2.0, "miss": -2.0, "neutral": 0.0}[outcome_value]
            session.add(DecisionSignalOutcomeRecord(
                signal_id=signal.id,
                horizon=horizon,
                engine_version="decision-signal-v1",
                eval_status="completed",
                outcome=outcome_value,
                direction_expected="not_up" if action in {"sell", "reduce", "avoid"} else "up",
                direction_correct=outcome_value == "hit" if outcome_value != "neutral" else None,
                anchor_date=date(2024, 1, 2),
                eval_window_days=3,
                start_price=100.0,
                end_close=100.0 + stock_return_pct,
                max_high=108.0,
                min_low=94.0,
                stock_return_pct=stock_return_pct,
                action=action,
                market="cn",
                market_phase=market_phase,
                source_type="analysis",
                source_agent="fixture",
                plan_quality="complete",
                data_quality_level=data_quality_level,
                holding_state="holding",
            ))


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


def test_profile_calibration_groups_six_dimensions_and_gates_each_bucket(isolated_db) -> None:
    _seed_calibration_outcomes(
        isolated_db,
        count=30,
        decision_profile="balanced",
        action="buy",
        horizon="3d",
        market_phase="postmarket",
        data_quality_level="good",
        profile_source="auto_default",
        outcomes=("hit", "miss", "neutral"),
    )
    _seed_calibration_outcomes(
        isolated_db,
        count=29,
        decision_profile="balanced",
        action="sell",
        horizon="10d",
        market_phase="postmarket",
        data_quality_level="good",
        profile_source="user_selected",
        outcomes=("hit", "miss"),
    )
    _seed_calibration_outcomes(
        isolated_db,
        count=1,
        decision_profile=None,
        action="hold",
        horizon="5d",
        market_phase="intraday",
        data_quality_level="medium",
        profile_source="legacy_unknown",
    )

    stats = DecisionSignalOutcomeService(db_manager=isolated_db).get_stats()
    calibration = stats["profile_calibration"]
    breakdowns = calibration["breakdowns"]

    assert calibration["minimum_completed_sample_size"] == 30
    assert stats["total"] == 60
    assert stats["completed"] == 60
    assert stats["breakdowns"]["action"][0]["value"] == "buy"
    assert set(breakdowns) == {
        "decision_profile",
        "decision_profile_action",
        "decision_profile_horizon",
        "decision_profile_market_phase",
        "decision_profile_data_quality_level",
        "profile_source",
    }

    expected_dimension_keys = {
        "decision_profile": {"decision_profile"},
        "decision_profile_action": {"decision_profile", "action"},
        "decision_profile_horizon": {"decision_profile", "horizon"},
        "decision_profile_market_phase": {"decision_profile", "market_phase"},
        "decision_profile_data_quality_level": {"decision_profile", "data_quality_level"},
        "profile_source": {"profile_source"},
    }
    for name, buckets in breakdowns.items():
        assert buckets
        assert all(set(bucket["dimensions"]) == expected_dimension_keys[name] for bucket in buckets)

    profile_buckets = {
        bucket["dimensions"]["decision_profile"]: bucket
        for bucket in breakdowns["decision_profile"]
    }
    assert profile_buckets["balanced"]["completed"] == 59
    assert profile_buckets["balanced"]["sample_sufficient"] is True
    assert profile_buckets["unknown"]["completed"] == 1
    assert profile_buckets["unknown"]["sample_sufficient"] is False
    assert profile_buckets["unknown"]["hit_rate_pct"] is None

    action_buckets = {
        (bucket["dimensions"]["decision_profile"], bucket["dimensions"]["action"]): bucket
        for bucket in breakdowns["decision_profile_action"]
    }
    buy = action_buckets[("balanced", "buy")]
    sell = action_buckets[("balanced", "sell")]
    assert buy["completed"] == 30
    assert buy["hit"] == 10
    assert buy["miss"] == 10
    assert buy["neutral"] == 10
    assert buy["sample_sufficient"] is True
    assert buy["hit_rate_pct"] == 50.0
    assert buy["miss_rate_pct"] == 50.0
    assert buy["unable_rate_pct"] == 0.0
    assert buy["avg_stock_return_pct"] == 0.0
    assert buy["max_adverse_excursion_pct"] == 6.0
    assert sell["completed"] == 29
    assert sell["sample_sufficient"] is False
    for metric in (
        "hit_rate_pct",
        "avg_stock_return_pct",
        "miss_rate_pct",
        "unable_rate_pct",
        "max_adverse_excursion_pct",
    ):
        assert sell[metric] is None

    horizon_buckets = {
        (bucket["dimensions"]["decision_profile"], bucket["dimensions"]["horizon"]): bucket
        for bucket in breakdowns["decision_profile_horizon"]
    }
    assert horizon_buckets[("balanced", "3d")]["sample_sufficient"] is True
    assert horizon_buckets[("balanced", "10d")]["sample_sufficient"] is False
    source_buckets = {
        bucket["dimensions"]["profile_source"]: bucket
        for bucket in breakdowns["profile_source"]
    }
    assert source_buckets["auto_default"]["completed"] == 30
    assert source_buckets["auto_default"]["sample_sufficient"] is True
    assert source_buckets["user_selected"]["completed"] == 29
    assert source_buckets["user_selected"]["sample_sufficient"] is False

    filtered = DecisionSignalOutcomeService(db_manager=isolated_db).get_stats(horizons=["3d"])
    filtered_horizons = filtered["profile_calibration"]["breakdowns"]["decision_profile_horizon"]
    assert filtered["total"] == 30
    assert [bucket["dimensions"] for bucket in filtered_horizons] == [
        {"decision_profile": "balanced", "horizon": "3d"},
    ]


@pytest.mark.parametrize(
    ("metadata_json", "expected"),
    [
        ('{"profile_source": "auto_default"}', "auto_default"),
        ('{"profile_source": "backfill_defaulted"}', "backfill_defaulted"),
        ('{"profile_source": "legacy_unknown"}', "legacy_unknown"),
        ('{"profile_source": "user_selected"}', "user_selected"),
        ('{"profile_source": "invalid"}', "unknown"),
        ('{"profile_source": 1}', "unknown"),
        ('["user_selected"]', "unknown"),
        ('{"profile_source":', "unknown"),
        (None, "unknown"),
    ],
)
def test_profile_source_normalization(isolated_db, metadata_json, expected) -> None:
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    assert service._profile_source(metadata_json) == expected


@pytest.mark.parametrize(
    ("summary_json", "metadata_quality", "expected"),
    [
        ('{"level": "good"}', "poor", "good"),
        ('{"level": "unknown"}', "high", "unknown"),
        ('{"data_quality": {"level": "usable"}}', "poor", "usable"),
        ('{}', "usable", "medium"),
        (None, "good", "high"),
        ('{"level":', "good", "unknown"),
        (None, "invalid", "unknown"),
    ],
)
def test_data_quality_snapshot_preserves_summary_and_narrowly_falls_back_to_metadata(
    isolated_db,
    summary_json,
    metadata_quality,
    expected,
) -> None:
    signal = DecisionSignalRecord(
        data_quality_summary_json=summary_json,
        metadata_json=json.dumps({"data_quality_level": metadata_quality}),
    )

    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    assert service._data_quality_level(signal) == expected


def test_real_outcome_uses_metadata_quality_and_profile_source_without_summary(isolated_db) -> None:
    signal_id = _add_signal(
        isolated_db,
        action="hold",
        horizon="3d",
        decision_profile="aggressive",
        profile_source="user_selected",
        metadata_data_quality="good",
        data_quality_summary_json=None,
    )
    _seed_bars(isolated_db, closes=[99.0, 98.0, 101.0])
    service = DecisionSignalOutcomeService(db_manager=isolated_db)

    result = service.run_outcomes(signal_id=signal_id)
    stats = service.get_stats()

    assert result["items"][0]["eval_status"] == "completed"
    assert result["items"][0]["data_quality_level"] == "high"
    profile_bucket = stats["profile_calibration"]["breakdowns"]["decision_profile"][0]
    quality_bucket = stats["profile_calibration"]["breakdowns"]["decision_profile_data_quality_level"][0]
    source_bucket = stats["profile_calibration"]["breakdowns"]["profile_source"][0]
    assert profile_bucket["dimensions"] == {"decision_profile": "aggressive"}
    assert quality_bucket["dimensions"] == {
        "decision_profile": "aggressive",
        "data_quality_level": "high",
    }
    assert source_bucket["dimensions"] == {"profile_source": "user_selected"}
    with isolated_db.session_scope() as session:
        outcome = session.query(DecisionSignalOutcomeRecord).filter_by(signal_id=signal_id).one()
        assert service._row_max_adverse_excursion_pct(outcome) == 3.0


@pytest.mark.parametrize("action", ["buy", "add", "hold", "watch", "alert"])
def test_long_side_max_adverse_excursion_formula(action) -> None:
    row = DecisionSignalOutcomeRecord(action=action, start_price=100.0, min_low=91.5, max_high=110.0)

    assert DecisionSignalOutcomeService._row_max_adverse_excursion_pct(row) == 8.5


@pytest.mark.parametrize("action", ["sell", "reduce", "avoid"])
def test_defensive_max_adverse_excursion_formula(action) -> None:
    row = DecisionSignalOutcomeRecord(action=action, start_price=100.0, min_low=91.5, max_high=112.0)

    assert DecisionSignalOutcomeService._row_max_adverse_excursion_pct(row) == 12.0


@pytest.mark.parametrize(
    "row",
    [
        DecisionSignalOutcomeRecord(action="buy", start_price=None, min_low=90.0),
        DecisionSignalOutcomeRecord(action="buy", start_price=0.0, min_low=90.0),
        DecisionSignalOutcomeRecord(action="buy", start_price=100.0, min_low=float("nan")),
        DecisionSignalOutcomeRecord(action="sell", start_price=100.0, max_high=float("inf")),
        DecisionSignalOutcomeRecord(action="unknown", start_price=100.0, min_low=90.0, max_high=110.0),
    ],
)
def test_max_adverse_excursion_returns_none_for_incomplete_or_invalid_rows(row) -> None:
    assert DecisionSignalOutcomeService._row_max_adverse_excursion_pct(row) is None


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


def test_watch_and_alert_outcomes_remain_unable_without_market_reads(isolated_db) -> None:
    class FailOnMarketRead:
        def get_daily_on_date(self, **_kwargs):
            raise AssertionError("watch/alert outcome must not read anchor prices")

        def get_forward_bars(self, **_kwargs):
            raise AssertionError("watch/alert outcome must not read forward bars")

    watch_id = _add_signal(
        isolated_db,
        code="000101",
        action="watch",
        decision_profile="balanced",
        profile_source="auto_default",
    )
    alert_id = _add_signal(
        isolated_db,
        code="000102",
        action="alert",
        decision_profile="balanced",
        profile_source="auto_default",
    )
    service = DecisionSignalOutcomeService(
        db_manager=isolated_db,
        stock_repo=FailOnMarketRead(),
    )

    watch = service.run_outcomes(signal_id=watch_id)["items"][0]
    alert = service.run_outcomes(signal_id=alert_id)["items"][0]
    stats = service.get_stats()

    assert watch["eval_status"] == "unable"
    assert alert["eval_status"] == "unable"
    assert watch["start_price"] is None
    assert alert["start_price"] is None
    profile_bucket = stats["profile_calibration"]["breakdowns"]["decision_profile"][0]
    assert profile_bucket["completed"] == 0
    assert profile_bucket["total"] == 2
    assert profile_bucket["max_adverse_excursion_pct"] is None


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
