# -*- coding: utf-8 -*-
"""
issue #1661 — GET /api/v1/history/daily 集成测试（G1a 方案一重组版）

首页历史区日期回看：
- 日期口径 = 北京时间（Asia/Shanghai）的分析生成日期（非服务器本地日期、非交易日）
- 列表轻量化：每股一行（当日最新一份），无价位字段，含当日份数 analysis_count
- 代码变体合并（002460 / 002460.SZ → 一行）
- is_latest 时效性（False = 已有更新）
- 点开即当时报告：GET /api/v1/history/{record_id} 按主键返回当时那份

范式照 tests/test_alert_api.py：
unittest.TestCase + FastAPI TestClient + DatabaseManager.reset_instance() + 真实 SQLite。
时区断言与测试机本地时区无关：边界记录一律相对 shanghai_day_bounds_local() 注入。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.report_language import get_sentiment_label
from src.services.history_service import HistoryService
from src.storage import AnalysisHistory, DatabaseManager

QUERY_DATE = date(2026, 10, 20)
QUERY_DATE_TEXT = "2026-10-20"

# 轻量契约：价位字段（ideal_buy 等）不得出现在列表行（spec 1：价位放报告详情）
DAILY_CONTRACT_KEYS = {
    "id",
    "code",
    "name",
    "report_type",
    "sentiment_score",
    "sentiment_label",
    "operation_advice",
    "action",
    "action_label",
    "trend_prediction",
    "is_latest",
    "analysis_count",
    "created_at",
}
FORBIDDEN_LIST_KEYS = {"ideal_buy", "secondary_buy", "stop_loss", "take_profit"}


class HistoryDailyApiTestCase(unittest.TestCase):
    """GET /api/v1/history/daily 契约测试（issue #1661 G1a）"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.db_path = self.data_dir / "history_daily_test.db"
        self.env_path = self.data_dir / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,002460",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    f"DATABASE_PATH={self.db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        app = create_app(static_dir=self.data_dir / "empty-static")
        self.client = TestClient(app)
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _add_history(self, code: str, created_at: datetime, **kwargs) -> int:
        """直接构造 AnalysisHistory 以注入指定 created_at（save_analysis_history 固定 now）。"""
        record = AnalysisHistory(
            code=code,
            name=kwargs.get("name", "测试股"),
            report_type=kwargs.get("report_type", "detailed"),
            sentiment_score=kwargs.get("sentiment_score", 75),
            operation_advice=kwargs.get("operation_advice", "持有"),
            trend_prediction=kwargs.get("trend_prediction", "看多"),
            query_id=kwargs.get("query_id", f"test-q-{code}-{int(created_at.timestamp())}"),
            raw_result=kwargs.get("raw_result"),
            created_at=created_at,
        )
        with self.db.get_session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return int(record.id or 0)

    def _get_daily(self, **params):
        query = {"date": QUERY_DATE_TEXT}
        query.update(params)
        return self.client.get("/api/v1/history/daily", params=query)

    # ------------------------------------------------------------------
    # 契约：轻量行
    # ------------------------------------------------------------------

    def test_daily_list_is_lightweight_without_price_fields(self) -> None:
        """spec 1：每股一行轻量字段，无价位列，字段缺失自适应（score 缺失 label 为 null）。"""
        bounds_start, _bounds_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history(
            "600519",
            bounds_start + timedelta(minutes=30),
            name="贵州茅台",
            sentiment_score=82,
        )
        # 无评分记录：sentiment_label 必须为 null（不落回 0 分标签）
        self._add_history(
            "000001",
            bounds_start + timedelta(minutes=10),
            name="平安银行",
            sentiment_score=None,
            operation_advice=None,
            trend_prediction=None,
        )

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual(len(payload["items"]), 2)

        for item in payload["items"]:
            self.assertEqual(set(item.keys()), DAILY_CONTRACT_KEYS)
            self.assertFalse(FORBIDDEN_LIST_KEYS & set(item.keys()))

        by_code = {item["code"]: item for item in payload["items"]}
        self.assertEqual(by_code["600519"]["name"], "贵州茅台")
        self.assertEqual(by_code["600519"]["sentiment_label"], "极度乐观")
        self.assertIsNone(by_code["000001"]["sentiment_label"])
        self.assertIsNone(by_code["000001"]["operation_advice"])

    # ------------------------------------------------------------------
    # spec 3：北京时间分析生成日期口径
    # ------------------------------------------------------------------

    def test_groups_by_shanghai_generation_date(self) -> None:
        """spec 3：归组边界 = 北京日历日 [00:00, +1d) 折算到服务器本地，与本地时区无关。"""
        day_start, day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        inside_id = self._add_history("600519", day_start + timedelta(minutes=30), name="贵州茅台")
        before_id = self._add_history("600519", day_start - timedelta(minutes=1), name="贵州茅台")
        after_id = self._add_history("600519", day_end, name="贵州茅台")

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], inside_id)
        self.assertNotIn(items[0]["id"], (before_id, after_id))
        # 边界外记录仍可通过按 ID 详情端点访问（点开即当时报告）
        detail = self.client.get(f"/api/v1/history/{after_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["meta"]["id"], after_id)

    # ------------------------------------------------------------------
    # 同股一天多次分析：先取最新一份 + 当日份数
    # ------------------------------------------------------------------

    def test_same_stock_multiple_runs_returns_latest_with_day_count(self) -> None:
        """spec 3：同股同日多份 → 行取最新一份，analysis_count 标注当日份数。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        older_id = self._add_history(
            "600519", day_start + timedelta(hours=1), name="贵州茅台", sentiment_score=60,
        )
        latest_id = self._add_history(
            "600519", day_start + timedelta(hours=9), name="贵州茅台", sentiment_score=82,
        )
        self.assertLess(older_id, latest_id)

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], latest_id)
        self.assertEqual(items[0]["analysis_count"], 2)
        self.assertTrue(items[0]["is_latest"])
        # 两份记录都能按 ID 打开当时那份报告
        older_detail = self.client.get(f"/api/v1/history/{older_id}")
        self.assertEqual(older_detail.status_code, 200)
        self.assertEqual(older_detail.json()["summary"]["sentiment_score"], 60)

    # ------------------------------------------------------------------
    # 代码变体合并 + 时效性
    # ------------------------------------------------------------------

    def test_code_variants_merge_to_single_row_with_merged_count(self) -> None:
        """002460 与 002460.SZ 同日合并为一行（取最大 id），份数求和。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history("002460", day_start + timedelta(hours=1), name="赣锋锂业")
        latest_id = self._add_history("002460.SZ", day_start + timedelta(hours=2), name="赣锋锂业")

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], latest_id)
        self.assertEqual(items[0]["analysis_count"], 2)

    def test_is_latest_false_when_superseded_by_newer_analysis(self) -> None:
        """spec 3：被更晚的分析取代 → is_latest=False（前端展示「已有更新」）。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history("600519", day_start + timedelta(hours=1), name="贵州茅台")
        _next_day_start, _ = HistoryService.shanghai_day_bounds_local(QUERY_DATE + timedelta(days=2))
        self._add_history("600519", _next_day_start + timedelta(hours=1), name="贵州茅台")

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["is_latest"])

    def test_market_and_market_review_excluded(self) -> None:
        """大盘复盘不进每股当日列表。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history("600519", day_start + timedelta(hours=1), name="贵州茅台")
        self._add_history("MARKET", day_start + timedelta(hours=2), name="大盘")
        self._add_history(
            "MARKET", day_start + timedelta(hours=3),
            name="大盘复盘", report_type="market_review",
        )

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["code"], "600519")

    # ------------------------------------------------------------------
    # 分页 / 参数校验 / 语言
    # ------------------------------------------------------------------

    def test_pagination_is_stable(self) -> None:
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        for index in range(3):
            self._add_history(f"60051{index}", day_start + timedelta(minutes=index), name=f"股{index}")

        page_one = self._get_daily(page=1, limit=2)
        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_one.json()["total"], 3)
        self.assertEqual(len(page_one.json()["items"]), 2)
        page_two = self._get_daily(page=2, limit=2)
        self.assertEqual(len(page_two.json()["items"]), 1)
        # 同页无重复
        ids_one = {item["id"] for item in page_one.json()["items"]}
        ids_two = {item["id"] for item in page_two.json()["items"]}
        self.assertFalse(ids_one & ids_two)

    def test_missing_date_rejected(self) -> None:
        response = self.client.get("/api/v1/history/daily")
        self.assertEqual(response.status_code, 422)

    def test_language_param_controls_label(self) -> None:
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history("600519", day_start + timedelta(hours=1), sentiment_score=82)
        response = self._get_daily(language="en")
        self.assertEqual(response.status_code, 200)
        # 与真实标签函数契约对齐，不在测试里硬编码标签文案
        self.assertEqual(
            response.json()["items"][0]["sentiment_label"],
            get_sentiment_label(82, "en"),
        )

    # ------------------------------------------------------------------
    # spec 2：点开即当时报告（按 ID 详情端点为既有能力，回归保障）
    # ------------------------------------------------------------------

    def test_detail_by_record_id_returns_that_exact_report(self) -> None:
        """点行下钻：GET /history/{id} 必须返回该 id 对应的那份（同股同日两份互不串）。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        first_id = self._add_history(
            "600519", day_start + timedelta(hours=1), name="贵州茅台",
            sentiment_score=55, operation_advice="观望", trend_prediction="震荡",
        )
        second_id = self._add_history(
            "600519", day_start + timedelta(hours=5), name="贵州茅台",
            sentiment_score=90, operation_advice="买入", trend_prediction="看多",
        )

        for record_id, expected_score in ((first_id, 55), (second_id, 90)):
            response = self.client.get(f"/api/v1/history/{record_id}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["meta"]["id"], record_id)
            self.assertEqual(payload["summary"]["sentiment_score"], expected_score)
            # 详情含价位字段（spec 1：价位放报告详情，有值再展示）
            self.assertIn("ideal_buy", payload["strategy"])


if __name__ == "__main__":
    unittest.main()
