# -*- coding: utf-8 -*-
"""Regression tests for YfinanceFetcher daily data normalization."""

import pandas as pd

from data_provider.yfinance_fetcher import YfinanceFetcher


def test_normalize_daily_data_recovers_unnamed_datetime_index_date_column() -> None:
    fetcher = YfinanceFetcher()
    raw = pd.DataFrame(
        {
            "Open": [10.0, 10.5],
            "High": [11.0, 11.2],
            "Low": [9.8, 10.1],
            "Close": [10.8, 11.0],
            "Volume": [1000, 1200],
        },
        index=pd.DatetimeIndex(["2026-05-25", "2026-05-26"]),
    )

    normalized = fetcher._normalize_data(raw, "DRAM")
    cleaned = fetcher._clean_data(normalized)

    assert "date" in normalized.columns
    assert cleaned["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-05-25", "2026-05-26"]
