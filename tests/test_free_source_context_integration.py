# -*- coding: utf-8 -*-
"""Offline integration tests for free-source report context injection."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestFreeSourceStockContext(unittest.TestCase):
    def test_pipeline_builds_bounded_free_a_stock_context(self):
        from src.core.pipeline import StockAnalysisPipeline

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_free_announcements.return_value = [
            {
                "title": "年度报告",
                "date": "2026-07-30",
                "source": "cninfo",
                "pdf_url": "https://static.cninfo.com.cn/test.pdf",
            }
        ]
        pipeline.fetcher_manager.get_fallback_announcements.return_value = []
        pipeline.fetcher_manager.get_fallback_fund_flow.return_value = [
            {
                "date": "2026-07-29",
                "net_amount": 12345,
                "close": 1500.5,
                "turnover": 1.2,
            }
        ]

        text = pipeline._build_free_a_stock_intelligence_context("SH600519", "贵州茅台")

        self.assertIn("A股免费情报源补充", text)
        self.assertIn("年度报告", text)
        self.assertIn("免费资金流 fallback", text)
        self.assertIn("净额 12345", text)
        pipeline.fetcher_manager.get_fallback_announcements.assert_not_called()

    def test_pipeline_falls_back_to_announcement_fallback_when_cninfo_empty(self):
        from src.core.pipeline import StockAnalysisPipeline

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.get_free_announcements.return_value = []
        pipeline.fetcher_manager.get_fallback_announcements.return_value = [
            {"title": "交易所公告", "date": "2026-07-30", "source": "szse_announcement"}
        ]
        pipeline.fetcher_manager.get_fallback_fund_flow.return_value = []

        text = pipeline._build_free_a_stock_intelligence_context("000001", "平安银行")

        self.assertIn("交易所公告", text)
        pipeline.fetcher_manager.get_fallback_announcements.assert_called_once()


class TestFreeSourceMarketNews(unittest.TestCase):
    def test_market_analyzer_uses_free_news_without_search_service(self):
        from src.market_analyzer import MarketAnalyzer

        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "cn"
        analyzer.search_service = None
        analyzer.data_manager = MagicMock()
        analyzer.data_manager.get_free_market_news.return_value = [
            {
                "title": "财联社快讯",
                "content": "市场消息",
                "source": "cls",
                "time": "2026-07-30 10:00:00",
                "url": "https://www.cls.cn/detail/1",
            }
        ]

        news = analyzer.search_market_news()

        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]["title"], "财联社快讯")
        self.assertEqual(news[0]["source"], "cls")


    def test_market_analyzer_skips_search_when_free_news_available(self):
        from src.market_analyzer import MarketAnalyzer

        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "cn"
        analyzer.search_service = MagicMock()
        analyzer.data_manager = MagicMock()
        analyzer.data_manager.get_free_market_news.return_value = [
            {
                "title": "CLS flash",
                "content": "market message",
                "source": "cls",
                "time": "2026-07-30 10:00:00",
                "url": "https://www.cls.cn/detail/1",
            }
        ]

        news = analyzer.search_market_news()

        self.assertEqual(len(news), 1)
        analyzer.search_service.search_stock_news.assert_not_called()


if __name__ == "__main__":
    unittest.main()
