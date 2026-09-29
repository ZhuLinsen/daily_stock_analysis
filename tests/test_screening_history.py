# -*- coding: utf-8 -*-
"""Persistence and DSA hand-off coverage for the built-in screening engine."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.config import Config
from src.services.screening.strategy import list_strategies
from src.services.screening_service import ScreeningService, _build_dsa_candidate_context
from src.storage import DatabaseManager


class ScreeningHistoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")
        self.config = Config(screening_enabled=True)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_completed_screen_run_is_persisted_and_loaded(self) -> None:
        raw_result = {
            "run_id": "screen-run-1",
            "strategy": "dual_low",
            "market": "cn",
            "snapshot_source": "sina",
            "snapshot_count": 5000,
            "after_filter_count": 12,
            "llm_ranked": True,
            "daily_enriched": False,
            "source_errors": ["efinance: request timed out"],
            "warnings": ["Snapshot source fallback: efinance: request timed out"],
            "candidates": [
                {
                    "rank": 1,
                    "code": "600519",
                    "name": "贵州茅台",
                    "final_score": 88.5,
                    "ranking_reason": "低估值与流动性通过",
                }
            ],
        }
        service = ScreeningService(self.config, db_manager=self.db)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, True, None),
            ),
            patch(
                "src.services.screening_service._call_screening_screen",
                return_value=raw_result,
            ),
            patch(
                "src.services.screening_service._enrich_candidates_with_dsa",
                side_effect=lambda candidates: (
                    candidates,
                    {
                        "enabled": True,
                        "requested_count": 1,
                        "enriched_count": 0,
                        "warnings": [],
                    },
                ),
            ),
        ):
            response = service.screen(strategy="dual_low", market="cn", max_results=3)

        self.assertEqual(response["run_id"], "screen-run-1")
        stored = self.db.get_screening_run("screen-run-1")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["candidate_count"], 1)
        self.assertEqual(stored["result"]["candidates"][0]["code"], "600519")

        history = service.history(limit=10, strategy="dual_low", market="cn")
        self.assertEqual(history["run_count"], 1)
        self.assertNotIn("result", history["runs"][0])

    def test_screen_maps_pipeline_degradation_into_warning_contract(self) -> None:
        raw_result = {
            "run_id": "screen-run-degradation",
            "strategy": "dual_low",
            "market": "cn",
            "snapshot_source": "sina",
            "snapshot_count": 5000,
            "after_filter_count": 12,
            "llm_ranked": False,
            "daily_enriched": False,
            "source_errors": ["efinance: request timed out"],
            "degradation": [
                "Snapshot source fallback: efinance: request timed out",
                "LLM ranking failed: fell back to screen_score",
            ],
            "candidates": [
                {
                    "rank": 1,
                    "code": "600519",
                    "name": "贵州茅台",
                    "final_score": 88.5,
                    "ranking_reason": "低估值与流动性通过",
                }
            ],
        }
        service = ScreeningService(self.config, db_manager=self.db)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, True, None),
            ),
            patch(
                "src.services.screening_service._call_screening_screen",
                return_value=raw_result,
            ),
            patch(
                "src.services.screening_service._enrich_candidates_with_dsa",
                side_effect=lambda candidates: (
                    candidates,
                    {
                        "enabled": True,
                        "requested_count": 1,
                        "enriched_count": 0,
                        "warnings": [],
                    },
                ),
            ),
        ):
            response = service.screen(strategy="dual_low", market="cn", max_results=3)

        self.assertEqual(
            response["warnings"],
            [
                "Snapshot source fallback: efinance: request timed out",
                "LLM ranking failed: fell back to screen_score",
            ],
        )
        self.assertEqual(
            response["degradation"],
            [
                "Snapshot source fallback: efinance: request timed out",
                "LLM ranking failed: fell back to screen_score",
            ],
        )
        stored = self.db.get_screening_run("screen-run-degradation")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["warnings"], response["warnings"])
        self.assertEqual(stored["result"]["warnings"], response["warnings"])
        self.assertEqual(stored["result"]["degradation"], response["degradation"])

        history = service.history(limit=10, strategy="dual_low", market="cn")
        self.assertEqual(history["runs"][0]["warnings"], response["warnings"])

        source_history = service.source_history(limit=10)
        self.assertEqual(source_history["fallback_runs"], 1)

    def test_save_is_idempotent_and_source_history_aggregates_failures(self) -> None:
        payload = {
            "run_id": "screen-run-2",
            "strategy": "volume_breakout",
            "market": "cn",
            "snapshot_source": "sina",
            "candidate_count": 2,
            "source_errors": ["efinance: empty response"],
            "warnings": [],
            "degradation": ["Snapshot source fallback: efinance: empty response"],
            "candidates": [],
        }
        self.assertEqual(self.db.save_screening_run(payload), 1)
        payload["candidate_count"] = 3
        self.assertEqual(self.db.save_screening_run(payload), 1)

        runs = self.db.list_screening_runs(limit=10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["candidate_count"], 3)
        self.assertEqual(
            runs[0]["warnings"],
            ["Snapshot source fallback: efinance: empty response"],
        )

        source_history = ScreeningService(
            self.config,
            db_manager=self.db,
        ).source_history(limit=10)
        self.assertEqual(source_history["runs_analyzed"], 1)
        self.assertEqual(source_history["fallback_runs"], 1)
        self.assertEqual(source_history["sources"]["sina"]["selected_runs"], 1)
        self.assertEqual(source_history["sources"]["efinance"]["error_count"], 1)

    def test_screening_strategies_declare_dsa_analysis_skill_handoffs(self) -> None:
        strategies = {item.name: item for item in list_strategies()}

        self.assertEqual(strategies["volume_breakout"].analysis_skills, ["volume_breakout"])
        self.assertEqual(
            strategies["capital_heat"].analysis_skills,
            ["hot_theme", "emotion_cycle"],
        )

    def test_fresh_post_rank_context_includes_dsa_events(self) -> None:
        manager = Mock()
        manager.get_stock_name.return_value = "贵州茅台"
        news = {
            "success": True,
            "results": [{"title": "贵州茅台经营动态", "url": "https://example.com/news"}],
        }
        events = {
            "success": True,
            "results": [{"title": "贵州茅台发布年度报告", "url": "https://example.com/event"}],
        }
        candidate = {
            "code": "600519",
            "name": "贵州茅台",
            "dsa_context": {
                "quote": {"price": 1688.0},
                "fundamentals": {"pe_ttm": 24.5},
            },
        }

        with (
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=manager),
            patch("src.services.screening_service.search_dsa_stock_news", return_value=news),
            patch("src.services.screening_service.search_dsa_stock_events", return_value=events) as event_search,
        ):
            enriched = _build_dsa_candidate_context(candidate)

        event_search.assert_called_once_with("600519", "贵州茅台", max_results=3)
        self.assertEqual(enriched["dsa_events"][0]["title"], "贵州茅台发布年度报告")
        self.assertEqual(enriched["dsa_context"]["events"], events)
        self.assertIn("DSA事件", enriched["dsa_analysis_summary"])


if __name__ == "__main__":
    unittest.main()
