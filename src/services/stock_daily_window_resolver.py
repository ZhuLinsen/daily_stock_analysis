# -*- coding: utf-8 -*-
"""Resolve one coherent local daily-bar window across equivalent stock codes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from src.repositories.stock_repo import StockRepository
from src.storage import StockDaily


@dataclass(frozen=True)
class StockDailyWindow:
    """A start bar and its forward bars from one stored stock-code shape."""

    code: str
    start_bar: StockDaily
    forward_bars: List[StockDaily]


def resolve_stock_daily_window(
    *,
    stock_repo: StockRepository,
    code_candidates: Sequence[str],
    expected_start_date: date,
    eval_window_days: int,
) -> Optional[StockDailyWindow]:
    """Choose one coherent window anchored to the expected trading session.

    Only candidates with a bar on the authoritative expected date are eligible.
    Complete windows outrank partial ones; remaining ties prefer more forward
    bars and then candidate order. Start and forward bars are never combined
    across code shapes.
    """
    best_window: Optional[StockDailyWindow] = None
    best_key: Optional[Tuple[bool, int, int]] = None
    if isinstance(eval_window_days, bool) or not isinstance(eval_window_days, int):
        raise ValueError("eval_window_days must be a positive integer")
    required_bars = eval_window_days
    if required_bars <= 0:
        raise ValueError("eval_window_days must be a positive integer")

    for rank, code in enumerate(dict.fromkeys(code_candidates)):
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
        key = (
            len(forward_bars) >= required_bars,
            len(forward_bars),
            -rank,
        )
        if best_key is None or key > best_key:
            best_key = key
            best_window = StockDailyWindow(
                code=code,
                start_bar=start_bar,
                forward_bars=forward_bars,
            )

    return best_window
