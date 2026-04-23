# -*- coding: utf-8 -*-
"""
===================================
Chip structure fallback tests (Issue #589)
===================================

Tests for fill_chip_structure_if_needed and related helpers.
"""

import sys
import unittest
from unittest.mock import MagicMock

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from data_provider.realtime_types import ChipDistribution
from src.analyzer import (
    AnalysisResult,
    fill_chip_structure_if_needed,
    _is_value_placeholder,
    _derive_chip_health,
    _build_chip_structure_from_data,
)


class TestIsValuePlaceholder(unittest.TestCase):
    """Tests for _is_value_placeholder."""

    def test_none_is_placeholder(self) -> None:
        self.assertTrue(_is_value_placeholder(None))

    def test_zero_is_placeholder(self) -> None:
        self.assertTrue(_is_value_placeholder(0))
        self.assertTrue(_is_value_placeholder(0.0))

    def test_empty_string_is_placeholder(self) -> None:
        self.assertTrue(_is_value_placeholder(""))
        self.assertTrue(_is_value_placeholder("   "))

    def test_na_variants_are_placeholder(self) -> None:
        self.assertTrue(_is_value_placeholder("N/A"))
        self.assertTrue(_is_value_placeholder("n/a"))
        self.assertTrue(_is_value_placeholder("NA"))
        self.assertTrue(_is_value_placeholder("na"))

    def test_data_missing_is_placeholder(self) -> None:
        self.assertTrue(_is_value_placeholder("数据缺失"))
        self.assertTrue(_is_value_placeholder("未知"))

    def test_valid_values_not_placeholder(self) -> None:
        self.assertFalse(_is_value_placeholder(0.5))
        self.assertFalse(_is_value_placeholder("50%"))
        self.assertFalse(_is_value_placeholder("67.5%"))
        self.assertFalse(_is_value_placeholder(25.6))
        self.assertFalse(_is_value_placeholder("健康"))


class TestDeriveChipHealth(unittest.TestCase):
    """Tests for _derive_chip_health."""

    def test_high_profit_ratio_returns_jingti(self) -> None:
        self.assertEqual(_derive_chip_health(0.95, 0.10), "警惕")
        self.assertEqual(_derive_chip_health(0.9, 0.05), "警惕")

    def test_high_concentration_returns_jingti(self) -> None:
        self.assertEqual(_derive_chip_health(0.5, 0.30), "警惕")
        self.assertEqual(_derive_chip_health(0.3, 0.25), "警惕")

    def test_concentrated_moderate_profit_returns_jiankang(self) -> None:
        self.assertEqual(_derive_chip_health(0.5, 0.10), "健康")
        self.assertEqual(_derive_chip_health(0.6, 0.12), "健康")
        self.assertEqual(_derive_chip_health(0.3, 0.14), "健康")

    def test_otherwise_returns_yiban(self) -> None:
        self.assertEqual(_derive_chip_health(0.2, 0.20), "一般")
        self.assertEqual(_derive_chip_health(0.5, 0.18), "一般")


class TestBuildChipStructureFromData(unittest.TestCase):
    """Tests for _build_chip_structure_from_data."""

    def test_from_chip_distribution(self) -> None:
        chip = ChipDistribution(
            code="600519",
            profit_ratio=0.567,
            avg_cost=1850.5,
            concentration_90=0.12,
        )
        out = _build_chip_structure_from_data(chip)
        self.assertEqual(out["profit_ratio"], "56.7%")
        self.assertEqual(out["avg_cost"], 1850.5)
        self.assertEqual(out["concentration"], "12.00%")
        self.assertEqual(out["chip_health"], "健康")

    def test_from_dict(self) -> None:
        d = {"profit_ratio": 0.9, "avg_cost": 100.0, "concentration_90": 0.08}
        out = _build_chip_structure_from_data(d)
        self.assertEqual(out["profit_ratio"], "90.0%")
        self.assertEqual(out["avg_cost"], 100.0)
        self.assertEqual(out["concentration"], "8.00%")
        self.assertEqual(out["chip_health"], "警惕")

    def test_dict_with_string_values(self) -> None:
        d = {"profit_ratio": "0.5", "avg_cost": "25.6", "concentration_90": "0.15"}
        out = _build_chip_structure_from_data(d)
        self.assertEqual(out["profit_ratio"], "50.0%")
        self.assertEqual(out["avg_cost"], "25.6")  # raw value preserved
        self.assertEqual(out["concentration"], "15.00%")

    def test_avg_cost_zero_shows_na(self) -> None:
        chip = ChipDistribution(code="600519", profit_ratio=0.5, avg_cost=0.0, concentration_90=0.1)
        out = _build_chip_structure_from_data(chip)
        self.assertEqual(out["avg_cost"], "N/A")

    def test_avg_cost_none_shows_na(self) -> None:
        d = {"profit_ratio": 0.5, "avg_cost": None, "concentration_90": 0.1}
        out = _build_chip_structure_from_data(d)
        self.assertEqual(out["avg_cost"], "N/A")


class TestFillChipStructureIfNeeded(unittest.TestCase):
    """Tests for fill_chip_structure_if_needed."""

    def _make_result(self, dashboard: dict = None) -> AnalysisResult:
        return AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard=dashboard,
        )

    def _make_chip(self) -> ChipDistribution:
        return ChipDistribution(
            code="600519",
            profit_ratio=0.67,
            avg_cost=1850.0,
            concentration_90=0.11,
        )

    def test_no_modification_when_chip_data_none(self) -> None:
        result = self._make_result(dashboard={"data_perspective": {"chip_structure": {}}})
        fill_chip_structure_if_needed(result, None)
        self.assertEqual(result.dashboard["data_perspective"]["chip_structure"], {})

    def test_no_modification_when_result_none(self) -> None:
        chip = self._make_chip()
        fill_chip_structure_if_needed(None, chip)
        # No crash

    def test_full_fill_when_cs_all_empty(self) -> None:
        result = self._make_result(
            dashboard={"data_perspective": {"chip_structure": {"profit_ratio": 0, "avg_cost": 0, "concentration": 0, "chip_health": ""}}}
        )
        chip = self._make_chip()
        fill_chip_structure_if_needed(result, chip)
        cs = result.dashboard["data_perspective"]["chip_structure"]
        self.assertEqual(cs["profit_ratio"], "67.0%")
        self.assertEqual(cs["avg_cost"], 1850.0)
        self.assertEqual(cs["concentration"], "11.00%")
        self.assertEqual(cs["chip_health"], "健康")

    def test_merge_fill_partial_placeholder(self) -> None:
        result = self._make_result(
            dashboard={
                "data_perspective": {
                    "chip_structure": {"profit_ratio": "65.0%", "avg_cost": 0, "concentration": 0, "chip_health": ""}
                }
            }
        )
        chip = self._make_chip()
        fill_chip_structure_if_needed(result, chip)
        cs = result.dashboard["data_perspective"]["chip_structure"]
        self.assertEqual(cs["profit_ratio"], "65.0%")  # LLM value kept
        self.assertEqual(cs["avg_cost"], 1850.0)  # filled from chip
        self.assertEqual(cs["concentration"], "11.00%")  # filled from chip
        self.assertEqual(cs["chip_health"], "健康")  # filled from chip

    def test_dashboard_none_initialized(self) -> None:
        result = self._make_result(dashboard=None)
        chip = self._make_chip()
        fill_chip_structure_if_needed(result, chip)
        self.assertIsNotNone(result.dashboard)
        cs = result.dashboard["data_perspective"]["chip_structure"]
        self.assertEqual(cs["profit_ratio"], "67.0%")
        self.assertEqual(cs["chip_health"], "健康")

    def test_no_overwrite_valid_llm_values(self) -> None:
        result = self._make_result(
            dashboard={
                "data_perspective": {
                    "chip_structure": {
                        "profit_ratio": "70.0%",
                        "avg_cost": 1900.0,
                        "concentration": "10.00%",
                        "chip_health": "健康",
                    }
                }
            }
        )
        chip = self._make_chip()
        fill_chip_structure_if_needed(result, chip)
        cs = result.dashboard["data_perspective"]["chip_structure"]
        self.assertEqual(cs["profit_ratio"], "70.0%")
        self.assertEqual(cs["avg_cost"], 1900.0)
        self.assertEqual(cs["concentration"], "10.00%")
        self.assertEqual(cs["chip_health"], "健康")

    def test_data_perspective_null_handled(self) -> None:
        """When LLM returns data_perspective: null, fill should still work."""
        result = self._make_result(
            dashboard={"data_perspective": None, "core_conclusion": {"one_sentence": "观望"}}
        )
        chip = self._make_chip()
        fill_chip_structure_if_needed(result, chip)
        self.assertIsNotNone(result.dashboard["data_perspective"])
        cs = result.dashboard["data_perspective"]["chip_structure"]
        self.assertEqual(cs["profit_ratio"], "67.0%")

    def test_extra_keys_in_chip_structure_preserved(self) -> None:
        """Extra keys added by LLM in chip_structure must not be dropped."""
        result = self._make_result(
            dashboard={
                "data_perspective": {
                    "chip_structure": {
                        "profit_ratio": 0,
                        "avg_cost": 0,
                        "concentration": 0,
                        "chip_health": "",
                        "custom_note": "LLM added this",
                    }
                }
            }
        )
        chip = self._make_chip()
        fill_chip_structure_if_needed(result, chip)
        cs = result.dashboard["data_perspective"]["chip_structure"]
        self.assertEqual(cs["profit_ratio"], "67.0%")
        self.assertEqual(cs["custom_note"], "LLM added this")
