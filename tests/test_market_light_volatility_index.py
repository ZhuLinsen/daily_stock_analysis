# -*- coding: utf-8 -*-
"""Volatility gauges must not enter the directional index reading.

Regression: a US session with 标普/纳指/道指 all down and VIX up +8% was scored
"偏暖" because VIX was averaged into 主要指数平均涨跌幅 and then into
``index_score = 50 + avg * 12``.
"""

from __future__ import annotations

import unittest

from src.market_analyzer import (
    MarketIndex,
    MarketOverview,
    _directional_index_changes,
    _is_volatility_index,
)


def _us_selloff_overview() -> MarketOverview:
    """Three benchmarks down, VIX sharply up — a risk-off session."""
    return MarketOverview(
        date="2026-08-21",
        indices=[
            MarketIndex(code="SPX", name="标普500指数", change_pct=-0.69),
            MarketIndex(code="IXIC", name="纳斯达克综合指数", change_pct=-0.94),
            MarketIndex(code="DJI", name="道琼斯工业指数", change_pct=-1.17),
            MarketIndex(code="VIX", name="VIX恐慌指数", change_pct=8.08),
        ],
    )


class DirectionalIndexChangesTestCase(unittest.TestCase):
    def test_recognises_volatility_gauges(self) -> None:
        self.assertTrue(_is_volatility_index(MarketIndex(code="VIX", name="VIX恐慌指数")))
        self.assertTrue(_is_volatility_index(MarketIndex(code="^vix", name="VIX")))
        self.assertFalse(_is_volatility_index(MarketIndex(code="SPX", name="标普500指数")))

    def test_excludes_volatility_gauge_from_average(self) -> None:
        changes = _directional_index_changes(_us_selloff_overview().indices)

        self.assertEqual(changes, [-0.69, -0.94, -1.17])
        avg = sum(changes) / len(changes)
        self.assertLess(avg, 0, "普跌交易日的平均涨跌幅必须为负")

    def test_average_would_flip_sign_without_the_filter(self) -> None:
        indices = _us_selloff_overview().indices
        naive = [idx.change_pct for idx in indices if idx.change_pct is not None]

        self.assertGreater(sum(naive) / len(naive), 0, "旧口径把普跌日算成上涨，正是该修复要防的回归")
        filtered = _directional_index_changes(indices)
        self.assertLess(sum(filtered) / len(filtered), 0)

    def test_missing_change_pct_is_still_skipped(self) -> None:
        indices = [
            MarketIndex(code="SPX", name="标普500指数", change_pct=-0.69),
            MarketIndex(code="DJI", name="道琼斯工业指数", change_pct=None),
        ]
        self.assertEqual(_directional_index_changes(indices), [-0.69])

    def test_empty_and_volatility_only_inputs_are_safe(self) -> None:
        self.assertEqual(_directional_index_changes([]), [])
        self.assertEqual(_directional_index_changes(None), [])
        self.assertEqual(
            _directional_index_changes([MarketIndex(code="VIX", name="VIX恐慌指数", change_pct=8.0)]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
