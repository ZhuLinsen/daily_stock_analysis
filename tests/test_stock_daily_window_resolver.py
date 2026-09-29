# -*- coding: utf-8 -*-
"""Direct contract tests for coherent local daily-window resolution."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.services.stock_daily_window_resolver import resolve_stock_daily_window


def _bar(day: date, close: float = 100.0):
    return SimpleNamespace(date=day, close=close)


class _FakeStockRepository:
    def __init__(self, starts, forwards):
        self.starts = starts
        self.forwards = forwards
        self.selected_start_dates = {}

    def get_daily_on_date(self, *, code, target_date):
        configured = self.starts.get(code)
        if configured is None:
            return None
        options = configured if isinstance(configured, list) else [configured]
        matching = [start for start in options if start.date == target_date]
        if not matching:
            return None
        start = matching[0]
        self.selected_start_dates[code] = start.date
        return start

    def get_forward_bars(self, *, code, analysis_date, eval_window_days):
        assert self.selected_start_dates[code] == analysis_date
        return list(self.forwards.get(code, ()))[:eval_window_days]


def _resolve(
    starts,
    forwards,
    candidates=("first", "second"),
    days=1,
    expected_start_date=date(2024, 1, 5),
):
    return resolve_stock_daily_window(
        stock_repo=_FakeStockRepository(starts, forwards),
        code_candidates=candidates,
        expected_start_date=expected_start_date,
        eval_window_days=days,
    )


def test_candidates_without_exact_start_return_none() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2020, 1, 2), 50.0),
            "second": _bar(date(2021, 1, 4), 60.0),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8), 55.0)],
            "second": [_bar(date(2024, 1, 8), 65.0)],
        },
    )

    assert window is None


def test_same_date_complete_window_outranks_partial_window() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2024, 1, 5)),
            "second": _bar(date(2024, 1, 5)),
        },
        forwards={
            "first": [],
            "second": [_bar(date(2024, 1, 8))],
        },
    )

    assert window.code == "second"


def test_same_date_tie_preserves_candidate_order() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2024, 1, 5)),
            "second": _bar(date(2024, 1, 5)),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8))],
            "second": [_bar(date(2024, 1, 8))],
        },
    )

    assert window.code == "first"


def test_partial_fallback_uses_more_bars_for_same_start_date() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2024, 1, 5)),
            "second": _bar(date(2024, 1, 5)),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8))],
            "second": [
                _bar(date(2024, 1, 8)),
                _bar(date(2024, 1, 9)),
            ],
        },
        days=3,
    )

    assert window.code == "second"
    assert len(window.forward_bars) == 2


@pytest.mark.parametrize("days", [0, -1, 1.5, True, "1", "invalid"])
def test_invalid_window_length_fails_closed(days) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _resolve(
            starts={"first": _bar(date(2024, 1, 5))},
            forwards={"first": []},
            candidates=("first",),
            days=days,
        )


# ---------------------------------------------------------------------------
# Story 1.2 — read-path compatibility after the canonical_id migration.
# ---------------------------------------------------------------------------
# These tests verify AC 4: existing code-based read paths (StockRepository)
# still return rows once the canonical_id column + plain index exist. They use
# a real SQLite temp DB so the self-healing migration runs end-to-end.


@pytest.fixture()
def _real_db(tmp_path):
    """Yield a DatabaseManager backed by a fresh SQLite temp file."""
    import os

    from src.config import Config
    from src.storage import DatabaseManager

    DatabaseManager.reset_instance()
    Config.reset_instance()
    db_path = os.path.join(str(tmp_path), "canonical_id_readpath.db")
    db = DatabaseManager(db_url=f"sqlite:///{db_path}")
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()


def test_read_path_still_returns_rows_by_code_after_canonical_id_migration(_real_db) -> None:
    """AC 4: ``get_daily_on_date(code=...)`` keeps working via the ``code`` column."""
    import pandas as pd
    from datetime import date

    from src.repositories.stock_repo import StockRepository

    df = pd.DataFrame(
        [
            {
                "date": date(2024, 1, 5),
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
                "volume": 100, "amount": 1050, "pct_chg": 1.2,
                "ma5": 10.1, "ma10": 10.2, "ma20": 10.3, "volume_ratio": 1.0,
            },
            {
                "date": date(2024, 1, 8),
                "open": 10.5, "high": 10.8, "low": 10.2, "close": 10.6,
                "volume": 110, "amount": 1166, "pct_chg": 0.95,
                "ma5": 10.2, "ma10": 10.3, "ma20": 10.3, "volume_ratio": 1.1,
            },
        ]
    )
    # Dual-write path populates canonical_id; read path must NOT depend on it.
    _real_db.save_daily_data(df, code="600519", data_source="test", canonical_id="sh600519")

    repo = StockRepository(db_manager=_real_db)
    start_bar = repo.get_daily_on_date(code="600519", target_date=date(2024, 1, 5))
    forward_bars = repo.get_forward_bars(
        code="600519", analysis_date=date(2024, 1, 5), eval_window_days=1
    )

    assert start_bar is not None
    assert start_bar.code == "600519"
    assert start_bar.close == 10.5
    assert len(forward_bars) == 1
    assert forward_bars[0].code == "600519"
    assert forward_bars[0].date == date(2024, 1, 8)


def test_resolve_window_works_against_real_repo_after_canonical_id_column(_real_db) -> None:
    """End-to-end: ``resolve_stock_daily_window`` still resolves via ``code``."""
    import pandas as pd
    from datetime import date

    from src.repositories.stock_repo import StockRepository

    df_start = pd.DataFrame(
        [
            {
                "date": date(2024, 1, 5),
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
                "volume": 100, "amount": 1050, "pct_chg": 1.2,
                "ma5": 10.1, "ma10": 10.2, "ma20": 10.3, "volume_ratio": 1.0,
            }
        ]
    )
    df_forward = pd.DataFrame(
        [
            {
                "date": date(2024, 1, 8),
                "open": 10.5, "high": 10.8, "low": 10.2, "close": 10.6,
                "volume": 110, "amount": 1166, "pct_chg": 0.95,
                "ma5": 10.2, "ma10": 10.3, "ma20": 10.3, "volume_ratio": 1.1,
            }
        ]
    )
    _real_db.save_daily_data(df_start, code="600519", data_source="test")
    _real_db.save_daily_data(df_forward, code="600519", data_source="test")

    repo = StockRepository(db_manager=_real_db)
    window = resolve_stock_daily_window(
        stock_repo=repo,
        code_candidates=("600519",),
        expected_start_date=date(2024, 1, 5),
        eval_window_days=1,
    )

    assert window is not None
    assert window.code == "600519"
    assert len(window.forward_bars) == 1
