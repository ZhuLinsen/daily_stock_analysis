"""Daily freshness through real cache, DSA bridge, features, and risk overlay."""

from contextlib import contextmanager
from datetime import datetime
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from src.core import trading_calendar
from src.services.screening import daily, snapshot_us
from src.services.screening.models import Pick
from src.services.screening.risk import apply_risk_overlay
from src.services import screening_service


def _freeze_time(monkeypatch, value):
    now = datetime.fromisoformat(value)
    build_context = trading_calendar.build_market_phase_context
    monkeypatch.setattr(
        daily, "build_market_phase_context",
        lambda *, market, current_time=None: build_context(market=market, current_time=current_time or now),
    )
    monkeypatch.setattr(daily.time, "time", lambda: now.timestamp())
    return now


@contextmanager
def _timezone(name):
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = name
        time.tzset()
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def _history(last_date, code="000001"):
    market = trading_calendar.get_market_for_stock(code)
    calendar = trading_calendar.xcals.get_calendar(trading_calendar.MARKET_EXCHANGE[market])
    dates = calendar.sessions[calendar.sessions <= pd.Timestamp(last_date)][-65:]
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 1000.0,
    })


def _cache(tmp_path, hist, acquired_at, code="000001", source="tencent"):
    path = daily._daily_history_cache_path(tmp_path, code=code, source=source, lookback_days=120)
    daily._write_daily_history_cache(path, hist, code=code, source=source, lookback_days=120)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at"] = acquired_at
    path.write_text(json.dumps(payload), encoding="utf-8")
    stamp = datetime.fromisoformat(acquired_at).timestamp()
    os.utime(path, (stamp, stamp))
    return path


@pytest.mark.parametrize("acquired,expected_stale", [
    ("2025-06-06T14:00:00+08:00", True),
    ("2025-06-06T16:00:00+08:00", False),
    ("2025-06-05T16:00:00+08:00", True),
])
def test_cache_restore_keeps_persisted_acquisition_time(monkeypatch, tmp_path, acquired, expected_stale):
    _freeze_time(monkeypatch, "2025-06-06T17:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), acquired)
    restored = datetime.fromisoformat("2025-06-06T17:00:00+08:00").timestamp()
    os.utime(path, (restored, restored))
    cached = daily._read_daily_history_cache(path, ttl_seconds=86400)
    assert (cached is None) == expected_stale
    assert daily._read_daily_history_cache(path, ttl_seconds=86400, allow_stale=True) is not None


@pytest.mark.parametrize("created_at", [None, "invalid"])
@pytest.mark.parametrize("acquired,expected_stale", [
    ("2025-06-06T14:00:00+08:00", True),
    ("2025-06-06T16:00:00+08:00", False),
])
def test_legacy_cache_retains_mtime_fallback(monkeypatch, tmp_path, created_at, acquired, expected_stale):
    _freeze_time(monkeypatch, "2025-06-06T17:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), acquired)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if created_at is None:
        payload.pop("created_at")
    else:
        payload["created_at"] = created_at
    path.write_text(json.dumps(payload), encoding="utf-8")
    stamp = datetime.fromisoformat(acquired).timestamp()
    os.utime(path, (stamp, stamp))
    assert (daily._read_daily_history_cache(path, ttl_seconds=86400) is None) == expected_stale


@pytest.mark.parametrize("system_timezone", ["Asia/Shanghai", "UTC", "America/New_York"])
@pytest.mark.parametrize("now", ["2025-06-06T17:00:00+08:00", "2025-06-07T15:00:00+08:00"])
def test_naive_created_at_migration_preserves_mtime_and_marks_quality_stale(
    monkeypatch, tmp_path, system_timezone, now,
):
    monkeypatch.setattr(daily, "_SOURCE_HEALTH", {})
    with _timezone("Asia/Shanghai"):
        path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T14:00:00")
    with _timezone(system_timezone):
        _freeze_time(monkeypatch, now)
        assert json.loads(path.read_text(encoding="utf-8"))["created_at"] == "2025-06-06T14:00:00"
        assert daily._read_daily_history_cache(path, ttl_seconds=86400) is None

        monkeypatch.setattr(daily, "_fetch_daily_tencent", Mock(side_effect=RuntimeError("offline")))
        enriched = daily.enrich_daily_features(
            pd.DataFrame([{"code": "000001"}]), source="tencent", fetch_retries=0, cache_dir=tmp_path,
        )
    assert enriched.attrs["daily_success_count"] == 1
    assert "stale_cache" in enriched.iloc[0]["daily_quality_flags"]
    assert enriched.iloc[0]["daily_quality_score"] < 100


@pytest.mark.parametrize("system_timezone", ["Asia/Shanghai", "UTC", "America/New_York"])
@pytest.mark.parametrize("acquired,expected_stale", [
    ("2025-06-06T14:00:00+08:00", True),
    ("2025-06-06T16:00:00+08:00", False),
])
def test_naive_cache_uses_mtime_regardless_of_reading_timezone(
    monkeypatch, tmp_path, system_timezone, acquired, expected_stale,
):
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T14:00:00")
    stamp = datetime.fromisoformat(acquired).timestamp()
    os.utime(path, (stamp, stamp))
    with _timezone(system_timezone):
        _freeze_time(monkeypatch, "2025-06-06T17:00:00+08:00")
        assert (daily._read_daily_history_cache(path, ttl_seconds=86400) is None) == expected_stale
        degraded = daily._read_daily_history_cache(path, ttl_seconds=86400, allow_stale=True)
        assert degraded is not None
        assert bool(degraded.attrs.get("daily_stale")) == expected_stale


@pytest.mark.parametrize("system_timezone", ["UTC", "America/New_York", "Asia/Shanghai"])
@pytest.mark.parametrize("now,last_date", [
    ("2025-06-06T21:00:00+00:00", "2025-06-06"),
    ("2025-06-07T00:30:00+00:00", "2025-06-06"),
    ("2025-12-05T22:00:00+00:00", "2025-12-05"),
])
def test_yfinance_postmarket_includes_closed_session_and_caches_fresh_history(
    monkeypatch, tmp_path, system_timezone, now, last_date,
):
    monkeypatch.setattr(daily, "_SOURCE_HEALTH", {})
    instant = _freeze_time(monkeypatch, now)
    history = _history(last_date, "AAPL").rename(columns={
        "date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })
    history["Date"] = pd.to_datetime(history["Date"])
    history = history.set_index("Date")

    def download(ticker, *, start, end, **kwargs):
        assert ticker == "AAPL"
        assert end == (pd.Timestamp(last_date) + pd.DateOffset(days=1)).strftime("%Y-%m-%d")
        # Model the real provider's exclusive end rather than mocking the daily fetcher.
        return history.loc[(history.index >= pd.Timestamp(start)) & (history.index < pd.Timestamp(end))].copy()

    yf_download = Mock(side_effect=download)
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=yf_download))
    clock_pd = Mock(wraps=pd, MultiIndex=pd.MultiIndex)

    def timestamp_now(tz=None):
        local = pd.Timestamp(instant).tz_convert(tz or system_timezone)
        return local if tz is not None else local.tz_localize(None)

    clock_pd.Timestamp.now.side_effect = timestamp_now
    monkeypatch.setattr(snapshot_us, "pd", clock_pd)
    with _timezone(system_timezone):
        enriched = daily.enrich_daily_features(
            pd.DataFrame([{"code": "AAPL"}]), source="yfinance", fetch_retries=0, cache_dir=tmp_path,
        )
        assert enriched.attrs["daily_success_count"] == 1
        assert "stale_cache" not in enriched.iloc[0]["daily_quality_flags"]
        assert enriched.iloc[0]["daily_source"] == "yfinance"
        path = daily._daily_history_cache_path(tmp_path, code="AAPL", source="yfinance", lookback_days=120)
        cached = daily._read_daily_history_cache(path, ttl_seconds=86400)
        assert cached is not None
        assert daily._latest_daily_bar_date(cached, code="AAPL") == pd.Timestamp(last_date)
        assert not cached.attrs.get("daily_stale")
        daily.fetch_daily_history("AAPL", source="yfinance", retries=0, cache_dir=tmp_path)
    yf_download.assert_called_once()


@pytest.mark.parametrize("now,bad_date,valid_date", [
    ("2025-06-08T10:00:00+08:00", "2025-06-07", "2025-06-06"),
    ("2025-06-08T10:00:00+08:00", "2025-06-08", "2025-06-06"),
    ("2025-10-01T16:00:00+08:00", "2025-10-01", "2025-09-30"),
    ("2025-06-09T14:00:00+08:00", "2025-06-08", "2025-06-09"),
    ("2025-10-09T14:00:00+08:00", "2025-10-08", "2025-10-09"),
    ("2025-06-06T16:00:00+08:00", "bad", "2025-06-06"),
    ("2025-06-06T16:00:00+08:00", None, "2025-06-06"),
])
@pytest.mark.parametrize("with_cache", [False, True])
@pytest.mark.parametrize("via_dsa", [False, True])
@pytest.mark.parametrize("invalid_row", [-1, -2])
def test_non_trading_bars_continue_fallback(
    monkeypatch, tmp_path, now, bad_date, valid_date, with_cache, via_dsa, invalid_row,
):
    _freeze_time(monkeypatch, now)
    malformed = _history(valid_date)
    malformed.loc[malformed.index[invalid_row], "date"] = bad_date
    malformed.loc[malformed.index[invalid_row], "close"] = 1000.0
    if with_cache:
        path = _cache(tmp_path, malformed, now, source="auto")
        assert daily._read_daily_history_cache(path, ttl_seconds=86400) is None
    fetchers = _auto_sources(monkeypatch, {
        "tencent": malformed, "sina": _history(valid_date),
        "akshare": RuntimeError("unused"), "baostock": RuntimeError("unused"),
    })
    fetcher = daily.fetch_daily_history
    if via_dsa:
        monkeypatch.setattr(screening_service, "get_dsa_daily_history", lambda code, **kwargs: (malformed, "db"))
        fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
    result = fetcher("000001", source="auto", retries=0, cache_dir=tmp_path if with_cache else None)
    assert result.attrs["daily_source"] == "sina"
    assert not result.attrs.get("daily_stale")
    assert result["date"].max() == valid_date
    assert result.attrs["daily_source_health"]["tencent"]["successes"] == 0
    assert result.attrs["daily_source_health"]["tencent"]["failures"] == 1
    assert daily.compute_daily_features(result)["ma5"] == 10.0
    if with_cache:
        cached = daily._read_daily_history_cache(path, ttl_seconds=86400)
        assert cached is not None
        assert cached["date"].max() == valid_date
        assert cached.attrs["daily_source"] == "sina"
    fetchers["tencent"].assert_called_once()
    fetchers["sina"].assert_called_once()
    fetchers["akshare"].assert_not_called()


@pytest.mark.parametrize("now,acquired,last_date,code,expected_stale", [
    ("2025-06-06T09:00:00+08:00", "2025-06-05T16:00:00+08:00", "2025-06-05", "000001", False),
    ("2025-06-06T14:00:00+08:00", "2025-06-06T13:00:00+08:00", "2025-06-06", "000001", False),
    ("2025-06-06T16:00:00+08:00", "2025-06-06T14:00:00+08:00", "2025-06-06", "000001", True),
    ("2025-06-06T16:00:00+08:00", "2025-06-06T16:00:00+08:00", "2025-06-05", "000001", True),
    ("2025-06-08T10:00:00+08:00", "2025-06-06T16:00:00+08:00", "2025-06-06", "000001", False),
    ("2025-10-01T16:00:00+08:00", "2025-09-30T16:00:00+08:00", "2025-09-30", "000001", False),
    ("2025-06-09T09:00:00+08:00", "2025-06-06T16:00:00+08:00", "2025-06-06", "000001", False),
    ("2025-06-09T16:00:00+08:00", "2025-06-06T16:00:00+08:00", "2025-06-06", "000001", True),
    ("2025-06-06T18:00:00+00:00", "2025-06-05T21:00:00+00:00", "2025-06-05", "AAPL", False),
    ("2025-06-06T21:00:00+00:00", "2025-06-06T18:00:00+00:00", "2025-06-06", "AAPL", True),
])
def test_cache_requires_session_freshness_in_addition_to_ttl(
    monkeypatch, tmp_path, now, acquired, last_date, code, expected_stale,
):
    _freeze_time(monkeypatch, now)
    path = _cache(tmp_path, _history(last_date, code), acquired, code)
    cached = daily._read_daily_history_cache(path, ttl_seconds=4 * 86400)
    assert (cached is None) == expected_stale
    degraded = daily._read_daily_history_cache(path, ttl_seconds=4 * 86400, allow_stale=True)
    assert degraded is not None
    assert bool(degraded.attrs.get("daily_stale")) == expected_stale


@pytest.mark.parametrize("restored", [False, True])
def test_close_transition_refreshes_partial_bar_and_replaces_cache(monkeypatch, tmp_path, restored):
    now = _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T14:00:00+08:00")
    if restored:
        os.utime(path, (now.timestamp(), now.timestamp()))
    refreshed = _history("2025-06-06")
    refreshed.loc[64, "close"] = 10.5
    fetch = Mock(return_value=refreshed)
    monkeypatch.setattr(daily, "_fetch_daily_tencent", fetch)
    result = daily.fetch_daily_history("000001", source="tencent", retries=0, cache_dir=tmp_path)
    fetch.assert_called_once()
    assert result.iloc[-1]["close"] == 10.5
    assert not result.attrs.get("daily_stale")
    assert daily._read_daily_history_cache(path, ttl_seconds=86400).iloc[-1]["close"] == 10.5


def test_expired_ttl_still_refreshes_on_non_trading_day(monkeypatch, tmp_path):
    _freeze_time(monkeypatch, "2025-06-08T10:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T16:00:00+08:00")
    assert daily._read_daily_history_cache(path, ttl_seconds=86400) is None


def test_failed_refresh_reaches_quality_and_risk_overlay(monkeypatch, tmp_path):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    _cache(tmp_path, _history("2025-06-05"), "2025-06-06T14:00:00+08:00")
    monkeypatch.setattr(daily, "_fetch_daily_tencent", Mock(side_effect=RuntimeError("offline")))
    enriched = daily.enrich_daily_features(
        pd.DataFrame([{"code": "000001"}]), source="tencent", fetch_retries=0, cache_dir=tmp_path,
    )
    assert enriched.attrs["daily_success_count"] == 1
    flags = enriched.iloc[0]["daily_quality_flags"]
    assert "stale_cache" in flags
    assert "fallback_errors" in flags
    pick = Pick(
        rank=1, code="000001", name="Test", screen_score=80, final_score=80,
        daily_quality_flags=flags, daily_quality_score=enriched.iloc[0]["daily_quality_score"],
    )
    ranked, _ = apply_risk_overlay([pick])
    assert "daily_stale_cache" in ranked[0].risk_flags
    assert "daily_source_fallback_errors" in ranked[0].risk_flags
    assert ranked[0].final_score < 80


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("explicit_stale", [False, True])
def test_stale_dsa_history_tries_native_sources_without_overwriting_last_good_cache(
    monkeypatch, tmp_path, fails, explicit_stale,
):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T16:00:00+08:00")
    before = path.read_bytes()
    dsa_history = _history("2025-06-06" if explicit_stale else "2025-06-05")
    dsa_history.attrs["daily_stale"] = explicit_stale
    monkeypatch.setattr(screening_service, "get_dsa_daily_history", lambda code, **kwargs: (dsa_history, "db"))
    native = Mock(side_effect=RuntimeError("sources failed")) if fails else Mock(return_value=_history("2025-06-06"))
    monkeypatch.setattr(daily, "fetch_daily_history", native)
    fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
    result = fetcher("000001", source="tencent", retries=0, cache_dir=tmp_path, cache_ttl_seconds=321)
    native.assert_called_once_with(
        "000001", lookback_days=120, source="tencent", retries=0, cache_dir=tmp_path, cache_ttl_seconds=321,
    )
    assert path.read_bytes() == before
    assert bool(result.attrs.get("daily_stale")) == fails
    if fails:
        assert result.attrs["daily_source"] == "dsa:db"
        assert result.attrs["source_errors"] == ["sources failed"]
        assert "stale_cache" in daily.compute_daily_features(result)["daily_quality_flags"]


def test_injected_history_provider_cannot_bypass_freshness_check(monkeypatch):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    old_history = _history("2025-06-05")
    enriched = daily.enrich_daily_features(
        pd.DataFrame([{"code": "000001"}]), history_fetcher=lambda *args, **kwargs: old_history,
    )
    assert "stale_cache" in enriched.iloc[0]["daily_quality_flags"]
    assert not old_history.attrs.get("daily_stale")


def test_lagging_native_source_is_not_promoted_by_new_cache_timestamp(monkeypatch, tmp_path):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T14:00:00+08:00")
    before = path.read_bytes()
    fetch = Mock(side_effect=lambda *args, **kwargs: _history("2025-06-05"))
    monkeypatch.setattr(daily, "_fetch_daily_tencent", fetch)
    for _ in range(2):
        result = daily.fetch_daily_history("000001", source="tencent", retries=0, cache_dir=tmp_path)
        assert result.attrs["daily_stale"]
        assert path.read_bytes() == before
    assert fetch.call_count == 2


def _auto_sources(monkeypatch, outcomes, *, has_tushare_token=False):
    monkeypatch.setattr(daily, "_has_tushare_token", lambda: has_tushare_token)
    monkeypatch.setattr(daily, "_SOURCE_HEALTH", {})
    fetchers = {}
    for source, outcome in outcomes.items():
        fetcher = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
        monkeypatch.setattr(daily, f"_fetch_daily_{source}", fetcher)
        fetchers[source] = fetcher
    return fetchers


@pytest.mark.parametrize("via_dsa", [False, True])
@pytest.mark.parametrize("has_tushare_token", [False, True])
def test_auto_skips_stale_source_and_caches_fresh_fallback(
    monkeypatch, tmp_path, via_dsa, has_tushare_token,
):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T14:00:00+08:00", source="auto")
    outcomes = {
        "tencent": _history("2025-06-05"), "sina": _history("2025-06-06"),
        "akshare": RuntimeError("should not be called"), "baostock": RuntimeError("should not be called"),
    }
    if has_tushare_token:
        outcomes["tushare"] = _history("2025-06-05")
    fetchers = _auto_sources(monkeypatch, outcomes, has_tushare_token=has_tushare_token)
    fetcher = daily.fetch_daily_history
    if via_dsa:
        monkeypatch.setattr(
            screening_service, "get_dsa_daily_history", lambda code, **kwargs: (_history("2025-06-05"), "db"),
        )
        fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
    result = fetcher("000001", source="auto", retries=2, cache_dir=tmp_path)
    if has_tushare_token:
        fetchers["tushare"].assert_called_once()
        assert result.attrs["daily_source_order"][0] == "tushare"
        assert "tushare: stale daily history" in result.attrs["daily_source_order_notes"]
    fetchers["tencent"].assert_called_once()
    fetchers["sina"].assert_called_once()
    fetchers["akshare"].assert_not_called()
    fetchers["baostock"].assert_not_called()
    assert result.attrs["daily_source"] == "sina"
    assert not result.attrs.get("daily_stale")
    assert result.attrs["source_errors"] == []
    assert "tencent: stale daily history" in result.attrs["daily_source_order_notes"]
    assert "stale_cache" not in daily.compute_daily_features(result)["daily_quality_flags"]
    assert daily._read_daily_history_cache(path, ttl_seconds=86400).attrs["daily_source"] == "sina"


@pytest.mark.parametrize("via_dsa", [False, True])
def test_fresh_auto_fallback_reaches_features_without_stale_risk_penalty(monkeypatch, via_dsa):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    fresh = _history("2025-06-06")
    fresh.loc[64, "close"] = 10.5
    fetchers = _auto_sources(monkeypatch, {
        "tencent": _history("2025-06-05"), "sina": fresh,
        "akshare": RuntimeError("should not be called"), "baostock": RuntimeError("should not be called"),
    })
    history_fetcher = None
    if via_dsa:
        monkeypatch.setattr(
            screening_service, "get_dsa_daily_history", lambda code, **kwargs: (_history("2025-06-05"), "db"),
        )
        history_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
    enriched = daily.enrich_daily_features(
        pd.DataFrame([{"code": "000001"}]), source="auto", fetch_retries=0,
        history_fetcher=history_fetcher,
    )
    fetchers["tencent"].assert_called_once()
    fetchers["sina"].assert_called_once()
    fetchers["akshare"].assert_not_called()
    fetchers["baostock"].assert_not_called()
    assert enriched.attrs["daily_success_count"] == 1
    assert enriched.attrs["daily_source_counts"] == {"sina": 1}
    row = enriched.iloc[0]
    assert row["ma5"] == pytest.approx(10.1)
    assert "stale_cache" not in row["daily_quality_flags"]
    assert "fallback_errors" not in row["daily_quality_flags"]
    pick = Pick(
        rank=1, code="000001", name="Test", screen_score=80, final_score=80,
        daily_quality_flags=row["daily_quality_flags"], daily_quality_score=row["daily_quality_score"],
    )
    ranked, _ = apply_risk_overlay([pick])
    assert "daily_stale_cache" not in ranked[0].risk_flags
    assert "daily_source_fallback_errors" not in ranked[0].risk_flags
    assert ranked[0].risk_penalty == 0
    assert ranked[0].final_score == 80


@pytest.mark.parametrize("with_cache", [False, True])
def test_auto_uses_stale_history_only_after_all_sources_are_stale(monkeypatch, tmp_path, with_cache):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T14:00:00+08:00", source="auto")
    before = path.read_bytes()
    fetchers = _auto_sources(monkeypatch, {
        source: _history("2025-06-05") for source in ("tencent", "sina", "akshare", "baostock")
    })
    result = daily.fetch_daily_history("000001", source="auto", retries=2, cache_dir=tmp_path if with_cache else None)
    for fetcher in fetchers.values():
        fetcher.assert_called_once()
    assert result.attrs["daily_source"] == ("auto" if with_cache else "tencent")
    assert result["date"].max() == ("2025-06-06" if with_cache else "2025-06-05")
    assert result.attrs["daily_stale"]
    assert len(result.attrs["daily_source_order_notes"]) == 4
    assert result.attrs["source_errors"] == []
    assert "stale_cache" in daily.compute_daily_features(result)["daily_quality_flags"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("cache_date,invalid_latest,expected", [
    ("2025-06-06", False, "auto"),
    ("2025-06-06", True, "sina"),
    ("2025-06-05", False, "sina"),
    ("2025-06-04", False, "sina"),
])
def test_stale_cache_candidate_keeps_latest_valid_bar_and_diagnostics(
    monkeypatch, tmp_path, cache_date, invalid_latest, expected,
):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    cached = _history(cache_date)
    if invalid_latest:
        cached.loc[cached.index[-1], "close"] = None
    path = _cache(tmp_path, cached, "2025-06-06T14:00:00+08:00", source="auto")
    before = path.read_bytes()
    fetchers = _auto_sources(monkeypatch, {
        "tencent": RuntimeError("offline"), "sina": _history("2025-06-05"),
        "akshare": _history("2025-06-05"), "baostock": _history("2025-06-05"),
    })
    result = daily.fetch_daily_history("000001", source="auto", retries=0, cache_dir=tmp_path)
    assert result.attrs["daily_source"] == expected
    assert result.attrs["daily_stale"]
    assert result.attrs["source_errors"] == ["tencent after 1 attempts: offline"]
    assert result.attrs["daily_source_order"] == list(fetchers)
    assert result.attrs["daily_source_health"]["tencent"]["failures"] == 1
    assert "stale_cache" in daily.compute_daily_features(result)["daily_quality_flags"]
    assert path.read_bytes() == before
    for fetcher in fetchers.values():
        fetcher.assert_called_once()


def test_auto_keeps_newest_stale_provider_with_tie_priority(monkeypatch):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    fetchers = _auto_sources(monkeypatch, {
        "tencent": _history("2025-06-03"), "sina": _history("2025-06-05"),
        "akshare": _history("2025-06-05"), "baostock": RuntimeError("offline"),
    })
    result = daily.fetch_daily_history("000001", source="auto", retries=0)
    assert result.attrs["daily_source"] == "sina"
    assert result["date"].max() == "2025-06-05"
    assert result.attrs["daily_stale"]
    assert result.attrs["source_errors"] == ["baostock after 1 attempts: offline"]
    for fetcher in fetchers.values():
        fetcher.assert_called_once()


@pytest.mark.parametrize("now", ["2025-06-06T09:00:00+08:00", "2025-06-06T14:00:00+08:00"])
def test_preopen_placeholder_cache_is_not_reused_intraday(monkeypatch, tmp_path, now):
    _freeze_time(monkeypatch, now)
    path = _cache(tmp_path, _history("2025-06-06"), "2025-06-06T09:00:00+08:00")
    assert daily._read_daily_history_cache(path, ttl_seconds=86400) is None
    assert daily._read_daily_history_cache(path, ttl_seconds=86400, allow_stale=True).attrs["daily_stale"]
    if now.startswith("2025-06-06T09"):
        fetchers = _auto_sources(monkeypatch, {
            "tencent": _history("2025-06-06"), "sina": _history("2025-06-05"),
            "akshare": RuntimeError("unused"), "baostock": RuntimeError("unused"),
        })
        result = daily.fetch_daily_history("000001", source="auto", retries=0)
        assert result.attrs["daily_source"] == "sina"
        fetchers["akshare"].assert_not_called()


@pytest.mark.parametrize("now,invalid_date,valid_date", [
    ("2025-06-08T10:00:00+08:00", "2025-06-07", "2025-06-05"),
    ("2025-10-01T16:00:00+08:00", "2025-10-01", "2025-09-29"),
    ("2025-06-06T16:00:00+08:00", "2025-06-09", "2025-06-05"),
])
@pytest.mark.parametrize("with_cache", [False, True])
def test_invalid_session_fallback_ranks_behind_valid_stale_data(
    monkeypatch, tmp_path, now, invalid_date, valid_date, with_cache,
):
    _freeze_time(monkeypatch, now)
    malformed = _history(valid_date)
    malformed.loc[malformed.index[-1], "date"] = invalid_date
    if with_cache:
        path = _cache(tmp_path, _history(valid_date), now, source="auto")
        before = path.read_bytes()
    fetchers = _auto_sources(monkeypatch, {
        "tencent": malformed, "sina": malformed if with_cache else _history(valid_date),
        "akshare": malformed, "baostock": RuntimeError("offline"),
    })
    result = daily.fetch_daily_history("000001", source="auto", retries=0, cache_dir=tmp_path if with_cache else None)
    assert result.attrs["daily_source"] == ("auto" if with_cache else "sina")
    assert result["date"].max() == valid_date
    assert result.attrs["daily_stale"]
    assert result.attrs["source_errors"][-1] == "baostock after 1 attempts: offline"
    assert len(result.attrs["source_errors"]) == (4 if with_cache else 3)
    if with_cache:
        assert path.read_bytes() == before
    for fetcher in fetchers.values():
        fetcher.assert_called_once()


@pytest.mark.parametrize("now,invalid_date,valid_date", [
    ("2025-06-08T10:00:00+08:00", "2025-06-07", "2025-06-05"),
    ("2025-10-01T16:00:00+08:00", "2025-10-01", "2025-09-29"),
    ("2025-06-06T16:00:00+08:00", "2025-06-09", "2025-06-05"),
    ("2025-06-06T09:00:00+08:00", "2025-06-06", "2025-06-05"),
    ("2025-06-09T14:00:00+08:00", "2025-06-08", "2025-06-06"),
    ("2025-10-09T14:00:00+08:00", "2025-10-08", "2025-09-30"),
    ("2025-06-06T16:00:00+08:00", "bad", "2025-06-06"),
    ("2025-06-06T16:00:00+08:00", None, "2025-06-06"),
])
@pytest.mark.parametrize("via_dsa,with_cache", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("invalid_row", [-1, -2])
def test_all_invalid_histories_follow_fetch_failure_path(
    monkeypatch, tmp_path, now, invalid_date, valid_date, via_dsa, with_cache, invalid_row,
):
    _freeze_time(monkeypatch, now)
    malformed = _history(valid_date)
    malformed.loc[malformed.index[invalid_row], "date"] = invalid_date
    if with_cache:
        path = _cache(tmp_path, malformed, now, source="auto")
        before = path.read_bytes()
    fetchers = _auto_sources(monkeypatch, {source: malformed for source in ("tencent", "sina", "akshare", "baostock")})
    if via_dsa:
        monkeypatch.setattr(screening_service, "get_dsa_daily_history", lambda code, **kwargs: (malformed, "db"))
    fetcher = screening_service._build_screening_dsa_daily_history_fetcher() if via_dsa else daily.fetch_daily_history
    with pytest.raises(RuntimeError, match="daily history fetch failed") as caught:
        fetcher("000001", source="auto", retries=0, cache_dir=tmp_path if with_cache else None)
    assert caught.value.daily_metadata["source_errors"] == [
        f"{source} after 1 attempts: invalid daily session" for source in fetchers
    ]
    if with_cache:
        assert path.read_bytes() == before
    for fetcher in fetchers.values():
        fetcher.assert_called_once()


def test_invalid_sessions_trip_source_circuit_and_valid_stale_response_recovers(monkeypatch):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    clock = [1000.0]
    monkeypatch.setattr(daily.time, "monotonic", lambda: clock[0])
    fetchers = _auto_sources(monkeypatch, {
        "tencent": _history("2025-06-09"), "sina": _history("2025-06-06"),
        "akshare": RuntimeError("unused"), "baostock": RuntimeError("unused"),
    })
    for _ in range(3):
        with pytest.raises(RuntimeError, match="invalid daily session"):
            daily.fetch_daily_history("000001", source="tencent", retries=0)
    health = daily._daily_source_health_snapshot(("tencent",))["tencent"]
    assert health["failures"] == 3
    assert health["cooldown_remaining_seconds"] > 0
    result = daily.fetch_daily_history("000001", source="auto", retries=0)
    assert result.attrs["daily_source"] == "sina"
    assert fetchers["tencent"].call_count == 3
    _freeze_time(monkeypatch, "2025-06-06T16:06:00+08:00")
    clock[0] += 360
    fetchers["tencent"].return_value = _history("2025-06-05")
    result = daily.fetch_daily_history("000001", source="tencent", retries=0)
    assert result.attrs["daily_stale"]
    assert result.attrs["daily_source_health"]["tencent"]["failures"] == 0
    assert result.attrs["daily_source_health"]["tencent"]["cooldown_remaining_seconds"] == 0


def test_auto_keeps_stale_history_when_remaining_sources_fail(monkeypatch):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    fetchers = _auto_sources(monkeypatch, {
        "tencent": _history("2025-06-05"), "sina": RuntimeError("offline"),
        "akshare": RuntimeError("offline"), "baostock": RuntimeError("offline"),
    })
    result = daily.fetch_daily_history("000001", source="auto", retries=1)
    fetchers["tencent"].assert_called_once()
    for source in ("sina", "akshare", "baostock"):
        assert fetchers[source].call_count == 2
    assert result.attrs["daily_stale"]
    assert result.attrs["source_errors"] == [f"{source} after 2 attempts: offline" for source in fetchers if source != "tencent"]
    assert result.attrs["daily_source_health"]["tencent"]["failures"] == 0


def test_auto_preserves_errors_before_stale_then_fresh_sources(monkeypatch):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    fetchers = _auto_sources(monkeypatch, {
        "tencent": RuntimeError("offline"), "sina": _history("2025-06-05"),
        "akshare": _history("2025-06-06"), "baostock": RuntimeError("should not be called"),
    })
    result = daily.fetch_daily_history("000001", source="auto", retries=0)
    assert result.attrs["daily_source"] == "akshare"
    assert not result.attrs.get("daily_stale")
    assert result.attrs["source_errors"] == ["tencent after 1 attempts: offline"]
    assert "sina: stale daily history" in result.attrs["daily_source_order_notes"]
    fetchers["baostock"].assert_not_called()


def test_dsa_stale_history_remains_available_when_all_native_sources_fail(monkeypatch):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    _auto_sources(monkeypatch, {
        source: RuntimeError("offline") for source in ("tencent", "sina", "akshare", "baostock")
    })
    monkeypatch.setattr(
        screening_service, "get_dsa_daily_history", lambda code, **kwargs: (_history("2025-06-05"), "db"),
    )
    fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
    result = fetcher("000001", source="auto", retries=0)
    assert result.attrs["daily_source"] == "dsa:db"
    assert result.attrs["daily_stale"]
    assert result.attrs["source_errors"] == [
        f"{source} after 1 attempts: offline" for source in ("tencent", "sina", "akshare", "baostock")
    ]
    features = daily.compute_daily_features(result)
    assert features["daily_quality_score"] == 55
    ranked, _ = apply_risk_overlay([Pick(
        rank=1, code="000001", name="Test", screen_score=80, final_score=80,
        daily_quality_flags=features["daily_quality_flags"], daily_quality_score=features["daily_quality_score"],
    )])
    assert "low_daily_quality" in ranked[0].risk_flags


@pytest.mark.parametrize("first_fails", [False, True])
@pytest.mark.parametrize("dsa_date,native_date", [("2025-06-05", "2025-06-04"), ("2025-06-05", "2025-06-05"), ("2025-06-04", "2025-06-05")])
def test_dsa_stale_history_keeps_priority_when_native_sources_are_also_stale(monkeypatch, tmp_path, first_fails, dsa_date, native_date):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    path = _cache(tmp_path, _history("2025-06-03"), "2025-06-06T14:00:00+08:00", source="auto")
    before = path.read_bytes()
    outcomes = {source: _history(native_date) for source in ("tencent", "sina", "akshare", "baostock")}
    if first_fails:
        outcomes["tencent"] = RuntimeError("offline")
    fetchers = _auto_sources(monkeypatch, outcomes)
    monkeypatch.setattr(
        screening_service, "get_dsa_daily_history", lambda code, **kwargs: (_history(dsa_date), "db"),
    )
    fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
    result = fetcher("000001", source="auto", retries=0, cache_dir=tmp_path)
    assert result.attrs["daily_source"] == ("dsa:db" if dsa_date >= native_date else ("sina" if first_fails else "tencent"))
    assert result["date"].max() == max(dsa_date, native_date)
    assert result.attrs["daily_stale"]
    assert path.read_bytes() == before
    for source in fetchers.values():
        source.assert_called_once()
    assert result.attrs["source_errors"] == (["tencent after 1 attempts: offline"] if first_fails else [])
    assert "stale_cache" in daily.compute_daily_features(result)["daily_quality_flags"]


def test_calendar_unavailable_retains_ttl_and_preserves_explicit_stale_metadata(monkeypatch, tmp_path):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    monkeypatch.setattr(trading_calendar, "_XCALS_AVAILABLE", False)
    old_history = _history("2025-06-05")
    path = _cache(tmp_path, old_history, "2025-06-06T16:00:00+08:00")
    assert daily._read_daily_history_cache(path, ttl_seconds=86400) is not None
    old_history.attrs["daily_stale"] = True
    _cache(tmp_path, old_history, "2025-06-06T16:00:00+08:00")
    assert daily._read_daily_history_cache(path, ttl_seconds=86400) is None
    assert daily._read_daily_history_cache(path, ttl_seconds=86400, allow_stale=True).attrs["daily_stale"]


@pytest.mark.parametrize("dates", [["bad"], ["2025-06-05"], ["2025-06-09"]])
def test_missing_invalid_old_or_future_dates_are_not_current(monkeypatch, dates):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    assert daily.daily_history_is_stale(pd.DataFrame({"date": dates, "close": 10}), code="000001")
    assert daily.daily_history_is_stale(pd.DataFrame({"close": [10]}), code="000001")


def test_compact_dates_and_missing_latest_close(monkeypatch):
    _freeze_time(monkeypatch, "2025-06-06T16:00:00+08:00")
    hist = pd.DataFrame({"trade_date": [20250605, 20250606], "close": [10, 11]})
    assert not daily.daily_history_is_stale(hist, code="000001")
    hist.loc[1, "close"] = float("nan")
    assert daily.daily_history_is_stale(hist, code="000001")


@pytest.mark.parametrize("invalid_close", [None, "invalid"])
@pytest.mark.parametrize("invalid_date", ["2025-06-08", "bad", None])
@pytest.mark.parametrize("date_column,close_column", [("date", "close"), ("日期", "收盘"), ("trade_date", "close")])
def test_session_validation_ignores_rows_without_usable_close(monkeypatch, invalid_close, invalid_date, date_column, close_column):
    _freeze_time(monkeypatch, "2025-06-09T16:00:00+08:00")
    hist = pd.DataFrame({date_column: ["2025-06-06", invalid_date, "2025-06-09"], close_column: [10, invalid_close, 11]})
    assert not daily.daily_history_is_stale(hist, code="000001")
    hist.loc[1, close_column] = 1000
    assert daily.daily_history_is_stale(hist, code="000001")
    assert pd.isna(daily._latest_daily_bar_date(hist, code="000001"))
