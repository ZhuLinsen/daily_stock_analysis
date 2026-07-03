# -*- coding: utf-8 -*-
"""Tests for Brinson backtest attribution algorithm."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Optional

from src.core.backtest_attribution import compute_brinson_attribution
from src.schemas.backtest_attribution import BacktestAttributionResult


@dataclass
class MockResult:
    """Minimal BacktestResult-like object for attribution tests."""

    position_recommendation: Optional[str] = "long"
    operation_advice: Optional[str] = None
    stock_return_pct: Optional[float] = 0.0
    simulated_return_pct: Optional[float] = 0.0
    outcome: Optional[str] = None


class BrinsonMathTestCase(unittest.TestCase):
    """Verify the Brinson-Fachler decomposition math."""

    def test_known_values(self) -> None:
        # 10 stocks: 6 long (avg stock +5%, avg sim +7%), 4 cash (avg stock -2%)
        results = []
        for _ in range(6):
            results.append(MockResult(
                position_recommendation="long",
                stock_return_pct=5.0,
                simulated_return_pct=7.0,
                outcome="win",
            ))
        for _ in range(4):
            results.append(MockResult(
                position_recommendation="cash",
                stock_return_pct=-2.0,
                simulated_return_pct=None,
                outcome="loss",
            ))

        attr = compute_brinson_attribution(results)

        # Benchmark = (6*5 + 4*(-2)) / 10 = (30 - 8) / 10 = 2.2%
        self.assertAlmostEqual(attr.brinson.benchmark_return_pct, 2.2, places=2)
        # Portfolio = (6*7 + 4*0) / 10 = 4.2%
        self.assertAlmostEqual(attr.brinson.portfolio_return_pct, 4.2, places=2)
        # Excess = 4.2 - 2.2 = 2.0%
        self.assertAlmostEqual(attr.brinson.total_excess_return, 2.0, places=2)

        # Selection = (0.6-0.6)*5 + (0-0.4)*(-2) = 0 + 0.8 = 0.8%
        self.assertAlmostEqual(attr.brinson.selection_effect, 0.8, places=2)
        # Timing = 0.6*(7-5) + 0.4*(0-(-2)) = 1.2 + 0.8 = 2.0%
        self.assertAlmostEqual(attr.brinson.timing_effect, 2.0, places=2)
        # Interaction = (0.6-0.6)*(7-5) + (0-0.4)*(0-(-2)) = 0 - 0.8 = -0.8%
        self.assertAlmostEqual(attr.brinson.interaction_effect, -0.8, places=2)
        # Selection + Timing + Interaction ≈ Total excess
        recon = attr.brinson.selection_effect + attr.brinson.timing_effect + attr.brinson.interaction_effect
        self.assertAlmostEqual(recon, attr.brinson.total_excess_return, places=2)

    def test_all_long_no_excess_when_simulated_equals_stock(self) -> None:
        results = [
            MockResult(position_recommendation="long", stock_return_pct=5.0, simulated_return_pct=5.0),
            MockResult(position_recommendation="long", stock_return_pct=3.0, simulated_return_pct=3.0),
        ]
        attr = compute_brinson_attribution(results)
        # When simulated == stock for all, portfolio == benchmark, excess = 0
        self.assertAlmostEqual(attr.brinson.total_excess_return, 0.0, places=4)

    def test_cash_group_provides_selection_benefit(self) -> None:
        """Avoiding losing stocks creates positive selection effect."""
        results = [
            MockResult(position_recommendation="long", stock_return_pct=5.0, simulated_return_pct=5.0),
            MockResult(position_recommendation="cash", stock_return_pct=-10.0, simulated_return_pct=None),
        ]
        attr = compute_brinson_attribution(results)
        # Selection = (0.5-0.5)*5 + (0-0.5)*(-10) = 0 + 5 = 5%
        self.assertAlmostEqual(attr.brinson.selection_effect, 5.0, places=2)
        self.assertGreater(attr.brinson.total_excess_return, 0)


class EdgeCasesTestCase(unittest.TestCase):
    """Test edge cases and graceful degradation."""

    def test_empty_results(self) -> None:
        attr = compute_brinson_attribution([])
        self.assertEqual(attr.total_results, 0)
        self.assertEqual(attr.brinson.total_excess_return, 0.0)
        self.assertEqual(len(attr.strategy_groups), 0)

    def test_single_result(self) -> None:
        attr = compute_brinson_attribution([
            MockResult(stock_return_pct=5.0, simulated_return_pct=6.0),
        ])
        self.assertEqual(attr.total_results, 1)
        # Single result is still processed (>= 2 check is for meaningful attribution,
        # but the algorithm handles it)
        self.assertGreaterEqual(attr.brinson.portfolio_return_pct, 0.0)

    def test_missing_returns_skipped(self) -> None:
        results = [
            MockResult(stock_return_pct=None, simulated_return_pct=None),
            MockResult(stock_return_pct=5.0, simulated_return_pct=6.0),
            MockResult(stock_return_pct=3.0, simulated_return_pct=4.0),
        ]
        attr = compute_brinson_attribution(results)
        self.assertEqual(attr.total_results, 2)

    def test_nan_returns_skipped(self) -> None:
        results = [
            MockResult(stock_return_pct=float("nan"), simulated_return_pct=6.0),
            MockResult(stock_return_pct=5.0, simulated_return_pct=6.0),
        ]
        attr = compute_brinson_attribution(results)
        # The NaN stock_return is replaced by simulated when sim is valid,
        # so both results should be counted
        self.assertEqual(attr.total_results, 2)

    def test_unknown_position_treated_as_cash(self) -> None:
        results = [
            MockResult(position_recommendation=None, stock_return_pct=-5.0, simulated_return_pct=None),
            MockResult(position_recommendation="long", stock_return_pct=5.0, simulated_return_pct=7.0),
        ]
        attr = compute_brinson_attribution(results)
        # Unknown position -> treated as "unknown" -> not "long" -> cash-like
        groups = {g.strategy: g for g in attr.strategy_groups}
        self.assertIn("unknown", groups)
        self.assertEqual(groups["unknown"].portfolio_weight, 0.0)


class StrategyGroupsTestCase(unittest.TestCase):
    """Test the per-strategy attribution summary."""

    def test_groups_sorted_by_contribution(self) -> None:
        results = [
            MockResult(position_recommendation="long", stock_return_pct=1.0, simulated_return_pct=5.0),
            MockResult(position_recommendation="long", stock_return_pct=1.0, simulated_return_pct=5.0),
            MockResult(position_recommendation="cash", stock_return_pct=-3.0, simulated_return_pct=None),
        ]
        attr = compute_brinson_attribution(results)
        self.assertEqual(len(attr.strategy_groups), 2)
        # The group with higher contribution should be first
        contributions = [g.contribution_pct for g in attr.strategy_groups]
        self.assertEqual(contributions, sorted(contributions, reverse=True))

    def test_win_rate_calculated(self) -> None:
        results = [
            MockResult(position_recommendation="long", stock_return_pct=1.0, simulated_return_pct=5.0, outcome="win"),
            MockResult(position_recommendation="long", stock_return_pct=1.0, simulated_return_pct=-2.0, outcome="loss"),
            MockResult(position_recommendation="long", stock_return_pct=1.0, simulated_return_pct=3.0, outcome="win"),
        ]
        attr = compute_brinson_attribution(results)
        long_group = next(g for g in attr.strategy_groups if g.strategy == "long")
        # 2 wins out of 3
        self.assertAlmostEqual(long_group.win_rate, 2 / 3, places=2)

    def test_weights_sum_correctly(self) -> None:
        results = [
            MockResult(position_recommendation="long", stock_return_pct=5.0, simulated_return_pct=6.0),
            MockResult(position_recommendation="long", stock_return_pct=3.0, simulated_return_pct=4.0),
            MockResult(position_recommendation="cash", stock_return_pct=-2.0, simulated_return_pct=None),
            MockResult(position_recommendation="cash", stock_return_pct=-1.0, simulated_return_pct=None),
        ]
        attr = compute_brinson_attribution(results)
        long_group = next(g for g in attr.strategy_groups if g.strategy == "long")
        cash_group = next(g for g in attr.strategy_groups if g.strategy == "cash")
        # Benchmark weights should sum to 1
        self.assertAlmostEqual(long_group.benchmark_weight + cash_group.benchmark_weight, 1.0, places=4)
        # Long group has 0.5 portfolio weight (2 of 4 stocks), cash has 0
        self.assertAlmostEqual(long_group.portfolio_weight, 0.5, places=4)
        self.assertAlmostEqual(cash_group.portfolio_weight, 0.0, places=4)


class SerializationTestCase(unittest.TestCase):
    """Test that the result serializes correctly for API responses."""

    def test_model_dump_roundtrip(self) -> None:
        results = [
            MockResult(position_recommendation="long", stock_return_pct=5.0, simulated_return_pct=7.0),
            MockResult(position_recommendation="cash", stock_return_pct=-2.0, simulated_return_pct=None),
        ]
        attr = compute_brinson_attribution(results)
        data = attr.model_dump()
        restored = BacktestAttributionResult.model_validate(data)
        self.assertEqual(restored.total_results, attr.total_results)
        self.assertEqual(restored.brinson.total_excess_return, attr.brinson.total_excess_return)
        self.assertEqual(len(restored.strategy_groups), len(attr.strategy_groups))


if __name__ == "__main__":
    unittest.main()
