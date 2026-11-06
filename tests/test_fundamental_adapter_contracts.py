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


@pytest.mark.parametrize("code, market", [("600519", "sh"), ("000001", "sz"), ("bj920001", "bj")])
def test_capital_flow_uses_market_and_latest_amount(monkeypatch, code, market):
    calls = []

    def individual(stock, market):
        calls.append((stock, market))
        return pd.DataFrame({
            "日期": ["2026-09-28", "invalid", "2026-09-30", "2026-09-29"],
            "主力净流入-净占比": [1, 2, 3, 4],
            "主力净流入-净额": [10, 999, -20, 30],
        })

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_individual_fund_flow=individual))
    result = AkshareFundamentalAdapter().get_capital_flow(code)
    assert calls == [(code.removeprefix("bj"), market)]
    assert result["stock_flow"] == {"main_net_inflow": -20, "inflow_5d": None, "inflow_10d": None}


@pytest.mark.parametrize("value", [0, -123, None, float("nan"), float("inf")])
def test_capital_flow_keeps_only_finite_amounts(monkeypatch, value):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_individual_fund_flow=lambda **kwargs: pd.DataFrame({"日期": ["2026-09-30"], "主力净流入-净额": [value]}),
    ))
    result = AkshareFundamentalAdapter().get_capital_flow("000001")
    if value is not None and value in (0, -123):
        assert result["stock_flow"]["main_net_inflow"] == value
    else:
        assert result["stock_flow"] == {}
        assert result["source_chain"] == []


def test_capital_flow_failure_keeps_sector_amounts_without_wrong_fallback(monkeypatch):
    wrong_calls = []

    def individual(stock, market):
        raise ConnectionError("unavailable")

    def wrong(**kwargs):
        wrong_calls.append(kwargs)
        return pd.DataFrame({"名称": ["unrelated"], "主力净流入-净占比": [99]})

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_individual_fund_flow=individual, stock_main_fund_flow=wrong,
        stock_sector_fund_flow_summary=wrong,
        stock_sector_fund_flow_rank=lambda **kwargs: pd.DataFrame({
            "名称": ["行业A", "行业B"], "今日主力净流入-净占比": [99, 1],
            "今日主力净流入-净额": [-100, 200],
        }),
    ))
    result = AkshareFundamentalAdapter().get_capital_flow("000001", top_n=1)
    assert wrong_calls == []
    assert result["stock_flow"] == {}
    assert result["sector_rankings"]["top"] == [{"name": "行业B", "net_inflow": 200}]
    assert result["status"] == "partial"
    assert result["errors"] == ["stock_individual_fund_flow:ConnectionError"]


@pytest.mark.parametrize("amounts", [
    ["-", None, float("nan")],
    [float("inf"), float("-inf"), pd.NA],
])
def test_capital_flow_keeps_stock_amount_when_sector_amounts_are_all_missing(monkeypatch, amounts):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_individual_fund_flow=lambda **kwargs: pd.DataFrame({
            "日期": ["2026-09-30"], "主力净流入-净额": [20],
        }),
        stock_sector_fund_flow_rank=lambda **kwargs: pd.DataFrame({
            "名称": ["行业A", "行业B", "行业C"],
            "今日主力净流入-净额": amounts,
        }),
    ))

    result = AkshareFundamentalAdapter().get_capital_flow("600519")

    assert result["stock_flow"] == {"main_net_inflow": 20, "inflow_5d": None, "inflow_10d": None}
    assert result["sector_rankings"] == {"top": [], "bottom": []}
    assert result["status"] == "partial"
    assert "capital_stock:stock_individual_fund_flow" in result["source_chain"]
    assert result["errors"] == []


def test_capital_flow_sector_rankings_keep_only_finite_amounts(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_sector_fund_flow_rank=lambda: pd.DataFrame({
            "名称": ["无穷流入", "无穷流出", "缺失", "零流入", "净流出"],
            "今日主力净流入-净额": [float("inf"), float("-inf"), "-", 0, -20],
            "今日主力净流入-净占比": [99, 98, 97, 96, 95],
        }),
    ))

    result = AkshareFundamentalAdapter().get_capital_flow("600519")

    zero = {"name": "零流入", "net_inflow": 0}
    negative = {"name": "净流出", "net_inflow": -20}
    assert result["sector_rankings"] == {"top": [zero, negative], "bottom": [negative, zero]}
    assert result["stock_flow"] == {}
    assert result["status"] == "partial"


@pytest.mark.parametrize("dates", [["invalid"], [None]])
def test_capital_flow_without_valid_date_is_unavailable(monkeypatch, dates):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_individual_fund_flow=lambda **kwargs: pd.DataFrame({"日期": dates, "主力净流入-净额": [100]}),
    ))
    result = AkshareFundamentalAdapter().get_capital_flow("000001")
    assert result["stock_flow"] == {}
    assert result["status"] == "not_supported"


def test_capital_flow_real_akshare_request_uses_shenzhen_security(monkeypatch):
    import akshare as ak
    import requests

    calls = []

    def get(url, params, **kwargs):
        calls.append(params["secid"])
        return SimpleNamespace(json=lambda: {"data": {"klines": [
            "2026-09-28,10,0,0,0,0,1,0,0,0,0,12,0,0,0",
            "2026-09-30,-20,0,0,0,0,-2,0,0,0,0,12,0,0,0",
        ]}})

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(ak, "stock_sector_fund_flow_rank", lambda: pd.DataFrame())
    result = AkshareFundamentalAdapter().get_capital_flow("000001")
    assert calls == ["0.000001"]
    assert result["stock_flow"]["main_net_inflow"] == -20


def test_capital_flow_real_akshare_missing_sector_amounts_reach_manager_and_agent(monkeypatch):
    import akshare as ak
    import requests

    from data_provider.base import DataFetcherManager
    from src.agent.tools.data_tools import _handle_get_capital_flow
    from src.analyzer import _capital_flow_bias_with_status

    calls = []

    def get(url, params, **kwargs):
        if "secid" in params:
            calls.append(("stock", params["secid"]))
            data = {"klines": ["2026-09-30,20,0,0,0,0,2,0,0,0,0,12,0,0,0"]}
        else:
            calls.append(("sector", params["fs"]))
            # Eastmoney's sector response, including placeholder numeric fields.
            row = {
                "f2": 100, "f3": 1, "f12": "BK0001",
                "f14": "行业A", "f62": "-", "f66": "-", "f69": "-",
                "f72": "-", "f75": "-", "f78": "-", "f81": "-",
                "f84": "-", "f87": "-", "f124": 0, "f184": "-",
                "f204": "股票A", "f205": "600519", "f206": 1,
            }
            data = {"total": 1, "diff": [row]}
        return SimpleNamespace(json=lambda: {"data": data})

    # Keep both AkShare implementations and the adapter/manager execution real;
    # replace only their HTTP boundary and runtime configuration.
    monkeypatch.setattr(requests, "get", get)
    sector_df = ak.stock_sector_fund_flow_rank()
    assert sector_df["今日主力净流入-净额"].isna().all()
    calls.clear()
    cfg = SimpleNamespace(fundamental_fetch_timeout_seconds=2.0, fundamental_retry_max=1)
    monkeypatch.setattr("src.config.get_config", lambda: cfg)
    manager = DataFetcherManager(fetchers=[])
    monkeypatch.setattr("src.agent.tools.data_tools._get_fetcher_manager", lambda: manager)

    context = manager.get_capital_flow_context("600519")

    assert context["status"] == "ok"
    assert context["coverage"] == {"status": "ok"}
    assert context["data"]["stock_flow"] == {"main_net_inflow": 20, "inflow_5d": None, "inflow_10d": None}
    assert context["data"]["sector_rankings"] == {"top": [], "bottom": []}
    assert context["errors"] == []
    assert {entry["provider"] for entry in context["source_chain"]} == {
        "capital_stock:stock_individual_fund_flow", "capital_sector:stock_sector_fund_flow_rank",
    }
    assert _capital_flow_bias_with_status({"capital_flow": context}) == ("inflow", "ok")

    tool_result = _handle_get_capital_flow("600519")
    assert tool_result["status"] == "ok"
    assert tool_result["main_net_inflow"] == 20
    assert tool_result["errors"] == []
    assert [value for kind, value in calls if kind == "stock"] == ["1.600519", "1.600519"]
    assert any(kind == "sector" for kind, _ in calls)


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


@pytest.mark.parametrize("metrics", [
    ["营业总收入同比增长率", "净利润同比增长率", "营业总收入", "归母净利润",
     "经营活动产生的现金流量净额", "净资产收益率", "销售毛利率"],
    ["营业总收入同比增长(%)", "归属净利润同比增长(%)", "营业总收入(元)", "归属净利润(元)",
     "经营活动产生的现金流量净额(元)", "净资产收益率(%)", "销售毛利率(%)"],
    ["营业总收入同比增长(%)", "归属净利润同比增长(%)", "营业总收入(元)", "归属净利润(元)",
     "经营现金流量净额(元)", "净资产收益率(加权)(%)", "销售毛利率(%)"],
    ["营业总收入增长率", "归属母公司净利润增长率", "营业总收入", "归母净利润",
     "经营现金流量净额", "净资产收益率(ROE)", "毛利率"],
])
def test_financial_abstract_wide_table_uses_latest_period_and_exact_metrics(monkeypatch, metrics):
    table = pd.DataFrame({
        "选项": ["成长能力"] * 7,
        "指标": metrics,
        "20250331": [99] * 7,
        "20260630": [0, -5, 1000, 120, 80, 12, 30],
        "20260331": [88] * 7,
    })
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_financial_abstract=lambda symbol: table))
    result = AkshareFundamentalAdapter().get_fundamental_bundle("600519")
    assert result["growth"] == {"revenue_yoy": 0, "net_profit_yoy": -5, "roe": 12, "gross_margin": 30}
    assert result["earnings"]["financial_report"] == {
        "report_date": "2026-06-30", "revenue": 1000, "net_profit_parent": 120,
        "operating_cash_flow": 80, "roe": 12,
    }
    assert result["status"] == "partial"
    assert result["source_chain"] == ["growth:stock_financial_abstract"]


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "--"])
@pytest.mark.parametrize("metric", ["营业总收入", "营业总收入(元)"])
def test_empty_financial_abstract_is_not_success(monkeypatch, value, metric):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_financial_abstract=lambda symbol: pd.DataFrame({"指标": [metric], "20260630": [value]}),
    ))
    result = AkshareFundamentalAdapter().get_fundamental_bundle("600519")
    assert result["growth"] == {}
    assert result["earnings"] == {}
    assert result["source_chain"] == []
    assert result["status"] == "not_supported"


@pytest.mark.parametrize("metrics", [
    ["营业总收入同比增长率", "归母净利润同比增长率"],
    ["营业总收入同比增长(%)", "归属净利润同比增长(%)"],
])
def test_financial_abstract_growth_does_not_fill_missing_amounts(monkeypatch, metrics):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_financial_abstract=lambda symbol: pd.DataFrame({
            "指标": metrics, "20260630": [20, -10],
        }),
    ))
    result = AkshareFundamentalAdapter().get_fundamental_bundle("600519")
    assert result["growth"]["revenue_yoy"] == 20
    assert result["growth"]["net_profit_yoy"] == -10
    assert result["earnings"] == {}


@pytest.mark.parametrize("metric", ["营业总收入", "营业总收入(元)"])
def test_financial_abstract_does_not_backfill_older_period(monkeypatch, metric):
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_financial_abstract=lambda symbol: pd.DataFrame({
            "指标": [metric], "20260630": [None], "20260331": [1000],
        }),
    ))
    result = AkshareFundamentalAdapter().get_fundamental_bundle("600519")
    assert result["earnings"] == {}
    assert result["status"] == "not_supported"
