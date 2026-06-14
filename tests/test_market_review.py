# -*- coding: utf-8 -*-
"""Tests for localized market review wrappers."""

import importlib
import json
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
from src.services.run_diagnostics import activate_run_diagnostic_context, reset_run_diagnostic_context
from src.storage import AnalysisHistory, DatabaseManager

run_market_review = market_review_module.run_market_review


class MarketReviewLocalizationTestCase(unittest.TestCase):
    def _make_notifier(self) -> MagicMock:
        notifier = MagicMock()
        notifier.save_report_to_file.return_value = "/tmp/market_review.md"
        notifier.is_available.return_value = True
        notifier.send.return_value = True
        return notifier

    def test_resolve_market_review_regions_returns_ordered_non_empty_list(self) -> None:
        cases = [
            (None, ["cn"]),
            ("", ["cn"]),
            ("both", ["cn", "hk", "us"]),
            (" CN,US,cn ", ["cn", "us"]),
            ("us,cn,us", ["cn", "us"]),
            ("eu,apac", ["cn"]),
            (",,", ["cn"]),
            ("HK", ["hk"]),
            ("invalid", ["cn"]),
        ]

        for raw_region, expected in cases:
            with self.subTest(raw_region=raw_region):
                self.assertEqual(
                    market_review_module._resolve_market_review_regions(raw_region),
                    expected,
                )

    def test_run_market_review_uses_english_notification_title(self) -> None:
        notifier = self._make_notifier()
        market_analyzer = MagicMock()
        market_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="## 2026-04-10 A-share Market Recap\n\nBody",
            market_light_snapshot={"region": "cn", "trade_date": "2026-04-10", "score": 60},
        )

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
        self.assertTrue(persist_history.call_args.kwargs["query_id"].startswith("market_review_"))

    def test_run_market_review_can_skip_report_file_for_context_generation(self) -> None:
        notifier = self._make_notifier()
        market_analyzer = MagicMock()
        market_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="CN body",
            market_light_snapshot={"region": "cn", "trade_date": "2026-03-06", "score": 60},
        )

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="zh", market_review_region="cn"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            return_value=market_analyzer,
        ), patch.object(market_review_module, "_persist_market_review_history") as persist_history:
            result = run_market_review(
                notifier,
                send_notification=False,
                return_structured=True,
                save_report_file=False,
            )

        self.assertIsInstance(result, market_review_module.MarketReviewRunResult)
        self.assertEqual(result.report, "CN body")
        notifier.save_report_to_file.assert_not_called()
        persist_history.assert_called_once()

    def test_run_market_review_passes_request_config_to_generation(self) -> None:
        notifier = self._make_notifier()
        request_config = SimpleNamespace(report_language="en", market_review_region="cn")
        global_config = SimpleNamespace(report_language="zh", market_review_region="cn")
        market_analyzer = MagicMock()
        market_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="English market review body",
            market_light_snapshot={"region": "cn", "trade_date": "2026-04-10", "score": 60},
        )

        with patch.object(
            market_review_module,
            "get_config",
            return_value=global_config,
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            return_value=market_analyzer,
        ) as analyzer_cls, patch.object(market_review_module, "_persist_market_review_history") as persist_history:
            result = run_market_review(
                notifier,
                config=request_config,
                send_notification=False,
                return_structured=True,
            )

        self.assertEqual(analyzer_cls.call_args.kwargs["config"], request_config)
        self.assertEqual(persist_history.call_args.kwargs["config"], request_config)
        self.assertTrue(notifier.save_report_to_file.call_args.args[0].startswith("# 🎯 Market Review\n\n"))
        self.assertEqual(result.market_review_payload["language"], "en")
        self.assertEqual(result.report, "English market review body")

    def test_run_market_review_merges_both_regions_with_english_wrappers(self) -> None:
        notifier = self._make_notifier()
        cn_analyzer = MagicMock()
        cn_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="CN body",
            market_light_snapshot={"region": "cn", "trade_date": "2026-03-06", "score": 60},
        )
        hk_analyzer = MagicMock()
        hk_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="HK body",
            market_light_snapshot={"region": "hk", "trade_date": "2026-03-06", "score": 58},
        )
        us_analyzer = MagicMock()
        us_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="US body",
            market_light_snapshot={"region": "us", "trade_date": "2026-03-06", "score": 55},
        )

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="en", market_review_region="both"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            side_effect=[cn_analyzer, hk_analyzer, us_analyzer],
        ), patch.object(market_review_module, "_persist_market_review_history") as persist_history:
            result = run_market_review(notifier, send_notification=True)

        self.assertIn("# A-share Market Recap\n\nCN body", result)
        self.assertIn("# HK Market Recap\n\nHK body", result)
        self.assertIn("> Next market recap follows", result)
        self.assertIn("# US Market Recap\n\nUS body", result)
        saved_content = notifier.save_report_to_file.call_args.args[0]
        self.assertTrue(saved_content.startswith("# 🎯 Market Review\n\n"))
        self.assertIn("# A-share Market Recap\n\nCN body", saved_content)
        self.assertIn("> Next market recap follows", saved_content)
        self.assertIn("# HK Market Recap\n\nHK body", saved_content)
        self.assertIn("# US Market Recap\n\nUS body", saved_content)
        self.assertIn(
            "# A-share Market Recap\n\nCN body",
            persist_history.call_args.kwargs["markdown_report"],
        )
        sent_content = notifier.send.call_args.args[0]
        self.assertTrue(sent_content.startswith("🎯 Market Review\n\n"))
        self.assertIn("# US Market Recap\n\nUS body", sent_content)

    def test_run_market_review_comma_joined_subset_cn_us(self) -> None:
        """Regression: compute_effective_region("both", {"cn","us"}) -> "cn,us"
        must produce A-share + US report without HK."""
        notifier = self._make_notifier()
        cn_analyzer = MagicMock()
        cn_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="CN body",
            market_light_snapshot={"region": "cn", "trade_date": "2026-03-06", "score": 60},
        )
        us_analyzer = MagicMock()
        us_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="US body",
            market_light_snapshot={"region": "us", "trade_date": "2026-03-06", "score": 55},
        )

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
        cn_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="CN body",
            market_light_snapshot={"region": "cn", "trade_date": "2026-03-06", "score": 60},
        )
        hk_analyzer = MagicMock()
        hk_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="HK body",
            market_light_snapshot={"region": "hk", "trade_date": "2026-03-06", "score": 58},
        )

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

    def test_run_market_review_persists_only_current_run_market_light_snapshots(self) -> None:
        notifier = self._make_notifier()
        cn_analyzer = MagicMock()
        cn_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="CN body",
            market_light_snapshot={"region": "cn", "trade_date": "2026-03-06", "score": 60},
        )
        us_analyzer = MagicMock()
        us_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="US body",
            market_light_snapshot={"region": "us", "trade_date": "2026-03-06", "score": 55},
        )

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="zh", market_review_region="cn"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            side_effect=[cn_analyzer, us_analyzer],
        ), patch.object(market_review_module, "_persist_market_review_history") as persist_history:
            run_market_review(notifier, send_notification=False, override_region="cn,us")

        snapshots = persist_history.call_args.kwargs["market_light_snapshots"]
        self.assertEqual(set(snapshots), {"cn", "us"})
        self.assertEqual(snapshots["cn"]["score"], 60)
        self.assertEqual(snapshots["us"]["score"], 55)

    def test_run_market_review_normalizes_single_region_snapshot_key(self) -> None:
        notifier = self._make_notifier()
        market_analyzer = MagicMock()
        market_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="CN body",
            market_light_snapshot={
                "region": "cn",
                "trade_date": "2026-03-06",
                "score": 60,
            },
        )

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="zh", market_review_region="cn"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            return_value=market_analyzer,
        ) as analyzer_cls, patch.object(
            market_review_module, "_persist_market_review_history"
        ) as persist_history:
            run_market_review(notifier, send_notification=False, override_region="CN")

        self.assertEqual(analyzer_cls.call_args.kwargs["region"], "cn")
        persist_history.assert_called_once()
        self.assertEqual(persist_history.call_args.kwargs["region"], "cn")
        snapshots = persist_history.call_args.kwargs["market_light_snapshots"]
        self.assertEqual(set(snapshots), {"cn"})
        self.assertEqual(snapshots["cn"]["trade_date"], "2026-03-06")

    def test_run_market_review_invalid_comma_subset_falls_back_to_cn(self) -> None:
        notifier = self._make_notifier()
        market_analyzer = MagicMock()
        market_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
            report="CN body",
            market_light_snapshot={
                "region": "cn",
                "trade_date": "2026-03-06",
                "score": 60,
            },
        )

        with patch.object(
            market_review_module,
            "get_config",
            return_value=SimpleNamespace(report_language="zh", market_review_region="cn"),
        ), patch.object(
            market_review_module,
            "MarketAnalyzer",
            return_value=market_analyzer,
        ) as analyzer_cls, patch.object(
            market_review_module, "_persist_market_review_history"
        ) as persist_history:
            result = run_market_review(
                notifier, send_notification=False, override_region="eu,apac"
            )

        self.assertEqual(result, "CN body")
        self.assertEqual(analyzer_cls.call_args.kwargs["region"], "cn")
        persist_history.assert_called_once()
        self.assertEqual(persist_history.call_args.kwargs["region"], "cn")
        snapshots = persist_history.call_args.kwargs["market_light_snapshots"]
        self.assertEqual(set(snapshots), {"cn"})

    def test_render_market_review_payload_markdown_does_not_repeat_title(self) -> None:
        markdown = market_review_module._render_market_review_payload_markdown(
            {
                "title": "2026-06-03 大盘复盘",
                "sections": [
                    {
                        "key": "daily_review",
                        "title": "2026-06-03 大盘复盘",
                        "markdown": "> 今日指数强弱分化。\n\n### 一、盘面总览\n正文",
                    }
                ],
            },
            wrapper_title="🎯 大盘复盘",
        )

        self.assertEqual(markdown.count("2026-06-03 大盘复盘"), 1)
        self.assertTrue(markdown.startswith("🎯 大盘复盘\n\n## 2026-06-03 大盘复盘"))

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
                    market_light_snapshots={
                        "cn": {
                            "region": "cn",
                            "trade_date": "2026-03-06",
                            "status": "red",
                            "score": 30,
                            "label": "偏防守",
                            "temperature_label": "偏弱",
                            "reasons": ["test"],
                            "guidance": "test",
                            "dimensions": {
                                "breadth": {"score": 20, "available": True},
                                "index": {"score": 30, "available": True},
                                "limit": {"score": 10, "available": True},
                            },
                            "data_quality": "ok",
                        }
                    },
                    market_review_payload={
                        "version": 1,
                        "kind": "market_review",
                        "region": "cn",
                        "sections": [{"title": "今日大盘", "markdown": "复盘正文"}],
                    },
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
                    self.assertIn('"market_light_snapshots"', row.context_snapshot)
                    self.assertIn('"market_review_payload"', row.context_snapshot)
                    self.assertIn('"trade_date": "2026-03-06"', row.context_snapshot)
            finally:
                DatabaseManager.reset_instance()
                Config._instance = None
                if old_db_path is None:
                    os.environ.pop("DATABASE_PATH", None)
                else:
                    os.environ["DATABASE_PATH"] = old_db_path

    def test_run_market_review_persists_notification_diagnostics_after_history_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_db_path = os.environ.get("DATABASE_PATH")
            os.environ["DATABASE_PATH"] = os.path.join(temp_dir, "market_review_notification.db")
            Config._instance = None
            DatabaseManager.reset_instance()
            query_id = "market-task-notification"
            notifier = self._make_notifier()
            market_analyzer = MagicMock()
            market_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
                report="## 今日大盘\n\n复盘正文",
                market_light_snapshot={"region": "cn", "trade_date": "2026-03-06", "score": 60},
            )
            token = activate_run_diagnostic_context(
                trace_id="trace-market-notification",
                task_id=query_id,
                query_id=query_id,
                stock_code=market_review_module.MARKET_REVIEW_HISTORY_CODE,
                trigger_source="api",
            )
            try:
                with patch.object(market_review_module, "MarketAnalyzer", return_value=market_analyzer):
                    result = run_market_review(
                        notifier,
                        config=SimpleNamespace(report_language="zh", market_review_region="cn"),
                        send_notification=True,
                        query_id=query_id,
                        trigger_source="api",
                    )

                self.assertEqual(result, "## 今日大盘\n\n复盘正文")
                db = DatabaseManager.get_instance()
                with db.get_session() as session:
                    row = session.query(AnalysisHistory).filter(
                        AnalysisHistory.query_id == query_id
                    ).first()
                    self.assertIsNotNone(row)
                    context_snapshot = json.loads(row.context_snapshot)
                    notification_runs = context_snapshot["diagnostics"]["notification_runs"]
                    self.assertEqual(notification_runs[-1]["status"], "success")
                    self.assertTrue(notification_runs[-1]["success"])
            finally:
                reset_run_diagnostic_context(token)
                DatabaseManager.reset_instance()
                Config._instance = None
                if old_db_path is None:
                    os.environ.pop("DATABASE_PATH", None)
                else:
                    os.environ["DATABASE_PATH"] = old_db_path

    def test_run_market_review_reuses_generated_query_id_for_notification_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_db_path = os.environ.get("DATABASE_PATH")
            os.environ["DATABASE_PATH"] = os.path.join(temp_dir, "market_review_generated_query.db")
            Config._instance = None
            DatabaseManager.reset_instance()
            notifier = self._make_notifier()
            market_analyzer = MagicMock()
            market_analyzer.run_daily_review_with_snapshot.return_value = SimpleNamespace(
                report="## 今日大盘\n\n复盘正文",
                market_light_snapshot={"region": "cn", "trade_date": "2026-03-06", "score": 60},
            )
            token = activate_run_diagnostic_context(
                trace_id="trace-market-generated",
                task_id="task-market-generated",
                stock_code=market_review_module.MARKET_REVIEW_HISTORY_CODE,
                trigger_source="cli",
            )
            try:
                with patch.object(market_review_module, "MarketAnalyzer", return_value=market_analyzer):
                    result = run_market_review(
                        notifier,
                        config=SimpleNamespace(report_language="zh", market_review_region="cn"),
                        send_notification=True,
                        trigger_source="cli",
                    )

                self.assertEqual(result, "## 今日大盘\n\n复盘正文")
                db = DatabaseManager.get_instance()
                with db.get_session() as session:
                    rows = session.query(AnalysisHistory).all()
                    self.assertEqual(len(rows), 1)
                    row = rows[0]
                    self.assertTrue(row.query_id.startswith("market_review_"))
                    context_snapshot = json.loads(row.context_snapshot)
                    notification_runs = context_snapshot["diagnostics"]["notification_runs"]
                    self.assertEqual(notification_runs[-1]["status"], "success")
                    self.assertTrue(notification_runs[-1]["success"])
            finally:
                reset_run_diagnostic_context(token)
                DatabaseManager.reset_instance()
                Config._instance = None
                if old_db_path is None:
                    os.environ.pop("DATABASE_PATH", None)
                else:
                    os.environ["DATABASE_PATH"] = old_db_path


if __name__ == "__main__":
    unittest.main()
