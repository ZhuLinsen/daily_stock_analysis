# -*- coding: utf-8 -*-
"""Tests for Tencent direct daily K-line fetcher."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from data_provider.tencent_fetcher import TencentFetcher, _to_tencent_symbol


def test_tencent_symbol_conversion_supports_a_share_markets() -> None:
    assert _to_tencent_symbol("600519") == "sh600519"
    assert _to_tencent_symbol("000001") == "sz000001"
    assert _to_tencent_symbol("920748") == "bj920748"


def test_tencent_fetcher_parses_qfq_daily_response() -> None:
    payload = {
        "data": {
            "sz000001": {
                "qfqday": [
                    ["2026-05-06", "10.00", "10.50", "10.80", "9.90", "12345", "67890"],
                    ["2026-05-07", "10.50", "10.70", "10.90", "10.30", "22345", "77890"],
                ]
            }
        }
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    fetcher = TencentFetcher()
    with patch("data_provider.tencent_fetcher.requests.get", fake_get):
        df = fetcher.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-10")

    assert captured["url"] == "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    assert captured["params"]["param"].startswith("sz000001,day,2026-05-01,2026-05-10,")
    assert captured["params"]["param"].endswith(",qfq")
    assert list(df.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pct_chg",
        "ma5",
        "ma10",
        "ma20",
        "volume_ratio",
    ]
    assert len(df) == 2
    assert float(df.iloc[0]["close"]) == 10.5
    assert float(df.iloc[0]["volume"]) == 1234500.0
    assert float(df.iloc[1]["amount"]) == 77890.0


def test_tencent_fetcher_requests_explicit_historical_date_window() -> None:
    payload = {
        "data": {
            "sz000001": {
                "qfqday": [
                    ["2020-05-04", "8.00", "8.20", "8.40", "7.80", "5000", "20000"],
                ]
            }
        }
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    fetcher = TencentFetcher()
    with patch("data_provider.tencent_fetcher.requests.get", fake_get):
        df = fetcher.get_daily_data("000001", start_date="2020-05-01", end_date="2020-05-31")

    assert captured["url"] == "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    assert ",day,2020-05-01,2020-05-31," in captured["params"]["param"]
    assert captured["params"]["param"].endswith(",qfq")
    assert len(df) == 1
    assert float(df.iloc[0]["close"]) == 8.2
    assert float(df.iloc[0]["volume"]) == 500000.0


def test_tencent_fetcher_preserves_amount_column_when_missing() -> None:
    payload = {
        "data": {
            "sh600519": {
                "qfqday": [
                    ["2026-05-06", "100.00", "101.00", "102.00", "99.00", "1000"],
                ]
            }
        }
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    with patch("data_provider.tencent_fetcher.requests.get", return_value=FakeResponse()):
        df = TencentFetcher().get_daily_data("600519", start_date="2026-05-01", end_date="2026-05-10")

    assert "amount" in df.columns
    assert pd.isna(df.iloc[0]["amount"])
    assert float(df.iloc[0]["volume"]) == 100000.0


def test_tencent_fetcher_returns_empty_frame_for_empty_history() -> None:
    payload = {"data": {"sz000001": {"qfqday": []}}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    with patch("data_provider.tencent_fetcher.requests.get", return_value=FakeResponse()):
        df = TencentFetcher().get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-10")

    assert df.empty


def test_tencent_fetcher_keeps_short_history_when_cap_not_hit() -> None:
    payload = {
        "data": {
            "sz000001": {
                "qfqday": [
                    ["2023-01-03", "10.00", "10.50", "10.80", "9.90", "12345", "67890"],
                    ["2023-01-04", "10.50", "10.70", "10.90", "10.30", "22345", "77890"],
                ]
            }
        }
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    with patch("data_provider.tencent_fetcher.requests.get", fake_get):
        df = TencentFetcher().get_daily_data("000001", start_date="2020-01-01", end_date="2026-05-10")

    assert ",day,2020-01-01,2026-05-10,800,qfq" in captured["params"]["param"]
    assert len(df) == 2
    assert float(df.iloc[0]["close"]) == 10.5


def test_tencent_fetcher_keeps_near_cap_short_history_for_new_listing() -> None:
    rows = [
        [
            day.strftime("%Y-%m-%d"),
            "10.00",
            "10.50",
            "10.80",
            "9.90",
            str(10000 + index),
            str(20000 + index),
        ]
        for index, day in enumerate(pd.date_range("2024-01-03", periods=799, freq="D"))
    ]
    payload = {"data": {"sz000001": {"qfqday": rows}}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    with patch("data_provider.tencent_fetcher.requests.get", fake_get):
        df = TencentFetcher().get_daily_data("000001", start_date="2020-01-01", end_date="2026-05-10")

    assert ",day,2020-01-01,2026-05-10,800,qfq" in captured["params"]["param"]
    assert len(df) == 799
    assert float(df.iloc[0]["close"]) == 10.5


def test_tencent_fetcher_keeps_capped_history_when_start_is_weekend() -> None:
    rows = [
        [
            day.strftime("%Y-%m-%d"),
            "10.00",
            "10.50",
            "10.80",
            "9.90",
            str(10000 + index),
            str(20000 + index),
        ]
        for index, day in enumerate(pd.bdate_range("2024-03-04", periods=800))
    ]
    payload = {"data": {"sz000001": {"qfqday": rows}}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    with patch("data_provider.tencent_fetcher.requests.get", fake_get):
        df = TencentFetcher().get_daily_data("000001", start_date="2024-03-02", end_date="2027-05-10")

    assert ",day,2024-03-02,2027-05-10,800,qfq" in captured["params"]["param"]
    assert len(df) == 800
    assert pd.Timestamp(df.iloc[0]["date"]).strftime("%Y-%m-%d") == "2024-03-04"


def test_tencent_fetcher_rejects_capped_incomplete_history() -> None:
    rows = [
        [
            day.strftime("%Y-%m-%d"),
            "10.00",
            "10.50",
            "10.80",
            "9.90",
            str(10000 + index),
            str(20000 + index),
        ]
        for index, day in enumerate(pd.date_range("2023-01-03", periods=800, freq="D"))
    ]
    payload = {"data": {"sz000001": {"qfqday": rows}}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    with patch("data_provider.tencent_fetcher.requests.get", fake_get):
        df = TencentFetcher().get_daily_data("000001", start_date="2020-01-01", end_date="2026-05-10")

    assert ",day,2020-01-01,2026-05-10,800,qfq" in captured["params"]["param"]
    assert df.empty


def test_tencent_symbol_conversion_supports_hk_market() -> None:
    assert _to_tencent_symbol("hk00700") == "hk00700"
    assert _to_tencent_symbol("HK00700") == "hk00700"
    assert _to_tencent_symbol("1810.HK") == "hk01810"
    # 非法港股代码不产生符号
    assert _to_tencent_symbol("HKABCDE") == ""


def test_tencent_fetcher_parses_hk_daily_response_without_lot_conversion() -> None:
    payload = {
        "data": {
            "hk00700": {
                # 港股仅返回不复权 day 数据；成交量已是股数；
                # 除权日行尾会附加分红事件 dict 而非成交额
                "day": [
                    ["2026-05-06", "500.00", "505.00", "508.00", "498.00", "21334027.000"],
                    [
                        "2026-05-07",
                        "506.00",
                        "509.00",
                        "512.00",
                        "504.00",
                        "22457714.000",
                        {"cqr": "2026-05-07", "FHcontent": "末期息4.5港元;"},
                    ],
                ]
            }
        }
    }

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return payload

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    fetcher = TencentFetcher()
    with patch("data_provider.tencent_fetcher.requests.get", fake_get):
        df = fetcher.get_daily_data("hk00700", start_date="2026-05-01", end_date="2026-05-10")

    assert captured["params"]["param"].startswith("hk00700,day,2026-05-01,2026-05-10,")
    assert len(df) == 2
    # 港股成交量不做手数→股数换算
    assert float(df.iloc[0]["volume"]) == 21334027.0
    assert float(df.iloc[1]["volume"]) == 22457714.0
    # 事件 dict 不得进入 amount 列
    assert pd.isna(df.iloc[1]["amount"])


def test_hk_daily_routing_demotes_tencent_to_last() -> None:
    from data_provider.base import DataFetcherManager

    class _Stub:
        def __init__(self, name: str) -> None:
            self.name = name

    fetchers = [
        _Stub("TencentFetcher"),
        _Stub("AkshareFetcher"),
        _Stub("YfinanceFetcher"),
    ]
    kept = DataFetcherManager._filter_daily_fetchers_for_market(fetchers, "hk")
    assert [f.name for f in kept] == ["AkshareFetcher", "YfinanceFetcher", "TencentFetcher"]

    # A 股不受降级影响，保持原优先级顺序
    kept_cn = DataFetcherManager._filter_daily_fetchers_for_market(
        [_Stub("TencentFetcher"), _Stub("AkshareFetcher")], "cn"
    )
    assert [f.name for f in kept_cn] == ["TencentFetcher", "AkshareFetcher"]


def test_cn_daily_routing_promotes_tencent_akshare_baostock_to_front() -> None:
    from data_provider.base import DataFetcherManager

    class _Stub:
        def __init__(self, name: str) -> None:
            self.name = name

    # 起始顺序模拟原始 priority 排序：Tushare(-1) < Efinance(0) < Tencent(0) <
    # Akshare(1) < Pytdx(2) < Baostock(3) < Yfinance(4)
    fetchers = [
        _Stub("TushareFetcher"),
        _Stub("EfinanceFetcher"),
        _Stub("TencentFetcher"),
        _Stub("AkshareFetcher"),
        _Stub("PytdxFetcher"),
        _Stub("BaostockFetcher"),
        _Stub("YfinanceFetcher"),
    ]
    kept = DataFetcherManager._filter_daily_fetchers_for_market(fetchers, "cn")
    assert [f.name for f in kept] == [
        "TencentFetcher",
        "AkshareFetcher",
        "BaostockFetcher",
        "TushareFetcher",
        "EfinanceFetcher",
        "PytdxFetcher",
        "YfinanceFetcher",
    ]


def test_cn_daily_routing_drops_us_hk_only_sources() -> None:
    from data_provider.base import DataFetcherManager

    class _Stub:
        def __init__(self, name: str) -> None:
            self.name = name

    fetchers = [
        _Stub("EfinanceFetcher"),
        _Stub("LongbridgeFetcher"),
        _Stub("FinnhubFetcher"),
        _Stub("AlphaVantageFetcher"),
    ]
    kept = DataFetcherManager._filter_daily_fetchers_for_market(fetchers, "cn")
    assert [f.name for f in kept] == ["EfinanceFetcher"]


def test_cn_daily_routing_end_to_end_prefers_tencent_over_efinance() -> None:
    """真实 get_daily_data 路由验证：Efinance 可用时，A 股仍优先命中腾讯。"""
    from unittest.mock import patch

    from data_provider.base import BaseFetcher, DataFetcherManager, STANDARD_COLUMNS

    class _SucceedingStub(BaseFetcher):
        allow_empty_daily_data = True

        def __init__(self, name: str, priority: int, close: float) -> None:
            self.name = name
            self.priority = priority
            self._close = close

        def _fetch_raw_data(self, stock_code, start_date, end_date):
            import pandas as pd

            return pd.DataFrame(
                {
                    "date": [end_date],
                    "open": [self._close],
                    "high": [self._close],
                    "low": [self._close],
                    "close": [self._close],
                    "volume": [1000.0],
                    "amount": [1000.0],
                }
            )

        def _normalize_data(self, df, stock_code):
            normalized = df.copy()
            normalized["pct_chg"] = 0.0
            return normalized[STANDARD_COLUMNS]

    efinance_stub = _SucceedingStub("EfinanceFetcher", priority=0, close=100.0)
    tencent_stub = _SucceedingStub("TencentFetcher", priority=0, close=200.0)

    manager = DataFetcherManager(fetchers=[efinance_stub, tencent_stub])
    with patch("data_provider.base.DataFetcherManager._daily_source_health") as mock_health:
        mock_health.is_available.return_value = True
        df, source = manager.get_daily_data("600519", start_date="2026-07-23", end_date="2026-07-23")

    assert source == "TencentFetcher"
    assert float(df.iloc[-1]["close"]) == 200.0
