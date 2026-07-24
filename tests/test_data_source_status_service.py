# -*- coding: utf-8 -*-
"""Tests for the external data source integration status service."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.services.data_source_status_service import (
    DETAIL_PUBLIC_INSTANCE_AUTO_DISCOVERY,
    STATUS_ACTIVE,
    STATUS_NOT_CONFIGURED,
    DataSourceStatusService,
)


def _make_config(**overrides):
    base = dict(
        tushare_token=None,
        tickflow_api_key=None,
        finnhub_api_key=None,
        alphavantage_api_key=None,
        longbridge_app_key=None,
        longbridge_app_secret=None,
        longbridge_access_token=None,
        longbridge_oauth_client_id=None,
        anspire_api_keys=[],
        bocha_api_keys=[],
        tavily_api_keys=[],
        brave_api_keys=[],
        serpapi_keys=[],
        minimax_api_keys=[],
        searxng_base_urls=[],
        searxng_public_instances_enabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _by_id(entries, source_id):
    return next(entry for entry in entries if entry["source_id"] == source_id)


class DataSourceStatusServiceTestCase(unittest.TestCase):
    """Unit tests for config-derived status derivation."""

    def _get_status(self, config):
        service = DataSourceStatusService(config=config)
        with patch.object(DataSourceStatusService, "_daily_circuit_states", return_value={}):
            return service.get_status()

    def test_free_sources_active_and_optional_sources_not_configured(self):
        status = self._get_status(_make_config())

        market_data = status["market_data"]
        for source_id in ("efinance", "tencent", "akshare", "pytdx", "baostock", "yfinance"):
            self.assertEqual(_by_id(market_data, source_id)["status"], STATUS_ACTIVE)
            self.assertFalse(_by_id(market_data, source_id)["requires_credentials"])
        for source_id in ("tushare", "tickflow", "longbridge", "finnhub", "alphavantage"):
            entry = _by_id(market_data, source_id)
            self.assertEqual(entry["status"], STATUS_NOT_CONFIGURED)
            self.assertTrue(entry["requires_credentials"])
            self.assertTrue(entry["config_keys"])

        self.assertEqual(status["summary"]["market_data_active"], 6)
        self.assertEqual(status["summary"]["market_data_total"], 11)

    def test_configured_credentials_activate_optional_sources(self):
        status = self._get_status(
            _make_config(tushare_token="token", finnhub_api_key="key", tavily_api_keys=["k1"])
        )

        self.assertEqual(_by_id(status["market_data"], "tushare")["status"], STATUS_ACTIVE)
        self.assertEqual(_by_id(status["market_data"], "finnhub")["status"], STATUS_ACTIVE)
        self.assertEqual(_by_id(status["search"], "tavily")["status"], STATUS_ACTIVE)
        self.assertEqual(status["summary"]["market_data_active"], 8)
        self.assertEqual(status["summary"]["search_active"], 2)

    def test_blank_token_counts_as_not_configured(self):
        status = self._get_status(_make_config(tushare_token="   "))
        self.assertEqual(_by_id(status["market_data"], "tushare")["status"], STATUS_NOT_CONFIGURED)

    def test_searxng_public_instances_mode(self):
        status = self._get_status(_make_config())
        entry = _by_id(status["search"], "searxng")
        self.assertEqual(entry["status"], STATUS_ACTIVE)
        self.assertEqual(entry["detail"], DETAIL_PUBLIC_INSTANCE_AUTO_DISCOVERY)
        self.assertEqual(status["summary"]["search_active"], 1)

    def test_searxng_self_hosted_mode(self):
        status = self._get_status(
            _make_config(searxng_base_urls=["http://127.0.0.1:8888"], searxng_public_instances_enabled=False)
        )
        entry = _by_id(status["search"], "searxng")
        self.assertEqual(entry["status"], STATUS_ACTIVE)
        self.assertIsNone(entry["detail"])

    def test_searxng_fully_disabled(self):
        status = self._get_status(
            _make_config(searxng_public_instances_enabled=False)
        )
        entry = _by_id(status["search"], "searxng")
        self.assertEqual(entry["status"], STATUS_NOT_CONFIGURED)
        self.assertEqual(status["summary"]["search_active"], 0)

    def test_circuit_states_attached_to_matching_fetcher(self):
        circuit = {
            "daily_data:cn:EfinanceFetcher": "open",
            "daily_data:hk:AkshareFetcher": "half_open",
            "daily_data:cn:AkshareFetcher": "closed",
            "malformed-key": "open",
        }
        service = DataSourceStatusService(config=_make_config())
        with patch.object(DataSourceStatusService, "_daily_circuit_states", return_value=circuit):
            status = service.get_status()

        efinance = _by_id(status["market_data"], "efinance")
        self.assertEqual(efinance["circuit"], [{"market": "cn", "state": "open"}])
        akshare = _by_id(status["market_data"], "akshare")
        self.assertEqual(akshare["circuit"], [{"market": "hk", "state": "half_open"}])
        tencent = _by_id(status["market_data"], "tencent")
        self.assertEqual(tencent["circuit"], [])

    def test_payload_matches_api_schema(self):
        from api.v1.schemas.system_config import DataSourceStatusResponse

        status = self._get_status(_make_config())
        response = DataSourceStatusResponse.model_validate(status)
        self.assertEqual(response.summary.market_data_total, 11)
        self.assertEqual(response.summary.search_total, 7)


class DailySourceHealthSnapshotTestCase(unittest.TestCase):
    """DataFetcherManager exposes a read-only circuit breaker snapshot."""

    def test_snapshot_reflects_recorded_failures(self):
        from data_provider.base import DataFetcherManager
        from data_provider.realtime_types import CircuitBreaker

        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=300.0)
        breaker.record_failure("daily_data:cn:EfinanceFetcher", error="boom")
        with patch.object(DataFetcherManager, "_daily_source_health", breaker):
            snapshot = DataFetcherManager.get_daily_source_health_status()
        self.assertEqual(snapshot.get("daily_data:cn:EfinanceFetcher"), "open")


if __name__ == "__main__":
    unittest.main()
