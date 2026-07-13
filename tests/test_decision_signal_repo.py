# -*- coding: utf-8 -*-
"""Repository tests for DecisionSignal P1."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect

from src.config import Config
from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.schemas.decision_profile import normalize_decision_profile_filter
from src.storage import Base, DatabaseManager, DecisionSignalRecord, utc_naive_now


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "decision_signal_repo.db"
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


def _fields(**overrides):
    fields = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "market": "cn",
        "source_type": "analysis",
        "source_agent": "test-agent",
        "source_report_id": 1001,
        "trace_id": "trace-1001",
        "market_phase": "intraday",
        "trigger_source": "api",
        "action": "buy",
        "action_label": "买入",
        "confidence": 0.8,
        "score": 88,
        "horizon": "3d",
        "entry_low": 1680.0,
        "entry_high": 1700.0,
        "stop_loss": 1600.0,
        "target_price": 1850.0,
        "invalidation": "跌破 1600",
        "watch_conditions": "量能继续放大",
        "reason": "趋势增强",
        "risk_summary": "波动加大",
        "catalyst_summary": "业绩披露",
        "evidence_json": '{"items":[]}',
        "data_quality_summary_json": '{"level":"good"}',
        "plan_quality": "complete",
        "status": "active",
        "metadata_json": '{"task_id":"task-1"}',
    }
    fields.update(overrides)
    return fields


def test_create_if_absent_deduplicates_report_and_trace_keys(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)

    row1, created1 = repo.create_if_absent(_fields())
    row2, created2 = repo.create_if_absent(_fields(reason="new reason"))
    assert created1 is True
    assert created2 is False
    assert row2.id == row1.id
    assert row2.reason == "趋势增强"

    different_horizon, horizon_created = repo.create_if_absent(_fields(horizon="10d", target_price=1900))
    assert horizon_created is True
    assert different_horizon.id != row1.id

    different_phase, phase_created = repo.create_if_absent(_fields(market_phase="premarket", target_price=1800))
    assert phase_created is True
    assert different_phase.id != row1.id

    different_market, market_created = repo.create_if_absent(
        _fields(market="hk", stock_code="600519", target_price=1810)
    )
    assert market_created is True
    assert different_market.id != row1.id

    different_source_type, source_type_created = repo.create_if_absent(
        _fields(source_type="manual", trace_id="trace-manual", target_price=1820)
    )
    assert source_type_created is True
    assert different_source_type.id != row1.id

    duplicate_manual, duplicate_manual_created = repo.create_if_absent(
        _fields(source_type="manual", trace_id="trace-manual-new", target_price=1830)
    )
    assert duplicate_manual_created is False
    assert duplicate_manual.id == different_source_type.id

    trace_row1, trace_created1 = repo.create_if_absent(
        _fields(source_report_id=None, trace_id="trace-only", stock_code="000001")
    )
    trace_row2, trace_created2 = repo.create_if_absent(
        _fields(source_report_id=None, trace_id="trace-only", stock_code="000001", reason="ignored")
    )
    assert trace_created1 is True
    assert trace_created2 is False
    assert trace_row2.id == trace_row1.id

    trace_horizon_row, trace_horizon_created = repo.create_if_absent(
        _fields(
            source_report_id=None,
            trace_id="trace-only",
            stock_code="000001",
            horizon="10d",
        )
    )
    assert trace_horizon_created is True
    assert trace_horizon_row.id != trace_row1.id

    trace_source_type_row, trace_source_type_created = repo.create_if_absent(
        _fields(
            source_type="manual",
            source_report_id=None,
            trace_id="trace-only",
            stock_code="000001",
        )
    )
    assert trace_source_type_created is True
    assert trace_source_type_row.id != trace_row1.id

    none_dim_row1, none_dim_created1 = repo.create_if_absent(
        _fields(source_report_id=1002, trace_id="trace-none-dim", horizon=None, market_phase=None)
    )
    none_dim_row2, none_dim_created2 = repo.create_if_absent(
        _fields(source_report_id=1002, trace_id="trace-none-dim", horizon=None, market_phase=None)
    )
    assert none_dim_created1 is True
    assert none_dim_created2 is False
    assert none_dim_row2.id == none_dim_row1.id

    no_key_row1, no_key_created1 = repo.create_if_absent(
        _fields(source_report_id=None, trace_id=None, stock_code="000002")
    )
    no_key_row2, no_key_created2 = repo.create_if_absent(
        _fields(source_report_id=None, trace_id=None, stock_code="000002")
    )
    assert no_key_created1 is True
    assert no_key_created2 is True
    assert no_key_row2.id != no_key_row1.id


def test_create_if_absent_does_not_dedup_same_report_across_profiles(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)

    balanced = repo.create_if_absent(_fields(source_report_id=2351, decision_profile="balanced"))
    aggressive = repo.create_if_absent(
        _fields(source_report_id=2351, trace_id="trace-2351-aggressive", decision_profile="aggressive")
    )
    balanced_duplicate = repo.create_if_absent(
        _fields(source_report_id=2351, trace_id="trace-2351-balanced-retry", decision_profile="balanced")
    )

    assert balanced.created is True
    assert aggressive.created is True
    assert aggressive.row.id != balanced.row.id
    assert balanced_duplicate.created is False
    assert balanced_duplicate.row.id == balanced.row.id

    legacy = repo.create_if_absent(_fields(source_report_id=2352, trace_id="trace-2352-null"))
    balanced_from_legacy_source = repo.create_if_absent(
        _fields(source_report_id=2352, trace_id="trace-2352-balanced", decision_profile="balanced")
    )
    legacy_duplicate = repo.create_if_absent(
        _fields(source_report_id=2352, trace_id="trace-2352-null-retry")
    )
    assert legacy.created is True
    assert balanced_from_legacy_source.created is True
    assert balanced_from_legacy_source.row.id != legacy.row.id
    assert legacy_duplicate.created is False
    assert legacy_duplicate.row.id == legacy.row.id


def test_create_if_absent_relaxed_merge_only_fills_missing_default_dimensions(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)

    original = repo.create_if_absent(
        _fields(
            source_report_id=2401,
            trace_id="trace-relaxed-original",
            horizon=None,
            market_phase=None,
            reason="original reason",
        )
    )
    merged = repo.create_if_absent(
        _fields(
            source_report_id=2401,
            trace_id="trace-relaxed-new",
            horizon="3d",
            market_phase="intraday",
            reason="new reason",
        ),
        allow_relaxed_horizon_fill=True,
    )

    assert original.created is True
    assert merged.created is False
    assert merged.refreshed is True
    assert merged.duplicate is False
    assert merged.row.id == original.row.id
    assert merged.row.horizon == "3d"
    assert merged.row.market_phase == "intraday"
    assert merged.row.reason == "original reason"

    duplicate = repo.create_if_absent(
        _fields(
            source_report_id=2401,
            trace_id="trace-relaxed-duplicate",
            horizon="3d",
            market_phase="intraday",
        ),
        allow_relaxed_horizon_fill=True,
    )
    assert duplicate.created is False
    assert duplicate.refreshed is False
    assert duplicate.duplicate is True
    assert duplicate.row.id == original.row.id

    explicit_horizon = repo.create_if_absent(
        _fields(
            source_report_id=2402,
            trace_id="trace-explicit-horizon-original",
            horizon=None,
            market_phase=None,
        )
    )
    explicit_horizon_new = repo.create_if_absent(
        _fields(
            source_report_id=2402,
            trace_id="trace-explicit-horizon-new",
            horizon="swing",
            market_phase="intraday",
        ),
        allow_relaxed_horizon_fill=False,
    )
    assert explicit_horizon.created is True
    assert explicit_horizon_new.created is True
    assert explicit_horizon_new.row.id != explicit_horizon.row.id

    different_phase = repo.create_if_absent(
        _fields(
            source_report_id=2403,
            trace_id="trace-different-phase-original",
            horizon=None,
            market_phase="postmarket",
        )
    )
    different_phase_new = repo.create_if_absent(
        _fields(
            source_report_id=2403,
            trace_id="trace-different-phase-new",
            horizon="3d",
            market_phase="intraday",
        ),
        allow_relaxed_horizon_fill=True,
    )
    assert different_phase.created is True
    assert different_phase_new.created is True
    assert different_phase_new.row.id != different_phase.row.id


def test_create_if_absent_relaxed_merge_does_not_fill_across_profiles(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)

    original = repo.create_if_absent(
        _fields(
            source_report_id=2411,
            trace_id="trace-relaxed-profile-balanced",
            decision_profile="balanced",
            horizon=None,
            market_phase=None,
        )
    )
    aggressive = repo.create_if_absent(
        _fields(
            source_report_id=2411,
            trace_id="trace-relaxed-profile-aggressive",
            decision_profile="aggressive",
            horizon="3d",
            market_phase="intraday",
        ),
        allow_relaxed_horizon_fill=True,
    )
    balanced_fill = repo.create_if_absent(
        _fields(
            source_report_id=2411,
            trace_id="trace-relaxed-profile-balanced-fill",
            decision_profile="balanced",
            horizon="3d",
            market_phase="intraday",
        ),
        allow_relaxed_horizon_fill=True,
    )

    assert original.created is True
    assert aggressive.created is True
    assert aggressive.row.id != original.row.id
    assert balanced_fill.created is False
    assert balanced_fill.refreshed is True
    assert balanced_fill.row.id == original.row.id
    assert balanced_fill.row.horizon == "3d"
    assert balanced_fill.row.market_phase == "intraday"


def test_create_if_absent_relaxed_merge_skips_terminal_candidates(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)
    closed = repo.create(
        _fields(
            source_report_id=2404,
            trace_id="trace-relaxed-closed",
            horizon=None,
            market_phase=None,
            status="closed",
            reason="closed reason",
        )
    )
    active = repo.create(
        _fields(
            source_report_id=2404,
            trace_id="trace-relaxed-active",
            horizon=None,
            market_phase=None,
            reason="active reason",
        )
    )

    merged = repo.create_if_absent(
        _fields(
            source_report_id=2404,
            trace_id="trace-relaxed-new-active",
            horizon="3d",
            market_phase="intraday",
            reason="new reason",
        ),
        allow_relaxed_horizon_fill=True,
    )

    assert merged.created is False
    assert merged.refreshed is True
    assert merged.row.id == active.id
    assert merged.row.horizon == "3d"
    assert merged.row.market_phase == "intraday"
    assert merged.row.reason == "active reason"

    closed_after = repo.get(closed.id)
    assert closed_after is not None
    assert closed_after.status == "closed"
    assert closed_after.horizon is None
    assert closed_after.market_phase is None


def test_list_latest_status_update_and_lazy_expire(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)
    old_row = repo.create(_fields(source_report_id=2001, trace_id="trace-2001", action="watch"))
    new_row = repo.create(_fields(source_report_id=2002, trace_id="trace-2002", action="buy"))
    expired_row = repo.create(
        _fields(
            source_report_id=2003,
            trace_id="trace-2003",
            action="alert",
            expires_at=utc_naive_now() - timedelta(minutes=1),
        )
    )

    with isolated_db.session_scope() as session:
        session.query(DecisionSignalRecord).filter_by(id=old_row.id).update(
            {"created_at": utc_naive_now() - timedelta(days=1)}
        )

    rows, total = repo.list(stock_codes=["600519"], action="buy", page=1, page_size=10)
    assert total == 1
    assert rows[0].id == new_row.id

    latest = repo.get_latest_active(stock_codes=["600519"], limit=2)
    assert [row.id for row in latest] == [new_row.id, old_row.id]
    assert repo.get(expired_row.id).status == "expired"
    assert repo.expire_due_signals() == 0

    latest_after_expire = repo.get_latest_active(stock_codes=["600519"], limit=2)
    assert [row.id for row in latest_after_expire] == [new_row.id, old_row.id]

    updated = repo.update_status(
        new_row.id,
        status="closed",
        metadata_json='{"closed_by":"test"}',
        replace_metadata=True,
    )
    assert updated.status == "closed"
    assert updated.metadata_json == '{"closed_by":"test"}'
    assert repo.update_status(999999, status="closed") is None


def test_expire_due_signals_normalizes_aware_now(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)
    now_utc = datetime.now(timezone.utc)
    expired_row = repo.create(
        _fields(
            source_report_id=2101,
            trace_id="trace-aware-now-expired",
            expires_at=now_utc - timedelta(minutes=1),
        )
    )
    future_row = repo.create(
        _fields(
            source_report_id=2102,
            trace_id="trace-aware-now-future",
            expires_at=now_utc + timedelta(minutes=1),
        )
    )

    assert repo.expire_due_signals(now=now_utc) == 1
    assert repo.get(expired_row.id).status == "expired"
    assert repo.get(future_row.id).status == "active"


def test_create_and_list_normalize_aware_datetimes(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)

    row = repo.create(
        _fields(
            source_report_id=2201,
            trace_id="trace-aware-fields",
            created_at=datetime(2026, 6, 8, 20, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 8, 20, 0, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=8))),
        )
    )

    assert row.created_at == datetime(2026, 6, 8, 20, 0)
    assert row.updated_at == datetime(2026, 6, 8, 20, 0)
    assert row.expires_at == datetime(2098, 12, 31, 16, 0)
    assert row.created_at.tzinfo is None
    assert row.updated_at.tzinfo is None
    assert row.expires_at.tzinfo is None

    rows, total = repo.list(
        created_from=datetime(2026, 6, 8, 19, 59, tzinfo=timezone.utc),
        created_to=datetime(2026, 6, 8, 20, 1, tzinfo=timezone.utc),
        expires_from=datetime(2098, 12, 31, 15, 59, tzinfo=timezone.utc),
        expires_to=datetime(2098, 12, 31, 16, 1, tzinfo=timezone.utc),
    )
    assert total == 1
    assert rows[0].id == row.id


def test_create_if_absent_refreshes_expired_same_key_only_with_future_active(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)
    expired_row, expired_created = repo.create_if_absent(
        _fields(
            source_report_id=2301,
            trace_id="trace-refresh-original",
            status="expired",
            expires_at=utc_naive_now() - timedelta(days=1),
            reason="old reason",
            target_price=1800,
        )
    )
    original_created_at = expired_row.created_at

    refreshed_row, refreshed_created = repo.create_if_absent(
        _fields(
            source_report_id=2301,
            trace_id="trace-refresh-new",
            source_agent="new-agent",
            trigger_source="alert",
            status="active",
            expires_at=utc_naive_now() + timedelta(days=2),
            reason="fresh reason",
            target_price=1900,
        )
    )

    assert expired_created is True
    assert refreshed_created is False
    assert refreshed_row.id == expired_row.id
    assert refreshed_row.status == "active"
    assert refreshed_row.reason == "fresh reason"
    assert refreshed_row.target_price == 1900
    assert refreshed_row.source_type == "analysis"
    assert refreshed_row.source_agent == "test-agent"
    assert refreshed_row.trace_id == "trace-refresh-original"
    assert refreshed_row.trigger_source == "api"
    assert refreshed_row.created_at == original_created_at

    different_source_type_row, different_source_type_created = repo.create_if_absent(
        _fields(
            source_report_id=2301,
            trace_id="trace-refresh-agent",
            source_type="agent",
            source_agent="new-agent",
            trigger_source="alert",
            status="active",
            expires_at=utc_naive_now() + timedelta(days=2),
            reason="agent reason",
            target_price=1950,
        )
    )
    assert different_source_type_created is True
    assert different_source_type_row.id != expired_row.id
    assert different_source_type_row.source_type == "agent"

    past_row, past_created = repo.create_if_absent(
        _fields(
            source_report_id=2302,
            trace_id="trace-refresh-past",
            status="expired",
            expires_at=utc_naive_now() - timedelta(days=1),
            reason="past old",
        )
    )
    still_expired, still_expired_created = repo.create_if_absent(
        _fields(
            source_report_id=2302,
            trace_id="trace-refresh-past-new",
            status="active",
            expires_at=utc_naive_now() - timedelta(minutes=1),
            reason="past fresh",
        )
    )
    assert past_created is True
    assert still_expired_created is False
    assert still_expired.id == past_row.id
    assert still_expired.status == "expired"
    assert still_expired.reason == "past old"

    closed_row, closed_created = repo.create_if_absent(
        _fields(
            source_report_id=2303,
            trace_id="trace-refresh-closed",
            status="closed",
            expires_at=utc_naive_now() - timedelta(days=1),
            reason="closed old",
        )
    )
    still_closed, still_closed_created = repo.create_if_absent(
        _fields(
            source_report_id=2303,
            trace_id="trace-refresh-closed-new",
            status="active",
            expires_at=utc_naive_now() + timedelta(days=2),
            reason="closed fresh",
        )
    )
    assert closed_created is True
    assert still_closed_created is False
    assert still_closed.id == closed_row.id
    assert still_closed.status == "closed"
    assert still_closed.reason == "closed old"


def test_create_if_absent_expired_refresh_keeps_profile_identity(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)
    expired_balanced = repo.create_if_absent(
        _fields(
            source_report_id=2361,
            trace_id="trace-refresh-profile-balanced",
            decision_profile="balanced",
            status="expired",
            expires_at=utc_naive_now() - timedelta(days=1),
            reason="old balanced",
        )
    )

    aggressive = repo.create_if_absent(
        _fields(
            source_report_id=2361,
            trace_id="trace-refresh-profile-aggressive",
            decision_profile="aggressive",
            status="active",
            expires_at=utc_naive_now() + timedelta(days=1),
            reason="new aggressive",
        )
    )
    refreshed_balanced = repo.create_if_absent(
        _fields(
            source_report_id=2361,
            trace_id="trace-refresh-profile-balanced-new",
            decision_profile="balanced",
            status="active",
            expires_at=utc_naive_now() + timedelta(days=1),
            reason="new balanced",
        )
    )

    assert expired_balanced.created is True
    assert aggressive.created is True
    assert aggressive.row.id != expired_balanced.row.id
    assert refreshed_balanced.created is False
    assert refreshed_balanced.refreshed is True
    assert refreshed_balanced.row.id == expired_balanced.row.id
    assert refreshed_balanced.row.decision_profile == "balanced"
    assert refreshed_balanced.row.reason == "new balanced"


def test_profile_filters_and_active_action_lookup_are_null_safe(isolated_db) -> None:
    repo = DecisionSignalRepository(isolated_db)
    legacy_buy = repo.create(_fields(source_report_id=2371, trace_id="trace-profile-null", decision_profile=None))
    balanced_buy = repo.create(
        _fields(source_report_id=2372, trace_id="trace-profile-balanced", decision_profile="balanced")
    )
    aggressive_buy = repo.create(
        _fields(source_report_id=2373, trace_id="trace-profile-aggressive", decision_profile="aggressive")
    )
    repo.create(_fields(source_report_id=2374, trace_id="trace-profile-balanced-sell", action="sell", decision_profile="balanced"))

    all_rows, all_total = repo.list(
        stock_codes=["600519"],
        decision_profile_filter=normalize_decision_profile_filter(None),
        page=1,
        page_size=10,
    )
    unknown_rows, unknown_total = repo.list(
        stock_codes=["600519"],
        decision_profile_filter=normalize_decision_profile_filter("unknown"),
        page=1,
        page_size=10,
    )
    balanced_rows, balanced_total = repo.list(
        stock_codes=["600519"],
        action="buy",
        decision_profile_filter=normalize_decision_profile_filter("balanced"),
        page=1,
        page_size=10,
    )

    assert all_total == 4
    assert {row.id for row in all_rows} >= {legacy_buy.id, balanced_buy.id, aggressive_buy.id}
    assert unknown_total == 1
    assert unknown_rows[0].id == legacy_buy.id
    assert balanced_total == 1
    assert balanced_rows[0].id == balanced_buy.id

    legacy_active = repo.list_active_by_stock_actions(
        market="cn",
        stock_code="600519",
        actions=["buy"],
        decision_profile=None,
    )
    balanced_active = repo.list_active_by_stock_actions(
        market="cn",
        stock_code="600519",
        actions=["buy"],
        decision_profile="balanced",
    )
    assert [row.id for row in legacy_active] == [legacy_buy.id]
    assert [row.id for row in balanced_active] == [balanced_buy.id]


def test_create_all_is_idempotent_and_indexes_exist(isolated_db) -> None:
    Base.metadata.create_all(isolated_db._engine)
    Base.metadata.create_all(isolated_db._engine)

    index_names = {
        item["name"]
        for item in inspect(isolated_db._engine).get_indexes("decision_signals")
    }
    assert "ix_decision_signal_stock_status_time" in index_names
    assert "ix_decision_signal_market_status_time" in index_names
    assert "ix_decision_signal_report_type_market_stock_action_horizon_phase" in index_names
    assert "ix_decision_signal_trace_type_market_stock_action_horizon_phase" in index_names
    assert "ix_decision_signal_market_stock_profile_created" in index_names
    assert "ix_decision_signal_report_type_market_stock_profile_action_horizon_phase" in index_names
    assert "ix_decision_signal_trace_type_market_stock_profile_action_horizon_phase" in index_names
