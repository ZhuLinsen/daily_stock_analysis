# -*- coding: utf-8 -*-
"""Tests for localized market review wrappers."""

import importlib
import os
import sys
import tempfile
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
from src.config import Config
from src.storage import AnalysisHistory, DatabaseManager

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
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            return_value=market_analyzer,
        ), patch.object(market_review_module, "_persist_market_review_history") as persist_history:
            result = run_market_review(notifier, send_notification=True)

        self.assertEqual(result, "## 2026-04-10 A-share Market Recap\n\nBody")
        saved_content = notifier.save_report_to_file.call_args.args[0]
        self.assertTrue(saved_content.startswith("# 🎯 Market Review\n\n"))
        sent_content = notifier.send.call_args.args[0]
        self.assertTrue(sent_content.startswith("🎯 Market Review\n\n"))
        self.assertTrue(notifier.send.call_args.kwargs["email_send_to_all"])
        self.assertEqual(notifier.send.call_args.kwargs["route_type"], "report")
        persist_history.assert_called_once()
        self.assertEqual(persist_history.call_args.kwargs["query_id"], None)

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
        ), patch.object(market_review_module, "_persist_market_review_history"):
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
        ), patch.object(market_review_module, "_persist_market_review_history"):
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
        ), patch.object(market_review_module, "_persist_market_review_history"):
            result = run_market_review(
                notifier, send_notification=False, override_region="cn,hk"
            )

        self.assertIn("# A股大盘复盘\n\nCN body", result)
        self.assertIn("# 港股大盘复盘\n\nHK body", result)
        self.assertNotIn("美股", result)
        self.assertNotIn("US Market", result)

    def test_persist_market_review_history_saves_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_db_path = os.environ.get("DATABASE_PATH")
            os.environ["DATABASE_PATH"] = os.path.join(temp_dir, "market_review_history.db")
            Config._instance = None
            DatabaseManager.reset_instance()
            try:
                saved = market_review_module._persist_market_review_history(
                    review_report="## 今日大盘\n\n复盘正文",
                    markdown_report="# 🎯 大盘复盘\n\n## 今日大盘\n\n复盘正文",
                    region="cn",
                    config=SimpleNamespace(report_language="zh"),
                    query_id="market-task-001",
                )

                self.assertEqual(saved, 1)
                db = DatabaseManager.get_instance()
                with db.get_session() as session:
                    row = session.query(AnalysisHistory).filter(
                        AnalysisHistory.query_id == "market-task-001"
                    ).first()
                    self.assertIsNotNone(row)
                    self.assertEqual(row.code, market_review_module.MARKET_REVIEW_HISTORY_CODE)
                    self.assertEqual(row.name, "大盘复盘")
                    self.assertEqual(row.report_type, market_review_module.MARKET_REVIEW_REPORT_TYPE)
                    self.assertEqual(row.news_content, "## 今日大盘\n\n复盘正文")
                    self.assertIn("# 🎯 大盘复盘", row.raw_result)
            finally:
                DatabaseManager.reset_instance()
                Config._instance = None
                if old_db_path is None:
                    os.environ.pop("DATABASE_PATH", None)
                else:
                    os.environ["DATABASE_PATH"] = old_db_path


if __name__ == "__main__":
    unittest.main()
