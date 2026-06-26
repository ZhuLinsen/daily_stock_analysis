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
