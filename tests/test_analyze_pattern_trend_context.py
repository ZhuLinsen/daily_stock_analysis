# -*- coding: utf-8 -*-
"""Trend-context tests for the analyze_pattern hammer family (issue #2596).

A hammer and a hanging man are the same candle shape, and so are an
inverted hammer and a shooting star.  What tells them apart is the trend
BEFORE the candle: after a decline the shape is a hammer / inverted
hammer (bottom reversal signals); after an advance it is a hanging man /
shooting star (top reversal signals).  These tests pin that behaviour.
"""

import pandas as pd

from src.agent.tools import analysis_tools
from src.services import history_loader


def _trend(n, start, step):
    """Build n consecutive OHLC rows trending at ``step`` per bar."""
    rows, close = [], start
    for _ in range(n):
        open_ = close
        close = round(open_ * (1 + step), 4)
        rows.append([
            open_,
            round(max(open_, close) * 1.002, 4),
            round(min(open_, close) * 0.998, 4),
            close,
        ])
    return rows


def _sideways(n, start=20.0, amp=0.003):
    """Build n rows oscillating around ``start`` (no clear trend)."""
    rows, close = [], start
    for k in range(n):
        open_ = close
        close = round(start * (1 + amp * (1 if k % 2 == 0 else -1)), 4)
        rows.append([
            open_,
            round(max(open_, close) * 1.002, 4),
            round(min(open_, close) * 0.998, 4),
            close,
        ])
    return rows


def _patterns(rows, monkeypatch):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B").date
    df["volume"] = 1_000_000.0
    monkeypatch.setattr(
        history_loader, "load_history_df",
        lambda stock_code, days=60, target_date=None: (df, "fixture"),
    )
    result = analysis_tools._handle_analyze_pattern("600519")
    assert "error" not in result, result
    return result


def _find(result, needle):
    matches = [p for p in result["patterns"] if needle in p["pattern"]]
    assert matches, f"no pattern matching {needle!r} in {result['patterns']}"
    return matches[0]


def test_long_lower_shadow_after_decline_is_hammer(monkeypatch):
    decline = _trend(20, 20.0, -0.012)
    o = round(decline[-1][3] * 0.985, 4)
    c = round(o * 1.002, 4)
    result = _patterns(decline + [[o, c, round(o - (c - o) * 6, 4), c]], monkeypatch)
    p = _find(result, "锤子线")
    assert p["pattern"] == "锤子线 (Hammer)"
    assert p["type"] == "bullish_reversal"
    assert p["trend_context"] == "down"


def test_long_lower_shadow_after_advance_is_hanging_man(monkeypatch):
    advance = _trend(20, 20.0, 0.012)
    o = round(advance[-1][3] * 1.015, 4)
    c = round(o * 1.002, 4)
    result = _patterns(advance + [[o, c, round(o - (c - o) * 6, 4), c]], monkeypatch)
    p = _find(result, "上吊线")
    assert p["pattern"] == "上吊线 (Hanging Man)"
    assert p["type"] == "bearish_reversal"
    assert p["trend_context"] == "up"


def test_long_upper_shadow_after_decline_is_inverted_hammer(monkeypatch):
    decline = _trend(20, 20.0, -0.012)
    o = round(decline[-1][3] * 0.985, 4)
    c = round(o * 1.002, 4)
    result = _patterns(decline + [[o, round(c + (c - o) * 6, 4), o, c]], monkeypatch)
    p = _find(result, "倒锤子")
    assert p["pattern"] == "倒锤子"
    assert p["type"] == "bullish_reversal"
    assert p["trend_context"] == "down"


def test_long_upper_shadow_after_advance_is_shooting_star(monkeypatch):
    advance = _trend(20, 20.0, 0.012)
    o = round(advance[-1][3] * 1.015, 4)
    c = round(o * 1.002, 4)
    result = _patterns(advance + [[o, round(c + (c - o) * 6, 4), o, c]], monkeypatch)
    p = _find(result, "流星线")
    assert p["pattern"] == "流星线 (Shooting Star)"
    assert p["type"] == "bearish_reversal"
    assert p["trend_context"] == "up"


def test_unclear_trend_degrades_to_neutral_combined_label(monkeypatch):
    flat = _sideways(20)
    o = round(flat[-1][3] * 0.995, 4)
    c = round(o * 1.002, 4)
    result = _patterns(flat + [[o, c, round(o - (c - o) * 6, 4), c]], monkeypatch)
    p = _find(result, "Hammer/Hanging Man")
    assert p["type"] == "neutral"
    assert p["trend_context"] == "neutral"


def test_return_structure_stays_backward_compatible(monkeypatch):
    rows = _trend(20, 20.0, -0.012)
    o = round(rows[-1][3] * 0.985, 4)
    c = round(o * 1.002, 4)
    result = _patterns(rows + [[o, c, round(o - (c - o) * 6, 4), c]], monkeypatch)
    for key in ("code", "source", "period_days", "current_price",
                "patterns_count", "patterns", "summary"):
        assert key in result, f"missing top-level key {key!r}"
    for p in result["patterns"]:
        assert {"pattern", "type", "day_offset", "strength", "desc"} <= set(p)
