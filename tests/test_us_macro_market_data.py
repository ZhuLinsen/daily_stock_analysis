import pandas as pd

from src.services.us_macro_market_data import summarize_history


def test_market_summary_calculates_returns_and_moving_averages():
    dates = pd.date_range('2025-01-01', periods=205, freq='B')
    history = pd.DataFrame({'close': range(100, 305)}, index=dates)
    summary = summarize_history('sp500', 'SPX', history)
    assert summary and summary['change_1d'] > 0
    assert summary['above_ma_20'] is True
    assert summary['above_ma_200'] is True


def test_market_summary_returns_none_for_empty_history():
    assert summarize_history('sp500', 'SPX', pd.DataFrame()) is None
