# -*- coding: utf-8 -*-
"""Tests for localized market review wrappers."""

import importlib
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

def _build_optional_module_stubs() -> dict[str, ModuleType]:
    stubs: dict[str, ModuleType] = {}
    google_module: ModuleType | None = None

    for module_name in ("google.generativeai", "google.genai", "anthropic"):
        try:
            importlib.import_module(module_name)
            continue
        except ImportError:
            stub = ModuleType(module_name)
            stubs[module_name] = stub
            if not module_name.startswith("google."):
                continue
            if google_module is None:
                try:
                    google_module = importlib.import_module("google")
                except ImportError:
                    google_module = ModuleType("google")
                    stubs["google"] = google_module
            setattr(google_module, module_name.split(".", 1)[1], stub)

    return stubs


sys.modules.update(_build_optional_module_stubs())
import src.core.market_review as market_review_module

run_market_review = market_review_module.run_market_review


class MarketReviewLocalizationTestCase(unittest.TestCase):
    def _make_notifier(self) -> MagicMock:
        notifier = MagicMock()
        notifier.save_report_to_file.return_value = "/tmp/market_review.md"
        notifier.is_available.return_value = True
        notifier.send.return_value = True
        return notifier

    def test_run_market_review_uses_english_notification_title(self) -> None:
        notifier = self._make_notifier()
        market_analyzer = MagicMock()
        market_analyzer.run_daily_review.return_value = "## 2026-04-10 A-share Market Recap\n\nBody"

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="en", market_review_region="cn"),
        ), patch.object(market_review_module, "MarketAnalyzer", return_value=market_analyzer):
            result = run_market_review(notifier, send_notification=True)

        self.assertEqual(result, "## 2026-04-10 A-share Market Recap\n\nBody")
        saved_content = notifier.save_report_to_file.call_args.args[0]
        self.assertTrue(saved_content.startswith("# 🎯 Market Review\n\n"))
        sent_content = notifier.send.call_args.args[0]
        self.assertTrue(sent_content.startswith("🎯 Market Review\n\n"))
        self.assertTrue(notifier.send.call_args.kwargs["email_send_to_all"])

    def test_run_market_review_merges_both_regions_with_english_wrappers(self) -> None:
        notifier = self._make_notifier()
        cn_analyzer = MagicMock()
        cn_analyzer.run_daily_review.return_value = "CN body"
        hk_analyzer = MagicMock()
        hk_analyzer.run_daily_review.return_value = "HK body"
        us_analyzer = MagicMock()
        us_analyzer.run_daily_review.return_value = "US body"

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="en", market_review_region="both"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            side_effect=[cn_analyzer, hk_analyzer, us_analyzer],
        ):
            result = run_market_review(notifier, send_notification=False)

        self.assertIn("# A-share Market Recap\n\nCN body", result)
        self.assertIn("# HK Market Recap\n\nHK body", result)
        self.assertIn("> Next market recap follows", result)
        self.assertIn("# US Market Recap\n\nUS body", result)
        saved_content = notifier.save_report_to_file.call_args.args[0]
        self.assertTrue(saved_content.startswith("# 🎯 Market Review\n\n"))
        notifier.send.assert_not_called()

    def test_run_market_review_comma_joined_subset_cn_us(self) -> None:
        """Regression: compute_effective_region("both", {"cn","us"}) -> "cn,us"
        must produce A-share + US report without HK."""
        notifier = self._make_notifier()
        cn_analyzer = MagicMock()
        cn_analyzer.run_daily_review.return_value = "CN body"
        us_analyzer = MagicMock()
        us_analyzer.run_daily_review.return_value = "US body"

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="zh", market_review_region="cn"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            side_effect=[cn_analyzer, us_analyzer],
        ):
            result = run_market_review(
                notifier, send_notification=False, override_region="cn,us"
            )

        self.assertIn("# A股大盘复盘\n\nCN body", result)
        self.assertIn("# 美股大盘复盘\n\nUS body", result)
        self.assertNotIn("港股", result)
        self.assertNotIn("HK", result)

    def test_run_market_review_comma_joined_subset_cn_hk(self) -> None:
        """Regression: compute_effective_region("both", {"cn","hk"}) -> "cn,hk"
        must produce A-share + HK report without US."""
        notifier = self._make_notifier()
        cn_analyzer = MagicMock()
        cn_analyzer.run_daily_review.return_value = "CN body"
        hk_analyzer = MagicMock()
        hk_analyzer.run_daily_review.return_value = "HK body"

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="zh", market_review_region="cn"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            side_effect=[cn_analyzer, hk_analyzer],
        ):
            result = run_market_review(
                notifier, send_notification=False, override_region="cn,hk"
            )

        self.assertIn("# A股大盘复盘\n\nCN body", result)
        self.assertIn("# 港股大盘复盘\n\nHK body", result)
        self.assertNotIn("美股", result)
        self.assertNotIn("US Market", result)


if __name__ == "__main__":
    unittest.main()
