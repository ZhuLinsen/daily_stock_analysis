# -*- coding: utf-8 -*-
"""Offline tests for how analyze_pattern names long-shadow candles."""

import pandas as pd
import pytest

from src.agent.tools import analysis_tools
from src.services import history_loader

LONG_SHADOW_NAMES = {"锤子线 (Hammer)", "上吊线 (Hanging Man)", "倒锤子", "流星线 (Shooting Star)"}


def _trend(n, start, step):
    """n ordinary candles moving ``step`` per bar; each opens at the previous close."""
    rows, close = [], start
    for _ in range(n):
        open_ = close
        close = round(open_ * (1 + step), 4)
        rows.append([open_, round(max(open_, close) * 1.002, 4), round(min(open_, close) * 0.998, 4), close])
    return rows


def _patterns(monkeypatch, rows, days=60):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B").date
    df["volume"] = 1_000_000.0
    monkeypatch.setattr(history_loader, "load_history_df", lambda stock_code, days=60, target_date=None: (df, "x"))
    return {p["pattern"]: p for p in analysis_tools._handle_analyze_pattern("600519", days=days)["patterns"]}


def _long_lower_shadow(prev_close, gap):
    """Small white body on top of a lower shadow six times its size."""
    open_ = round(prev_close * (1 + gap), 4)
    close = round(open_ * 1.002, 4)
    return [open_, close, round(open_ - (close - open_) * 6, 4), close]


def _long_upper_shadow(prev_close, gap, white=True):
    """Small body under an upper shadow six times its size."""
    low = round(prev_close * (1 + gap), 4)
    top = round(low * 1.002, 4)
    open_, close = (low, top) if white else (top, low)
    return [open_, round(top + (top - low) * 6, 4), low, close]


def test_long_lower_shadow_after_a_decline_is_a_hammer(monkeypatch):
    # The candle closes below the previous close, which used to make it a Hanging Man.
    rows = _trend(20, 20.0, -0.012)
    found = _patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], -0.015)])
    assert (found["锤子线 (Hammer)"]["type"], found["锤子线 (Hammer)"]["day_offset"]) == ("bullish_reversal", 0)
    assert "上吊线 (Hanging Man)" not in found


def test_long_lower_shadow_after_an_advance_is_a_hanging_man(monkeypatch):
    # The candle closes above the previous close, which used to make it a Hammer.
    rows = _trend(20, 20.0, 0.012)
    found = _patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0.015)])
    assert found["上吊线 (Hanging Man)"]["type"] == "bearish_reversal"
    assert "支撑" not in found["上吊线 (Hanging Man)"]["desc"]  # support is the hammer's reading
    assert "锤子线 (Hammer)" not in found


@pytest.mark.parametrize("white", [True, False])
def test_long_upper_shadow_after_a_decline_is_an_inverted_hammer(monkeypatch, white):
    rows = _trend(20, 20.0, -0.012)
    found = _patterns(monkeypatch, rows + [_long_upper_shadow(rows[-1][3], -0.015, white)])
    assert found["倒锤子"]["type"] == "bullish_reversal"
    assert "流星线 (Shooting Star)" not in found


@pytest.mark.parametrize("white", [True, False])
def test_long_upper_shadow_after_an_advance_is_a_shooting_star(monkeypatch, white):
    rows = _trend(20, 20.0, 0.012)
    found = _patterns(monkeypatch, rows + [_long_upper_shadow(rows[-1][3], 0.015, white)])
    assert found["流星线 (Shooting Star)"]["type"] == "bearish_reversal"
    assert "倒锤子" not in found


def test_the_trend_is_read_before_the_candle_not_through_it(monkeypatch):
    # Ten falling bars, then a long-lower-shadow candle that itself opens far above all of them.
    rows = _trend(12, 20.0, 0.0) + _trend(10, 20.0, -0.012)
    found = _patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0.4)])
    assert "锤子线 (Hammer)" in found and "上吊线 (Hanging Man)" not in found


def test_the_recent_leg_decides_after_a_reversal(monkeypatch):
    # A collapse followed by nine rising bars: the candle follows an advance.
    rows = _trend(10, 30.0, 0.0) + [[30.0, 30.06, 14.97, 15.0]] + _trend(9, 15.0, 0.03)
    assert "上吊线 (Hanging Man)" in _patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0)])

    # Fourteen rising bars followed by six falling ones: the candle follows a decline.
    rows = _trend(14, 20.0, 0.01)
    rows += _trend(6, rows[-1][3], -0.02)
    assert "锤子线 (Hammer)" in _patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0)])


def test_one_bar_against_the_trend_does_not_change_it(monkeypatch):
    rows = _trend(20, 20.0, -0.02)
    rows += _trend(1, rows[-1][3], 0.005)  # one small up day inside the decline
    assert "锤子线 (Hammer)" in _patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0)])


def test_a_turn_too_short_to_be_a_trend_gives_no_name(monkeypatch):
    # Three falling bars after twenty rising ones: MA5 is still above MA10, the last close below MA5.
    rows = _trend(20, 20.0, 0.01)
    rows += _trend(3, rows[-1][3], -0.03)
    assert not LONG_SHADOW_NAMES & set(_patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0)]))


@pytest.mark.parametrize("price", [20.0, 0.1])  # sums of 0.1 are not exact
def test_a_flat_history_gives_no_name(monkeypatch, price):
    rows = _trend(12, price, 0.0)  # every close is the same
    for candle in (_long_lower_shadow(price, 0), _long_upper_shadow(price, 0)):
        assert not LONG_SHADOW_NAMES & set(_patterns(monkeypatch, rows + [candle]))


def test_the_name_does_not_depend_on_how_many_days_are_scanned(monkeypatch):
    # With days=10 only nine closes before the candle are inside the scanned rows.
    rows = _trend(20, 20.0, -0.012)
    rows.append(_long_lower_shadow(rows[-1][3], -0.015))
    for days in (10, 60):
        assert "锤子线 (Hammer)" in _patterns(monkeypatch, rows, days=days)


def test_fewer_than_ten_closes_before_the_candle_give_no_name(monkeypatch):
    rows = _trend(10, 20.0, -0.012)
    candle = _long_lower_shadow(rows[-1][3], -0.015)
    assert "锤子线 (Hammer)" in _patterns(monkeypatch, rows + [candle])
    assert not LONG_SHADOW_NAMES & set(_patterns(monkeypatch, rows[1:] + [candle]))


def test_a_candle_one_bar_back_is_named_by_the_trend_before_it(monkeypatch):
    rows = _trend(20, 20.0, -0.012)
    rows.append(_long_lower_shadow(rows[-1][3], -0.015))
    rows += _trend(1, rows[-1][3], 0.012)
    found = _patterns(monkeypatch, rows)
    assert found["锤子线 (Hammer)"]["day_offset"] == -1
