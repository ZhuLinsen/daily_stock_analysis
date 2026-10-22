# -*- coding: utf-8 -*-
"""Unit tests for the DeepSeek Search provider (https://api.deepseek.com/v1/tools/search)."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import DeepSeekSearchProvider, SearchService


def _response(status_code=200, json_payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = {} if json_payload is None else json_payload
    return resp


class TestDeepSeekSearchProvider(unittest.TestCase):
    def _provider(self):
        return DeepSeekSearchProvider(["sk-test"])

    def test_query_gets_after_before_window(self):
        provider = self._provider()
        query = provider._build_query("海峡创新 300300", days=7)
        today = datetime.now().date()
        earliest = today - timedelta(days=6)
        self.assertIn(f"after:{earliest.isoformat()}", query)
        self.assertIn(f"before:{today.isoformat()}", query)

    def test_overlong_query_skips_date_window(self):
        provider = self._provider()
        long_query = "海" * 128
        self.assertEqual(provider._build_query(long_query, days=7), long_query)

    def test_utc_date_converted_to_beijing_date(self):
        provider = self._provider()
        # 2026-10-21T16:00:00Z == 2026-10-22 00:00 北京时间
        self.assertEqual(
            provider._to_local_date("2026-10-21T16:00:00+00:00"), "2026-10-22"
        )
        self.assertIsNone(provider._to_local_date(None))

    @patch("src.search_service._post_with_retry")
    def test_response_mapping_dedupes_and_skips_incomplete_items(self, mock_post):
        mock_post.return_value = _response(
            json_payload={
                "results": [
                    {
                        "title": "海峡创新中标智慧城市项目",
                        "url": "https://news.example.com/a",
                        "snippet": "短摘要",
                        "summary": "长摘要内容，给模型阅读。",
                        "site_name": "证券时报",
                        "date": "2026-10-21T16:00:00+00:00",
                    },
                    {
                        "title": "重复链接",
                        "url": "https://news.example.com/a",
                        "summary": "重复",
                        "date": None,
                    },
                    {"title": "无链接", "url": "", "summary": "x"},
                ]
            }
        )
        provider = self._provider()
        resp = provider._do_search("海峡创新 300300", "sk-test", 10, days=7)
        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "DeepSeek")
        self.assertEqual(len(resp.results), 1)
        item = resp.results[0]
        self.assertEqual(item.title, "海峡创新中标智慧城市项目")
        self.assertEqual(item.snippet, "长摘要内容，给模型阅读。")
        self.assertEqual(item.source, "证券时报")
        self.assertEqual(item.published_date, "2026-10-22")
        # query 已带 after/before，count 透传
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["count"], 10)
        self.assertIn("after:", payload["query"])

    @patch("src.search_service._post_with_retry")
    def test_http_402_reports_balance_error(self, mock_post):
        mock_post.return_value = _response(
            status_code=402,
            json_payload={"error": {"message": "Insufficient Balance"}},
        )
        resp = self._provider()._do_search("query", "sk-test", 5, days=7)
        self.assertFalse(resp.success)
        self.assertIn("余额不足", resp.error_message)

    @patch("src.search_service._post_with_retry")
    def test_search_stock_news_prefers_deepseek_provider(self, mock_post):
        now_utc = datetime.now(timezone.utc).isoformat()
        today_local = DeepSeekSearchProvider._to_local_date(now_utc)
        mock_post.return_value = _response(
            json_payload={
                "results": [
                    {
                        "title": "海峡创新 智慧城市 中标公告",
                        "url": "https://news.example.com/300300",
                        "summary": "公司公告中标智慧城市项目，合同金额约 1 亿元。",
                        "site_name": "证券时报",
                        "date": now_utc,
                    }
                ]
            }
        )
        service = SearchService(
            deepseek_search_keys=["sk-test"],
            searxng_base_urls=["http://127.0.0.1:8888"],
            news_max_age_days=7,
            news_strategy_profile="medium",
        )
        # DeepSeek 必须排在首位
        self.assertIsInstance(service._providers[0], DeepSeekSearchProvider)
        resp = service.search_stock_news("300300", "海峡创新", max_results=3)
        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "DeepSeek")
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].published_date, today_local)

    @patch("src.search_service._post_with_retry")
    def test_quote_pages_dropped_for_any_provider(self, mock_post):
        """DeepSeek 也会返回行情页，准入阶段必须按统一规则剔除。"""
        now_utc = datetime.now(timezone.utc).isoformat()
        mock_post.return_value = _response(
            json_payload={
                "results": [
                    {
                        "title": "海峡创新（300300）行情走势",
                        "url": "https://quote.example.com/300300",
                        "summary": "行情页",
                        "date": now_utc,
                    },
                    {
                        "title": "海峡创新中标的智慧城市项目正式落地",
                        "url": "https://news.example.com/300300-news",
                        "summary": "公司公告智慧城市项目落地。",
                        "site_name": "证券时报",
                        "date": now_utc,
                    },
                ]
            }
        )
        service = SearchService(
            deepseek_search_keys=["sk-test"],
            news_max_age_days=7,
            news_strategy_profile="medium",
        )
        resp = service.search_stock_news("300300", "海峡创新", max_results=3)
        self.assertEqual(resp.provider, "DeepSeek")
        self.assertEqual(len(resp.results), 1)
        self.assertNotIn("行情走势", resp.results[0].title)

    @patch("src.search_service._post_with_retry")
    def test_quote_page_url_patterns_are_dropped(self, mock_post):
        """标题只有「名称(代码)」的数据中心页靠 URL 识别并剔除。"""
        now_utc = datetime.now(timezone.utc).isoformat()
        mock_post.return_value = _response(
            json_payload={
                "results": [
                    {
                        "title": "海峡创新(300300)",
                        "url": "https://data.eastmoney.com/stockcomment/stock/300300.html",
                        "summary": "千股千评",
                        "date": now_utc,
                    },
                    {
                        "title": "海峡创新与某央企签署智慧城市框架协议",
                        "url": "https://news.example.com/300300-deal",
                        "summary": "公司签署框架协议。",
                        "site_name": "证券时报",
                        "date": now_utc,
                    },
                ]
            }
        )
        service = SearchService(
            deepseek_search_keys=["sk-test"],
            news_max_age_days=7,
            news_strategy_profile="medium",
        )
        resp = service.search_stock_news("300300", "海峡创新", max_results=3)
        self.assertEqual(len(resp.results), 1)
        self.assertIn("框架协议", resp.results[0].title)


if __name__ == "__main__":
    unittest.main()
