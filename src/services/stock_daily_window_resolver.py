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
    analysis_date: date,
    eval_window_days: int,
    exact_start_required: bool = False,
) -> Optional[StockDailyWindow]:
    """Choose the newest complete same-code window, with a deterministic fallback.

    Complete windows always outrank partial windows. Within either group, the
    newest start bar wins; ties prefer more forward bars and then candidate order.
    The start and forward bars are never combined across different code shapes.
    """
    best_window: Optional[StockDailyWindow] = None
    best_key: Optional[Tuple[bool, date, int, int]] = None
    required_bars = max(int(eval_window_days), 0)

    for rank, code in enumerate(dict.fromkeys(code_candidates)):
        if not code:
            continue
        if exact_start_required:
            start_bar = stock_repo.get_daily_on_date(
                code=code,
                target_date=analysis_date,
            )
        else:
            start_bar = stock_repo.get_start_daily(
                code=code,
                analysis_date=analysis_date,
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
            start_bar.date,
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
