# -*- coding: utf-8 -*-
"""Regression tests for pipeline-level related board enrichment."""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from api.v1.schemas.history import ReportDetails
from data_provider.base import DataFetcherManager
from src.core.pipeline import StockAnalysisPipeline
from src.services.market_hotspot_service import MarketHotspotService
from src.services.market_structure_service import MarketStructureService
from src.utils.data_processing import (
    extract_board_detail_fields,
    extract_market_structure_detail_field,
)


class _SlowConceptRankingFetcher:
    name = "SlowConceptRankingFetcher"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def get_concept_rankings(self, n: int = 5):
        with self._lock:
            self.calls += 1
        time.sleep(0.05)
        return (
            [{"name": f"top-{n}", "change_pct": 1.2}],
            [{"name": f"bottom-{n}", "change_pct": -0.8}],
        )


class _HangingConceptRankingFetcher:
    def __init__(self, delay_seconds: float = 0.5) -> None:
        self.calls = 0
        self.delay_seconds = delay_seconds

    def get_concept_rankings(self, n: int = 5):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return (
            [{"name": f"top-{n}", "change_pct": 1.0}],
            [{"name": f"bottom-{n}", "change_pct": -1.0}],
        )


class PipelineRelatedBoardsTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        DataFetcherManager.clear_concept_rankings_cache_for_tests()

    def test_attach_belong_boards_shallow_copies_context_before_injecting(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "白酒", "type": "行业"}]

        cached_context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", cached_context)

        self.assertIsNot(enriched, cached_context)
        self.assertNotIn("belong_boards", cached_context)
        self.assertEqual(enriched["belong_boards"], [{"name": "白酒", "type": "行业"}])

    def test_attach_belong_boards_adds_concept_rankings_for_cn(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "机器人概念", "type": "概念"}]
        pipeline.fetcher_manager.get_concept_rankings.return_value = (
            [{"name": "机器人概念", "change_pct": 4.2}],
            [{"name": "转基因", "change_pct": -2.05}],
        )

        context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertEqual(enriched["concept_boards"]["data"]["top"][0]["name"], "机器人概念")
        self.assertEqual(enriched["concept_boards"]["data"]["bottom"][0]["change_pct"], -2.05)

    def test_attach_belong_boards_reuses_concept_rankings_per_pipeline_run(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.side_effect = [
            [{"name": "Robot Theme", "type": "concept"}],
            [{"name": "AI Theme", "type": "concept"}],
        ]
        pipeline.fetcher_manager.get_concept_rankings.return_value = (
            [{"name": "Robot Theme", "change_pct": 4.2}],
            [{"name": "Chip Theme", "change_pct": -2.05}],
        )

        context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        first = pipeline._attach_belong_boards_to_fundamental_context("600519", context)
        second = pipeline._attach_belong_boards_to_fundamental_context("000001", context)

        pipeline.fetcher_manager.get_concept_rankings.assert_called_once_with(5)
        self.assertEqual(first["concept_boards"]["data"]["top"][0]["name"], "Robot Theme")
        self.assertEqual(second["concept_boards"]["data"]["top"][0]["name"], "Robot Theme")

    def test_empty_concept_rankings_are_reused_by_market_structure_builds(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.side_effect = [
            [{"name": "Robot Theme", "type": "concept"}],
            [{"name": "AI Theme", "type": "concept"}],
        ]
        pipeline.fetcher_manager.get_concept_rankings.return_value = ([], [])

        context = {
            "market": "cn",
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {
                "status": "ok",
                "data": {
                    "top": [{"name": "Technology", "change_pct": 1.2}],
                    "bottom": [],
                },
            },
        }

        first = pipeline._attach_belong_boards_to_fundamental_context("600519", context)
        second = pipeline._attach_belong_boards_to_fundamental_context("000001", context)

        self.assertEqual(first["concept_boards"]["status"], "partial")
        self.assertEqual(first["concept_boards"]["data"]["top"], [])
        self.assertTrue(first["concept_boards"]["data"]["fetch_attempted"])
        self.assertEqual(
            extract_board_detail_fields(
                {"fundamental_context": first}
            )["concept_rankings"],
            {"top": [], "bottom": [], "status": "partial"},
        )

        market_structure_service = MarketStructureService(
            fetcher_manager=pipeline.fetcher_manager,
        )
        market_structure_service.build_context(
            code="600519",
            stock_name="First",
            market="cn",
            fundamental_context=first,
        )
        market_structure_service.build_context(
            code="000001",
            stock_name="Second",
            market="cn",
            fundamental_context=second,
        )

        pipeline.fetcher_manager.get_concept_rankings.assert_called_once_with(5)

    def test_get_concept_rankings_for_market_no_long_block_with_hanging_fetcher(self) -> None:
        fetcher = _HangingConceptRankingFetcher()
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = fetcher
        pipeline.market_hotspot_service = MarketHotspotService(
            fetcher_manager=fetcher,
            ranking_fetch_timeout_seconds=0.05,
        )
        pipeline._concept_rankings_cache = {}
        pipeline._concept_rankings_cache_lock = threading.Lock()

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(pipeline._get_concept_rankings_for_market, "cn")
            second = executor.submit(pipeline._get_concept_rankings_for_market, "cn")
            first_result = first.result()
            second_result = second.result()

        duration = time.perf_counter() - start
        self.assertLess(duration, 0.30)
        self.assertEqual(first_result, ([], []))
        self.assertEqual(second_result, ([], []))
        self.assertGreaterEqual(fetcher.calls, 1)

    def test_concept_rankings_cache_is_shared_across_manager_instances(self) -> None:
        fetcher = _SlowConceptRankingFetcher()
        first_manager = DataFetcherManager.__new__(DataFetcherManager)
        first_manager._fetchers = [fetcher]
        second_manager = DataFetcherManager.__new__(DataFetcherManager)
        second_manager._fetchers = [fetcher]

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_result, second_result = list(
                executor.map(
                    lambda manager: manager.get_concept_rankings(5),
                    [first_manager, second_manager],
                )
            )

        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(first_result, second_result)

        first_result[0][0]["name"] = "mutated"
        fresh_result = second_manager.get_concept_rankings(5)

        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(fresh_result[0][0]["name"], "top-5")

    def test_extract_board_details_exposes_concept_rankings(self) -> None:
        snapshot = {
            "fundamental_context": {
                "belong_boards": [{"name": "机器人概念", "type": "概念"}],
                "concept_boards": {
                    "status": "ok",
                    "data": {
                        "top": [{"name": "机器人概念", "change_pct": "4.2%", "source": "akshare"}],
                        "bottom": [],
                    },
                },
            },
        }

        extracted = extract_board_detail_fields(snapshot)
        details = ReportDetails(context_snapshot=snapshot)

        self.assertEqual(extracted["concept_rankings"]["top"][0]["name"], "机器人概念")
        self.assertEqual(extracted["concept_rankings"]["top"][0]["change_pct"], 4.2)
        self.assertEqual(extracted["concept_rankings"]["top"][0]["source"], "akshare")
        self.assertEqual(details.concept_rankings["top"][0]["name"], "机器人概念")

    def test_extract_market_structure_details_from_enhanced_context(self) -> None:
        snapshot = {
            "enhanced_context": {
                "market_structure_context": {
                    "schema_version": "market-structure-v1",
                    "status": "partial",
                    "market": "cn",
                    "market_theme_context": {
                        "schema_version": "market-theme-v1",
                        "status": "partial",
                        "market": "cn",
                        "active_themes": [{"name": "机器人概念"}],
                    },
                    "stock_market_position": {
                        "schema_version": "stock-market-position-v1",
                        "status": "partial",
                        "stock_code": "300024",
                        "market": "cn",
                        "primary_theme": {"name": "机器人概念"},
                    },
                }
            }
        }

        extracted = extract_market_structure_detail_field(snapshot)
        details = ReportDetails(context_snapshot=snapshot)

        self.assertEqual(extracted["stock_market_position"]["primary_theme"]["name"], "机器人概念")
        self.assertEqual(details.market_structure["market_theme_context"]["active_themes"][0]["name"], "机器人概念")

    def test_extract_market_structure_details_from_raw_result_fallback(self) -> None:
        payload = {
            "schema_version": "market-structure-v1",
            "status": "partial",
            "market": "cn",
            "market_theme_context": {
                "schema_version": "market-theme-v1",
                "status": "partial",
                "market": "cn",
                "active_themes": [{"name": "机器人概念"}],
            },
            "stock_market_position": {
                "schema_version": "stock-market-position-v1",
                "status": "partial",
                "stock_code": "300024",
                "market": "cn",
                "primary_theme": {"name": "机器人概念"},
            },
        }

        extracted = extract_market_structure_detail_field(
            None,
            {"market_structure_context": payload},
        )
        details = ReportDetails(raw_result={"market_structure_context": payload})

        self.assertEqual(extracted["stock_market_position"]["primary_theme"]["name"], "机器人概念")
        self.assertEqual(details.market_structure["market_theme_context"]["active_themes"][0]["name"], "机器人概念")

    def test_attach_belong_boards_copies_existing_board_list(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        existing_boards = [{"name": "白酒", "type": "行业"}]
        context = {
            "market": "cn",
            "status": "ok",
            "belong_boards": existing_boards,
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertIsNot(enriched, context)
        self.assertEqual(enriched["belong_boards"], existing_boards)
        self.assertIsNot(enriched["belong_boards"], existing_boards)
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_refetches_empty_cn_board_list(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "白酒", "type": "行业"}]

        context = {
            "market": "cn",
            "status": "ok",
            "belong_boards": [],
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertEqual(enriched["belong_boards"], [{"name": "白酒", "type": "行业"}])
        pipeline.fetcher_manager.get_belong_boards.assert_called_once_with("600519")

    def test_attach_belong_boards_skips_provider_for_non_cn(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        context = {"market": "us", "status": "not_supported"}
        enriched = pipeline._attach_belong_boards_to_fundamental_context("AAPL", context)

        self.assertEqual(enriched["belong_boards"], [])
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_preserves_adapter_boards_for_offshore(self) -> None:
        """HK/US adapters populate belong_boards from yfinance; pipeline must not clobber."""
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        existing_boards = [
            {"name": "Technology", "type": "行业"},
            {"name": "Consumer Electronics", "type": "概念"},
        ]
        context = {"market": "us", "status": "ok", "belong_boards": existing_boards}
        enriched = pipeline._attach_belong_boards_to_fundamental_context("AAPL", context)

        self.assertEqual(enriched["belong_boards"], existing_boards)
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_skips_provider_when_board_block_not_supported(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        context = {
            "market": "cn",
            "status": "partial",
            "coverage": {"boards": "not_supported"},
            "boards": {"status": "not_supported", "data": {}},
            "errors": ["etf not fully supported"],
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("159915", context)

        self.assertEqual(enriched["belong_boards"], [])
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_skips_provider_when_pipeline_disabled_payload(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        context = {
            "market": "cn",
            "status": "not_supported",
            "coverage": {"boards": "not_supported"},
            "boards": {"status": "not_supported", "data": {}},
            "errors": ["fundamental pipeline disabled"],
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("600519", context)

        self.assertEqual(enriched["belong_boards"], [])
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()

    def test_attach_belong_boards_uses_normalized_a_share_code_when_market_missing(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_belong_boards.return_value = [{"name": "白酒"}]

        context = {
            "status": "ok",
            "coverage": {"boards": "ok"},
            "boards": {"status": "ok", "data": {"top": [], "bottom": []}},
        }

        enriched = pipeline._attach_belong_boards_to_fundamental_context("SH600519", context)

        self.assertEqual(enriched["belong_boards"], [{"name": "白酒"}])
        pipeline.fetcher_manager.get_belong_boards.assert_called_once_with("SH600519")

if __name__ == "__main__":
    unittest.main()
