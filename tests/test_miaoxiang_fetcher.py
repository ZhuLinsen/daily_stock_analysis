# -*- coding: utf-8 -*-
"""Tests for the Miaoxiang (妙想 MX_API) supplementary data provider."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from data_provider.miaoxiang_fetcher import (
    MiaoxiangFetcher,
    _parse_money_yuan,
    _parse_number,
    _parse_ratio,
)


def _make_table(head: List[str], indicators: Dict[str, List[str]], name_map: Dict[str, str]) -> Dict[str, Any]:
    table: Dict[str, Any] = {"headName": head}
    table.update(indicators)
    return {"table": table, "nameMap": name_map, "entityName": "test"}


def _make_response(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "status": 0,
        "message": "",
        "data": {"data": {"searchDataResultDTO": {"dataTableDTOList": tables}}},
    }


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload
        self.status_code = 200

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _fetcher_with_response(monkeypatch, payload: Dict[str, Any]) -> MiaoxiangFetcher:
    fetcher = MiaoxiangFetcher(api_key="test-key", cache_ttl=0)

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(payload)

    monkeypatch.setattr("data_provider.miaoxiang_fetcher.requests.post", fake_post)
    return fetcher


class TestParsers:
    def test_parse_number(self):
        assert _parse_number("13.91") == 13.91
        assert _parse_number("14.03元") == 14.03
        assert _parse_number("1,234.5") == 1234.5
        assert _parse_number("无数据") is None

    def test_parse_money_yuan(self):
        assert _parse_money_yuan("-93.64万元") == pytest.approx(-936400.0)
        assert _parse_money_yuan("1.2亿") == pytest.approx(1.2e8)
        assert _parse_money_yuan("-493.5万") == pytest.approx(-4935000.0)

    def test_parse_ratio(self):
        assert _parse_ratio("83.24%") == pytest.approx(0.8324)
        assert _parse_ratio("0.83") == pytest.approx(0.83)
        assert _parse_ratio(None) is None


class TestChipDistribution:
    def test_prefers_table_with_more_target_fields(self, monkeypatch):
        """自然语言返回的表格组合不稳定：应选中字段最全的快照表而非单字段序列表。"""
        snapshot = {
            "table": {
                "headName": ["2026-08-21 21:52"],
                "f1": ["13.91"],
                "f2": ["4.79%"],
                "f3": ["83.24%"],
                "f4": ["10.57%"],
            },
            "nameMap": {"f1": "平均成本", "f2": "70%筹码集中度", "f3": "获利比例", "f4": "90%筹码集中度"},
            "entityName": "盛航股份",
        }
        series = {
            "table": {
                "headName": ["2026-08-21(日)", "2026-08-20(日)", "2026-08-19(日)"],
                "f1": ["14.03元", "14.02元", "14.01元"],
            },
            "nameMap": {"f1": "平均成本"},
            "entityName": "盛航股份",
        }
        fetcher = _fetcher_with_response(monkeypatch, _make_response([snapshot, series]))
        chip = fetcher.get_chip_distribution("001205")
        assert chip is not None
        assert chip.avg_cost == pytest.approx(13.91)
        assert chip.profit_ratio == pytest.approx(0.8324)
        assert chip.concentration_90 == pytest.approx(0.1057)
        assert chip.concentration_70 == pytest.approx(0.0479)
        assert chip.source == "miaoxiang"

    def test_non_cn_codes_return_none(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, _make_response([]))
        assert fetcher.get_chip_distribution("AAPL") is None
        assert fetcher.get_chip_distribution("00700") is None


class TestCapitalFlow:
    def test_series_aggregation(self, monkeypatch):
        series = {
            "table": {
                "headName": ["2026-08-21(日)", "2026-08-20(日)", "2026-08-19(日)", "2026-08-18(日)", "2026-08-17(日)"],
                "f1": ["-93.64万", "-100万", "-200万", "300万", "400万"],
            },
            "nameMap": {"f1": "主力净流入资金"},
            "entityName": "盛航股份",
        }
        fetcher = _fetcher_with_response(monkeypatch, _make_response([series]))
        flow = fetcher.get_capital_flow("001205")
        assert flow["status"] == "partial"
        assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(-936400.0)
        assert flow["stock_flow"]["inflow_5d"] == pytest.approx(-936400.0 - 1e6 - 2e6 + 3e6 + 4e6)
        assert "miaoxiang:capital_flow" in flow["source_chain"]

    def test_empty_response_returns_not_supported(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, _make_response([]))
        flow = fetcher.get_capital_flow("001205")
        assert flow["status"] == "not_supported"
        assert flow["stock_flow"] == {}


class TestDailyNotSupported:
    def test_daily_raises_quickly(self):
        fetcher = MiaoxiangFetcher(api_key="test-key")
        from data_provider.base import DataFetchError

        with pytest.raises(DataFetchError):
            fetcher._fetch_raw_data("001205", "2026-01-01", "2026-01-31")
