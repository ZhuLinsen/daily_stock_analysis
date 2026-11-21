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

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

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

    # ------------------------------------------------------------------
    # OR-COR-a911f1cb：指数与同号裸码股票不得折叠为一行
    # ------------------------------------------------------------------

    def test_sz_index_and_bare_same_code_stock_stay_separate(self) -> None:
        """归组键必须区分资产类型：``sz399001``（指数）与裸 ``399001``（股票）
        是两个标的，同日各出一行、份数互不并入（与个股栏既有语义一致，
        tests/test_analysis_history.py::test_stock_bar_exposes_sz_index_canonical_row_with_independent_count）。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history("sz399001", day_start + timedelta(hours=1), name="深证成指")
        self._add_history("399001", day_start + timedelta(hours=2), name="平安银行")

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)
        by_code = {item["code"]: item for item in payload["items"]}
        self.assertIn("sz399001", by_code)
        self.assertIn("399001", by_code)
        self.assertEqual(by_code["sz399001"]["analysis_count"], 1)
        self.assertEqual(by_code["399001"]["analysis_count"], 1)

    # ------------------------------------------------------------------
    # OR-COR-c9984f4e / OR-COR-c60dfc2b：旧日韩裸码与现行带后缀代码必须合并
    # ------------------------------------------------------------------

    def test_legacy_bare_jp_kr_code_merges_with_resolved_suffix_code(self) -> None:
        """``005930`` 与 ``005930.KS`` 同日保存 → 合并一行、份数求和（与个股栏
        test_history_filter_and_stock_bar_merge_bare_and_resolved_jp_kr_codes 同语义）。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history("005930", day_start + timedelta(hours=1), name="Samsung Electronics")
        latest_id = self._add_history(
            "005930.KS", day_start + timedelta(hours=2), name="Samsung Electronics",
        )

        with patch(
            "src.services.history_service.resolve_index_stock_code",
            return_value="005930.KS",
        ):
            response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["id"], latest_id)
        self.assertEqual(payload["items"][0]["code"], "005930.KS")
        self.assertEqual(payload["items"][0]["analysis_count"], 2)

    def test_legacy_bare_jp_kr_code_superseded_across_days(self) -> None:
        """跨日：旧裸码报告被新 ``.KS`` 报告取代 → is_latest=False（不得因拆键失真）。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        next_day_start, _ = HistoryService.shanghai_day_bounds_local(QUERY_DATE + timedelta(days=1))
        self._add_history("005930", day_start + timedelta(hours=1), name="Samsung Electronics")
        self._add_history("005930.KS", next_day_start + timedelta(hours=1), name="Samsung Electronics")

        with patch(
            "src.services.history_service.resolve_index_stock_code",
            return_value="005930.KS",
        ):
            response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["is_latest"])

    # ------------------------------------------------------------------
    # OR-COR-afa444c6：当日列表与全局时效标记必须来自同一读取快照
    # ------------------------------------------------------------------

    def test_snapshot_pair_is_consistent_for_day_and_global_scopes(self) -> None:
        """get_daily_history_snapshot 单次读取同时给出当日 (最新行, 份数) 与
        全局 per-code 最新 id：窗口外记录只进全局（跨日取代语义），窗口内
        记录两者皆进，且服务层单次调用只取一次快照。"""
        day_start, day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        in_day_id = self._add_history("600519", day_start + timedelta(hours=1), name="贵州茅台")
        self._add_history("600519", day_end + timedelta(hours=1), name="贵州茅台")
        outside_only_id = self._add_history("000002", day_end + timedelta(hours=2), name="万科")

        daily, global_latest = self.db.get_daily_history_snapshot(
            day_start=day_start, day_end=day_end,
        )
        daily_by_id = {int(record.id): count for record, count in daily}
        self.assertIn(in_day_id, daily_by_id)
        self.assertEqual(daily_by_id[in_day_id], 1)
        self.assertNotIn(outside_only_id, daily_by_id)
        self.assertEqual(global_latest.get("600519"), in_day_id + 1)
        self.assertEqual(global_latest.get("000002"), outside_only_id)

        service = HistoryService(self.db)
        with patch.object(
            self.db, "get_daily_history_snapshot", wraps=self.db.get_daily_history_snapshot,
        ) as spy:
            service.get_daily_history(QUERY_DATE)
        self.assertEqual(spy.call_count, 1)

    # ------------------------------------------------------------------
    # OR-COR-71b5736f：列表时间必须是北京钟点（与归组日历日一致）
    # ------------------------------------------------------------------

    def test_created_at_serialized_in_shanghai_time(self) -> None:
        """行内分析时间以 Asia/Shanghai 显式偏移序列化：服务器 UTC（17:30 本地）
        时所选北京日的行也显示北京钟点（01:30），不再暴露服务器钟点。"""
        # 直接验证转换契约（OR-COR-71b5736f 场景）：UTC 10-19 17:30 == 北京 10-20 01:30
        utc_value = datetime(2026, 10, 19, 17, 30, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(
            HistoryService._serialize_created_at_shanghai(utc_value),
            "2026-10-20T01:30:00+08:00",
        )

        # 存储为 naive 本地时间 → 行内时间必须是北京钟点 + 北京日历日
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history("600519", day_start + timedelta(minutes=30), name="贵州茅台")

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        created_at = response.json()["items"][0]["created_at"]
        # day_start 构造上即北京零点 → 行内日期必须仍是所选北京日（服务器西侧
        # 时区部署下，旧实现会泄漏本地钟点/前一天日期）
        self.assertTrue(
            created_at.startswith(f"{QUERY_DATE.isoformat()}T"),
            f"created_at 应为北京日 {QUERY_DATE}，实际 {created_at}",
        )
        expected_bj = (
            (day_start + timedelta(minutes=30))
            .astimezone()
            .astimezone(HistoryService._SHANGHAI_TZ)
            .isoformat()
        )
        self.assertEqual(created_at, expected_bj)

    # ------------------------------------------------------------------
    # OR-COM-cb90db57：摘要列缺失时回退 raw_result（与个股栏同语义）
    # ------------------------------------------------------------------

    def test_raw_result_fallback_restores_score_and_advice(self) -> None:
        """旧记录 sentiment_score/operation_advice 列为空、raw_result 仍有
        78 分与 Hold 建议 → 新接口必须像 /history/stocks 一样补齐，动作计算
        使用补齐后的评分。"""
        day_start, _day_end = HistoryService.shanghai_day_bounds_local(QUERY_DATE)
        self._add_history(
            "600519", day_start + timedelta(hours=1), name="贵州茅台",
            sentiment_score=None, operation_advice=None,
            raw_result=json.dumps({
                "summary": {"sentiment_score": 78, "operation_advice": "Hold"},
                "action": "hold",
                "report_language": "en",
            }),
        )

        response = self._get_daily()
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["sentiment_score"], 78)
        self.assertEqual(item["operation_advice"], "Hold")
        self.assertEqual(item["sentiment_label"], get_sentiment_label(78, "zh"))
        # 动作基于补齐后的 78 分 + Hold：不得因评分缺失退化
        self.assertIsNotNone(item["action"])
        self.assertIsNotNone(item["action_label"])


if __name__ == "__main__":
    unittest.main()
