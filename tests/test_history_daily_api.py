# -*- coding: utf-8 -*-
"""
issue #1661 — GET /api/v1/history/daily 集成测试

按交易日返回每股当日最新分析结果（规范化合并 + is_latest 时效性 +
sentiment_label + 稳定分页）。范式照 tests/test_alert_api.py：
unittest.TestCase + FastAPI TestClient + DatabaseManager.reset_instance() + 真实 SQLite。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.storage import AnalysisHistory, DatabaseManager

# 固定历史日期，避免与 datetime.now() 或其他用例互相干扰
D1 = datetime(2026, 10, 20)          # 主查询日
D1_LATER = datetime(2026, 10, 20, 12, 0, 0)
D2 = datetime(2026, 10, 21, 9, 0, 0)  # 次日
D3 = datetime(2026, 10, 22, 9, 0, 0)  # 第三日
QUERY_DATE = "2026-10-20"

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
    "ideal_buy",
    "secondary_buy",
    "stop_loss",
    "take_profit",
    "created_at",
}


class HistoryDailyApiTestCase(unittest.TestCase):
    """GET /api/v1/history/daily 契约测试（issue #1661 Wave 1）"""

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
            ideal_buy=kwargs.get("ideal_buy", 10.5),
            secondary_buy=kwargs.get("secondary_buy", 10.2),
            stop_loss=kwargs.get("stop_loss", 9.5),
            take_profit=kwargs.get("take_profit", 12.0),
            raw_result=kwargs.get("raw_result"),
            created_at=created_at,
        )
        with self.db.get_session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return int(record.id or 0)

    def _get_daily(self, **params):
        query = {"date": QUERY_DATE}
        query.update(params)
        return self.client.get("/api/v1/history/daily", params=query)

    def test_1_same_day_multiple_records_returns_only_latest(self) -> None:
        """同日同股多条 → 仅返回最新一条（核心去重用例）。"""
        self._add_history("600519", D1, sentiment_score=40)
        self._add_history("600519", datetime(2026, 10, 20, 11, 0, 0), sentiment_score=60)
        latest_id = self._add_history("600519", D1_LATER, sentiment_score=85)

        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["id"], latest_id)
        self.assertEqual(item["sentiment_score"], 85)
        # 响应模型字段与前端契约一致
        self.assertEqual(set(item.keys()), DAILY_CONTRACT_KEYS)
        self.assertEqual(
            {key for key in payload.keys()},
            {"total", "page", "limit", "items"},
        )

    def test_2_is_latest_flags_global_latest_only(self) -> None:
        """is_latest：当日最新但次日已有新记录 → False；全局最新 → True。"""
        day1_id = self._add_history("600519", D1)
        day2_id = self._add_history("600519", D2)

        resp_day1 = self._get_daily()
        self.assertEqual(resp_day1.status_code, 200, resp_day1.text)
        self.assertEqual(resp_day1.json()["items"][0]["id"], day1_id)
        self.assertFalse(resp_day1.json()["items"][0]["is_latest"])

        resp_day2 = self._get_daily(date="2026-10-21")
        self.assertEqual(resp_day2.status_code, 200, resp_day2.text)
        self.assertEqual(resp_day2.json()["items"][0]["id"], day2_id)
        self.assertTrue(resp_day2.json()["items"][0]["is_latest"])

        # 变体写法（600519.SH）更新的分析同样取代旧记录（规范化归组语义）
        variant_id = self._add_history("600519.SH", D3)
        resp_day2_after = self._get_daily(date="2026-10-21")
        self.assertFalse(resp_day2_after.json()["items"][0]["is_latest"])
        resp_day3 = self._get_daily(date="2026-10-22")
        item_day3 = resp_day3.json()["items"][0]
        self.assertEqual(item_day3["id"], variant_id)
        self.assertTrue(item_day3["is_latest"])

    def test_3_pagination_total_and_validation(self) -> None:
        """total=合并后股票数；翻页正确；page/limit 越界 → 422。"""
        id_a = self._add_history("600519", D1)
        id_b = self._add_history("000001", D1)
        id_c = self._add_history("300750", D1)

        resp = self._get_daily(page=1, limit=2)
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(len(payload["items"]), 2)
        # 同 created_at 时按 id desc 稳定排序
        self.assertEqual([item["id"] for item in payload["items"]], [id_c, id_b])

        resp_page2 = self._get_daily(page=2, limit=2)
        self.assertEqual(resp_page2.status_code, 200, resp_page2.text)
        page2_ids = [item["id"] for item in resp_page2.json()["items"]]
        self.assertEqual(page2_ids, [id_a])
        self.assertEqual(
            set(page2_ids) & {item["id"] for item in payload["items"]},
            set(),
        )

        resp_page3 = self._get_daily(page=3, limit=2)
        self.assertEqual(resp_page3.status_code, 200, resp_page3.text)
        self.assertEqual(resp_page3.json()["items"], [])

        for bad in ({"page": 0}, {"limit": 0}, {"limit": 101}, {"page": -1}):
            with self.subTest(bad=bad):
                resp_bad = self._get_daily(**bad)
                self.assertEqual(resp_bad.status_code, 422, resp_bad.text)

    def test_4_missing_or_invalid_date_returns_422(self) -> None:
        """缺 date 或非法日期（2026-13-40）→ 422。"""
        resp_missing = self.client.get("/api/v1/history/daily")
        self.assertEqual(resp_missing.status_code, 422, resp_missing.text)

        resp_invalid = self.client.get(
            "/api/v1/history/daily", params={"date": "2026-13-40"}
        )
        self.assertEqual(resp_invalid.status_code, 422, resp_invalid.text)

    def test_5_empty_day_returns_empty_list(self) -> None:
        """当日无记录 → 200 {total:0, items:[]}（非 404）。"""
        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["items"], [])

    def test_6_market_and_market_review_excluded(self) -> None:
        """code=MARKET 与 report_type=market_review 默认被排除。"""
        normal_id = self._add_history("600519", D1)
        self._add_history("MARKET", D1, report_type="market_review")
        self._add_history("MARKET", D1, report_type="detailed")
        self._add_history("600519", D1, report_type="market_review")

        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([item["id"] for item in payload["items"]], [normal_id])
        self.assertEqual(payload["items"][0]["code"], "600519")

    def test_7_daily_route_not_shadowed_by_record_id(self) -> None:
        """/daily 不被 /{record_id} 吞（record_id="daily" 会 404）。"""
        self._add_history("600519", D1)
        resp = self.client.get("/api/v1/history/daily", params={"date": QUERY_DATE})
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        # DailyHistoryListResponse 形状（而非 AnalysisReport 或 404 错误包络）
        self.assertEqual(set(payload.keys()), {"total", "page", "limit", "items"})
        self.assertIsInstance(payload["items"], list)
        self.assertEqual(payload["items"][0]["id"] > 0, True)

    def test_8_same_second_many_stocks_pagination_stable(self) -> None:
        """同秒 ≥ limit+1 只股票 → 跨页 id 集合不重复、不漏行。"""
        same_second = datetime(2026, 10, 20, 10, 0, 0)
        expected_ids = []
        for i in range(1, 26):  # 25 只 > limit=20
            expected_ids.append(self._add_history(f"{i:06d}", same_second))

        resp1 = self._get_daily(page=1, limit=20)
        self.assertEqual(resp1.status_code, 200, resp1.text)
        resp2 = self._get_daily(page=2, limit=20)
        self.assertEqual(resp2.status_code, 200, resp2.text)

        payload1 = resp1.json()
        payload2 = resp2.json()
        self.assertEqual(payload1["total"], 25)
        ids1 = [item["id"] for item in payload1["items"]]
        ids2 = [item["id"] for item in payload2["items"]]
        self.assertEqual(len(ids1), 20)
        self.assertEqual(len(ids2), 5)
        self.assertEqual(set(ids1) & set(ids2), set())  # 不重复
        self.assertEqual(set(ids1) | set(ids2), set(expected_ids))  # 不漏行
        # 排序 tiebreaker：created_at 相同 → id desc
        self.assertEqual(ids1, sorted(ids1, reverse=True))
        self.assertEqual(ids2, sorted(ids2, reverse=True))

    def test_9_variant_codes_merge_to_one_row(self) -> None:
        """002460 与 002460.SZ 同日各有记录 → 合并一行取 id 大者，total=1。"""
        # 故意让 002460 的 created_at 更晚但 id 更小：钉死"取 id 最大"而非"取时间最新"
        bare_id = self._add_history(
            "002460", datetime(2026, 10, 20, 11, 0, 0), name="宁德时代"
        )
        suffix_id = self._add_history(
            "002460.SZ", datetime(2026, 10, 20, 9, 0, 0), name="宁德时代.SZ"
        )
        self.assertGreater(suffix_id, bare_id)

        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["id"], suffix_id)
        self.assertEqual(item["code"], "002460.SZ")
        self.assertTrue(item["is_latest"])

    def test_10_structured_action_overrides_legacy_advice(self) -> None:
        """结构化动作优先：raw action='avoid' + 旧文案 operation_advice='买入' → 最终动作 回避。"""
        self._add_history(
            "600519",
            D1,
            sentiment_score=35,
            operation_advice="买入",
            raw_result=json.dumps({"action": "avoid", "operation_advice": "买入"}),
        )

        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        item = resp.json()["items"][0]
        self.assertEqual(item["action"], "avoid")
        self.assertEqual(item["action_label"], "回避")
        # 原始文案字段保持原样，不回写
        self.assertEqual(item["operation_advice"], "买入")

    def test_11_action_falls_back_to_advice_without_structured_action(self) -> None:
        """无结构化 action 时按旧文案派生最终动作（与 /stocks 路径同语义）。"""
        self._add_history(
            "600519",
            D1,
            sentiment_score=35,
            operation_advice="不建议买入，等待确认",
        )

        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        item = resp.json()["items"][0]
        self.assertEqual(item["action"], "avoid")
        self.assertEqual(item["action_label"], "回避")

    def test_12_null_score_keeps_null_label(self) -> None:
        """sentiment_score=NULL → label=null；真实 0 分仍产出 极度悲观（评审 OR-COR-82e95195）。"""
        null_id = self._add_history("600519", D1, sentiment_score=None)
        zero_id = self._add_history("000001", D1, sentiment_score=0)

        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["total"], 2)
        by_id = {item["id"]: item for item in payload["items"]}
        self.assertIsNone(by_id[null_id]["sentiment_score"])
        self.assertIsNone(by_id[null_id]["sentiment_label"])
        self.assertEqual(by_id[zero_id]["sentiment_score"], 0)
        self.assertEqual(by_id[zero_id]["sentiment_label"], "极度悲观")

    def test_13_hk_code_variants_merge_to_one_row(self) -> None:
        """同日 00700/HK00700/00700.HK → canonical hk00700 归组，total=1（评审 OR-COR-f3050c49）。"""
        bare_id = self._add_history("00700", D1, name="腾讯控股")
        hk_id = self._add_history("HK00700", D1, name="腾讯控股HK")
        suffix_id = self._add_history("00700.HK", D1_LATER, name="腾讯控股.HK")
        winner = max(bare_id, hk_id, suffix_id)

        resp = self._get_daily()
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["id"], winner)
        self.assertTrue(item["is_latest"])

    def test_14_hk_variant_update_supersedes_older_record(self) -> None:
        """前日 00700 记录在次日以 HK00700 保存新分析后 is_latest=False。"""
        day1_id = self._add_history("00700", D1)
        day2_id = self._add_history("HK00700", D2)

        resp_day1 = self._get_daily()
        self.assertEqual(resp_day1.status_code, 200, resp_day1.text)
        item_day1 = resp_day1.json()["items"][0]
        self.assertEqual(item_day1["id"], day1_id)
        self.assertFalse(item_day1["is_latest"])

        resp_day2 = self._get_daily(date="2026-10-21")
        self.assertEqual(resp_day2.status_code, 200, resp_day2.text)
        item_day2 = resp_day2.json()["items"][0]
        self.assertEqual(item_day2["id"], day2_id)
        self.assertTrue(item_day2["is_latest"])


if __name__ == "__main__":
    unittest.main()
