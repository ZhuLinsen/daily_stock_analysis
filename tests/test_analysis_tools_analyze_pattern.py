# -*- coding: utf-8 -*-
"""Offline tests for how analyze_pattern names long-shadow candles."""

import json

import pandas as pd
import pytest

from src.agent.tools import analysis_tools
from src.config import Config
from src.mcp_server import McpReadOnlySurface, _mcp_tool_result_is_error
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


def _candles(closes):
    """Ordinary candles with the given closes; each opens at the previous close."""
    rows, open_ = [], closes[0]
    for close in closes:
        rows.append([open_, round(max(open_, close) * 1.002, 4), round(min(open_, close) * 0.998, 4), close])
        open_ = close
    return rows


def _serve_history(monkeypatch, rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B").date
    df["volume"] = 1_000_000.0
    monkeypatch.setattr(history_loader, "load_history_df", lambda stock_code, days=60, target_date=None: (df, "x"))


def _patterns(monkeypatch, rows, days=60):
    _serve_history(monkeypatch, rows)
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
    assert found["锤子线 (Hammer)"] == {  # the entry itself is what it always was
        "pattern": "锤子线 (Hammer)", "type": "reversal_signal", "day_offset": 0,
        "strength": "中", "desc": "下影线长，潜在支撑/反转",
    }
    assert "上吊线 (Hanging Man)" not in found


def test_long_lower_shadow_after_an_advance_is_a_hanging_man(monkeypatch):
    # The candle closes above the previous close, which used to make it a Hammer.
    rows = _trend(20, 20.0, 0.012)
    found = _patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0.015)])
    assert found["上吊线 (Hanging Man)"] == {  # same type as before; support was the hammer's reading
        "pattern": "上吊线 (Hanging Man)", "type": "reversal_signal", "day_offset": 0,
        "strength": "中", "desc": "下影线长，上涨后的潜在见顶",
    }
    assert "锤子线 (Hammer)" not in found


@pytest.mark.parametrize("white", [True, False])
def test_long_upper_shadow_after_a_decline_is_an_inverted_hammer(monkeypatch, white):
    rows = _trend(20, 20.0, -0.012)
    found = _patterns(monkeypatch, rows + [_long_upper_shadow(rows[-1][3], -0.015, white)])
    assert found["倒锤子"] == {  # it was bearish_signal, wrong after a decline
        "pattern": "倒锤子", "type": "reversal_signal", "day_offset": 0,
        "strength": "中", "desc": "上影线长，下跌后的潜在反转",
    }
    assert "流星线 (Shooting Star)" not in found


@pytest.mark.parametrize("white", [True, False])
def test_long_upper_shadow_after_an_advance_is_a_shooting_star(monkeypatch, white):
    rows = _trend(20, 20.0, 0.012)
    found = _patterns(monkeypatch, rows + [_long_upper_shadow(rows[-1][3], 0.015, white)])
    assert found["流星线 (Shooting Star)"] == {  # the entry itself is what it always was
        "pattern": "流星线 (Shooting Star)", "type": "bearish_signal", "day_offset": 0,
        "strength": "中", "desc": "上影线长，潜在压力/反转",
    }
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


@pytest.mark.parametrize("step", [0.01, -0.01])
def test_a_turn_too_short_to_be_a_trend_gives_no_name(monkeypatch, step):
    # Twenty bars one way, then one bar twice the size the other way: MA5 is still on its old side of
    # MA10, and the last close is between the two.
    rows = _trend(20, 20.0, step)
    rows += _trend(1, rows[-1][3], -2 * step)
    assert not LONG_SHADOW_NAMES & set(_patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], 0)]))


def test_a_flat_history_gives_no_name(monkeypatch):
    rows = _trend(12, 20.0, 0.0)  # every close is the same
    for candle in (_long_lower_shadow(20.0, 0), _long_upper_shadow(20.0, 0)):
        assert not LONG_SHADOW_NAMES & set(_patterns(monkeypatch, rows + [candle]))


# Ten closes that tie as quoted: in the first three the last close equals MA5, in the other two MA5
# equals MA10. Summed as floats they can miss the tie by about 1e-15. The first row is the series from
# the review of #2597.
@pytest.mark.parametrize("closes", [
    [10.25, 10.25, 10.25, 10.25, 10.25, 9.85, 9.87, 9.97, 10.07, 9.94],
    [9.9, 10.35, 10.13, 9.8, 9.74, 10.17, 9.81, 9.9, 9.8, 9.92],
    [9.62, 9.87, 9.64, 10.23, 10.27, 10.38, 10.16, 10.03, 9.95, 10.13],
    [9.97, 9.8, 9.92, 10.35, 10.2, 10.11, 9.99, 10.4, 9.79, 9.95],
    [9.97, 10.21, 10.04, 9.97, 9.8, 9.92, 10.36, 9.7, 9.77, 10.24],
])
def test_a_tie_in_quoted_prices_gives_no_name(monkeypatch, closes):
    rows = _candles(closes)
    for candle in (_long_lower_shadow(closes[-1], 0), _long_upper_shadow(closes[-1], 0)):
        assert not LONG_SHADOW_NAMES & set(_patterns(monkeypatch, rows + [candle]))


@pytest.mark.parametrize("base, tick", [(1700.0, 0.01), (30000.0, 0.01), (0.5, 0.0001)])
def test_a_one_tick_difference_is_a_direction(monkeypatch, base, tick):
    # MA5 is a tenth of a tick above MA10 and four tenths of a tick below the last close.
    closes = [round(base + k * tick, 4) for k in (0, 1, 2, 3, 1, 0, 1, 2, 3, 2)]
    found = _patterns(monkeypatch, _candles(closes) + [_long_lower_shadow(closes[-1], 0)])
    assert "上吊线 (Hanging Man)" in found


def test_a_missing_close_among_the_ten_before_the_candle_gives_no_name(monkeypatch):
    rows = _trend(20, 20.0, -0.012)
    rows[-4][3] = float("nan")
    assert not LONG_SHADOW_NAMES & set(_patterns(monkeypatch, rows + [_long_lower_shadow(rows[-1][3], -0.015)]))


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


@pytest.mark.parametrize("candle, name", [(_long_lower_shadow, "锤子线 (Hammer)"), (_long_upper_shadow, "倒锤子")])
def test_a_candle_one_bar_back_is_named_by_the_trend_before_it(monkeypatch, candle, name):
    rows = _trend(20, 20.0, -0.012)
    rows.append(candle(rows[-1][3], -0.015))
    rows += _trend(1, rows[-1][3], 0.012)
    found = _patterns(monkeypatch, rows)
    assert found[name]["day_offset"] == -1


# The handler tests above already pin these types. This one pins them where the read-only MCP server
# hands them over: allowlist, stock scope, redaction and serialisation all sit in between.
@pytest.mark.parametrize("step, candle, name, type_", [
    (-0.012, _long_lower_shadow, "锤子线 (Hammer)", "reversal_signal"),
    (0.012, _long_lower_shadow, "上吊线 (Hanging Man)", "reversal_signal"),
    (-0.012, _long_upper_shadow, "倒锤子", "reversal_signal"),
    (0.012, _long_upper_shadow, "流星线 (Shooting Star)", "bearish_signal"),
], ids=["hammer", "hanging_man", "inverted_hammer", "shooting_star"])
def test_the_read_only_mcp_surface_returns_each_long_shadow_type(monkeypatch, step, candle, name, type_):
    rows = _trend(20, 20.0, step)
    _serve_history(monkeypatch, rows + [candle(rows[-1][3], 1.25 * step)])
    response = McpReadOnlySurface(config=Config(stock_list=["600519"])).call_tool(
        "analyze_pattern", {"stock_code": "600519"}
    )
    assert response["ok"] is True and not _mcp_tool_result_is_error(response)
    for result in (response["result"], json.loads(response["result_text"])):  # the client gets both
        named = [(p["pattern"], p["type"]) for p in result["patterns"] if p["pattern"] in LONG_SHADOW_NAMES]
        assert named == [(name, type_)]
