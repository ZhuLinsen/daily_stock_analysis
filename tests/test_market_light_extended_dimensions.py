# -*- coding: utf-8 -*-
"""Tests for extended Market Light dimensions (margin_balance, northbound_flow,
turnover_quantile, limit_ratio, continuous_board).

These tests verify the scoring logic and backward compatibility without
requiring network access to akshare.
"""

from __future__ import annotations

import unittest

from src.config import get_config
from src.core.market_profile import get_profile
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview
from src.schemas.market_light import MarketLightSnapshot


def _make_overview(**kwargs) -> MarketOverview:
    """Build a MarketOverview with sensible defaults for dimension tests."""
    defaults = {
        "date": "2026-07-03",
        "indices": [MarketIndex(code="000001", name="上证指数", current=3200, change_pct=0.5)],
        "up_count": 2500,
        "down_count": 2500,
        "limit_up_count": 40,
        "limit_down_count": 10,
        "total_amount": 12000.0,
    }
    defaults.update(kwargs)
    return MarketOverview(**defaults)


class ExtendedDimensionsTestCase(unittest.TestCase):
    """Test the five extended Market Light dimension scoring methods."""

    def setUp(self) -> None:
        # MarketAnalyzer only needs region/profile/config for these scoring
        # methods; the data_manager and analyzer deps are not invoked in
        # _build_market_light_scores.
        self.analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        self.analyzer.region = "cn"
        self.analyzer.profile = get_profile("cn")
        self.analyzer.config = get_config()

    def test_margin_balance_available_when_two_values(self) -> None:
        overview = _make_overview(
            extended_inputs={"margin_balance_recent": [15000.0, 15300.0]}
        )
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["margin_balance"]
        self.assertTrue(dim["available"])
        # +2% change -> 50 + 0.02*800 = 66
        self.assertEqual(dim["score"], 66)

    def test_margin_balance_unavailable_when_single_value(self) -> None:
        overview = _make_overview(
            extended_inputs={"margin_balance_recent": [15000.0]}
        )
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["margin_balance"]
        self.assertFalse(dim["available"])
        self.assertEqual(dim["score"], 50)

    def test_margin_balance_negative_change_scores_below_50(self) -> None:
        overview = _make_overview(
            extended_inputs={"margin_balance_recent": [15300.0, 15000.0]}
        )
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["margin_balance"]
        self.assertTrue(dim["available"])
        self.assertLess(dim["score"], 50)

    def test_northbound_flow_cumulative_positive(self) -> None:
        overview = _make_overview(
            extended_inputs={"northbound_flow_recent": [10.0, 20.0, 30.0]}
        )
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["northbound_flow"]
        self.assertTrue(dim["available"])
        # cumulative = 60 -> 50 + 60*0.4 = 74
        self.assertEqual(dim["score"], 74)

    def test_northbound_flow_empty_returns_unavailable(self) -> None:
        overview = _make_overview(extended_inputs={})
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["northbound_flow"]
        self.assertFalse(dim["available"])

    def test_turnover_quantile_percentile(self) -> None:
        history = [float(i) for i in range(30, 90)]  # 60 values: 30..89
        overview = _make_overview(
            total_amount=59.0,
            extended_inputs={"turnover_history": history},
        )
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["turnover_quantile"]
        self.assertTrue(dim["available"])
        # values <= 59.0 are 30..59 = 30 out of 60 -> percentile 0.5 -> score 50
        self.assertEqual(dim["score"], 50)

    def test_turnover_quantile_high_percentile(self) -> None:
        history = [float(i) for i in range(30, 90)]
        overview = _make_overview(
            total_amount=88.0,
            extended_inputs={"turnover_history": history},
        )
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["turnover_quantile"]
        self.assertTrue(dim["available"])
        self.assertGreater(dim["score"], 90)

    def test_turnover_quantile_insufficient_history(self) -> None:
        overview = _make_overview(
            total_amount=100.0,
            extended_inputs={"turnover_history": [10.0, 20.0, 30.0]},
        )
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["turnover_quantile"]
        self.assertFalse(dim["available"])

    def test_limit_ratio_available(self) -> None:
        overview = _make_overview(limit_up_count=60, limit_down_count=40)
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["limit_ratio"]
        self.assertTrue(dim["available"])
        self.assertEqual(dim["score"], 60)

    def test_limit_ratio_no_limits_unavailable(self) -> None:
        overview = _make_overview(limit_up_count=0, limit_down_count=0)
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["limit_ratio"]
        self.assertFalse(dim["available"])

    def test_continuous_board_height_mapping(self) -> None:
        for height, expected in [(1, 30), (2, 45), (3, 58), (4, 68), (5, 76), (6, 82), (7, 86), (10, 90)]:
            with self.subTest(height=height):
                overview = _make_overview(
                    extended_inputs={"continuous_board_height": height}
                )
                scores = self.analyzer._build_market_light_scores(overview)
                dim = scores["dimensions"]["continuous_board"]
                self.assertTrue(dim["available"])
                self.assertEqual(dim["score"], expected)

    def test_continuous_board_none_unavailable(self) -> None:
        overview = _make_overview(extended_inputs={})
        scores = self.analyzer._build_market_light_scores(overview)
        dim = scores["dimensions"]["continuous_board"]
        self.assertFalse(dim["available"])

    def test_extended_dimensions_do_not_affect_core_score(self) -> None:
        """The overall score must stay based on the 3 core dimensions."""
        overview_core_only = _make_overview(extended_inputs={})
        overview_full = _make_overview(
            extended_inputs={
                "margin_balance_recent": [15000.0, 15300.0],
                "northbound_flow_recent": [10.0, 20.0, 30.0],
                "turnover_history": [float(i) for i in range(30, 90)],
                "continuous_board_height": 5,
            }
        )
        scores_core = self.analyzer._build_market_light_scores(overview_core_only)
        scores_full = self.analyzer._build_market_light_scores(overview_full)
        self.assertEqual(scores_core["score"], scores_full["score"])
        self.assertEqual(scores_core["temperature_label"], scores_full["temperature_label"])

    def test_all_extended_unavailable_when_no_inputs(self) -> None:
        overview = _make_overview(extended_inputs={})
        scores = self.analyzer._build_market_light_scores(overview)
        for key in ("margin_balance", "northbound_flow", "turnover_quantile", "limit_ratio", "continuous_board"):
            # limit_ratio is derived from overview, not extended_inputs
            dim = scores["dimensions"][key]
            self.assertIn("available", dim)
            self.assertIn("score", dim)
            self.assertIsInstance(dim["score"], int)
            self.assertTrue(0 <= dim["score"] <= 100)


class BackwardCompatTestCase(unittest.TestCase):
    """Old snapshots persisted with only 3 dimensions must still validate."""

    def test_old_snapshot_with_three_dimensions_validates(self) -> None:
        old_snapshot = {
            "region": "cn",
            "trade_date": "2026-06-01",
            "status": "yellow",
            "score": 50,
            "label": "需观察",
            "temperature_label": "震荡",
            "reasons": ["test"],
            "guidance": "test",
            "dimensions": {
                "breadth": {"score": 50, "available": True},
                "index": {"score": 50, "available": True},
                "limit": {"score": 50, "available": True},
            },
            "data_quality": "ok",
        }
        snapshot = MarketLightSnapshot.model_validate(old_snapshot)
        self.assertIsNone(snapshot.dimensions.margin_balance)
        self.assertIsNone(snapshot.dimensions.northbound_flow)
        self.assertIsNone(snapshot.dimensions.turnover_quantile)
        self.assertIsNone(snapshot.dimensions.limit_ratio)
        self.assertIsNone(snapshot.dimensions.continuous_board)

    def test_new_snapshot_with_all_dimensions_validates(self) -> None:
        new_snapshot = {
            "region": "cn",
            "trade_date": "2026-07-03",
            "status": "green",
            "score": 72,
            "label": "可进攻",
            "temperature_label": "偏暖",
            "reasons": ["test"],
            "guidance": "test",
            "dimensions": {
                "breadth": {"score": 72, "available": True},
                "index": {"score": 70, "available": True},
                "limit": {"score": 80, "available": True},
                "margin_balance": {"score": 66, "available": True},
                "northbound_flow": {"score": 74, "available": True},
                "turnover_quantile": {"score": 50, "available": True},
                "limit_ratio": {"score": 80, "available": True},
                "continuous_board": {"score": 58, "available": True},
            },
            "data_quality": "ok",
        }
        snapshot = MarketLightSnapshot.model_validate(new_snapshot)
        self.assertEqual(snapshot.dimensions.margin_balance.score, 66)
        self.assertEqual(snapshot.dimensions.continuous_board.score, 58)


if __name__ == "__main__":
    unittest.main()
