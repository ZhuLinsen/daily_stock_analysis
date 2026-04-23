# -*- coding: utf-8 -*-
"""
===================================
get_latest_data 测试
===================================

职责：
1. 验证 get_latest_data 方法
2. 测试返回数据按日期降序排列
3. 测试 days 参数限制
"""

import os
import tempfile
import unittest
from datetime import date, timedelta

import pandas as pd

from src.config import Config
from src.storage import DatabaseManager, StockDaily


class GetLatestDataTestCase(unittest.TestCase):
    """get_latest_data 方法测试"""

    def setUp(self) -> None:
        """Initialize an isolated database for each test case."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_get_latest_data.db")
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        """Clean up resources."""
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _insert_stock_data(self, code: str, days_ago: int, close: float) -> None:
        """插入测试用股票数据"""
        target_date = date.today() - timedelta(days=days_ago)
        df = pd.DataFrame([{
            'date': target_date,
            'open': close - 1,
            'high': close + 1,
            'low': close - 2,
            'close': close,
            'volume': 1000000,
            'amount': 10000000,
            'pct_chg': 1.5,
        }])
        self.db.save_daily_data(df, code, data_source="TestData")

    def test_get_latest_data_returns_empty_when_no_data(self) -> None:
        """无数据时返回空列表"""
        result = self.db.get_latest_data("999999", days=2)
        self.assertEqual(result, [])

    def test_get_latest_data_returns_correct_count(self) -> None:
        """返回正确数量的数据"""
        # 插入5天数据
        for i in range(5):
            self._insert_stock_data("600519", days_ago=i, close=100.0 + i)

        # 请求2天数据
        result = self.db.get_latest_data("600519", days=2)
        self.assertEqual(len(result), 2)

        # 请求5天数据
        result = self.db.get_latest_data("600519", days=5)
        self.assertEqual(len(result), 5)

    def test_get_latest_data_ordered_by_date_desc(self) -> None:
        """验证数据按日期降序排列"""
        # 插入3天数据
        for i in range(3):
            self._insert_stock_data("600519", days_ago=i, close=100.0 + i)

        result = self.db.get_latest_data("600519", days=3)

        # 验证日期降序（最新日期在前）
        self.assertEqual(len(result), 3)
        self.assertGreater(result[0].date, result[1].date)
        self.assertGreater(result[1].date, result[2].date)

    def test_get_latest_data_filters_by_code(self) -> None:
        """验证按股票代码过滤"""
        # 插入不同股票的数据
        self._insert_stock_data("600519", days_ago=0, close=100.0)
        self._insert_stock_data("000001", days_ago=0, close=50.0)

        result = self.db.get_latest_data("600519", days=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, "600519")

    def test_save_daily_data_batch_upsert_updates_existing_rows_and_keeps_insert_count(self) -> None:
        base_date = date(2026, 1, 2)
        first_batch = pd.DataFrame(
            [
                {
                    "date": base_date,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1000.0,
                    "amount": 100000.0,
                    "pct_chg": 0.5,
                    "ma5": 98.0,
                },
                {
                    "date": base_date + timedelta(days=1),
                    "open": 101.0,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.0,
                    "volume": 1100.0,
                    "amount": 111000.0,
                    "pct_chg": 1.0,
                    "ma5": 99.0,
                },
            ]
        )
        second_batch = pd.DataFrame(
            [
                {
                    "date": base_date,
                    "open": 120.0,
                    "high": 121.0,
                    "low": 119.0,
                    "close": 120.0,
                    "volume": 2200.0,
                    "amount": 264000.0,
                    "pct_chg": 2.0,
                    "ma5": 110.0,
                    "volume_ratio": 1.8,
                },
                {
                    "date": base_date + timedelta(days=1),
                    "open": 121.0,
                    "high": 122.0,
                    "low": 120.0,
                    "close": 121.0,
                    "volume": 2300.0,
                    "amount": 278300.0,
                    "pct_chg": 1.5,
                    "ma5": 111.0,
                    "volume_ratio": 1.6,
                },
                {
                    "date": base_date + timedelta(days=2),
                    "open": 122.0,
                    "high": 123.0,
                    "low": 121.0,
                    "close": 122.0,
                    "volume": 2400.0,
                    "amount": 292800.0,
                    "pct_chg": 1.2,
                    "ma5": 112.0,
                    "volume_ratio": 1.4,
                },
            ]
        )

        saved_first = self.db.save_daily_data(first_batch, "600519", data_source="batch-1")
        saved_second = self.db.save_daily_data(second_batch, "600519", data_source="batch-2")

        self.assertEqual(saved_first, 2)
        self.assertEqual(saved_second, 1)

        rows = self.db.get_latest_data("600519", days=5)
        by_date = {row.date: row for row in rows}

        self.assertEqual(len(by_date), 3)
        self.assertAlmostEqual(by_date[base_date].close, 120.0, places=6)
        self.assertAlmostEqual(by_date[base_date].volume_ratio or 0.0, 1.8, places=6)
        self.assertEqual(by_date[base_date].data_source, "batch-2")
        self.assertAlmostEqual(by_date[base_date + timedelta(days=2)].close, 122.0, places=6)


if __name__ == "__main__":
    unittest.main()
