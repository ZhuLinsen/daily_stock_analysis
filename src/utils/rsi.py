# -*- coding: utf-8 -*-
"""Shared Wilder RSI used by screening, alerts and the stock analysis report.

One implementation so the three entry points always classify the same bars the
same way. Wilder smoothing is seeded with the simple mean of the first
``period`` changes, as in TA-Lib and common charting tools (computed by
``fin-primitives``).
"""

from __future__ import annotations

import fin_primitives as fp
import pandas as pd

NEUTRAL_RSI = 50.0


def wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder RSI aligned to ``close``.

    Bars before the first full ``period`` of changes, and bars where the price
    has not moved at all yet, are ``50.0`` (neutral), matching the previous
    ``fillna(50)`` behaviour.
    """
    close = pd.Series(close, dtype="float64")
    values = pd.Series(fp.rsi(close, period), dtype="float64")
    values.index = close.index
    no_move_yet = close.diff().abs().fillna(0).cumsum().eq(0)
    return values.mask(no_move_yet).fillna(NEUTRAL_RSI)
