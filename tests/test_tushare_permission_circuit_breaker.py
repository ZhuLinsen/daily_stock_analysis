# -*- coding: utf-8 -*-
"""Regression tests for Tushare per-endpoint permission recognition & circuit breaking (#1696)."""

from __future__ import annotations

from datetime import datetime
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.base import BaseFetcher, DataFetcherManager, DataFetchError, RateLimitError
from data_provider.tushare_fetcher import (
    TushareFetcher,
    TusharePermissionError,
    _build_tushare_token_scope,
    is_tushare_permission_error,
    is_tushare_rate_limit_error,
    reset_tushare_permission_cache,
)
from src.services.screening import daily as screening_daily
from src.services.screening import snapshot as screening_snapshot


@pytest.fixture(autouse=True)
def _clean_tushare_state():
    reset_tushare_permission_cache()
    DataFetcherManager.reset_daily_source_health()
    with screening_snapshot._SOURCE_HEALTH_LOCK:
        screening_snapshot._SOURCE_HEALTH.clear()
    with screening_daily._SOURCE_HEALTH_LOCK:
        screening_daily._SOURCE_HEALTH.clear()
    yield
    reset_tushare_permission_cache()
    DataFetcherManager.reset_daily_source_health()
    with screening_snapshot._SOURCE_HEALTH_LOCK:
        screening_snapshot._SOURCE_HEALTH.clear()
    with screening_daily._SOURCE_HEALTH_LOCK:
        screening_daily._SOURCE_HEALTH.clear()


def _http_json_response(payload: dict) -> MagicMock:
    return MagicMock(status_code=200, text=json.dumps(payload, ensure_ascii=False))


class _DummyFallbackFetcher(BaseFetcher):
    name = "DummyFallbackFetcher"
    priority = 1

    def __init__(self, rows: pd.DataFrame) -> None:
        self._rows = rows
        self.calls: list[str] = []

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append(stock_code)
        return self._rows.copy()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        out = df.copy()
        out["code"] = stock_code
        return out


def test_distinguishes_tushare_rate_limit_doc_link_from_permission_denial() -> None:
    """Tushare's frequency limit message contains '权限的具体详情访问' and must stay RateLimitError."""
    rate_limit_msg = (
        "抱歉，您每分钟最多访问该接口80次，"
        "权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。"
    )
    daily_cap_msg = (
        "抱歉，您每天最多访问该接口2次，"
        "权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。"
    )
    perm_msg = (
        "抱歉，您没有访问该接口的权限，"
        "权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。"
    )

    assert not is_tushare_permission_error(Exception(rate_limit_msg))
    assert is_tushare_rate_limit_error(Exception(rate_limit_msg))
    assert not is_tushare_permission_error(Exception(daily_cap_msg))
    assert is_tushare_rate_limit_error(Exception(daily_cap_msg))

    assert is_tushare_permission_error(Exception(perm_msg))
    assert not is_tushare_rate_limit_error(Exception(perm_msg))


def test_rate_limit_response_does_not_trip_permission_circuit_breaker() -> None:
    config = SimpleNamespace(tushare_token="token-rate-limit")
    with patch("data_provider.tushare_fetcher.get_config", return_value=config):
        fetcher = TushareFetcher()

    rate_resp = _http_json_response(
        {
            "code": 40203,
            "msg": "抱歉，您每分钟最多访问该接口80次，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。",
        }
    )
    with patch("data_provider.tushare_fetcher.requests.post", return_value=rate_resp):
        with pytest.raises(RateLimitError):
            fetcher._fetch_raw_data("600519", "2026-03-01", "2026-03-05")

    assert not fetcher.is_api_denied("daily")


def test_high_point_cyq_chips_denial_skips_subsequent_stocks_while_keeping_daily_active() -> None:
    """A 120-point token lacks 5000-point cyq_chips but retains daily K-line access."""
    config = SimpleNamespace(tushare_token="token-120pts")
    with patch("data_provider.tushare_fetcher.get_config", return_value=config):
        fetcher = TushareFetcher()

    def fake_post(_url: str, json: dict, timeout: int) -> MagicMock:
        api_name = json["api_name"]
        if api_name == "trade_cal":
            return _http_json_response(
                {
                    "code": 0,
                    "data": {
                        "fields": ["cal_date", "is_open"],
                        "items": [["20260320", 1], ["20260319", 1]],
                    },
                }
            )
        if api_name == "cyq_chips":
            return _http_json_response(
                {
                    "code": 40203,
                    "msg": "抱歉，您没有访问该接口的权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。",
                }
            )
        if api_name == "daily":
            return _http_json_response(
                {
                    "code": 0,
                    "data": {
                        "fields": [
                            "ts_code",
                            "trade_date",
                            "open",
                            "high",
                            "low",
                            "close",
                            "vol",
                            "amount",
                            "pct_chg",
                        ],
                        "items": [["600519.SH", "20260320", 1500.0, 1520.0, 1495.0, 1510.0, 100.0, 15000.0, 0.8]],
                    },
                }
            )
        raise AssertionError(f"Unexpected api_name: {api_name}")

    with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 20, 20, 0)), patch(
        "data_provider.tushare_fetcher.requests.post",
        side_effect=fake_post,
    ) as post_mock:
        assert fetcher.get_chip_distribution("600519") is None
        calls_after_first_stock = post_mock.call_count
        rate_count_after_first = fetcher._call_count
        assert calls_after_first_stock == 2  # trade_cal + cyq_chips
        assert fetcher.is_api_denied("cyq_chips")

        # Subsequent stocks skip cyq_chips in 0 HTTP calls and 0 rate-limit increments!
        assert fetcher.get_chip_distribution("000001") is None
        assert fetcher.get_chip_distribution("601318") is None
        assert post_mock.call_count == calls_after_first_stock
        assert fetcher._call_count == rate_count_after_first

        # Meanwhile, 120-point daily interface continues working on the same fetcher!
        daily_df = fetcher.get_daily_data("600519", start_date="2026-03-19", end_date="2026-03-20")
        assert len(daily_df) == 1
        assert float(daily_df.iloc[0]["close"]) == 1510.0


def test_hk_daily_permission_denial_falls_back_cleanly_without_blocking_cn_daily() -> None:
    config = SimpleNamespace(tushare_token="token-cn-only")
    with patch("data_provider.tushare_fetcher.get_config", return_value=config):
        tushare_fetcher = TushareFetcher()

    fallback_rows = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-03-20"]),
            "open": [380.0],
            "high": [385.0],
            "low": [378.0],
            "close": [382.0],
            "volume": [100000.0],
            "amount": [38200000.0],
            "pct_chg": [0.5],
        }
    )
    fallback = _DummyFallbackFetcher(fallback_rows)
    manager = DataFetcherManager(fetchers=[tushare_fetcher, fallback])

    def fake_post(_url: str, json: dict, timeout: int) -> MagicMock:
        api_name = json["api_name"]
        if api_name == "hk_daily":
            return _http_json_response({"code": 40203, "msg": "抱歉，您没有接口访问权限"})
        if api_name == "daily":
            return _http_json_response(
                {
                    "code": 0,
                    "data": {
                        "fields": [
                            "ts_code",
                            "trade_date",
                            "open",
                            "high",
                            "low",
                            "close",
                            "vol",
                            "amount",
                            "pct_chg",
                        ],
                        "items": [["600519.SH", "20260320", 1500.0, 1520.0, 1495.0, 1510.0, 100.0, 15000.0, 0.8]],
                    },
                }
            )
        raise AssertionError(f"Unexpected api_name: {api_name}")

    with patch("data_provider.tushare_fetcher.requests.post", side_effect=fake_post) as post_mock:
        hk_df_1, hk_source_1 = manager.get_daily_data("HK00700", start_date="2026-03-19", end_date="2026-03-20")
        assert hk_source_1 == "DummyFallbackFetcher"
        assert len(hk_df_1) == 1
        assert post_mock.call_count == 1  # No @retry on permission error!

        # Second HK stock skips Tushare hk_daily with 0 HTTP calls
        hk_df_2, hk_source_2 = manager.get_daily_data("HK09988", start_date="2026-03-19", end_date="2026-03-20")
        assert hk_source_2 == "DummyFallbackFetcher"
        assert len(hk_df_2) == 1
        assert post_mock.call_count == 1

        # CN A-share stock still uses TushareFetcher primary source
        cn_df, cn_source = manager.get_daily_data("600519", start_date="2026-03-19", end_date="2026-03-20")
        assert cn_source == "TushareFetcher"
        assert len(cn_df) == 1
        assert post_mock.call_count == 2


def test_token_rotation_immediately_clears_permission_circuit_breaker() -> None:
    denied_resp = _http_json_response({"code": 40203, "msg": "抱歉，您没有接口访问权限"})
    ok_resp = _http_json_response(
        {
            "code": 0,
            "data": {
                "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"],
                "items": [["600519.SH", "20260320", 1500.0, 1520.0, 1495.0, 1510.0, 100.0, 15000.0, 0.8]],
            },
        }
    )

    with patch("data_provider.tushare_fetcher.get_config", return_value=SimpleNamespace(tushare_token="token-zero-pts")):
        fetcher_low_1 = TushareFetcher()
        fetcher_low_2 = TushareFetcher()

    with patch("data_provider.tushare_fetcher.requests.post", return_value=denied_resp) as post_low:
        with pytest.raises(TusharePermissionError):
            fetcher_low_1._fetch_raw_data("600519", "2026-03-19", "2026-03-20")
        assert post_low.call_count == 1
        # Fresh instance with the SAME token inherits the permission circuit breaker immediately
        assert fetcher_low_2.is_api_denied("daily")
        with pytest.raises(TusharePermissionError):
            fetcher_low_2._fetch_raw_data("000001", "2026-03-19", "2026-03-20")
        assert post_low.call_count == 1

    # Rotating to a newly upgraded token starts clean immediately without waiting for TTL
    with patch("data_provider.tushare_fetcher.get_config", return_value=SimpleNamespace(tushare_token="token-2000-pts")):
        fetcher_upgraded = TushareFetcher()

    assert not fetcher_upgraded.is_api_denied("daily")
    with patch("data_provider.tushare_fetcher.requests.post", return_value=ok_resp) as post_ok:
        df = fetcher_upgraded._fetch_raw_data("600519", "2026-03-19", "2026-03-20")
        assert len(df) == 1
        assert post_ok.call_count == 1


@pytest.mark.parametrize(
    "other_url, same_scope",
    [
        ("HTTPS://GW.EXAMPLE.COM/Pro?route=AbC", True),
        ("https://gw.example.com/pro?route=AbC", False),
        ("https://gw.example.com/Pro?route=abc", False),
        ("https://gw.example.com/pro?route=abc", False),
        ("https://gw.example.com/Pro/?route=AbC", False),
        ("https://gw.example.com/Pro?route=AbC/", False),
    ],
)
def test_permission_scope_normalizes_only_scheme_and_host(other_url: str, same_scope: bool) -> None:
    original = _build_tushare_token_scope("same-token", "https://gw.example.com/Pro?route=AbC")
    assert (_build_tushare_token_scope("same-token", other_url) == original) is same_scope


@pytest.mark.parametrize(
    "new_url",
    [
        "https://gw.example.com/pro?route=AbC",
        "https://gw.example.com/Pro?route=abc",
        "https://gw.example.com/pro?route=abc",
    ],
)
def test_gateway_route_change_clears_fetcher_permission_circuit(
    monkeypatch: pytest.MonkeyPatch, new_url: str,
) -> None:
    old_url = "https://gw.example.com/Pro?route=AbC"
    monkeypatch.setenv("TUSHARE_HTTP_URL", old_url)
    with patch("data_provider.tushare_fetcher.get_config", return_value=SimpleNamespace(tushare_token="same-token")):
        denied_fetcher = TushareFetcher()
        denied_response = _http_json_response({"code": 40203, "msg": "抱歉，您没有接口访问权限"})
        with patch("data_provider.tushare_fetcher.requests.post", return_value=denied_response) as post:
            with pytest.raises(TusharePermissionError):
                denied_fetcher._fetch_raw_data("600519", "2026-03-19", "2026-03-20")
            assert post.call_args.args[0] == old_url
            same_route_fetcher = TushareFetcher()
            with pytest.raises(TusharePermissionError):
                same_route_fetcher._fetch_raw_data("600519", "2026-03-19", "2026-03-20")
            assert post.call_count == 1

        monkeypatch.setenv("TUSHARE_HTTP_URL", new_url)
        recovered_fetcher = TushareFetcher()

    assert not recovered_fetcher.is_api_denied("daily")
    ok_response = _http_json_response({
        "code": 0,
        "data": {"fields": ["ts_code", "trade_date", "close"], "items": [["600519.SH", "20260320", 1510.0]]},
    })
    with patch("data_provider.tushare_fetcher.requests.post", return_value=ok_response) as post:
        assert len(recovered_fetcher._fetch_raw_data("600519", "2026-03-19", "2026-03-20")) == 1
        post.assert_called_once()
        assert post.call_args.args[0] == new_url
    assert denied_fetcher.is_api_denied("daily")


@pytest.mark.parametrize("url_env", ["TUSHARE_HTTP_URL", "TUSHARE_API_URL"])
@pytest.mark.parametrize(
    "new_url",
    [
        "https://gw.example.com/pro?route=AbC",
        "https://gw.example.com/Pro?route=abc",
        "https://gw.example.com/pro?route=abc",
    ],
)
def test_gateway_route_change_restores_screening_sources(
    monkeypatch: pytest.MonkeyPatch, url_env: str, new_url: str,
) -> None:
    old_url = "https://gw.example.com/Pro?route=AbC"
    monkeypatch.delenv("TUSHARE_API_URL", raising=False)
    monkeypatch.delenv("TUSHARE_HTTP_URL", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN", "same-token")
    monkeypatch.setenv(url_env, old_url)
    history = pd.DataFrame({"date": pd.to_datetime(["2026-03-20"]), "close": [1510.0]})

    def fetch_route(*args, **kwargs) -> pd.DataFrame:
        if os.environ[url_env] == old_url:
            raise RuntimeError("抱歉，您没有访问该接口的权限")
        return history.copy()

    snapshot_fetch = MagicMock(side_effect=fetch_route)
    daily_fetch = MagicMock(side_effect=fetch_route)
    monkeypatch.setattr(screening_snapshot, "_fetch_tushare", snapshot_fetch)
    monkeypatch.setattr(screening_snapshot, "_fetch_sina", lambda: history.copy())
    monkeypatch.setattr(screening_daily, "_fetch_daily_tushare", daily_fetch)
    monkeypatch.setattr(screening_daily, "_fetch_daily_tencent", lambda *args, **kwargs: history.copy())
    monkeypatch.setattr(screening_daily, "daily_history_is_stale", lambda *args, **kwargs: False)

    for _ in range(2):
        snapshot = screening_snapshot.fetch_snapshot_with_fallback(["tushare", "sina"])
        daily = screening_daily.fetch_daily_history("600519", source="auto", retries=2)
        assert snapshot.attrs["snapshot_source"] == "sina"
        assert daily.attrs["daily_source"] == "tencent"
    assert snapshot_fetch.call_count == daily_fetch.call_count == 1
    assert screening_snapshot.snapshot_source_health_snapshot(["tushare"])["tushare"]["disabled"] is True
    assert screening_daily.daily_source_health_snapshot()["tushare"]["disabled"] is True

    monkeypatch.setenv(url_env, new_url)
    snapshot = screening_snapshot.fetch_snapshot_with_fallback(["tushare", "sina"])
    daily = screening_daily.fetch_daily_history("600519", source="auto", retries=2)
    assert snapshot.attrs["snapshot_source"] == "tushare"
    assert daily.attrs["daily_source"] == "tushare"
    assert daily.attrs["daily_source_order"][0] == "tushare"
    assert snapshot_fetch.call_count == daily_fetch.call_count == 2
    assert screening_snapshot.snapshot_source_health_snapshot(["tushare"])["tushare"]["disabled"] is False
    assert screening_daily.daily_source_health_snapshot()["tushare"]["disabled"] is False


@pytest.mark.parametrize("url_env", ["TUSHARE_HTTP_URL", "TUSHARE_API_URL"])
def test_malformed_gateway_change_preserves_screening_fallback(
    monkeypatch: pytest.MonkeyPatch, url_env: str,
) -> None:
    old_url = "https://gw.example.com/Pro?route=AbC"
    monkeypatch.delenv("TUSHARE_API_URL", raising=False)
    monkeypatch.delenv("TUSHARE_HTTP_URL", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN", "same-token")
    monkeypatch.setenv(url_env, old_url)
    history = pd.DataFrame({"date": pd.to_datetime(["2026-03-20"]), "close": [1510.0]})

    def fetch_route(*args, **kwargs) -> pd.DataFrame:
        if os.environ[url_env] == old_url:
            raise RuntimeError("抱歉，您没有访问该接口的权限")
        raise ValueError("Invalid IPv6 URL")

    monkeypatch.setattr(screening_snapshot, "_fetch_tushare", fetch_route)
    monkeypatch.setattr(screening_snapshot, "_fetch_sina", lambda: history.copy())
    monkeypatch.setattr(screening_daily, "_fetch_daily_tushare", fetch_route)
    monkeypatch.setattr(screening_daily, "_fetch_daily_tencent", lambda *args, **kwargs: history.copy())
    monkeypatch.setattr(screening_daily, "daily_history_is_stale", lambda *args, **kwargs: False)

    for url in (old_url, "https://[broken"):
        monkeypatch.setenv(url_env, url)
        snapshot = screening_snapshot.fetch_snapshot_with_fallback(["tushare", "sina"])
        daily = screening_daily.fetch_daily_history("600519", source="auto", retries=0)
        assert snapshot.attrs["snapshot_source"] == "sina"
        assert daily.attrs["daily_source"] == "tencent"
    assert "Invalid IPv6 URL" in snapshot.attrs["source_errors"][0]
    assert "Invalid IPv6 URL" in daily.attrs["source_errors"][0]


def test_screening_snapshot_and_daily_disable_tushare_on_first_permission_error_and_recover_on_token_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "low-points-token")
    tushare_snap_calls = 0

    def fake_tushare_snapshot() -> pd.DataFrame:
        nonlocal tushare_snap_calls
        tushare_snap_calls += 1
        raise RuntimeError("抱歉，您没有访问该接口的权限，积分不足")

    sina_df = pd.DataFrame(
        {
            "code": ["600519"],
            "name": ["贵州茅台"],
            "price": [1510.0],
            "change_pct": [0.8],
            "amount": [1.5e8],
            "total_mv": [1.9e12],
            "circ_mv": [1.9e12],
            "pe_ratio": [25.0],
            "pb_ratio": [8.0],
            "volume_ratio": [1.1],
            "turnover_rate": [0.3],
        }
    )
    monkeypatch.setattr(screening_snapshot, "_fetch_tushare", fake_tushare_snapshot)
    monkeypatch.setattr(screening_snapshot, "_fetch_sina", lambda: sina_df.copy())

    out1 = screening_snapshot.fetch_snapshot_with_fallback(["tushare", "sina"])
    assert out1.attrs["snapshot_source"] == "sina"
    assert tushare_snap_calls == 1
    assert screening_snapshot.snapshot_source_health_snapshot(["tushare"])["tushare"]["disabled"] is True

    # Second screening run skips tushare immediately (not waiting for 3 failures!)
    out2 = screening_snapshot.fetch_snapshot_with_fallback(["tushare", "sina"])
    assert out2.attrs["snapshot_source"] == "sina"
    assert tushare_snap_calls == 1

    # Updating TUSHARE_TOKEN clears the permission cooldown automatically
    monkeypatch.setenv("TUSHARE_TOKEN", "upgraded-2000pt-token")
    assert screening_snapshot.snapshot_source_health_snapshot(["tushare"])["tushare"]["disabled"] is False

    # Screening daily: permission error does NOT retry 3 times and disables immediately
    monkeypatch.setenv("TUSHARE_TOKEN", "zero-pt-daily-token")
    tushare_daily_calls = 0

    def fake_daily_tushare(code: str, *, lookback_days: int) -> pd.DataFrame:
        nonlocal tushare_daily_calls
        tushare_daily_calls += 1
        raise RuntimeError("抱歉，您没有访问该接口的权限")

    fresh_bar_date = pd.Timestamp("2026-03-20")
    tencent_hist = pd.DataFrame(
        {
            "date": pd.date_range(end=fresh_bar_date, periods=35, freq="B"),
            "open": [10.0] * 35,
            "high": [10.5] * 35,
            "low": [9.8] * 35,
            "close": [10.2] * 35,
            "volume": [100000.0] * 35,
            "amount": [1020000.0] * 35,
        }
    )
    monkeypatch.setattr(screening_daily, "_fetch_daily_tushare", fake_daily_tushare)
    monkeypatch.setattr(screening_daily, "_fetch_daily_tencent", lambda code, *, lookback_days: tencent_hist.copy())
    monkeypatch.setattr(screening_daily, "daily_history_is_stale", lambda df, code=None: False)

    hist1 = screening_daily.fetch_daily_history("600519", source="auto", retries=2)
    assert hist1.attrs["daily_source"] == "tencent"
    assert tushare_daily_calls == 1  # Zero wasted retries!
    assert screening_daily.daily_source_health_snapshot()["tushare"]["disabled"] is True

    hist2 = screening_daily.fetch_daily_history("000001", source="auto", retries=2)
    assert hist2.attrs["daily_source"] == "tencent"
    assert tushare_daily_calls == 1  # Skipped on subsequent candidate stocks!


@pytest.mark.parametrize(
    "denied_api, denied_codes, allowed_code",
    [
        ("fund_daily", ["510300", "510500", "159915"], "600519"),
        ("daily", ["600519", "000001", "601318"], "510300"),
    ],
)
def test_manager_permission_denials_do_not_disable_other_endpoints_or_new_tokens(
    denied_api, denied_codes, allowed_code,
) -> None:
    """Exercise HTTP -> fetcher -> manager, including cached denials in the same market."""
    rows = pd.DataFrame({
        "date": pd.to_datetime(["2026-03-20"]), "open": [10.0], "high": [11.0],
        "low": [9.0], "close": [10.5], "volume": [100.0], "amount": [1050.0],
        "pct_chg": [5.0],
    })
    fallback = _DummyFallbackFetcher(rows)
    with patch("data_provider.tushare_fetcher.get_config", return_value=SimpleNamespace(tushare_token="old-token")):
        fetcher = TushareFetcher()
    manager = DataFetcherManager(fetchers=[fetcher, fallback])
    calls = []

    def fake_post(url, json, timeout):
        calls.append((json["token"], json["api_name"]))
        if json["token"] == "old-token" and json["api_name"] == denied_api:
            return _http_json_response({"code": 40203, "msg": "permission denied"})
        return _http_json_response({"code": 0, "data": {
            "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"],
            "items": [[json["params"]["ts_code"], "20260320", 10, 11, 9, 10.5, 100, 1050, 5]],
        }})

    def get(provider_manager, code):
        return provider_manager.get_daily_data(code, start_date="2026-03-19", end_date="2026-03-20")[1]

    with patch("data_provider.tushare_fetcher.requests.post", side_effect=fake_post):
        for code in denied_codes:
            assert get(manager, code) == fallback.name
        assert calls == [("old-token", denied_api)]
        # Check rotation before any successful old-token request could clear health.
        with patch("data_provider.tushare_fetcher.get_config", return_value=SimpleNamespace(tushare_token="new-token")):
            renewed = TushareFetcher()
        renewed_manager = DataFetcherManager(fetchers=[renewed, fallback])
        assert get(renewed_manager, denied_codes[0]) == fetcher.name
        assert get(manager, allowed_code) == fetcher.name
        assert calls[1] == ("new-token", denied_api)
        assert calls[2][0] == "old-token" and calls[2][1] != denied_api


def test_manager_permission_denial_preserves_network_failures_and_half_open_recovery() -> None:
    rows = pd.DataFrame({
        "date": pd.to_datetime(["2026-03-20"]), "open": [10.0], "high": [11.0],
        "low": [9.0], "close": [10.5], "volume": [100.0], "amount": [1050.0],
        "pct_chg": [5.0],
    })
    with patch("data_provider.tushare_fetcher.get_config", return_value=SimpleNamespace(tushare_token="network-token")):
        fetcher = TushareFetcher()
    fallback = _DummyFallbackFetcher(rows)
    manager = DataFetcherManager(fetchers=[fetcher, fallback])
    key = manager._daily_health_key(fetcher, "cn")
    clock = [1000.0]

    def fake_post(url, json, timeout):
        if json["api_name"] == "fund_daily":
            return _http_json_response({"code": 40203, "msg": "permission denied"})
        return MagicMock(status_code=503)

    def get(code):
        assert manager.get_daily_data(code, start_date="2026-03-19", end_date="2026-03-20")[1] == fallback.name

    with patch("data_provider.tushare_fetcher.requests.post", side_effect=fake_post) as post, patch(
        "data_provider.realtime_types.time.time", side_effect=lambda: clock[0],
    ):
        get("600519")
        get("000001")
        get("510300")  # Permission must neither increment nor clear the two failures.
        state = manager._daily_source_health._states[key]
        assert state["failures"] == 2 and state["state"] == "closed"
        get("601318")
        assert state["failures"] == 3 and state["state"] == "open"
        calls_before = post.call_count
        get("600519")
        assert post.call_count == calls_before
        clock[0] += 301
        get("510500")  # Cached permission rejection consumes no HTTP/probe forever.
        assert post.call_count == calls_before
        assert state["state"] == "open" and state["failures"] == 3
        clock[0] += 301
        get("600519")
        assert post.call_count == calls_before + 1
