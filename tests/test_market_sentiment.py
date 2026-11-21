"""Offline checks for provider validation, calculations and the real task queue."""

from datetime import date, datetime, timedelta
import json
from threading import Event
import time
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient as ApiTestClient
import pandas as pd
import pytest

from api.app import create_app
from data_provider import DataFetcherManager, efinance_fetcher
from data_provider.market_sentiment import LimitPool, LimitPoolUnavailable, fetch_limit_pool
from src.config import Config
from src.services import market_sentiment as sentiment
from src.services.task_queue import AnalysisTaskQueue
from src.storage import DatabaseManager, MarketSentimentSnapshot


TARGET = date(2026, 11, 13)
PREVIOUS = date(2026, 11, 12)
BASE = "/api/v1/market-sentiment"


def _pools(kind, day, *, corroborate_for=None):
    if kind == "closed" and day == TARGET:
        return LimitPool({"000001": 2, "000003": 1}, day)
    if kind == "closed" or kind == "previous":
        return LimitPool({"000001": 1, "000002": 1}, corroborate_for or day)
    return LimitPool({}, day)


def test_pool_requires_date_count_and_unique_codes():
    with patch("data_provider.market_sentiment.requests.Session") as factory:
        response = factory.return_value.__enter__.return_value.get.return_value
        for data in (
            {"qdate": 20261112, "tc": 0, "pool": []},
            {"qdate": 20261113, "tc": 1, "pool": []},
            {"qdate": 20261113, "tc": 2, "pool": [{"c": "000001"}, {"c": "000001"}]},
            None,
        ):
            response.json.return_value = {"rc": 0, "data": data}
            with pytest.raises(LimitPoolUnavailable):
                fetch_limit_pool("broken", TARGET)
        response.json.return_value = {"rc": 0, "data": {"qdate": 20261113, "tc": 0, "pool": []}}
        assert fetch_limit_pool("broken", TARGET).boards == {}
        response.json.return_value = {
            "rc": 0, "data": {"qdate": 20261113, "tc": 1, "pool": [{"c": "000001", "ylbc": 2}]},
        }
        assert fetch_limit_pool("previous", TARGET).boards == {"000001": 2}
        response.json.return_value = {
            "rc": 0, "data": {"qdate": 20261113, "tc": 1, "pool": [{"c": "000001", "lbc": 2}]},
        }
        with pytest.raises(LimitPoolUnavailable):
            fetch_limit_pool("closed", PREVIOUS)
        assert fetch_limit_pool("closed", PREVIOUS, corroborate_for=TARGET) == LimitPool({"000001": 2}, TARGET)
        response.json.return_value = {"rc": 0, "data": {"qdate": 20261113, "tc": 0, "pool": []}}
        with pytest.raises(LimitPoolUnavailable):
            fetch_limit_pool("closed", PREVIOUS, corroborate_for=TARGET)


def test_breadth_uses_manager_fallback_but_pool_failures_remain_missing(monkeypatch):
    cache_modes = []

    def fail_stats(*, allow_cache=True):
        cache_modes.append(("primary", allow_cache))
        raise TimeoutError

    data = {"up_count": 7, "down_count": 2, "flat_count": 1, "total_amount": 2.5, "limit_down_count": 6}

    def fallback_stats(*, allow_cache=True):
        cache_modes.append(("fallback", allow_cache))
        return data

    manager = DataFetcherManager(fetchers=[
        SimpleNamespace(name="primary", priority=1, get_market_stats=fail_stats),
        SimpleNamespace(name="fallback", priority=2, get_market_stats=fallback_stats),
    ])
    monkeypatch.setattr(manager, "_get_tickflow_fetcher", lambda: None)
    monkeypatch.setattr(sentiment, "DataFetcherManager", lambda: manager)
    monkeypatch.setattr(sentiment, "get_market_now", lambda _: datetime(2026, 11, 13, 18))
    assert manager.get_market_stats() == data

    def pools(kind, day, **kwargs):
        if kind == "down":
            raise LimitPoolUnavailable
        if kind == "previous":
            return LimitPool({"000001": 1}, day)
        return _pools(kind, day, **kwargs)

    monkeypatch.setattr(sentiment, "fetch_limit_pool", pools)
    snapshot = sentiment.compute_snapshot(TARGET, PREVIOUS)
    assert cache_modes == [("primary", True), ("fallback", True), ("primary", False), ("fallback", False)]
    assert snapshot["quality_status"] == "partial"
    assert snapshot["metrics"]["promotions"] is None
    assert snapshot["metrics"]["limit_up_count"] == 2
    assert snapshot["metrics"]["limit_down_count"] is None
    assert snapshot["metrics"]["break_rate"] == 0
    assert snapshot["metrics"]["advancing_ratio"] == 0.7
    assert snapshot["metrics"]["turnover_yuan"] == 250_000_000
    assert snapshot["provider_trace"]["market_stats"]["provider"] == "fallback"
    monkeypatch.setattr(sentiment, "fetch_limit_pool", _pools)
    checked = sentiment.compute_snapshot(TARGET, PREVIOUS)
    assert checked["quality_status"] == "complete"
    assert checked["completeness"]["board_verified"]
    assert not checked["completeness"]["previous_closed_date_verified"]


@pytest.mark.parametrize("refresh_succeeds", [True, False])
def test_close_snapshot_bypasses_real_efinance_intraday_cache(api, monkeypatch, refresh_succeeds):
    now = datetime(2026, 11, 13, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(sentiment, "get_market_now", lambda _: now)
    monkeypatch.setattr(sentiment, "fetch_limit_pool", _pools)
    monkeypatch.setattr(efinance_fetcher, "time", SimpleNamespace(
        time=now.timestamp, monotonic=time.monotonic,
    ))
    cached = pd.DataFrame({
        "股票代码": ["000001"], "股票名称": ["样例"],
        "最新价": [9.99], "昨日收盘": [10.0], "成交额": [100_000_000.0],
    })
    fresh = cached.assign(最新价=10.01, 成交额=400_000_000.0)
    monkeypatch.setattr(efinance_fetcher, "_realtime_cache", {
        "data": cached, "timestamp": (now - timedelta(minutes=2)).timestamp(), "ttl": 600,
    })
    fetcher = efinance_fetcher.EfinanceFetcher()
    monkeypatch.setattr(fetcher, "_set_random_user_agent", lambda: None)
    monkeypatch.setattr(fetcher, "_enforce_rate_limit", lambda: None)
    manager = DataFetcherManager(fetchers=[fetcher])
    monkeypatch.setattr(manager, "_get_tickflow_fetcher", lambda: None)
    monkeypatch.setattr(sentiment, "DataFetcherManager", lambda: manager)

    with patch.object(efinance_fetcher, "_ef_call_with_timeout") as request:
        if refresh_succeeds:
            request.return_value = fresh
        else:
            request.side_effect = TimeoutError
        assert manager.get_market_stats()["down_count"] == 1
        request.assert_not_called()

        submitted = api.post(f"{BASE}/snapshots")
        assert submitted.status_code == 202, submitted.text
        task = _wait_for_task(api, submitted.json()["task_id"])
        assert task["status"] == "completed", task
        request.assert_called_once()

    record = api.get(f"{BASE}/snapshots/{TARGET}").json()
    metrics = record["metrics"]
    trace = record["provider_trace"]["market_stats"]
    if refresh_succeeds:
        assert record["quality_status"] == "complete"
        assert metrics["advancing_count"] == 1
        assert metrics["declining_count"] == 0
        assert metrics["turnover_yuan"] == 400_000_000
        assert trace["provider"] == "EfinanceFetcher"
        assert trace["collected_at"] == now.isoformat()
    else:
        assert record["quality_status"] == "partial"
        assert metrics["advancing_count"] is None
        assert metrics["declining_count"] is None
        assert metrics["turnover_yuan"] is None
        assert trace["status"] == "source_unavailable"


@pytest.mark.parametrize("overlapping_pools", [True, False])
def test_invalid_pool_relationships_are_reported_without_deriving_wrong_metrics(monkeypatch, overlapping_pools):
    monkeypatch.setattr(sentiment, "get_market_now", lambda _: datetime(2026, 11, 14, 18))

    def pools(kind, day, **kwargs):
        if overlapping_pools and kind == "broken":
            return LimitPool({"000001": None}, day)
        if not overlapping_pools and kind == "closed" and day == TARGET:
            return LimitPool({"000001": 3, "000003": 1}, day)
        return _pools(kind, day, **kwargs)

    monkeypatch.setattr(sentiment, "fetch_limit_pool", pools)
    snapshot = sentiment.compute_snapshot(TARGET, PREVIOUS)
    metrics = snapshot["metrics"]
    assert snapshot["quality_status"] == "partial"
    assert metrics["limit_up_count"] == 2
    if overlapping_pools:
        assert snapshot["provider_trace"]["limit_pools"]["broken"] == "overlaps_closed"
        assert not snapshot["completeness"]["broken_pool_verified"]
        assert metrics["broken_count"] is metrics["break_rate"] is metrics["touched_count"] is None
    else:
        assert snapshot["provider_trace"]["limit_pools"]["closed"] == "available"
        assert not snapshot["completeness"]["board_verified"]
        assert metrics["max_consecutive"] is metrics["limit_up_ladder"] is metrics["promotions"] is None


def test_legacy_snapshot_hides_market_stats_without_collection_time(api):
    payload = {
        "definition_version": sentiment.DEFINITION_VERSION,
        "quality_status": "complete",
        "metrics": {"limit_up_count": 2, "advancing_count": 10, "turnover_yuan": 400_000_000},
        "provider_trace": {"market_stats": {"provider": "EfinanceFetcher", "status": "available"}},
        "completeness": {"board_verified": True},
    }
    db = DatabaseManager.get_instance()
    with db.session_scope() as session:
        session.add(MarketSentimentSnapshot(market="cn", trade_date=PREVIOUS, payload=json.dumps(payload)))

    response = api.get(f"{BASE}/snapshots/{PREVIOUS}")
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["quality_status"] == "partial"
    assert record["metrics"]["limit_up_count"] == 2
    assert record["metrics"]["advancing_count"] is None
    assert record["metrics"]["turnover_yuan"] is None
    assert record["provider_trace"]["market_stats"]["status"] == "freshness_unverified"
    trend = api.get(f"{BASE}/trend", params={"end_date": str(TARGET), "limit": 10})
    assert trend.json()["items"] == [record]
    with db.session_scope() as session:
        assert json.loads(sentiment.get_snapshot(session, PREVIOUS).payload) == payload


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sentiment.sqlite"))
    monkeypatch.setenv("ADMIN_AUTH_ENABLED", "false")
    monkeypatch.setenv("STOCK_INDEX_REMOTE_UPDATE_ENABLED", "false")
    monkeypatch.setenv("DSA_RUNTIME_SCHEDULER_SUPPRESS_START", "true")
    DatabaseManager.reset_instance()
    Config.reset_instance()
    monkeypatch.setattr(AnalysisTaskQueue, "_instance", None)
    queue = AnalysisTaskQueue(max_workers=1)
    monkeypatch.setattr("api.v1.endpoints.market_sentiment.get_task_queue", lambda: queue)
    monkeypatch.setattr(sentiment, "get_market_now", lambda _: datetime(2026, 11, 14, 18))
    try:
        with ApiTestClient(create_app()) as client:
            yield client
    finally:
        queue.shutdown()
        DatabaseManager.reset_instance()
        Config.reset_instance()


def _wait_for_task(client, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = client.get(f"{BASE}/tasks/{task_id}").json()
        if task["status"] in ("completed", "failed"):
            return task
        time.sleep(0.025)
    pytest.fail("Sentiment task did not finish")


def test_trigger_returns_before_fetch_then_completes_after_commit(api, monkeypatch):
    entered, release = Event(), Event()

    def wait_for_provider(kind, day, **kwargs):
        entered.set()
        assert release.wait(5)
        return _pools(kind, day, **kwargs)

    monkeypatch.setattr(sentiment, "fetch_limit_pool", wait_for_provider)
    try:
        response = api.post(f"{BASE}/snapshots")
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert accepted["trade_date"] == str(TARGET)
        assert accepted["status"] == "accepted"
        assert accepted["trace_id"] == accepted["task_id"]
        assert accepted["message"]
        assert entered.wait(2)
        active = api.get(f"{BASE}/tasks/{accepted['task_id']}").json()
        assert active["trace_id"] == accepted["trace_id"]
        assert active["status"] == "processing"
        assert active["result"] is None
        missing = api.get(f"{BASE}/snapshots/{TARGET}")
        assert missing.status_code == 404
        assert missing.json()["error"] == "market_sentiment_snapshot_not_found"
        duplicate = api.post(f"{BASE}/snapshots")
        assert duplicate.status_code == 409
        assert duplicate.json()["error"] == "market_sentiment_in_progress"
    finally:
        release.set()

    task = _wait_for_task(api, accepted["task_id"])
    assert task["status"] == "completed", task
    assert task["progress"] == 100
    assert task["result"] == {"trade_date": str(TARGET), "action": "inserted", "quality_status": "partial"}
    shared_tasks = api.get("/api/v1/analysis/tasks").json()["tasks"]
    shared = next(item for item in shared_tasks if item["task_id"] == accepted["task_id"])
    assert shared["status"] == task["status"]
    assert shared["trace_id"] == task["trace_id"]
    assert shared["report_type"] == "market_sentiment_snapshot"
    snapshot = api.get(f"{BASE}/snapshots/{TARGET}").json()
    assert snapshot["metrics"]["promotions"]["1_to_2"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert snapshot["metrics"]["turnover_yuan"] is None
    assert api.get(f"{BASE}/snapshots").json()["items"] == [snapshot]

    def unexpected_fetch(*_):
        raise AssertionError("An existing snapshot must not trigger another provider request")

    monkeypatch.setattr(sentiment, "fetch_limit_pool", unexpected_fetch)
    retry = api.post(f"{BASE}/snapshots").json()
    assert _wait_for_task(api, retry["task_id"])["result"]["action"] == "unchanged"


def test_source_failure_marks_task_failed_without_writing(api, monkeypatch):
    def fail(*_, **__):
        raise LimitPoolUnavailable

    monkeypatch.setattr(sentiment, "fetch_limit_pool", fail)
    response = api.post(f"{BASE}/snapshots")
    assert response.status_code == 202
    task = _wait_for_task(api, response.json()["task_id"])
    assert task["status"] == "failed"
    assert task["error"] and task["result"] is None
    assert api.get(f"{BASE}/snapshots").json()["items"] == []
    invalid = api.post(f"{BASE}/snapshots", params={"trade_date": "2026-11-16"})
    assert invalid.status_code == 422
    assert invalid.json()["error"] == "invalid_trade_date"


def test_trend_preserves_gaps_and_excludes_incompatible_target_and_future_rows(api):
    days = [(date(2026, 11, 10), "old"), (date(2026, 11, 12), "new"),
            (TARGET, "new"), (date(2026, 11, 16), "new")]
    with DatabaseManager.get_instance().session_scope() as session:
        for trade_date, version in days:
            session.add(MarketSentimentSnapshot(
                market="cn", trade_date=trade_date, payload=json.dumps({
                    "definition_version": version,
                    "quality_status": "partial",
                    "metrics": {"limit_up_count": 1},
                    "provider_trace": {},
                    "completeness": {},
                }),
            ))
    for window in (10, 30, 60):
        response = api.get(f"{BASE}/trend", params={"end_date": str(TARGET), "limit": window})
        assert response.status_code == 200, response.text
        trend = response.json()
        assert len(trend["session_dates"]) == window
        assert len(trend["missing_dates"]) == window - 2
        assert trend["different_definition_dates"] == ["2026-11-10"]
        assert [item["trade_date"] for item in trend["items"]] == ["2026-11-12"]
    assert api.get(f"{BASE}/trend", params={"end_date": "2026-11-16"}).status_code == 422
    assert api.get(f"{BASE}/snapshots/2026-11-16").status_code == 422


def test_api_declares_response_models_and_standard_errors(api, monkeypatch):
    endpoints = api.get("/openapi.json").json()["paths"]
    responses = endpoints[f"{BASE}/snapshots"]["post"]["responses"]
    assert responses["202"]["content"]["application/json"]["schema"]["$ref"].endswith("/MarketSentimentAccepted")
    assert responses["401"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    assert responses["409"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
    assert responses["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")

    with monkeypatch.context() as auth_patch:
        auth_patch.setattr("api.middlewares.auth.is_auth_enabled", lambda: True)
        unauthorized = api.post(f"{BASE}/snapshots")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"] == "unauthorized"

    missing = api.get(f"{BASE}/tasks/missing")
    assert missing.status_code == 404
    assert missing.json()["error"] == "market_sentiment_task_not_found"
    invalid_window = api.get(f"{BASE}/trend", params={"end_date": str(TARGET), "limit": 7})
    assert invalid_window.status_code == 422
    assert invalid_window.json()["error"] == "invalid_trend_window"

    def unavailable():
        raise sentiment.SentimentCalendarUnavailable("A-share trading calendar is unavailable")

    monkeypatch.setattr(sentiment, "latest_closed_session", unavailable)
    response = api.get(f"{BASE}/snapshots")
    assert response.status_code == 503
    assert response.json()["error"] == "trade_calendar_unavailable"
