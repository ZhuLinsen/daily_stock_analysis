from src.services.intraday_picker.models import IntradayCandidate
from src.services.intraday_picker.stock_analysis_rules import (
    bottom_reversal,
    buy_pullback,
    reversal_breakout,
)


def test_reversal_breakout_confirmation():
    candidate = IntradayCandidate(
        stock_code="600000",
        price=12.0,
        change_pct=3.0,
        metadata={"量比": 2.0, "MA20": 11.0, "breakout_score": 80, "60日涨跌幅": 20},
    )
    assert reversal_breakout(candidate).matched


def test_buy_pullback_rejects_chasing():
    candidate = IntradayCandidate(
        stock_code="600000",
        price=12.0,
        change_pct=6.0,
        metadata={"量比": 0.8, "MA10": 11.8, "MA20": 11.0, "60日涨跌幅": 30},
    )
    assert not buy_pullback(candidate).matched


def test_bottom_reversal_confirmation():
    candidate = IntradayCandidate(
        stock_code="600000",
        change_pct=3.0,
        metadata={"量比": 1.6, "60日涨跌幅": -18, "market_cap": 120},
    )
    assert bottom_reversal(candidate).matched
