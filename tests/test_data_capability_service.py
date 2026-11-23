# -*- coding: utf-8 -*-
"""Tests for the data capability overview service."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from src.services.data_capability_service import DataCapabilityService


class _Fetcher:
    def __init__(
        self,
        name: str,
        priority: int,
        *,
        available=None,
        last_error: str = "",
        is_available=None,
        is_available_for_request=None,
    ) -> None:
        self.name = name
        self.priority = priority
        if available is not None:
            self._available = available
        if last_error:
            self.last_error = last_error
        if is_available is not None:
            self.is_available = lambda: is_available
        if is_available_for_request is not None:
            self.is_available_for_request = lambda _capability="": is_available_for_request


class _FetcherManager:
    def __init__(self, fetchers) -> None:
        self._fetchers = fetchers

    def _get_fetchers_snapshot(self):
        return list(self._fetchers)


class _RuntimeScheduler:
    def __init__(self, active: bool) -> None:
        self.active = active

    def is_background_task_active(self, name: str) -> bool:
        return self.active and name == "agent_event_monitor"


def _config(**overrides):
    values = {
        "tushare_token": None,
        "tickflow_api_key": None,
        "tickflow_priority": 2,
        "futu_opend_host": None,
        "longbridge_app_key": None,
        "longbridge_app_secret": None,
        "longbridge_access_token": None,
        "longbridge_oauth_client_id": None,
        "finnhub_api_key": None,
        "alphavantage_api_key": None,
        "enable_realtime_quote": True,
        "enable_fundamental_pipeline": True,
        "realtime_source_priority": "tencent,akshare_sina,efinance,akshare_em",
        "futu_hk_realtime_source_priority": "futu,longbridge,akshare,yfinance",
        "screening_enabled": False,
        "agent_event_monitor_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _dataset(overview, name: str):
    return next(item for item in overview["datasets"] if item["dataset"] == name)


def _provider(overview, name: str):
    return next(item for item in overview["providers"] if item["name"] == name)


def test_overview_marks_tickflow_priority_gap_without_leaking_secret() -> None:
    manager = _FetcherManager([
        _Fetcher("AkshareFetcher", 1, available=True),
        _Fetcher("EfinanceFetcher", 3, available=True),
        _Fetcher("TickFlowFetcher", 2),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    secret = "tickflow-secret-value"
    service = DataCapabilityService(
        config=_config(tickflow_api_key=secret, realtime_source_priority="tencent,efinance"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()

    assert _provider(overview, "tickflow")["configured"] is True
    assert _provider(overview, "tickflow")["status"] == "unknown"
    assert _provider(overview, "tickflow")["warnings"] == ["runtime_probe_not_performed"]
    assert "tickflow_configured_but_not_in_realtime_priority" in overview["warnings"]
    assert secret not in json.dumps(overview, ensure_ascii=False)


def test_realtime_dataset_degrades_when_first_priority_source_is_unconfigured() -> None:
    manager = _FetcherManager([
        _Fetcher("EfinanceFetcher", 0, available=True),
        _Fetcher("AkshareFetcher", 1, available=True),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(realtime_source_priority="tushare,efinance"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    quote_quality = _dataset(overview, "quote.realtime")

    assert quote_quality["status"] == "degraded"
    assert quote_quality["source"] is None
    assert quote_quality["fallback_from"] == ["cn:tushare", "hk:longbridge"]
    assert quote_quality["coverage"]["markets"]["cn"]["status"] == "degraded"
    assert quote_quality["coverage"]["markets"]["cn"]["source"] == "efinance"
    assert "cn:source_status:tushare:unconfigured" in quote_quality["warnings"]


def test_provider_runtime_probe_preserves_unknown_until_checked() -> None:
    manager = _FetcherManager([
        _Fetcher("TickFlowFetcher", 1),
        _Fetcher("TushareFetcher", 2, is_available=False),
    ])
    service = DataCapabilityService(
        config=_config(tickflow_api_key="secret", tushare_token="token"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()

    assert _provider(overview, "tickflow")["status"] == "unknown"
    assert _provider(overview, "tushare")["status"] == "unavailable"


def test_provider_runtime_probe_honors_request_time_unavailable_over_cached_available_flag() -> None:
    manager = _FetcherManager([
        _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=False),
    ])
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()

    assert _provider(overview, "longbridge")["status"] == "unavailable"
    assert _provider(overview, "longbridge")["warnings"] == ["provider_marked_unavailable"]


def test_us_realtime_priority_skips_longbridge_during_request_cooldown() -> None:
    manager = _FetcherManager([
        _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=False),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    us_quality = _dataset(overview, "quote.realtime")["coverage"]["markets"]["us"]

    assert priorities["us.realtime"]["providers"] == ["yfinance", "longbridge"]
    assert us_quality["status"] == "ok"
    assert us_quality["source"] == "yfinance"
    assert us_quality["fallback_from"] == []


def test_provider_dataset_market_matrix_matches_fundamental_runtime_routes() -> None:
    service = DataCapabilityService(
        config=_config(
            tushare_token="token",
            longbridge_app_key="key",
            futu_opend_host="127.0.0.1",
        ),
        fetcher_manager=_FetcherManager([]),
    )

    overview = service.get_overview()

    assert _provider(overview, "akshare")["dataset_markets"]["financial.snapshot"] == ["cn"]
    assert _provider(overview, "futu")["dataset_markets"]["financial.snapshot"] == ["hk"]
    assert _provider(overview, "yfinance")["dataset_markets"]["financial.snapshot"] == [
        "hk",
        "us",
        "jp",
        "kr",
        "tw",
    ]
    assert "financial.snapshot" not in _provider(overview, "tushare")["datasets"]
    assert "financial.snapshot" not in _provider(overview, "longbridge")["datasets"]
    assert _provider(overview, "tushare")["dataset_markets"]["quote.realtime"] == ["cn"]
    assert "index.daily" not in _provider(overview, "tushare")["datasets"]
    assert _provider(overview, "yfinance")["dataset_markets"]["quote.realtime"] == [
        "hk",
        "us",
        "jp",
        "kr",
        "tw",
    ]
    assert _provider(overview, "yfinance")["dataset_markets"]["index.daily"] == [
        "cn",
        "us",
    ]
    assert "quote.realtime" not in _provider(overview, "pytdx")["datasets"]
    assert "quote.realtime" not in _provider(overview, "finnhub")["datasets"]
    assert "quote.realtime" not in _provider(overview, "alphavantage")["datasets"]
    assert "index.daily" not in _provider(overview, "finnhub")["datasets"]


def test_hk_realtime_priority_skips_futu_when_opend_is_unconfigured() -> None:
    service = DataCapabilityService(
        config=_config(futu_opend_host=None),
        fetcher_manager=_FetcherManager([_Fetcher("YfinanceFetcher", 4, available=True)]),
    )

    overview = service.get_overview()
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    hk_quality = _dataset(overview, "quote.realtime")["coverage"]["markets"]["hk"]

    assert priorities["hk.realtime"]["providers"] == ["longbridge", "akshare", "yfinance"]
    assert "futu" not in hk_quality["fallback_from"]


def test_realtime_dataset_quality_is_market_aware() -> None:
    manager = _FetcherManager([
        _Fetcher("EfinanceFetcher", 0, available=True),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(
            realtime_source_priority="efinance",
            futu_hk_realtime_source_priority="futu,longbridge",
        ),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    quote_quality = _dataset(overview, "quote.realtime")
    priorities = {item["scenario"]: item for item in overview["priorities"]}

    assert priorities["us.realtime"]["providers"] == ["yfinance", "longbridge"]
    assert quote_quality["status"] == "partial"
    assert quote_quality["coverage"]["markets"]["cn"]["status"] == "ok"
    assert quote_quality["coverage"]["markets"]["cn"]["source"] == "efinance"
    assert quote_quality["coverage"]["markets"]["hk"]["status"] == "unavailable"
    assert quote_quality["coverage"]["markets"]["us"]["status"] == "ok"
    for market in ("jp", "kr", "tw"):
        assert quote_quality["coverage"]["markets"][market] == {
            "status": "ok",
            "source": "yfinance",
            "fallback_from": [],
            "warnings": [],
        }


def test_cn_realtime_quality_honors_akshare_subsource_circuit_breaker() -> None:
    from data_provider.realtime_types import get_realtime_circuit_breaker

    breaker = get_realtime_circuit_breaker()
    breaker.reset("akshare_tencent")
    try:
        for _ in range(3):
            breaker.record_failure("akshare_tencent", "test failure")
        service = DataCapabilityService(
            config=_config(realtime_source_priority="tencent,efinance"),
            fetcher_manager=_FetcherManager([
                _Fetcher("AkshareFetcher", 0),
                _Fetcher("EfinanceFetcher", 1, available=True),
                _Fetcher("YfinanceFetcher", 4, available=True),
            ]),
        )

        quote_quality = _dataset(service.get_overview(), "quote.realtime")
        cn_quality = quote_quality["coverage"]["markets"]["cn"]

        assert cn_quality["status"] == "degraded"
        assert cn_quality["source"] == "efinance"
        assert cn_quality["fallback_from"] == ["tencent"]
        assert cn_quality["warnings"] == ["source_status:tencent:cooldown"]
    finally:
        breaker.reset("akshare_tencent")


def test_daily_circuit_open_precedes_unknown_provider_probe() -> None:
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=_FetcherManager([
            _Fetcher("EfinanceFetcher", 0),
            _Fetcher("PytdxFetcher", 1, available=True),
        ]),
    )

    with patch(
        "data_provider.base.DataFetcherManager._is_daily_source_available",
        side_effect=lambda fetcher, _market: fetcher.name != "EfinanceFetcher",
    ):
        cn_quality = _dataset(service.get_overview(), "kline.daily")["coverage"]["markets"]["cn"]

    assert cn_quality["status"] == "degraded"
    assert cn_quality["source"] == "pytdx"
    assert cn_quality["fallback_from"] == ["efinance"]
    assert cn_quality["warnings"] == ["source_status:efinance:cooldown"]


def test_cn_realtime_reports_fixed_index_route_separately_from_stock_priority() -> None:
    service = DataCapabilityService(
        config=_config(
            tushare_token="token",
            realtime_source_priority="tushare",
        ),
        fetcher_manager=_FetcherManager([
            _Fetcher("TushareFetcher", 0, available=True),
            _Fetcher("EfinanceFetcher", 1, available=False),
        ]),
    )

    quote_quality = _dataset(service.get_overview(), "quote.realtime")
    markets = quote_quality["coverage"]["markets"]

    assert markets["cn"]["status"] == "ok"
    assert markets["cn"]["source"] == "tushare"
    assert markets["cn.index.exchange"]["status"] == "unavailable"
    assert markets["cn.index.csi"]["status"] == "unavailable"
    assert quote_quality["status"] == "partial"


def test_efinance_realtime_breakers_apply_to_stock_and_index_routes() -> None:
    from data_provider.realtime_types import get_realtime_circuit_breaker

    breaker = get_realtime_circuit_breaker()
    try:
        for key in ("efinance", "efinance_index"):
            breaker.reset(key)
            for _ in range(3):
                breaker.record_failure(key, "test")
        service = DataCapabilityService(
            config=_config(realtime_source_priority="efinance,tencent"),
            fetcher_manager=_FetcherManager([
                _Fetcher("EfinanceFetcher", 0, available=True),
                _Fetcher("AkshareFetcher", 1, available=True),
            ]),
        )

        markets = _dataset(service.get_overview(), "quote.realtime")["coverage"]["markets"]

        assert markets["cn"]["source"] == "tencent"
        assert markets["cn"]["fallback_from"] == ["efinance"]
        assert markets["cn.index.csi"]["status"] == "unavailable"
        assert markets["cn.index.csi"]["warnings"] == ["source_status:efinance:cooldown"]
    finally:
        breaker.reset("efinance")
        breaker.reset("efinance_index")


def test_hk_realtime_falls_back_only_when_both_akshare_routes_are_open() -> None:
    from data_provider.realtime_types import get_realtime_circuit_breaker

    breaker = get_realtime_circuit_breaker()
    try:
        for key in ("akshare_hk_em", "akshare_hk_sina"):
            breaker.reset(key)
            for _ in range(3):
                breaker.record_failure(key, "test")
        service = DataCapabilityService(
            config=_config(futu_hk_realtime_source_priority="akshare,yfinance"),
            fetcher_manager=_FetcherManager([
                _Fetcher("AkshareFetcher", 1, available=True),
                _Fetcher("YfinanceFetcher", 4, available=True),
            ]),
        )

        hk_quality = _dataset(service.get_overview(), "quote.realtime")["coverage"]["markets"]["hk"]

        assert hk_quality["status"] == "degraded"
        assert hk_quality["source"] == "yfinance"
        assert hk_quality["fallback_from"] == ["akshare"]
    finally:
        breaker.reset("akshare_hk_em")
        breaker.reset("akshare_hk_sina")


def test_us_index_realtime_keeps_yfinance_ahead_of_healthy_longbridge() -> None:
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=_FetcherManager([
            _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=True),
            _Fetcher("YfinanceFetcher", 4, available=True),
        ]),
    )

    markets = _dataset(service.get_overview(), "quote.realtime")["coverage"]["markets"]

    assert markets["us"]["source"] == "longbridge"
    assert markets["us.index"]["source"] == "yfinance"
    assert markets["us.index"]["fallback_from"] == []


def test_us_index_realtime_does_not_fallback_to_longbridge() -> None:
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=_FetcherManager([
            _Fetcher("LongbridgeFetcher", 1, available=True, is_available_for_request=True),
            _Fetcher("YfinanceFetcher", 4, available=False),
        ]),
    )

    markets = _dataset(service.get_overview(), "quote.realtime")["coverage"]["markets"]

    assert markets["us"]["source"] == "longbridge"
    assert markets["us.index"]["status"] == "unavailable"
    assert markets["us.index"]["source"] is None
    assert markets["us.index"]["fallback_from"] == ["yfinance"]


def test_cn_realtime_rejects_tokens_without_runtime_handlers() -> None:
    service = DataCapabilityService(
        config=_config(realtime_source_priority="yfinance,efinance"),
        fetcher_manager=_FetcherManager([
            _Fetcher("YfinanceFetcher", 0, available=True),
            _Fetcher("EfinanceFetcher", 1, available=True),
        ]),
    )

    overview = service.get_overview()
    cn_quality = _dataset(overview, "quote.realtime")["coverage"]["markets"]["cn"]
    priorities = {item["scenario"]: item for item in overview["priorities"]}

    assert priorities["cn.realtime"]["warnings"] == ["unknown_source:yfinance"]
    assert cn_quality["status"] == "degraded"
    assert cn_quality["source"] == "efinance"
    assert cn_quality["fallback_from"] == ["yfinance"]
    assert "source_status:yfinance:unsupported" in cn_quality["warnings"]


def test_hk_realtime_rejects_configured_provider_without_runtime_handler() -> None:
    service = DataCapabilityService(
        config=_config(
            tushare_token="token",
            futu_hk_realtime_source_priority="tushare,yfinance",
        ),
        fetcher_manager=_FetcherManager([
            _Fetcher("TushareFetcher", 0, available=True),
            _Fetcher("YfinanceFetcher", 1, available=True),
        ]),
    )

    overview = service.get_overview()
    hk_quality = _dataset(overview, "quote.realtime")["coverage"]["markets"]["hk"]

    assert hk_quality["status"] == "degraded"
    assert hk_quality["source"] == "yfinance"
    assert hk_quality["fallback_from"] == ["tushare"]
    assert "source_status:tushare:unsupported" in hk_quality["warnings"]


def test_runtime_ordered_daily_route_stops_at_unprobed_preferred_source() -> None:
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=_FetcherManager([
            _Fetcher("EfinanceFetcher", 0),
            _Fetcher("PytdxFetcher", 1, available=True),
        ]),
    )

    cn_quality = _dataset(service.get_overview(), "kline.daily")["coverage"]["markets"]["cn"]

    assert cn_quality["status"] == "unknown"
    assert cn_quality["source"] is None
    assert cn_quality["fallback_from"] == []
    assert cn_quality["warnings"] == ["source_status:efinance:unknown"]


def test_daily_dataset_quality_is_market_aware() -> None:
    manager = _FetcherManager([
        _Fetcher("EfinanceFetcher", 0, available=True),
        _Fetcher("YfinanceFetcher", 4, available=False),
    ])
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    daily_quality = _dataset(overview, "kline.daily")

    assert daily_quality["status"] == "partial"
    assert daily_quality["coverage"]["markets"]["cn"]["status"] == "ok"
    assert daily_quality["coverage"]["markets"]["cn"]["source"] == "efinance"
    assert daily_quality["coverage"]["markets"]["hk"]["status"] == "unavailable"
    assert daily_quality["coverage"]["markets"]["us"]["status"] == "unavailable"
    for market in ("jp", "kr", "tw"):
        assert daily_quality["coverage"]["markets"][market]["status"] == "unavailable"
    assert "hk:request_available_priority_empty" in daily_quality["warnings"]
    assert "us:request_available_priority_empty" in daily_quality["warnings"]


def test_daily_dataset_quality_prefers_longbridge_for_us_when_available() -> None:
    manager = _FetcherManager([
        _Fetcher("LongbridgeFetcher", 5, available=True, is_available_for_request=True),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(longbridge_app_key="key"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    daily_quality = _dataset(overview, "kline.daily")

    assert daily_quality["coverage"]["markets"]["us"]["status"] == "ok"
    assert daily_quality["coverage"]["markets"]["us"]["source"] == "longbridge"
    assert "us:finnhub" not in daily_quality["fallback_from"]


def test_us_daily_priority_omits_unregistered_configured_sources() -> None:
    manager = _FetcherManager([
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(config=_config(), fetcher_manager=manager)

    overview = service.get_overview()
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    us_quality = _dataset(overview, "kline.daily")["coverage"]["markets"]["us"]

    assert priorities["daily.generic"]["providers"] == ["yfinance"]
    assert us_quality["status"] == "ok"
    assert us_quality["source"] == "yfinance"
    assert us_quality["fallback_from"] == []


def test_daily_priority_excludes_request_unavailable_fetchers() -> None:
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=_FetcherManager([
            _Fetcher("EfinanceFetcher", 0, available=True, is_available_for_request=False),
            _Fetcher("PytdxFetcher", 1, available=True, is_available_for_request=True),
        ]),
    )

    overview = service.get_overview()
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    cn_daily = _dataset(overview, "kline.daily")["coverage"]["markets"]["cn"]

    assert priorities["daily.generic"]["providers"] == ["pytdx"]
    assert cn_daily["source"] == "pytdx"
    assert cn_daily["fallback_from"] == []


def test_daily_dataset_quality_honors_market_specific_circuit_breakers() -> None:
    manager = _FetcherManager([
        _Fetcher("EfinanceFetcher", 0, available=True),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=manager,
    )

    with patch(
        "data_provider.base.DataFetcherManager._is_daily_source_available",
        side_effect=lambda fetcher, market: not (
            getattr(fetcher, "name", "") == "YfinanceFetcher" and market == "hk"
        ),
    ):
        overview = service.get_overview()

    daily_quality = _dataset(overview, "kline.daily")

    assert daily_quality["status"] == "partial"
    assert daily_quality["coverage"]["markets"]["cn"]["status"] == "ok"
    assert daily_quality["coverage"]["markets"]["hk"]["status"] == "unavailable"
    assert daily_quality["coverage"]["markets"]["hk"]["source"] is None
    assert daily_quality["coverage"]["markets"]["us"]["status"] == "ok"
    assert daily_quality["coverage"]["markets"]["us"]["source"] == "yfinance"
    assert "hk:source_status:yfinance:cooldown" in daily_quality["warnings"]


def test_index_daily_quality_uses_only_the_executable_us_runtime_route() -> None:
    service = DataCapabilityService(
        config=_config(finnhub_api_key="key"),
        fetcher_manager=_FetcherManager([
            _Fetcher("TencentFetcher", 0, available=True),
            _Fetcher("AkshareFetcher", 1, available=True),
            _Fetcher("YfinanceFetcher", 2, available=False),
            _Fetcher("FinnhubFetcher", 3, available=True),
        ]),
    )

    overview = service.get_overview()
    index_quality = _dataset(overview, "index.daily")
    us_quality = index_quality["coverage"]["markets"]["us"]

    assert index_quality["status"] == "partial"
    assert us_quality["status"] == "unavailable"
    assert us_quality["source"] is None
    assert us_quality["fallback_from"] == ["yfinance"]
    assert "us:source_status:yfinance:unavailable" in index_quality["warnings"]
    assert not any("finnhub" in warning for warning in index_quality["warnings"])
    assert "index.daily" not in _provider(overview, "finnhub")["datasets"]


def test_market_overview_dataset_quality_is_market_aware() -> None:
    manager = _FetcherManager([
        _Fetcher("EfinanceFetcher", 0, available=True),
        _Fetcher("YfinanceFetcher", 4, available=True),
    ])
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    market_overview = _dataset(overview, "market.overview")

    assert market_overview["status"] == "ok"
    assert market_overview["source"] is None
    assert market_overview["coverage"]["markets"]["cn"]["source"] == "efinance"
    assert market_overview["coverage"]["markets"]["hk"]["source"] == "yfinance"
    assert market_overview["coverage"]["markets"]["us"]["source"] == "yfinance"
    assert market_overview["coverage"]["markets"]["jp"]["source"] == "yfinance"
    assert market_overview["coverage"]["markets"]["kr"]["source"] == "yfinance"
    assert market_overview["coverage"]["markets"]["tw"]["source"] == "yfinance"


def test_index_daily_quality_honors_cn_index_circuit_breakers() -> None:
    manager = _FetcherManager([
        _Fetcher("TencentFetcher", 0, available=True),
        _Fetcher("AkshareFetcher", 1, available=True),
        _Fetcher("YfinanceFetcher", 2, available=True),
    ])
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=manager,
    )

    with patch(
        "data_provider.base.DataFetcherManager._is_daily_source_available",
        side_effect=lambda fetcher, market: not (
            getattr(fetcher, "name", "") == "TencentFetcher" and market == "cn_index"
        ),
    ):
        overview = service.get_overview()

    index_quality = _dataset(overview, "index.daily")

    assert index_quality["status"] == "degraded"
    assert index_quality["source"] is None
    assert index_quality["coverage"]["markets"]["cn.exchange"]["status"] == "degraded"
    assert index_quality["coverage"]["markets"]["cn.exchange"]["fallback_from"] == ["tencent"]
    assert index_quality["coverage"]["markets"]["cn.csi"]["status"] == "ok"
    assert index_quality["coverage"]["markets"]["us"]["source"] == "yfinance"
    assert index_quality["fallback_from"] == ["cn.exchange:tencent"]
    assert index_quality["warnings"] == ["cn.exchange:source_status:tencent:cooldown"]


def test_index_daily_requires_akshare_for_csi_family() -> None:
    service = DataCapabilityService(
        config=_config(),
        fetcher_manager=_FetcherManager([
            _Fetcher("TencentFetcher", 0, available=True),
            _Fetcher("AkshareFetcher", 1, available=False),
        ]),
    )

    index_quality = _dataset(service.get_overview(), "index.daily")

    assert index_quality["status"] == "partial"
    assert index_quality["coverage"]["markets"]["cn.exchange"]["source"] == "tencent"
    assert index_quality["coverage"]["markets"]["cn.csi"]["status"] == "unavailable"
    assert index_quality["coverage"]["markets"]["cn.csi"]["source"] is None


def test_fundamental_dataset_quality_is_market_aware() -> None:
    manager = _FetcherManager([
        _Fetcher("AkshareFetcher", 1, available=True),
        _Fetcher("TushareFetcher", 2, available=True),
        _Fetcher("YfinanceFetcher", 4, available=False),
    ])
    service = DataCapabilityService(
        config=_config(tushare_token="token"),
        fetcher_manager=manager,
    )

    overview = service.get_overview()
    fundamental_quality = _dataset(overview, "financial.snapshot")

    assert fundamental_quality["status"] == "partial"
    assert fundamental_quality["coverage"]["markets"]["cn"]["status"] == "ok"
    assert fundamental_quality["coverage"]["markets"]["cn"]["source"] == "akshare"
    assert fundamental_quality["coverage"]["markets"]["hk"]["status"] == "unavailable"
    assert fundamental_quality["coverage"]["markets"]["hk"]["source"] is None
    assert fundamental_quality["coverage"]["markets"]["us"]["status"] == "unavailable"
    assert fundamental_quality["coverage"]["markets"]["us"]["source"] is None
    for market in ("jp", "kr", "tw"):
        assert fundamental_quality["coverage"]["markets"][market]["status"] == "unavailable"
        assert fundamental_quality["coverage"]["markets"][market]["source"] is None
    assert "hk:source_status:yfinance:unavailable" in fundamental_quality["warnings"]
    assert "us:source_status:yfinance:unavailable" in fundamental_quality["warnings"]


def test_screening_snapshot_priority_preserves_explicit_env_override() -> None:
    service = DataCapabilityService(
        config=_config(screening_enabled=True),
        fetcher_manager=_FetcherManager([]),
    )

    with patch.dict("os.environ", {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False):
        with patch(
            "src.services.screening_service._resolve_screening_snapshot_source_priority",
            side_effect=AssertionError("resolver should not run when override is set"),
        ):
            overview = service.get_overview()

    priorities = {item["scenario"]: item for item in overview["priorities"]}
    screening = priorities["screening.snapshot"]

    assert screening["providers"] == ["tushare", "em_datacenter"]


def test_screening_dataset_reports_engine_unavailable() -> None:
    service = DataCapabilityService(
        config=_config(screening_enabled=True),
        fetcher_manager=_FetcherManager([]),
    )

    with patch.dict("os.environ", {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False):
        with patch(
            "src.services.screening_service._get_screening_status_snapshot",
            return_value=({}, False, {"error": "screening_unavailable"}),
        ):
            with patch(
                "src.services.screening_service._get_screening_source_health_snapshot",
                return_value={},
            ):
                overview = service.get_overview()

    screening_quality = _dataset(overview, "strategy.screening")

    assert screening_quality["status"] == "unavailable"
    assert screening_quality["source"] is None
    assert screening_quality["warnings"] == ["screening_engine_unavailable"]


def test_screening_dataset_reports_cooldown_sources_as_unavailable() -> None:
    service = DataCapabilityService(
        config=_config(screening_enabled=True),
        fetcher_manager=_FetcherManager([]),
    )

    with patch.dict("os.environ", {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False):
        with patch(
            "src.services.screening_service._get_screening_status_snapshot",
            return_value=({"available": True}, True, None),
        ):
            with patch(
                "src.services.screening_service._get_screening_source_health_snapshot",
                return_value={
                    "snapshot": {
                        "tushare": {"disabled": True},
                        "em_datacenter": {"disabled": True},
                    }
                },
            ):
                overview = service.get_overview()

    screening_quality = _dataset(overview, "strategy.screening")

    assert screening_quality["status"] == "unavailable"
    assert screening_quality["source"] is None
    assert screening_quality["fallback_from"] == ["tushare", "em_datacenter"]
    assert screening_quality["warnings"] == [
        "source_status:tushare:cooldown",
        "source_status:em_datacenter:cooldown",
    ]


def test_screening_dataset_keeps_known_sources_unknown_before_runtime_probe() -> None:
    service = DataCapabilityService(
        config=_config(screening_enabled=True),
        fetcher_manager=_FetcherManager([]),
    )

    with patch.dict("os.environ", {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False):
        with patch(
            "src.services.screening_service._get_screening_status_snapshot",
            return_value=({"available": True}, True, None),
        ):
            with patch(
                "src.services.screening_service._get_screening_source_health_snapshot",
                return_value={
                    "snapshot": {
                        "tushare": {"successes": 0, "failures": 0, "disabled": False},
                        "em_datacenter": {"successes": 0, "failures": 0, "disabled": False},
                    }
                },
            ):
                overview = service.get_overview()

    screening_quality = _dataset(overview, "strategy.screening")

    assert screening_quality["status"] == "unknown"
    assert screening_quality["source"] is None
    assert screening_quality["fallback_from"] == []
    assert screening_quality["warnings"] == [
        "source_status:tushare:unknown",
    ]


def test_screening_dataset_does_not_skip_unprobed_preferred_source() -> None:
    service = DataCapabilityService(
        config=_config(screening_enabled=True),
        fetcher_manager=_FetcherManager([]),
    )

    with patch.dict("os.environ", {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False):
        with patch(
            "src.services.screening_service._get_screening_status_snapshot",
            return_value=({"available": True}, True, None),
        ):
            with patch(
                "src.services.screening_service._get_screening_source_health_snapshot",
                return_value={
                    "snapshot": {
                        "tushare": {"successes": 0, "failures": 0, "disabled": False},
                        "em_datacenter": {"successes": 1},
                    }
                },
            ):
                screening_quality = _dataset(service.get_overview(), "strategy.screening")

    assert screening_quality["status"] == "unknown"
    assert screening_quality["source"] is None
    assert screening_quality["fallback_from"] == []
    assert screening_quality["warnings"] == ["source_status:tushare:unknown"]


def test_screening_dataset_does_not_select_unknown_snapshot_source() -> None:
    service = DataCapabilityService(
        config=_config(screening_enabled=True),
        fetcher_manager=_FetcherManager([]),
    )

    with patch.dict("os.environ", {"SNAPSHOT_SOURCE_PRIORITY": "mystery_source,em_datacenter"}, clear=False):
        with patch(
            "src.services.screening_service._get_screening_status_snapshot",
            return_value=({"available": True}, True, None),
        ):
            with patch(
                "src.services.screening_service._get_screening_source_health_snapshot",
                return_value={"snapshot": {"em_datacenter": {"successes": 1}}},
            ):
                overview = service.get_overview()

    screening_quality = _dataset(overview, "strategy.screening")

    assert screening_quality["status"] == "degraded"
    assert screening_quality["source"] == "em_datacenter"
    assert screening_quality["fallback_from"] == ["mystery_source"]
    assert screening_quality["warnings"] == [
        "unknown_source:mystery_source",
        "source_status:mystery_source:unsupported",
    ]


def test_daily_capability_contract_includes_market_specific_daily_fetchers() -> None:
    service = DataCapabilityService(
        config=_config(
            futu_opend_host="127.0.0.1",
            finnhub_api_key="key",
            alphavantage_api_key="key",
        ),
        fetcher_manager=_FetcherManager([]),
    )

    overview = service.get_overview()

    assert "kline.daily" in _provider(overview, "futu")["datasets"]
    assert "kline.daily" in _provider(overview, "finnhub")["datasets"]
    assert "kline.daily" in _provider(overview, "alphavantage")["datasets"]


def test_disabled_runtime_features_surface_dataset_quality_warnings() -> None:
    manager = _FetcherManager([_Fetcher("AkshareFetcher", 1), _Fetcher("YfinanceFetcher", 4)])
    service = DataCapabilityService(
        config=_config(
            enable_realtime_quote=False,
            enable_fundamental_pipeline=False,
            screening_enabled=False,
        ),
        fetcher_manager=manager,
    )

    overview = service.get_overview()

    assert _dataset(overview, "quote.realtime")["status"] == "unavailable"
    assert _dataset(overview, "quote.realtime")["warnings"] == ["realtime_quote_disabled"]
    assert _dataset(overview, "financial.snapshot")["status"] == "unavailable"
    assert _dataset(overview, "financial.snapshot")["warnings"] == ["fundamental_pipeline_disabled"]
    assert _dataset(overview, "strategy.screening")["status"] == "unconfigured"
    assert _dataset(overview, "strategy.screening")["warnings"] == ["screening_disabled"]
    assert _dataset(overview, "alert.monitor")["status"] == "unavailable"
    assert _dataset(overview, "alert.monitor")["source"] is None
    assert _dataset(overview, "alert.monitor")["warnings"] == ["agent_event_monitor_disabled"]
    assert _dataset(overview, "news.events")["source"] is None


def test_enabled_alert_monitor_requires_a_registered_live_scheduler_task() -> None:
    service = DataCapabilityService(
        config=_config(agent_event_monitor_enabled=True),
        fetcher_manager=_FetcherManager([]),
        runtime_scheduler=_RuntimeScheduler(active=False),
    )

    quality = _dataset(service.get_overview(), "alert.monitor")

    assert quality["status"] == "unavailable"
    assert quality["source"] is None
    assert quality["warnings"] == ["agent_event_monitor_not_running"]


def test_running_alert_monitor_surfaces_local_dataset_as_available() -> None:
    service = DataCapabilityService(
        config=_config(agent_event_monitor_enabled=True),
        fetcher_manager=_FetcherManager([]),
        runtime_scheduler=_RuntimeScheduler(active=True),
    )

    quality = _dataset(service.get_overview(), "alert.monitor")

    assert quality["status"] == "ok"
    assert quality["source"] == "alerts"
    assert quality["warnings"] == []


def test_data_capability_api_paths_return_valid_contract() -> None:
    overview_payload = {
        "as_of": "2026-08-26T15:05:00+08:00",
        "providers": [
            {
                "name": "efinance",
                "label": "Efinance",
                "enabled": True,
                "configured": True,
                "status": "ok",
                "priority": 0,
                "markets": ["cn"],
                "datasets": ["quote.realtime"],
                "dataset_markets": {"quote.realtime": ["cn"]},
                "warnings": [],
                "last_error": None,
                "cooldown": None,
            }
        ],
        "datasets": [
            {
                "dataset": "quote.realtime",
                "status": "ok",
                "source": "efinance",
                "stale": False,
                "last_success": None,
                "last_error": None,
                "fallback_from": [],
                "coverage": None,
                "warnings": [],
            }
        ],
        "priorities": [
            {
                "scenario": "cn.realtime",
                "providers": ["efinance"],
                "source": "test",
                "warnings": [],
            }
        ],
        "warnings": [],
    }

    class _Service:
        def __init__(self, *, config, runtime_scheduler=None) -> None:
            self.config = config
            self.runtime_scheduler = runtime_scheduler

        def get_overview(self):
            return overview_payload

    with tempfile.TemporaryDirectory() as temp_dir:
        client = TestClient(create_app(static_dir=Path(temp_dir)))
        with patch("api.v1.endpoints.data.DataCapabilityService", _Service):
            overview_response = client.get("/api/v1/data/overview")
            capabilities_response = client.get("/api/v1/data/capabilities")

    assert overview_response.status_code == 200
    assert capabilities_response.status_code == 200
    assert overview_response.json() == overview_payload
    assert capabilities_response.json() == overview_payload
