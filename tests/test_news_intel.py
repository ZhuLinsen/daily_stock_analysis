# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 新闻情报存储单元测试
===================================

职责：
1. 验证新闻情报的保存与去重逻辑
2. 验证无 URL 情况下的兜底去重键
"""

import os
import tempfile
import unittest

from datetime import datetime

from src.config import Config
from src.storage import DatabaseManager, NewsIntel
from src.search_service import SearchResponse, SearchResult


class NewsIntelStorageTestCase(unittest.TestCase):
    """新闻情报存储测试"""

    def setUp(self) -> None:
        """为每个用例初始化独立数据库"""
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_news_intel.db")
        os.environ["DATABASE_PATH"] = self._db_path

        # 重置配置与数据库单例，确保使用临时库
        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        """清理资源"""
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _build_response(self, results) -> SearchResponse:
        """构造 SearchResponse 快捷函数"""
        return SearchResponse(
            query="贵州茅台 最新消息",
            results=results,
            provider="Bocha",
            success=True,
        )

    def test_save_news_intel_with_url_dedup(self) -> None:
        """相同 URL 去重，仅保留一条记录"""
        result = SearchResult(
            title="茅台发布新产品",
            snippet="公司发布新品...",
            url="https://news.example.com/a",
            source="example.com",
            published_date="2025-01-02"
        )
        response = self._build_response([result])

        query_context = {
            "query_id": "task_001",
            "query_source": "bot",
            "requester_platform": "feishu",
            "requester_user_id": "u_123",
            "requester_user_name": "测试用户",
            "requester_chat_id": "c_456",
            "requester_message_id": "m_789",
            "requester_query": "/analyze 600519",
        }

        saved_first = self.db.save_news_intel(
            code="600519",
            name="贵州茅台",
            dimension="latest_news",
            query=response.query,
            response=response,
            query_context=query_context
        )
        saved_second = self.db.save_news_intel(
            code="600519",
            name="贵州茅台",
            dimension="latest_news",
            query=response.query,
            response=response,
            query_context=query_context
        )

        self.assertEqual(saved_first, 1)
        self.assertEqual(saved_second, 0)

        with self.db.get_session() as session:
            total = session.query(NewsIntel).count()
            row = session.query(NewsIntel).first()
        self.assertEqual(total, 1)
        if row is None:
            self.fail("未找到保存的新闻记录")
        self.assertEqual(row.query_id, "task_001")
        self.assertEqual(row.requester_user_name, "测试用户")

    def test_save_news_intel_without_url_fallback_key(self) -> None:
        """无 URL 时使用兜底键去重"""
        result = SearchResult(
            title="茅台业绩预告",
            snippet="业绩大幅增长...",
            url="",
            source="example.com",
            published_date="2025-01-03"
        )
        response = self._build_response([result])

        saved_first = self.db.save_news_intel(
            code="600519",
            name="贵州茅台",
            dimension="earnings",
            query=response.query,
            response=response
        )
        saved_second = self.db.save_news_intel(
            code="600519",
            name="贵州茅台",
            dimension="earnings",
            query=response.query,
            response=response
        )

        self.assertEqual(saved_first, 1)
        self.assertEqual(saved_second, 0)

        with self.db.get_session() as session:
            row = session.query(NewsIntel).first()
            if row is None:
                self.fail("未找到保存的新闻记录")
            self.assertTrue(row.url.startswith("no-url:"))

    def test_get_recent_news(self) -> None:
        """可按时间范围查询最新新闻"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = SearchResult(
            title="茅台股价震荡",
            snippet="盘中波动较大...",
            url="https://news.example.com/b",
            source="example.com",
            published_date=now
        )
        response = self._build_response([result])

        self.db.save_news_intel(
            code="600519",
            name="贵州茅台",
            dimension="market_analysis",
            query=response.query,
            response=response
        )

        recent_news = self.db.get_recent_news(code="600519", days=7, limit=10)
        self.assertEqual(len(recent_news), 1)
        self.assertEqual(recent_news[0].title, "茅台股价震荡")


if __name__ == "__main__":
    unittest.main()
