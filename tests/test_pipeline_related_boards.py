# -*- coding: utf-8 -*-
"""Regression tests for pipeline-level related board enrichment."""

import unittest
from unittest.mock import MagicMock

from src.core.pipeline import StockAnalysisPipeline


class PipelineRelatedBoardsTestCase(unittest.TestCase):
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

    def test_attach_belong_boards_skips_provider_for_non_cn(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()

        context = {"market": "us", "status": "not_supported"}
        enriched = pipeline._attach_belong_boards_to_fundamental_context("AAPL", context)

        self.assertEqual(enriched["belong_boards"], [])
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
