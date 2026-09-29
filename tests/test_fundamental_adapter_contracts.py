"""Exercise AkShare argument and stock-scope contracts through the real adapter."""

from datetime import datetime
from types import SimpleNamespace
import sys

import pandas as pd
import pytest

from data_provider.fundamental_adapter import (
    AkshareFundamentalAdapter,
    _recent_report_dates,
)


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 1, 1), ["20251231", "20250930"]),
    (datetime(2024, 3, 31), ["20231231", "20230930"]),
    (datetime(2024, 4, 1), ["20240331", "20231231"]),
    (datetime(2026, 9, 27), ["20260630", "20260331"]),
])
def test_recent_report_dates_follow_completed_quarters(now, expected):
    assert _recent_report_dates(now) == expected


def test_bulk_endpoints_filter_target_before_stopping_period_fallback(monkeypatch):
    calls = []

    def forecast(date):
        calls.append(("forecast", date))
        code = "000001" if date == "20260630" else "600519"
        return pd.DataFrame({"股票代码": [code], "业绩变动": ["目标预告"]})

    def quick(date):
        calls.append(("quick", date))
        # A nonempty market table without a code cannot establish stock identity.
        if date == "20260630":
            return pd.DataFrame({"每股收益": [1.2]})
        return pd.DataFrame({"股票代码": ["600519"], "每股收益": [1.2]})

    def institution(symbol):
        calls.append(("institution", symbol))
        code = "000001" if symbol == "20262" else "600519"
        return pd.DataFrame({"证券代码": [code], "机构数变化": [3]})

    def top10(symbol, date):
        calls.append(("top10", symbol, date))
        assert symbol == "sh600519"
        return pd.DataFrame({"股东名称": ["某股东"], "增减": [100]})

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_yjyg_em=forecast, stock_yjkb_em=quick,
        stock_institute_hold=institution, stock_gdfx_top_10_em=top10,
    ))
    monkeypatch.setattr(
        "data_provider.fundamental_adapter._recent_report_dates",
        lambda: ["20260630", "20260331"],
    )
    result = AkshareFundamentalAdapter().get_fundamental_bundle("600519.SH")

    assert result["errors"] == ["stock_yjkb_em:ValueError"]
    assert result["earnings"]["forecast_summary"] == "目标预告"
    assert result["earnings"]["quick_report_summary"] == "每股收益1.2元"
    assert result["institution"] == {
        "institution_holding_change": 3.0, "top10_holder_change": 100.0,
    }
    assert calls == [
        ("forecast", "20260630"), ("forecast", "20260331"),
        ("quick", "20260630"), ("quick", "20260331"),
        ("institution", "20262"), ("institution", "20261"),
        ("top10", "sh600519", "20260630"),
    ]


@pytest.mark.parametrize("code, expected", [
    ("600519", "sh600519"), ("000001.SZ", "sz000001"),
    ("920002", "bj920002"), ("SH688111", "sh688111"),
])
def test_top10_keeps_stock_scope_and_errors_without_unrelated_fallback(
    monkeypatch, code, expected,
):
    calls = []

    def top10(symbol, date):
        calls.append((symbol, date))
        raise KeyError("sdgd")

    def unrelated(**kwargs):
        pytest.fail("A different indicator or a default stock must not be used")

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_gdfx_top_10_em=top10,
        stock_zh_a_gdhs_detail_em=unrelated,
        stock_institute_recommend=unrelated,
        stock_yjbb_em=unrelated,
    ))
    result = AkshareFundamentalAdapter().get_fundamental_bundle(code)
    assert calls == [(expected, date) for date in _recent_report_dates()]
    assert result["institution"] == {}
    assert result["errors"] == ["stock_gdfx_top_10_em:KeyError"] * 2
    assert result["status"] == "not_supported"


def test_installed_akshare_receives_valid_parameters_at_http_boundary(monkeypatch):
    # Keep the real AkShare functions: mocking the adapter or permissive **kwargs
    # stubs would hide signature errors and upstream request construction.
    import akshare as ak
    import requests

    calls = []

    def stop_at_http(url, **kwargs):
        calls.append((url, dict(kwargs.get("params", {}))))
        raise RuntimeError("offline transport boundary")

    monkeypatch.setattr(requests, "get", stop_at_http)
    for name in (
        "stock_financial_abstract", "stock_financial_analysis_indicator",
        "stock_fhps_detail_em", "stock_history_dividend_detail", "stock_dividend_cninfo",
    ):
        monkeypatch.setattr(ak, name, lambda **kwargs: pd.DataFrame(), raising=False)
    monkeypatch.setattr(
        "data_provider.fundamental_adapter._recent_report_dates",
        lambda: ["20260630", "20260331"],
    )
    result = AkshareFundamentalAdapter().get_fundamental_bundle("000001")

    assert len(calls) == 8  # two bounded periods per endpoint, no no-arg calls
    assert not any("TypeError" in error for error in result["errors"])
    period_filters = [params["filter"] for _, params in calls if "filter" in params]
    assert len(period_filters) == 4
    assert all("2026-06-30" in value or "2026-03-31" in value for value in period_filters)
    shareholder_calls = [params for url, params in calls if "PageSDGD" in url]
    assert shareholder_calls == [
        {"code": "SZ000001", "date": "2026-06-30"},
        {"code": "SZ000001", "date": "2026-03-31"},
    ]
    institution_calls = [params for _, params in calls if "reportdate" in params]
    assert [(params["reportdate"], params["quarter"]) for params in institution_calls] == [
        ("2026", "2"), ("2026", "1"),
    ]


def _quick_report_row():
    # Full returned-column contract from AkShare 1.18.97 stock_yjkb_em.
    # Metadata precedes metrics to catch column-order-dependent extraction.
    return {
        "公告日期": datetime(2026, 7, 20).date(), "序号": 1,
        "股票代码": "600519", "股票简称": "贵州茅台", "所处行业": "酿酒行业",
        "每股收益": 1.25, "营业收入-营业收入": 120000000.0,
        "营业收入-去年同期": 100000000.0, "营业收入-同比增长": 20.0,
        "营业收入-季度环比增长": 2.0, "净利润-净利润": -5000000.0,
        "净利润-去年同期": 5000000.0, "净利润-同比增长": -200.0,
        "净利润-季度环比增长": -50.0, "每股净资产": 5.0, "净资产收益率": -3.5,
    }


@pytest.mark.parametrize("reverse_columns", [False, True])
def test_real_quick_report_columns_reach_context_cache_and_agent(monkeypatch, reverse_columns):
    from data_provider.base import DataFetcherManager
    from src.agent.tools.data_tools import _compact_fundamental_context

    row = _quick_report_row()
    if reverse_columns:
        row = dict(reversed(list(row.items())))
    calls = []

    def quick(date):
        calls.append(date)
        other = {**row, "股票代码": "000001", "每股收益": 999.0}
        return pd.DataFrame([other, row])

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_yjkb_em=quick))
    manager = DataFetcherManager(fetchers=[])
    cfg = SimpleNamespace(
        enable_fundamental_pipeline=True, fundamental_cache_ttl_seconds=120,
        fundamental_stage_timeout_seconds=5.0, fundamental_fetch_timeout_seconds=2.0,
        fundamental_retry_max=1,
    )
    monkeypatch.setattr("src.config.get_config", lambda: cfg)
    monkeypatch.setattr(manager, "get_realtime_quote", lambda code: None)
    for method in ("get_capital_flow_context", "get_dragon_tiger_context", "get_board_context"):
        monkeypatch.setattr(manager, method, lambda *args, **kwargs: {
            "status": "not_supported", "data": {}, "source_chain": [], "errors": [],
        })

    # Do not mock the adapter, extraction, manager aggregation, or cache.
    context = manager.get_fundamental_context("600519")
    expected = (
        "营业收入120000000元；营收同比20%；净利润-5000000元；"
        "净利润同比-200%；每股收益1.25元；净资产收益率-3.5%"
    )
    assert context["earnings"]["data"] == {"quick_report_summary": expected}
    assert context["coverage"]["earnings"] == "ok"
    cached = manager.get_fundamental_context("600519")
    assert cached == context
    assert len(calls) == 1
    assert _compact_fundamental_context(cached)["earnings"]["data"] == {
        "quick_report_summary": expected,
    }


@pytest.mark.parametrize("value, expected", [
    (None, None), (float("nan"), None), (float("inf"), None),
    (pd.NA, None), ("-", None), (0, "每股收益0元"),
])
def test_quick_report_metadata_and_missing_metrics_are_not_earnings(monkeypatch, value, expected):
    from data_provider.base import DataFetcherManager

    row = {"股票代码": "600519", "公告日期": datetime(2026, 7, 20).date(), "每股收益": value}
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_yjkb_em=lambda date: pd.DataFrame([row]),
    ))
    result = AkshareFundamentalAdapter().get_fundamental_bundle("600519")
    if expected is None:
        assert result["earnings"] == {}
        assert result["source_chain"] == []
        assert result["status"] == "not_supported"
        assert DataFetcherManager._infer_block_status(result["earnings"], result["status"]) == "not_supported"
    else:
        assert result["earnings"] == {"quick_report_summary": expected}


@pytest.mark.parametrize("text, expected", [
    ("预计净利润增长20%", "预计净利润增长20%"), (None, None), (float("nan"), None),
])
def test_forecast_text_does_not_fall_back_to_announcement_or_numeric_change(monkeypatch, text, expected):
    row = {
        "股票代码": "600519", "公告日期": datetime(2026, 7, 20).date(),
        "业绩变动幅度": 20.0, "业绩变动": text,
    }
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_yjyg_em=lambda date: pd.DataFrame([row]),
    ))
    result = AkshareFundamentalAdapter().get_fundamental_bundle("600519")
    assert result["earnings"] == ({"forecast_summary": expected} if expected else {})
