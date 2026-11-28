# -*- coding: utf-8 -*-
"""Resolve one coherent local daily-bar window across equivalent stock codes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence

from src.repositories.stock_repo import StockRepository
from src.storage import StockDaily


@dataclass(frozen=True)
class StockDailyWindow:
    """A start bar and its forward bars from one stored stock-code shape."""

    code: str
    start_bar: StockDaily
    forward_bars: List[StockDaily]


def _has_usable_close(bar: StockDaily) -> bool:
    price = bar.close
    return isinstance(price, (float, int)) and price > 0 and math.isfinite(price)


def resolve_stock_daily_window(
    *,
    stock_repo: StockRepository,
    code_candidates: Sequence[str],
    expected_start_date: date,
    eval_window_days: int,
) -> Optional[StockDailyWindow]:
    """Choose one coherent window anchored to the expected trading session.

    Only candidates with a bar on the authoritative expected date are eligible.
    Prefer the first full window with usable entry and horizon closes.
    Otherwise return the longest available window, breaking ties by candidate
    order. Start and forward bars always come from the same code shape.
    """
    fallback: Optional[StockDailyWindow] = None
    if isinstance(eval_window_days, bool) or not isinstance(eval_window_days, int):
        raise ValueError("eval_window_days must be a positive integer")
    required_bars = eval_window_days
    if required_bars <= 0:
        raise ValueError("eval_window_days must be a positive integer")

    for code in dict.fromkeys(code_candidates):
        if not code:
            continue
        start_bar = stock_repo.get_daily_on_date(
            code=code,
            target_date=expected_start_date,
        )
        if start_bar is None or start_bar.close is None:
            continue

        forward_bars = stock_repo.get_forward_bars(
            code=code,
            analysis_date=start_bar.date,
            eval_window_days=required_bars,
        )
        window = StockDailyWindow(code=code, start_bar=start_bar, forward_bars=forward_bars)
        if (
            len(forward_bars) >= required_bars
            and _has_usable_close(start_bar)
            and _has_usable_close(forward_bars[required_bars - 1])
        ):
            return window
        if fallback is None or len(forward_bars) > len(fallback.forward_bars):
            fallback = window

    return fallback
