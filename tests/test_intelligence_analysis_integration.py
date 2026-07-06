# -*- coding: utf-8 -*-
"""Tests for using persisted intelligence in analysis contexts."""

from __future__ import annotations

from dataclasses import replace
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from src.config import Config, get_config
from src.core.pipeline import StockAnalysisPipeline
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview
from src.repositories.intelligence_repo import IntelligenceRepository
from src.storage import DatabaseManager


class PersistedIntelligenceAnalysisIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._temp_dir.name, "intel_analysis.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        self.config = get_config()
        repo = IntelligenceRepository()
        now = datetime.now()
        repo.upsert_items([
            {
                "source_name": "symbol-feed",
                "source_type": "rss",
                "title": "Company wins major AI order",
                "summary": "Order expands visibility for next quarter.",
                "url": "https://news.example.com/symbol",
                "source": "symbol-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "600519",
                "market": "cn",
            },
            {
                "source_name": "market-feed",
                "source_type": "rss",
                "title": "Policy support lifts market sentiment",
                "summary": "Market-level catalyst.",
                "url": "https://news.example.com/market",
                "source": "market-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "market",
                "scope_value": None,
                "market": "cn",
            },
        ])

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config._instance = None
        os.environ.pop("DATABASE_PATH", None)
        self._temp_dir.cleanup()

    def test_pipeline_loads_persisted_symbol_and_market_intelligence(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self.config
        context = pipeline._load_persisted_intelligence_context(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
        )
        self.assertIsNotNone(context)
        assert context is not None
        self.assertIn("本地资讯证据池", context)
        self.assertIn("Company wins major AI order", context)
        self.assertIn("https://news.example.com/symbol", context)

    def test_pipeline_refreshes_auto_sources_before_loading_local_intelligence(self) -> None:
        self.config.news_intel_auto_fetch_enabled = True
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self.config

        with patch("src.core.pipeline.IntelligenceService.refresh_auto_sources", return_value={"ok": True}) as refresh:
            context = pipeline._load_persisted_intelligence_context(
                code="600519",
                stock_name="贵州茅台",
                market="cn",
            )

        refresh.assert_called_once()
        self.assertIsNotNone(context)

    def test_pipeline_refreshes_auto_sources_with_pipeline_config(self) -> None:
        self.config.news_intel_auto_fetch_enabled = True
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = replace(self.config, news_intel_auto_fetch_enabled=False)

        with patch("src.core.pipeline.IntelligenceService") as service_cls:
            service = service_cls.return_value
            service.refresh_auto_sources.return_value = {"ok": True}
            service.list_items.return_value = {"items": [], "total": 0}
            context = pipeline._load_persisted_intelligence_context(
                code="600519",
                stock_name="贵州茅台",
                market="cn",
            )

        service_cls.assert_called_once_with(config=pipeline.config)
        self.assertIsNone(context)

    def test_pipeline_loads_symbol_intelligence_with_exchange_alias_scope(self) -> None:
        repo = IntelligenceRepository()
        now = datetime.now()
        repo.upsert_items([
            {
                "source_name": "symbol-feed",
                "source_type": "rss",
                "title": "SH-prefixed symbol feed",
                "summary": "Prefixed source should match normalized analysis code.",
                "url": "https://news.example.com/symbol-sh-prefix",
                "source": "symbol-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "SH600519",
                "market": "cn",
            },
            {
                "source_name": "symbol-feed",
                "source_type": "rss",
                "title": "SH-suffixed symbol feed",
                "summary": "Suffixed source should match normalized analysis code.",
                "url": "https://news.example.com/symbol-sh-suffix",
                "source": "symbol-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "600519.SH",
                "market": "cn",
            },
        ])

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self.config
        context = pipeline._load_persisted_intelligence_context(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
        )

        self.assertIsNotNone(context)
        assert context is not None
        self.assertIn("SH-prefixed symbol feed", context)
        self.assertIn("SH-suffixed symbol feed", context)

    def test_pipeline_loads_hk_symbol_intelligence_with_plain_code_scope(self) -> None:
        repo = IntelligenceRepository()
        now = datetime.now()
        repo.upsert_items([
            {
                "source_name": "hk-symbol-feed",
                "source_type": "rss",
                "title": "Plain HK code symbol feed",
                "summary": "Plain five-digit HK source should match canonical and suffixed analysis codes.",
                "url": "https://news.example.com/hk-plain-code",
                "source": "hk-symbol-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "00700",
                "market": "hk",
            },
            {
                "source_name": "hk-trimmed-symbol-feed",
                "source_type": "rss",
                "title": "Trimmed HK code symbol feed",
                "summary": "Trimmed HK source should match canonical analysis code.",
                "url": "https://news.example.com/hk-trimmed-code",
                "source": "hk-trimmed-symbol-feed",
                "published_at": now,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "HK700",
                "market": "hk",
            },
        ])

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self.config
        for code in ("HK00700", "00700.HK"):
            with self.subTest(code=code):
                context = pipeline._load_persisted_intelligence_context(
                    code=code,
                    stock_name="腾讯控股",
                    market="hk",
                )

                self.assertIsNotNone(context)
                assert context is not None
                self.assertIn("Plain HK code symbol feed", context)
                self.assertIn("Trimmed HK code symbol feed", context)

    def test_market_review_merges_persisted_market_intelligence(self) -> None:
        analyzer = MarketAnalyzer(config=self.config, region="cn")
        merged = analyzer._merge_persisted_market_intelligence([])
        self.assertTrue(any(item.get("title") == "Policy support lifts market sentiment" for item in merged))
        item = next(item for item in merged if item.get("title") == "Policy support lifts market sentiment")
        self.assertEqual(item["snippet"], "Market-level catalyst.")
        self.assertEqual(item["url"], "https://news.example.com/market")

    def test_market_review_refreshes_auto_sources_before_merging_local_intelligence(self) -> None:
        self.config.news_intel_auto_fetch_enabled = True
        analyzer = MarketAnalyzer(config=self.config, region="cn")

        with patch("src.market_analyzer.IntelligenceService.refresh_auto_sources", return_value={"ok": True}) as refresh:
            merged = analyzer._merge_persisted_market_intelligence([])

        refresh.assert_called_once()
        self.assertTrue(any(item.get("title") == "Policy support lifts market sentiment" for item in merged))

    def test_market_review_refreshes_auto_sources_with_analyzer_config(self) -> None:
        self.config.news_intel_auto_fetch_enabled = True
        analyzer = MarketAnalyzer(config=replace(self.config, news_intel_auto_fetch_enabled=False), region="cn")

        with patch("src.market_analyzer.IntelligenceService") as service_cls:
            service = service_cls.return_value
            service.refresh_auto_sources.return_value = {"ok": True}
            service.list_items.return_value = {"items": [], "total": 0}
            merged = analyzer._merge_persisted_market_intelligence([])

        service_cls.assert_called_once_with(config=analyzer.config)
        self.assertEqual(merged, [])

    def test_market_review_local_intelligence_kept_in_top_payload_when_search_news_filled(self) -> None:
        analyzer = MarketAnalyzer(config=self.config, region="cn")
        search_news = [
            {
                "title": f"Search headline {i}",
                "snippet": f"Search summary {i}",
                "source": "search-source",
                "published_date": "2026-06-17",
                "url": f"https://news.example.com/search/{i}",
            }
            for i in range(8)
        ]

        merged = analyzer._merge_persisted_market_intelligence(search_news)
        self.assertEqual(merged[0]["title"], "Policy support lifts market sentiment")

        payload = analyzer.build_market_review_payload(
            MarketOverview(
                date="2026-06-17",
                indices=[
                    MarketIndex(
                        code="000001",
                        name="SSE Composite",
                        current=3200.0,
                        change=10.0,
                        change_pct=0.25,
                    )
                ],
            ),
            news=merged,
            report="复盘正文",
            market_light_snapshot={"dimensions": {"breadth": {"available": True}}},
        )
        self.assertEqual(payload["news"][0]["url"], "https://news.example.com/market")
        self.assertGreaterEqual(len(payload["news"]), 1)

    def test_market_review_keeps_search_news_when_local_pool_is_full(self) -> None:
        repo = IntelligenceRepository()
        now = datetime.now()
        for index in range(5):
            repo.upsert_items([
                {
                    "source_name": f"market-local-{index}",
                    "source_type": "rss",
                    "title": f"Market local headline {index}",
                    "summary": f"Local market signal {index}",
                    "url": f"https://news.example.com/market-local/{index}",
                    "source": f"market-local-{index}",
                    "published_at": now + timedelta(minutes=index + 1),
                    "fetched_at": now + timedelta(minutes=index + 1),
                    "scope_type": "market",
                    "scope_value": None,
                    "market": "cn",
                }
            ])

        analyzer = MarketAnalyzer(config=self.config, region="cn")
        search_news = [
            {
                "title": f"Search headline {i}",
                "snippet": f"Search summary {i}",
                "source": "search-source",
                "published_date": "2026-06-17",
                "url": f"https://news.example.com/search/{i}",
            }
            for i in range(8)
        ]

        merged = analyzer._merge_persisted_market_intelligence(search_news)
        first_six = merged[:6]
        local_count = len([item for item in first_six if str(item.get("title", "")).startswith("Market local headline")])
        search_count = len([item for item in first_six if str(item.get("title", "")).startswith("Search headline")])
        self.assertEqual(local_count, 3)
        self.assertEqual(search_count, 3)

        prompt = analyzer._build_review_prompt(
            MarketOverview(date="2026-06-17"),
            merged,
        )
        self.assertIn("Search headline 0", prompt)

        payload = analyzer.build_market_review_payload(
            MarketOverview(
                date="2026-06-17",
                indices=[
                    MarketIndex(
                        code="000001",
                        name="SSE Composite",
                        current=3200.0,
                        change=10.0,
                        change_pct=0.25,
                    )
                ],
            ),
            news=merged,
            report="复盘正文",
            market_light_snapshot={"dimensions": {"breadth": {"available": True}}},
        )
        self.assertGreaterEqual(len(payload["news"]), 8)
        self.assertEqual(sum(item["title"].startswith("Search headline") for item in payload["news"][0:8]), 4)

    def test_analysis_evidence_excludes_missing_or_stale_publish_time(self) -> None:
        self.config.news_max_age_days = 30
        self.config.news_strategy_profile = "short"
        repo = IntelligenceRepository()
        now = datetime.now()
        old_time = now - timedelta(days=5)
        repo.upsert_items([
            {
                "source_name": "symbol-feed",
                "source_type": "rss",
                "title": "Stale symbol item fetched today",
                "summary": "Old publication date should not be prompt evidence.",
                "url": "https://news.example.com/stale-symbol",
                "source": "symbol-feed",
                "published_at": old_time,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "600519",
                "market": "cn",
            },
            {
                "source_name": "symbol-feed",
                "source_type": "rss",
                "title": "Undated symbol item fetched today",
                "summary": "Missing publication date should not be prompt evidence.",
                "url": "https://news.example.com/undated-symbol",
                "source": "symbol-feed",
                "published_at": None,
                "fetched_at": now,
                "scope_type": "symbol",
                "scope_value": "600519",
                "market": "cn",
            },
            {
                "source_name": "market-feed",
                "source_type": "rss",
                "title": "Stale market item fetched today",
                "summary": "Old market publication date should not be prompt evidence.",
                "url": "https://news.example.com/stale-market",
                "source": "market-feed",
                "published_at": old_time,
                "fetched_at": now,
                "scope_type": "market",
                "scope_value": None,
                "market": "cn",
            },
            {
                "source_name": "market-feed",
                "source_type": "rss",
                "title": "Undated market item fetched today",
                "summary": "Missing market publication date should not be prompt evidence.",
                "url": "https://news.example.com/undated-market",
                "source": "market-feed",
                "published_at": None,
                "fetched_at": now,
                "scope_type": "market",
                "scope_value": None,
                "market": "cn",
            },
        ])

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self.config
        context = pipeline._load_persisted_intelligence_context(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
        )
        assert context is not None
        self.assertIn("Company wins major AI order", context)
        self.assertNotIn("Stale symbol item fetched today", context)
        self.assertNotIn("Undated symbol item fetched today", context)
        self.assertNotIn("Stale market item fetched today", context)
        self.assertNotIn("Undated market item fetched today", context)

        analyzer = MarketAnalyzer(config=self.config, region="cn")
        merged = analyzer._merge_persisted_market_intelligence([])
        titles = {item.get("title") for item in merged}
        self.assertIn("Policy support lifts market sentiment", titles)
        self.assertNotIn("Stale market item fetched today", titles)
        self.assertNotIn("Undated market item fetched today", titles)


if __name__ == "__main__":
    unittest.main()
