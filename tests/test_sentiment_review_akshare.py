from __future__ import annotations

import pandas as pd
import pytest

from data_provider.akshare_fetcher import AkshareFetcher


def test_broken_limit_pool_normalizes_rows(monkeypatch) -> None:
    import akshare as ak
    frame = pd.DataFrame([{
        "代码": "600001", "名称": "示例股份", "涨跌幅": 7.2,
        "成交额": 123000000.0, "首次封板时间": 93001, "炸板次数": 2,
        "所属行业": "电子",
    }])
    monkeypatch.setattr(ak, "stock_zt_pool_zbgc_em", lambda date: frame)
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    assert fetcher.get_broken_limit_pool("20260626") == [{
        "code": "600001", "name": "示例股份", "change_pct": 7.2,
        "amount": 123000000.0, "first_limit_time": "093001",
        "break_count": 2, "industry": "电子", "source": "akshare",
    }]


def test_previous_limit_pool_calculates_auction_and_close_returns(monkeypatch) -> None:
    import akshare as ak
    frame = pd.DataFrame([{
        "代码": "600002", "名称": "昨日涨停", "涨跌幅": 3.32,
        "昨日连板数": 2, "今开": 11.0, "昨收": 10.0,
    }])
    monkeypatch.setattr(ak, "stock_zt_pool_previous_em", lambda date: frame)
    row = AkshareFetcher(sleep_min=0, sleep_max=0).get_previous_limit_up_pool("20260626")[0]
    assert row["auction_return"] == pytest.approx(0.1)
    assert row["close_return"] == pytest.approx(0.0332)
    assert row["previous_consecutive_boards"] == 2


def test_market_stats_uses_spot_snapshot(monkeypatch) -> None:
    import akshare as ak
    frame = pd.DataFrame([
        {"代码": "600001", "涨跌幅": 1.0, "成交额": 100.0},
        {"代码": "600002", "涨跌幅": -2.0, "成交额": 200.0},
        {"代码": "600003", "涨跌幅": 0.0, "成交额": 300.0},
    ])
    monkeypatch.setattr(ak, "stock_zh_a_spot_em", lambda: frame)
    result = AkshareFetcher(sleep_min=0, sleep_max=0).get_sentiment_market_stats("20260626")
    assert result == {"up_count": 1, "down_count": 1, "flat_count": 1, "total_amount": 600.0, "source": "akshare"}
