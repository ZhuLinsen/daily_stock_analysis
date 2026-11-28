# -*- coding: utf-8 -*-
"""Regression tests for Issue #2608: yfinance daily bar bounds and intraday guards."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.yfinance_fetcher import YfinanceFetcher
from src.core.pipeline import StockAnalysisPipeline
from src.services.alert_indicators import evaluate_indicator_alert, normalize_indicator_parameters
from src.storage import DatabaseManager, StockDaily


def _make_yf_hk_frame(dates: list[str], closes: list[float], tz: str | None = None) -> pd.DataFrame:
    index = pd.DatetimeIndex(dates, name="Date")
    if tz is not None:
        index = index.tz_localize(tz)
    df = pd.DataFrame(
        {
            "Open": [c - 0.1 for c in closes],
            "High": [c + 0.1 for c in closes],
            "Low": [c - 0.2 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 for _ in closes],
        },
        index=index,
    )
    df.columns = pd.MultiIndex.from_product([df.columns, ["2142.HK"]])
    return df


def test_yfinance_passes_exclusive_end_plus_one_and_retains_requested_hk_bar() -> None:
    """Issue #2608: yf.download excludes *end*, so fetching through end_date requires end+1."""
    captured: dict = {}

    def fake_download(*, tickers, start, end, progress, auto_adjust, multi_level_index):
        captured["tickers"] = tickers
        captured["start"] = start
        captured["end"] = end
        assert end == "2026-11-24"
        return _make_yf_hk_frame(
            ["2026-11-20", "2026-11-23", "2026-11-24"],
            [8.40, 8.85, 8.99],
            tz="Asia/Hong_Kong",
        )

    fetcher = YfinanceFetcher()
    with patch("yfinance.download", side_effect=fake_download):
        df = fetcher.get_daily_data(
            "HK02142",
            start_date="2026-11-01",
            end_date="2026-11-23",
        )

    assert captured == {
        "tickers": "2142.HK",
        "start": "2026-11-01",
        "end": "2026-11-24",
    }
    assert df["date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-11-20", "2026-11-23"]
    assert df["close"].tolist() == [8.40, 8.85]


def test_pipeline_excludes_intraday_bar_before_close_and_refetches_after_close(tmp_path) -> None:
    """OR-COR-fa6866d7: pre-close intraday bars must not poison post-close resume cache."""
    db_url = f"sqlite:///{tmp_path / 'hk_delay_intraday_guard.db'}"
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=db_url)
    try:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.db = db
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_stock_name.return_value = "Toyota"

        def _daily_row(day: str, close: float) -> dict:
            return {
                "date": day,
                "open": close - 5.0,
                "high": close + 5.0,
                "low": close - 10.0,
                "close": close,
                "volume": 1000,
                "amount": close * 1000.0,
                "pct_chg": 1.0,
                "ma5": close,
                "ma10": close,
                "ma20": close,
                "volume_ratio": 1.0,
            }

        intraday_frame = pd.DataFrame([
            _daily_row("2026-11-24", 2800.0),
            _daily_row("2026-11-25", 2950.0),
        ])
        closed_frame = pd.DataFrame([
            _daily_row("2026-11-24", 2800.0),
            _daily_row("2026-11-25", 2910.0),
        ])
        pipeline.fetcher_manager.get_daily_data.side_effect = [
            (intraday_frame, "YfinanceFetcher"),
            (closed_frame, "YfinanceFetcher"),
        ]

        pre_close_jst = datetime(2026, 11, 25, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        ok_pre, err_pre = pipeline.fetch_and_save_stock_data("7203.T", current_time=pre_close_jst)
        assert (ok_pre, err_pre) == (True, None)
        pipeline.fetcher_manager.get_daily_data.assert_called_once_with(
            "7203.T", end_date="2026-11-24", days=30
        )
        assert db.has_today_data("7203.T", date(2026, 11, 24)) is True
        assert db.has_today_data("7203.T", date(2026, 11, 25)) is False

        post_close_jst = datetime(2026, 11, 25, 16, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        ok_post, err_post = pipeline.fetch_and_save_stock_data("7203.T", current_time=post_close_jst)
        assert (ok_post, err_post) == (True, None)
        assert pipeline.fetcher_manager.get_daily_data.call_count == 2
        assert db.has_today_data("7203.T", date(2026, 11, 25)) is True

        with db.get_session() as session:
            row = (
                session.query(StockDaily)
                .filter(StockDaily.code == "7203.T", StockDaily.date == date(2026, 11, 25))
                .one()
            )
            assert row.close == 2910.0

        later_post_close = datetime(2026, 11, 25, 17, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        ok_resume, err_resume = pipeline.fetch_and_save_stock_data("7203.T", current_time=later_post_close)
        assert (ok_resume, err_resume) == (True, None)
        assert pipeline.fetcher_manager.get_daily_data.call_count == 2
    finally:
        DatabaseManager.reset_instance()


def test_alert_indicators_uses_market_timezone_cutoff_for_us_stock_on_utc_server() -> None:
    """OR-COR-d25f0048: US intraday bar at 17:00 UTC (12:00 NY) must be dropped."""
    params = normalize_indicator_parameters("ma_price_cross", {"window": 2, "direction": "above"})
    dates = [
        date(2026, 11, 20),
        date(2026, 11, 23),
        date(2026, 11, 24),
        date(2026, 11, 25),
    ]
    df_intraday = pd.DataFrame({"date": dates, "close": [100.0, 100.0, 90.0, 110.0]})
    utc_intraday = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)

    res_intraday = evaluate_indicator_alert("ma_price_cross", "AAPL", params, df_intraday, now=utc_intraday)
    assert res_intraday.status == "not_triggered"
    assert res_intraday.data_timestamp == datetime(2026, 11, 24, 0, 0)

    utc_post_close = datetime(2026, 11, 25, 21, 30, tzinfo=timezone.utc)
    df_closed_low = pd.DataFrame({"date": dates, "close": [100.0, 100.0, 90.0, 85.0]})
    res_closed_low = evaluate_indicator_alert("ma_price_cross", "AAPL", params, df_closed_low, now=utc_post_close)
    assert res_closed_low.status == "not_triggered"
    assert res_closed_low.data_timestamp == datetime(2026, 11, 25, 0, 0)

    res_closed_high = evaluate_indicator_alert("ma_price_cross", "AAPL", params, df_intraday, now=utc_post_close)
    assert res_closed_high.status == "triggered"
    assert res_closed_high.data_timestamp == datetime(2026, 11, 25, 0, 0)
