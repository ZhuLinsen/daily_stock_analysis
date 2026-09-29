# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 分析历史存储单元测试
===================================

职责：
1. 验证分析历史保存逻辑
2. 验证上下文快照保存开关
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Keep this test runnable when optional LLM runtime deps are not installed.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

try:
    from fastapi.testclient import TestClient
    from api.app import create_app
    from api.v1.endpoints.history import delete_history_by_code, get_history_detail, get_history_list, get_stock_bar
except ModuleNotFoundError:
    TestClient = None
    create_app = None
    delete_history_by_code = None
    get_history_detail = None
    get_history_list = None
    get_stock_bar = None

from src.config import Config
from src.storage import (
    DatabaseManager,
    AnalysisHistory,
    BacktestResult,
    DecisionSignalFeedbackRecord,
    DecisionSignalOutcomeRecord,
    DecisionSignalRecord,
)
from src.analyzer import AnalysisResult
from src.daily_market_context_guardrail import apply_daily_market_context_guardrail
from src.services.history_service import HistoryService
import src.auth as auth


class TestHistoryCsiCandidateConvergence(unittest.TestCase):
    """PR #2267 review remediation: registered CSI explicit identities must
    converge in history filter candidates so a record saved under any
    equivalent form is reachable from every equivalent query input."""

    def test_registered_csi_forms_include_canonical_uppercase_and_aliases(self):
        """A registered CSI identity is a *persisted-read* filter path: the
        candidate set must include the parser canonical (``csi930955``), the
        old resolver's uppercase canonical (``CSI930955`` — how pre-fix records
        were saved) and the IndexEntry's explicit aliases (``930955.CSI``) so a
        record stored under any of them is hit by any equivalent input."""
        for code in ("csi930955", "930955.CSI", "CSI930955", "  csi930955  "):
            candidates = HistoryService._history_code_filter_candidates(code)
            self.assertEqual(
                set(candidates),
                {"csi930955", "CSI930955", "930955.CSI"},
            )
            self.assertEqual(len(candidates), len(set(candidates)))

    def test_bare_csi_base_remains_stock_candidates(self):
        candidates = HistoryService._history_code_filter_candidates("930955")
        self.assertIn("930955", candidates)
        self.assertNotIn("csi930955", candidates)

    def test_unregistered_csi_form_is_not_converged(self):
        candidates = HistoryService._history_code_filter_candidates("csi930956")
        self.assertNotIn("csi930956", candidates)

    def test_market_aware_offshore_lookup_keeps_same_market_bare_numeric_alias(self):
        db = MagicMock()
        db.get_analysis_history_paginated.return_value = ([], 0)

        HistoryService(db).get_history_list(
            stock_code="005930.KS",
            page=1,
            limit=5,
            include_ambiguous_numeric_aliases=False,
            market_hint="kr",
        )

        queried_codes = db.get_analysis_history_paginated.call_args.kwargs["code"]
        self.assertIn("005930.KS", queried_codes)
        self.assertIn("005930", queried_codes)

    def test_market_hint_blocks_indexed_cross_market_reexpansion(self):
        db = MagicMock()
        db.get_analysis_history_paginated.return_value = ([], 0)

        HistoryService(db).get_history_list(
            stock_code="000660",
            page=1,
            limit=5,
            market_hint="cn",
        )

        queried_codes = db.get_analysis_history_paginated.call_args.kwargs["code"]
        self.assertIn("SZ000660", queried_codes)
        self.assertIn("000660.SZ", queried_codes)
        self.assertNotIn("000660", queried_codes)
        self.assertNotIn("000660.KS", queried_codes)

    def test_market_hint_keeps_unambiguous_same_market_bare_numeric_alias(self):
        db = MagicMock()
        db.get_analysis_history_paginated.return_value = ([], 0)

        HistoryService(db).get_history_list(
            stock_code="600519",
            page=1,
            limit=5,
            market_hint="cn",
        )

        queried_codes = db.get_analysis_history_paginated.call_args.kwargs["code"]
        self.assertIn("600519", queried_codes)

    def test_empty_market_qualified_candidate_set_fails_closed(self):
        db = MagicMock()

        result = HistoryService(db).get_history_list(
            stock_code="AAPL",
            page=1,
            limit=5,
            market_hint="cn",
        )

        self.assertEqual(result, {"total": 0, "items": []})
        db.get_analysis_history_paginated.assert_not_called()


class TestHistoryIndexCanonicalCandidates(unittest.TestCase):
    """PR #2312 review remediation: registered SH/SZ indices (not just CSI)
    must use parser-aware persisted-read candidates — lowercase canonical +
    uppercase legacy canonical + explicit aliases — and must never include the
    bare same-code stock, so an index record is never reachable through a
    stock query and vice versa."""

    def test_registered_sh_index_forms_include_canonical_uppercase_and_aliases(self):
        """``sh000016`` must map to canonical + uppercase legacy + ``000016.SH``
        alias, and must NOT include the bare ``000016`` stock."""
        for code in ("sh000016", "SH000016", "000016.SH", "  sh000016  "):
            candidates = HistoryService._history_code_filter_candidates(code)
            self.assertEqual(
                set(candidates),
                {"sh000016", "SH000016", "000016.SH"},
            )
            self.assertEqual(len(candidates), len(set(candidates)))
            self.assertNotIn("000016", candidates)

    def test_registered_sz_index_forms_include_canonical_uppercase_and_aliases(self):
        for code in ("sz399001", "SZ399001", "399001.SZ"):
            candidates = HistoryService._history_code_filter_candidates(code)
            self.assertEqual(
                set(candidates),
                {"sz399001", "SZ399001", "399001.SZ"},
            )
            self.assertNotIn("399001", candidates)

    def test_multi_alias_sh300_index_candidates_include_uppercase_alias_forms(self):
        """sqlite `IN` 大小写敏感：`sz399300` 的旧 uppercase 持久化形态
        `SZ399300` 必须进入候选集，否则旧记录查不到。"""
        expected = {
            "sh000300",
            "SH000300",
            "sz399300",
            "SZ399300",
            "000300.SH",
            "000300.CSI",
        }
        for code in ("sh000300", "sz399300", "SZ399300", "000300.SH", "000300.CSI"):
            candidates = HistoryService._history_code_filter_candidates(code)
            self.assertEqual(set(candidates), expected)
            self.assertEqual(len(candidates), len(set(candidates)))
            self.assertNotIn("000300", candidates)

    def test_registered_csi_forms_keep_existing_converged_candidates(self):
        """The unified parser-aware branch must preserve the PR #2267 CSI
        candidate contract exactly."""
        for code in ("csi930955", "930955.CSI", "CSI930955", "  csi930955  "):
            candidates = HistoryService._history_code_filter_candidates(code)
            self.assertEqual(
                set(candidates),
                {"csi930955", "CSI930955", "930955.CSI"},
            )
            self.assertEqual(len(candidates), len(set(candidates)))
            self.assertNotIn("930955", candidates)

    def test_multi_alias_sh300_index_converges_all_explicit_forms(self):
        """``sh000300`` owns ``sz399300`` / ``000300.SH`` / ``000300.CSI``
        aliases; every explicit form must converge to the same candidate set,
        including the uppercase alias form ``SZ399300`` (case-sensitive SQL)."""
        for code in ("sh000300", "sz399300", "SZ399300", "000300.SH", "000300.CSI"):
            candidates = HistoryService._history_code_filter_candidates(code)
            self.assertEqual(
                set(candidates),
                {"sh000300", "SH000300", "sz399300", "SZ399300", "000300.SH", "000300.CSI"},
            )
            self.assertNotIn("000300", candidates)

    def test_bare_stock_does_not_include_index_identity(self):
        """Filtering the bare stock ``000016`` must not reach the ``sh000016``
        index or its ``000016.SH`` alias."""
        candidates = HistoryService._history_code_filter_candidates("000016")
        self.assertIn("000016", candidates)
        self.assertNotIn("sh000016", candidates)
        self.assertNotIn("000016.SH", candidates)

    def test_unregistered_prefixed_index_form_stays_stock(self):
        """An unregistered ``sh``-prefixed token parses as a stock and must
        keep the legacy stock candidate path untouched — no lowercase index
        canonical (``sh900999``) and no registry alias are invented."""
        candidates = HistoryService._history_code_filter_candidates("sh900999")
        self.assertEqual(
            set(candidates),
            {"SH900999", "900999", "900999.SH", "900999.SS", "SS900999"},
        )
        self.assertNotIn("sh900999", candidates)


def _analysis_context_pack_overview() -> dict:
    return {
        "pack_version": "1.0",
        "created_at": "2026-04-10T08:30:00+00:00",
        "subject": {
            "code": "600519",
            "stock_name": "贵州茅台",
            "market": "cn",
        },
        "blocks": [
            {
                "key": "quote",
                "label": "行情",
                "status": "available",
                "source": "mock",
                "warnings": [],
                "missing_reasons": [],
            }
        ],
        "counts": {
            "available": 1,
            "missing": 0,
            "not_supported": 0,
            "fallback": 0,
            "stale": 0,
            "estimated": 0,
            "partial": 0,
            "fetch_failed": 0,
        },
        "data_quality": {
            "overall_score": 100,
            "level": "good",
            "block_scores": {
                "quote": 100,
                "daily_bars": 100,
                "technical": 100,
                "news": 100,
                "fundamentals": 100,
                "chip": 100,
            },
            "limitations": [],
        },
        "warnings": [],
        "metadata": {
            "trigger_source": "api",
            "news_result_count": 2,
        },
    }


def _market_phase_summary() -> dict:
    return {
        "market": "cn",
        "phase": "intraday",
        "market_local_time": "2026-03-27T10:00:00+08:00",
        "session_date": "2026-03-27",
        "effective_daily_bar_date": "2026-03-26",
        "is_trading_day": True,
        "is_market_open_now": True,
        "is_partial_bar": True,
        "minutes_to_open": None,
        "minutes_to_close": 300,
        "trigger_source": "api",
        "analysis_intent": "auto",
        "warnings": ["partial_bar"],
    }


class AnalysisHistoryTestCase(unittest.TestCase):
    """分析历史存储测试"""

    def setUp(self) -> None:
        """为每个用例初始化独立数据库"""
        auth._auth_enabled = False
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_analysis_history.db")
        self._original_env = {
            key: os.environ.get(key)
            for key in (
                "ENV_FILE",
                "DATABASE_PATH",
            )
        }
        self._env_path = os.path.join(self._temp_dir.name, ".env")
        with open(self._env_path, "w", encoding="utf-8") as env_file:
            env_file.write("STOCK_LIST=600519,000001\n")

        os.environ["ENV_FILE"] = self._env_path
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        """清理资源"""
        Config._instance = None
        DatabaseManager.reset_instance()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    def test_history_timestamps_include_server_timezone_offset(self) -> None:
        serialized = HistoryService._serialize_created_at(datetime(2026, 7, 11, 0, 30))

        self.assertIsNotNone(serialized)
        self.assertRegex(serialized or "", r"[+-]\d{2}:\d{2}$")

    def test_history_query_failure_is_not_returned_as_an_empty_success(self) -> None:
        db = MagicMock()
        db.get_analysis_history_paginated.side_effect = RuntimeError("database unavailable")

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            HistoryService(db).get_history_list(page=1, limit=20)

        if get_history_list is None:
            self.skipTest("fastapi is not installed in this test environment")

        with self.assertRaises(Exception) as raised:
            get_history_list(
                stock_code=None,
                report_type=None,
                start_date=None,
                end_date=None,
                page=1,
                limit=20,
                db_manager=db,
            )

        self.assertEqual(getattr(raised.exception, "status_code", None), 500)

    def test_delete_history_by_code_deletes_more_than_one_lookup_batch(self) -> None:
        if delete_history_by_code is None:
            self.skipTest("fastapi is not installed in this test environment")

        remaining = {record_id: SimpleNamespace(id=record_id) for record_id in range(1, 10_002)}
        db = MagicMock()

        def get_records(*, code, limit=20, offset=0, **_kwargs):
            records = list(remaining.values())[offset:offset + limit]
            return records, len(remaining)

        def delete_records(record_ids):
            deleted = 0
            for record_id in record_ids:
                if remaining.pop(record_id, None) is not None:
                    deleted += 1
            return deleted

        db.get_analysis_history_paginated.side_effect = get_records
        db.delete_analysis_history_records.side_effect = delete_records

        response = delete_history_by_code("600519", db_manager=db)

        self.assertEqual(response.deleted, 10_001)
        self.assertEqual(remaining, {})
        self.assertEqual(db.get_analysis_history_paginated.call_count, 2)

    def test_delete_history_by_code_rejects_blank_code_before_query(self) -> None:
        if delete_history_by_code is None:
            self.skipTest("fastapi is not installed in this test environment")

        record_id = self._save_history("query_delete_blank_code")
        with (
            patch.object(
                self.db,
                "get_analysis_history_paginated",
                wraps=self.db.get_analysis_history_paginated,
            ) as query,
            patch.object(
                self.db,
                "delete_analysis_history_records",
                wraps=self.db.delete_analysis_history_records,
            ) as delete,
        ):
            with self.assertRaises(Exception) as raised:
                delete_history_by_code(" ", db_manager=self.db)

        self.assertEqual(getattr(raised.exception, "status_code", None), 400)
        query.assert_not_called()
        delete.assert_not_called()
        with self.db.get_session() as session:
            self.assertIsNotNone(session.query(AnalysisHistory).filter(AnalysisHistory.id == record_id).first())

    def _build_result(self) -> AnalysisResult:
        """构造分析结果"""
        return AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=78,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="基本面稳健，短期震荡",
        )

    def _save_history(self, query_id: str) -> int:
        """保存一条测试历史记录并返回主键 ID。"""
        result = self._build_result()
        saved = self.db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            return row.id

    def test_save_analysis_history_with_snapshot(self) -> None:
        """保存历史记录并写入上下文快照"""
        result = self._build_result()
        result.dashboard = {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "理想买入点：125.5元",
                    "secondary_buy": "120",
                    "stop_loss": "止损位：110元",
                    "take_profit": "目标位：150.0元",
                }
            }
        }
        context_snapshot = {"enhanced_context": {"code": "600519"}}

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_001",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=context_snapshot,
            save_snapshot=True
        )

        self.assertGreater(saved, 0)

        history = self.db.get_analysis_history(code="600519", days=7, limit=10)
        self.assertEqual(len(history), 1)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            self.assertEqual(row.query_id, "query_001")
            self.assertIsNotNone(row.context_snapshot)
            self.assertEqual(row.ideal_buy, 125.5)
            self.assertEqual(row.secondary_buy, 120.0)
            self.assertEqual(row.stop_loss, 110.0)
            self.assertEqual(row.take_profit, 150.0)

    def test_history_display_resolves_bare_jp_kr_code_from_stock_pool(self) -> None:
        result = self._build_result()
        result.code = "005930"
        result.name = "Samsung Electronics"
        persisted_phase_summary = {
            **_market_phase_summary(),
            "phase": "postmarket",
            "market_local_time": "2025-01-02T16:10:00+09:00",
            "session_date": "2025-01-02",
            "effective_daily_bar_date": "2025-01-02",
            "is_market_open_now": False,
            "is_partial_bar": False,
            "minutes_to_open": 900,
            "minutes_to_close": None,
            "trigger_source": "scheduled_job",
            "analysis_intent": "postmarket",
            "warnings": ["legacy_snapshot"],
        }
        expected_phase_summary = {**persisted_phase_summary, "market": "kr"}
        expected_phase_summary["minutes_to_open"] = None

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_kr_bare",
            report_type="simple",
            news_content="news",
            context_snapshot={"market_phase_summary": persisted_phase_summary},
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        service = HistoryService(self.db)
        with patch("src.services.history_service.resolve_index_stock_code", return_value="005930.KS"):
            listing = service.get_history_list(page=1, limit=5)
            detail = service.resolve_and_get_detail("query_kr_bare")

        self.assertEqual(listing["items"][0]["stock_code"], "005930.KS")
        self.assertEqual(listing["items"][0]["market_phase_summary"], expected_phase_summary)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["stock_code"], "005930.KS")
        self.assertEqual(detail["market_phase_summary"], expected_phase_summary)

    def test_history_display_rebuilds_market_phase_summary_for_legacy_cn_snapshot(self) -> None:
        result = self._build_result()
        result.code = "005930"
        result.name = "Samsung Electronics"
        persisted_phase_summary = {
            **_market_phase_summary(),
            "phase": "postmarket",
            "market_local_time": "2026-01-01T10:00:00+08:00",
            "session_date": "2026-01-01",
            "effective_daily_bar_date": "2025-12-31",
            "is_market_open_now": False,
            "is_partial_bar": False,
            "minutes_to_open": 900,
            "minutes_to_close": None,
            "trigger_source": "scheduled_job",
            "analysis_intent": "postmarket",
            "warnings": ["legacy_snapshot"],
        }

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_kr_legacy_snapshot",
            report_type="simple",
            news_content="news",
            context_snapshot={"market_phase_summary": persisted_phase_summary},
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        service = HistoryService(self.db)
        with patch("src.services.history_service.resolve_index_stock_code", return_value="005930.KS"):
            items = service.get_history_list(page=1, limit=5)["items"]

        self.assertEqual(items[0]["stock_code"], "005930.KS")
        rebuilt = items[0]["market_phase_summary"]
        self.assertIsNotNone(rebuilt)
        self.assertEqual(rebuilt["market"], "kr")
        self.assertEqual(rebuilt["market_local_time"], "2026-01-01T11:00:00+09:00")
        self.assertEqual(rebuilt["effective_daily_bar_date"], "2025-12-30")
        self.assertIsNone(rebuilt["minutes_to_open"])

    def test_history_filter_and_stock_bar_merge_bare_and_resolved_jp_kr_codes(self) -> None:
        if get_stock_bar is None:
            self.skipTest("fastapi is not installed in this test environment")

        legacy = self._build_result()
        legacy.code = "005930"
        legacy.name = "Samsung Electronics"
        current = self._build_result()
        current.code = "005930.KS"
        current.name = "Samsung Electronics"

        self.assertGreater(
            self.db.save_analysis_history(
                result=legacy,
                query_id="query_kr_legacy",
                report_type="simple",
                news_content="news",
                context_snapshot={"market_phase_summary": _market_phase_summary()},
                save_snapshot=True,
            ),
            0,
        )
        self.assertGreater(
            self.db.save_analysis_history(
                result=current,
                query_id="query_kr_current",
                report_type="simple",
                news_content="news",
                context_snapshot={"market_phase_summary": _market_phase_summary()},
                save_snapshot=True,
            ),
            0,
        )

        with patch("src.services.history_service.resolve_index_stock_code", side_effect=lambda code: "005930.KS" if str(code).split(".", 1)[0] == "005930" else None):
            listing = HistoryService(self.db).get_history_list(stock_code="005930.KS", page=1, limit=10)
            stock_bar = get_stock_bar(
                start_date=None,
                end_date=None,
                limit=10,
                db_manager=self.db,
            )

        self.assertEqual(listing["total"], 2)
        self.assertEqual({item["query_id"] for item in listing["items"]}, {"query_kr_legacy", "query_kr_current"})
        self.assertEqual(len(stock_bar.items), 1)
        self.assertEqual(stock_bar.items[0].stock_code, "005930.KS")
        self.assertEqual(stock_bar.items[0].analysis_count, 2)

    def test_save_analysis_history_persists_sniper_columns_via_shared_parser(self) -> None:
        """迁出 sniper parser 后历史狙击点位列仍按原规则保存。"""
        result = self._build_result()
        result.dashboard = {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "理想买入点：125.5元",
                    "secondary_buy": "1.52-1.53 (回踩MA5/10附近)",
                    "stop_loss": "—",
                    "take_profit": "目标位：150.0元",
                }
            }
        }

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_shared_sniper_parser",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False,
        )

        self.assertGreater(saved, 0)
        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_shared_sniper_parser"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            self.assertEqual(row.ideal_buy, 125.5)
            self.assertEqual(row.secondary_buy, 1.53)
            self.assertIsNone(row.stop_loss)
            self.assertEqual(row.take_profit, 150.0)

    def test_get_latest_analysis_history_id_filters_by_report_type_and_latest_record(self) -> None:
        """按 query/code/report_type 返回最新真实历史主键。"""
        for report_type in ("simple", "full", "simple"):
            saved = self.db.save_analysis_history(
                result=self._build_result(),
                query_id="query_latest_id",
                report_type=report_type,
                news_content="新闻摘要",
                context_snapshot=None,
                save_snapshot=False,
            )
            self.assertGreater(saved, 0)

        simple_id = self.db.get_latest_analysis_history_id(
            query_id="query_latest_id",
            code="600519",
            report_type="simple",
        )
        full_id = self.db.get_latest_analysis_history_id(
            query_id="query_latest_id",
            code="600519",
            report_type="full",
        )

        self.assertIsNotNone(simple_id)
        self.assertIsNotNone(full_id)
        self.assertGreater(simple_id, full_id)

    def test_get_latest_analysis_history_id_requires_report_type(self) -> None:
        """report_type 是必传参数，避免误取同 query/code 的其他报告。"""
        with self.assertRaises(TypeError):
            self.db.get_latest_analysis_history_id(query_id="query", code="600519")

    def test_save_analysis_history_without_snapshot(self) -> None:
        """关闭快照保存时不写入 context_snapshot"""
        result = self._build_result()

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_002",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot={"foo": "bar"},
            save_snapshot=False
        )

        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            self.assertIsNone(row.context_snapshot)

    def test_save_analysis_history_persists_model_used(self) -> None:
        """model_used should be persisted in raw_result for history detail."""
        result = self._build_result()
        result.model_used = "gemini/gemini-2.0-flash"

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_003",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "query_003").first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            payload = json.loads(row.raw_result or "{}")
            self.assertEqual(payload.get("model_used"), "gemini/gemini-2.0-flash")

    def test_update_analysis_history_diagnostics_preserves_snapshot_fields(self) -> None:
        """通知发送后补写 diagnostics 时，不应覆盖已有上下文字段。"""
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id="query_diag_patch",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot={
                "enhanced_context": {"code": "600519"},
                "diagnostics": {
                    "trace_id": "trace-1",
                    "query_id": "query_diag_patch",
                    "stock_code": "600519",
                    "notification_runs": [],
                },
            },
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        updated = self.db.update_analysis_history_diagnostics(
            query_id="query_diag_patch",
            code="600519",
            notification_runs=[
                {
                    "channel": "report",
                    "status": "success",
                    "success": True,
                }
            ],
        )

        self.assertEqual(updated, 1)
        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_diag_patch"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            snapshot = json.loads(row.context_snapshot or "{}")
            self.assertEqual(snapshot["enhanced_context"]["code"], "600519")
            notification_run = snapshot["diagnostics"]["notification_runs"][-1]
            self.assertEqual(notification_run["status"], "success")
            self.assertEqual(notification_run["trace_id"], "trace-1")

    def test_history_detail_hides_placeholder_model_used(self) -> None:
        """Placeholder model values should be normalized to None in detail response."""
        result = self._build_result()
        result.model_used = "unknown"

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_004",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "query_004").first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        service = HistoryService(self.db)
        detail = service.get_history_detail_by_id(record_id)
        self.assertIsNotNone(detail)
        self.assertIsNone(detail.get("model_used"))

    def test_history_list_includes_timeline_summary_fields(self) -> None:
        """History list items expose the fields needed by the same-stock timeline drawer."""
        result = self._build_result()
        result.model_used = "gemini/gemini-2.5-pro"
        context_snapshot = {
            "enhanced_context": {
                "realtime": {
                    "price": "51.5",
                    "change_pct": "-4.61%",
                    "volume_ratio": "1.17",
                    "turnover_rate": "11.46",
                },
            },
            "market_phase_summary": _market_phase_summary(),
        }

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_timeline_summary",
            report_type="detailed",
            news_content="新闻摘要",
            context_snapshot=context_snapshot,
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        service = HistoryService(self.db)
        payload = service.get_history_list(stock_code="600519.SH", page=1, limit=5)

        self.assertEqual(payload["total"], 1)
        item = payload["items"][0]
        self.assertEqual(item["stock_code"], "600519")
        self.assertEqual(item["trend_prediction"], "看多")
        self.assertEqual(item["analysis_summary"], "基本面稳健，短期震荡")
        self.assertEqual(item["operation_advice"], "持有")
        self.assertEqual(item["action"], "buy")
        self.assertEqual(item["action_label"], "买入")
        self.assertEqual(item["model_used"], "gemini/gemini-2.5-pro")
        self.assertEqual(item["current_price"], 51.5)
        self.assertEqual(item["change_pct"], -4.61)
        self.assertEqual(item["volume_ratio"], 1.17)
        self.assertEqual(item["turnover_rate"], 11.46)
        self.assertEqual(item["market_phase_summary"]["phase"], "intraday")
        self.assertEqual(item["market_phase_summary"]["minutes_to_close"], 300)

    def test_history_persistence_keeps_softened_operation_advice_from_guardrail(self) -> None:
        """Conservative-market guardrail short operation_advice is persisted and exposed to history list."""
        result = self._build_result()
        result.decision_type = "buy"
        result.operation_advice = "立即买入并积极加仓"

        apply_daily_market_context_guardrail(
            result,
            daily_market_context={
                "region": "cn",
                "trade_date": "2026-06-06",
                "summary": "大盘退潮，高风险，建议观望，仓位上限30%。",
                "risk_tags": ["high_risk", "low_position_cap"],
            },
            report_language="zh",
        )

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_softened_operation_advice",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        service = HistoryService(self.db)
        payload = service.get_history_list(stock_code="600519", page=1, limit=10)

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["operation_advice"], "观望")
        self.assertLessEqual(len(payload["items"][0]["operation_advice"]), 20)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_softened_operation_advice"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            self.assertEqual(row.operation_advice, "观望")

    def test_market_review_history_can_be_filtered_without_stock_records(self) -> None:
        """Market review records should be queryable as a dedicated history collection."""
        stock_result = self._build_result()
        market_result = AnalysisResult(
            code="MARKET",
            name="大盘复盘",
            sentiment_score=50,
            trend_prediction="大盘复盘",
            operation_advice="查看复盘",
            analysis_summary="大盘复盘摘要",
        )

        self.assertGreater(
            self.db.save_analysis_history(
                result=stock_result,
                query_id="query_stock_history",
                report_type="detailed",
                news_content="个股正文",
                context_snapshot=None,
                save_snapshot=False,
            ),
            0,
        )
        self.assertGreater(
            self.db.save_analysis_history(
                result=market_result,
                query_id="query_market_review_history",
                report_type="market_review",
                news_content="大盘复盘正文",
                context_snapshot={
                    "report_kind": "market_review",
                    "market_review_region": "jp,kr",
                    "market_review_payload": {
                        "kind": "market_review",
                        "region": "jp,kr",
                        "sections": [{"title": "复盘", "markdown": "结构化正文"}],
                    },
                },
                save_snapshot=True,
            ),
            0,
        )

        service = HistoryService(self.db)
        payload = service.get_history_list(
            stock_code="MARKET",
            report_type="market_review",
            page=1,
            limit=10,
        )

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["stock_code"], "MARKET")
        self.assertEqual(payload["items"][0]["report_type"], "market_review")
        self.assertEqual(payload["items"][0]["region"], "jp,kr")
        self.assertIsNone(payload["items"][0]["action"])
        self.assertIsNone(payload["items"][0]["action_label"])

        if get_history_list is not None:
            response = get_history_list(
                stock_code="MARKET",
                report_type="market_review",
                start_date=None,
                end_date=None,
                page=1,
                limit=10,
                db_manager=self.db,
            )
            self.assertEqual(response.items[0].region, "jp,kr")

    def test_distinct_stock_bar_excludes_market_review_records_by_default(self) -> None:
        """The stock bar aggregation should not mix MARKET into ordinary stock entries."""
        stock_result = self._build_result()
        market_result = AnalysisResult(
            code="MARKET",
            name="大盘复盘",
            sentiment_score=50,
            trend_prediction="大盘复盘",
            operation_advice="查看复盘",
            analysis_summary="大盘复盘摘要",
        )

        self.assertGreater(
            self.db.save_analysis_history(
                result=stock_result,
                query_id="query_stock_bar_stock",
                report_type="detailed",
                news_content="个股正文",
                context_snapshot=None,
                save_snapshot=False,
            ),
            0,
        )
        self.assertGreater(
            self.db.save_analysis_history(
                result=market_result,
                query_id="query_stock_bar_market",
                report_type="market_review",
                news_content="大盘复盘正文",
                context_snapshot=None,
                save_snapshot=False,
            ),
            0,
        )

        records = self.db.get_distinct_stocks_from_history(limit=10)

        self.assertEqual([record.code for record in records], ["600519"])

    def test_stock_bar_item_derives_action_fields_from_legacy_advice(self) -> None:
        if get_stock_bar is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = self._build_result()
        result.operation_advice = "不建议买入"

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_stock_bar_action",
            report_type="detailed",
            news_content="个股正文",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        response = get_stock_bar(
            start_date=None,
            end_date=None,
            limit=10,
            db_manager=self.db,
        )

        self.assertEqual(len(response.items), 1)
        self.assertEqual(response.items[0].operation_advice, "不建议买入")
        self.assertEqual(response.items[0].action, "avoid")
        self.assertEqual(response.items[0].action_label, "回避")

    def test_stock_bar_item_aligns_score_and_legacy_advice(self) -> None:
        if get_stock_bar is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = self._build_result()
        result.operation_advice = "持有"
        result.sentiment_score = 78

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_stock_bar_score_align",
            report_type="detailed",
            news_content="个股正文",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        response = get_stock_bar(
            start_date=None,
            end_date=None,
            limit=10,
            db_manager=self.db,
        )

        self.assertEqual(len(response.items), 1)
        self.assertEqual(response.items[0].operation_advice, "持有")
        self.assertEqual(response.items[0].sentiment_score, 78)
        self.assertEqual(response.items[0].action, "buy")
        self.assertEqual(response.items[0].action_label, "买入")

    def test_stock_bar_item_falls_back_to_raw_result_summary_fields(self) -> None:
        if get_stock_bar is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = self._build_result()
        result.operation_advice = "Hold"
        result.report_language = "en"

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_stock_bar_raw_fallback",
            report_type="detailed",
            news_content="stock report",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.session_scope() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_stock_bar_raw_fallback"
            ).first()
            self.assertIsNotNone(row)
            row.sentiment_score = None
            row.operation_advice = None

        response = get_stock_bar(
            start_date=None,
            end_date=None,
            limit=10,
            db_manager=self.db,
        )

        self.assertEqual(len(response.items), 1)
        self.assertEqual(response.items[0].sentiment_score, 78)
        self.assertEqual(response.items[0].operation_advice, "Hold")
        self.assertEqual(response.items[0].action, "buy")
        self.assertEqual(response.items[0].action_label, "Buy")

    def test_history_detail_uses_service_resolved_action_fields(self) -> None:
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        service = MagicMock()
        service.resolve_and_get_detail.return_value = {
            "id": 1,
            "query_id": "query_action_conflict",
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "report_type": "detailed",
            "report_language": "zh",
            "created_at": "2026-05-21T17:40:00",
            "sentiment_score": 45,
            "operation_advice": "持有观察",
            "action": "watch",
            "action_label": "观望",
            "trend_prediction": "震荡",
            "analysis_summary": "等待确认",
            "raw_result": {
                "operation_advice": "持有观察",
                "action": "watch",
                "report_language": "zh",
            },
        }

        with patch("api.v1.endpoints.history.HistoryService", return_value=service):
            response = get_history_detail("query_action_conflict", db_manager=self.db)

        self.assertEqual(response.summary.operation_advice, "持有观察")
        self.assertEqual(response.summary.action, "watch")
        self.assertEqual(response.summary.action_label, "观望")

    def test_history_list_matches_equivalent_suffixed_stock_codes(self) -> None:
        """Same-stock history should include rows saved with supported suffixed codes."""

        def save_record(code: str, query_id: str) -> None:
            result = self._build_result()
            result.code = code
            if "HK" in code:
                result.name = "腾讯控股"
            saved = self.db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type="simple",
                news_content="新闻摘要",
                context_snapshot=None,
                save_snapshot=False,
            )
            self.assertGreater(saved, 0)

        save_record("600519.SH", "query_cn_suffix")
        save_record("600519", "query_cn_plain")
        save_record("00700.HK", "query_hk_suffix")
        save_record("HK00700", "query_hk_prefix")

        service = HistoryService(self.db)

        cn_from_suffix = service.get_history_list(stock_code="600519.SH", page=1, limit=10)
        self.assertEqual(cn_from_suffix["total"], 2)
        self.assertEqual(
            {item["stock_code"] for item in cn_from_suffix["items"]},
            {"600519.SH", "600519"},
        )

        cn_from_plain = service.get_history_list(stock_code="600519", page=1, limit=10)
        self.assertEqual(cn_from_plain["total"], 2)
        self.assertEqual(
            {item["stock_code"] for item in cn_from_plain["items"]},
            {"600519.SH", "600519"},
        )

        hk_from_suffix = service.get_history_list(stock_code="00700.HK", page=1, limit=10)
        self.assertEqual(hk_from_suffix["total"], 2)
        self.assertEqual(
            {item["stock_code"] for item in hk_from_suffix["items"]},
            {"00700.HK", "HK00700"},
        )

        hk_from_prefix = service.get_history_list(stock_code="HK00700", page=1, limit=10)
        self.assertEqual(hk_from_prefix["total"], 2)
        self.assertEqual(
            {item["stock_code"] for item in hk_from_prefix["items"]},
            {"00700.HK", "HK00700"},
        )

    def test_history_list_matches_unpadded_hk_suffix_variants(self) -> None:
        """HK short suffix forms (e.g. 1810.HK) should match 5-digit canonical suffix/prefix forms."""

        def save_record(code: str, query_id: str) -> None:
            result = self._build_result()
            result.code = code
            if "HK" in code:
                result.name = "腾讯控股"
            saved = self.db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type="simple",
                news_content="新闻摘要",
                context_snapshot=None,
                save_snapshot=False,
            )
            self.assertGreater(saved, 0)

        save_record("1810.HK", "query_hk_unpadded")
        save_record("01810.HK", "query_hk_padded")
        save_record("HK01810", "query_hk_prefix")

        service = HistoryService(self.db)

        hk_from_suffix = service.get_history_list(stock_code="01810.HK", page=1, limit=10)
        self.assertEqual(hk_from_suffix["total"], 3)
        self.assertEqual(
            {item["stock_code"] for item in hk_from_suffix["items"]},
            {"1810.HK", "01810.HK", "HK01810"},
        )

        hk_from_prefix = service.get_history_list(stock_code="HK01810", page=1, limit=10)
        self.assertEqual(hk_from_prefix["total"], 3)
        self.assertEqual(
            {item["stock_code"] for item in hk_from_prefix["items"]},
            {"1810.HK", "01810.HK", "HK01810"},
        )

    def test_history_list_matches_sh_and_ss_suffixed_variants(self) -> None:
        """SH suffix and legacy `.SS` variants should be treated as the same A-share stock."""

        def save_record(code: str, query_id: str) -> None:
            result = self._build_result()
            result.code = code
            saved = self.db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type="simple",
                news_content="新闻摘要",
                context_snapshot=None,
                save_snapshot=False,
            )
            self.assertGreater(saved, 0)

        save_record("600519.SH", "query_cn_sh")
        save_record("600519.SS", "query_cn_ss")
        save_record("600519", "query_cn_plain")

        service = HistoryService(self.db)
        expected = {"600519.SH", "600519.SS", "600519"}

        from_sh = service.get_history_list(stock_code="600519.SH", page=1, limit=10)
        self.assertEqual(from_sh["total"], 3)
        self.assertEqual({item["stock_code"] for item in from_sh["items"]}, expected)

        from_ss = service.get_history_list(stock_code="600519.SS", page=1, limit=10)
        self.assertEqual(from_ss["total"], 3)
        self.assertEqual({item["stock_code"] for item in from_ss["items"]}, expected)

        from_plain = service.get_history_list(stock_code="600519", page=1, limit=10)
        self.assertEqual(from_plain["total"], 3)
        self.assertEqual({item["stock_code"] for item in from_plain["items"]}, expected)

    def test_history_detail_preserves_zero_change_pct(self) -> None:
        """change_pct=0.0（平盘）应原样返回，而不是被当成缺失值丢失。

        Regression for issue #1084: history endpoint used `or` chains that
        treated 0.0 as falsy and silently dropped the daily change.
        """
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        context_snapshot = {
            "enhanced_context": {
                "realtime": {"price": 100.0, "change_pct": 0.0},
            }
        }
        query_id = "query_change_pct_zero"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=context_snapshot,
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertEqual(report.meta.current_price, 100.0)
        self.assertEqual(report.meta.change_pct, 0.0)

    def test_history_detail_falls_back_to_realtime_quote_raw_change_pct(self) -> None:
        """缺少 enhanced_context.realtime.change_pct 时，应回退到 realtime_quote_raw。

        Regression for issue #1084: previously the realtime_quote_raw fallback
        was only consulted when current_price was missing, so reports with
        price-only enhanced_context lost their change_pct entirely.
        """
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        context_snapshot = {
            "enhanced_context": {
                "realtime": {"price": 200.0},
            },
            "realtime_quote_raw": {"change_pct": 1.23},
        }
        query_id = "query_change_pct_fallback"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=context_snapshot,
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertEqual(report.meta.current_price, 200.0)
        self.assertEqual(report.meta.change_pct, 1.23)

    def test_history_detail_reports_index_asset_type_from_canonical_code(self) -> None:
        """Index reports must expose meta.asset_type='index' so the Web can hide
        the stock-only watchlist action, and bare same-digit stock codes must
        remain 'stock' (never index via display normalization)."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        def save_record(code: str, query_id: str) -> int:
            result = self._build_result()
            result.code = code
            saved = self.db.save_analysis_history(
                result=result,
                query_id=query_id,
                report_type="simple",
                news_content="新闻摘要",
                context_snapshot=None,
                save_snapshot=False,
            )
            self.assertGreater(saved, 0)
            with self.db.get_session() as session:
                row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
                self.assertIsNotNone(row)
                return row.id

        index_id = save_record("sh000016", "query_asset_type_index")
        stock_id = save_record("000016", "query_asset_type_stock")
        stock_id2 = save_record("600519", "query_asset_type_stock2")

        index_report = get_history_detail(str(index_id), db_manager=self.db)
        self.assertEqual(index_report.meta.asset_type, "index")

        stock_report = get_history_detail(str(stock_id), db_manager=self.db)
        self.assertEqual(stock_report.meta.asset_type, "stock")

        stock_report2 = get_history_detail(str(stock_id2), db_manager=self.db)
        self.assertEqual(stock_report2.meta.asset_type, "stock")

    def test_history_detail_omits_asset_type_for_market_review(self) -> None:
        """Market review records must omit the optional asset_type field."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = self._build_result()
        result.code = "MARKET"
        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_asset_type_market_review",
            report_type="market_review",
            news_content="大盘复盘",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)
        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "query_asset_type_market_review").first()
            self.assertIsNotNone(row)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertIsNone(report.meta.asset_type)

    @patch("src.auth.is_auth_enabled", return_value=False)
    def test_history_detail_ignores_non_dict_realtime_quote_raw(self, mock_auth) -> None:
        """GET /api/v1/history/{id} should tolerate truthy non-dict realtime_quote_raw."""
        if TestClient is None or create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        context_snapshot = {
            "enhanced_context": {
                "realtime": {"price": 300.0},
            },
            "realtime_quote_raw": "not-a-dict",
        }
        query_id = "query_change_pct_non_dict_raw"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=context_snapshot,
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        static_dir = Path(self._temp_dir.name) / "empty-static"
        static_dir.mkdir(exist_ok=True)
        client = TestClient(create_app(static_dir=static_dir))

        response = client.get(f"/api/v1/history/{record_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["current_price"], 300.0)
        self.assertIsNone(payload["meta"]["change_pct"])

    def test_history_detail_accepts_dict_raw_result(self) -> None:
        """_record_to_detail_dict should handle dict raw_result without json.loads errors."""
        result = self._build_result()
        result.model_used = "gemini/gemini-2.0-flash"
        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_005",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "query_005").first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            row.raw_result = {"model_used": "unknown", "extra": "v"}

            service = HistoryService(self.db)
            detail = service._record_to_detail_dict(row)

        self.assertIsNotNone(detail)
        self.assertIsInstance(detail.get("raw_result"), dict)
        self.assertIsNone(detail.get("model_used"))

    def test_history_detail_prefers_raw_sniper_strings(self) -> None:
        """History detail should display the original sniper point strings from raw_result."""
        result = self._build_result()
        result.dashboard = {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "理想买入点：125.5元",
                    "secondary_buy": "120-121 元分批",
                    "stop_loss": "跌破 110 元止损",
                    "take_profit": "目标位：150.0元",
                }
            }
        }

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_006",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "query_006").first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        service = HistoryService(self.db)
        detail = service.get_history_detail_by_id(record_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.get("ideal_buy"), "理想买入点：125.5元")
        self.assertEqual(detail.get("secondary_buy"), "120-121 元分批")
        self.assertEqual(detail.get("stop_loss"), "跌破 110 元止损")
        self.assertEqual(detail.get("take_profit"), "目标位：150.0元")

    def test_history_detail_falls_back_to_numeric_sniper_columns(self) -> None:
        """History detail should still fall back to stored numeric sniper columns when raw strings are unavailable."""
        result = self._build_result()
        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_007",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "query_007").first()
            if row is None:
                self.fail("未找到保存的历史记录")
            row.ideal_buy = 125.5
            row.secondary_buy = 120.0
            row.stop_loss = 110.0
            row.take_profit = 150.0
            row.raw_result = json.dumps({"model_used": "gemini/gemini-2.0-flash"})
            session.commit()
            self.assertEqual(row.id, saved)
            record_id = row.id

        service = HistoryService(self.db)
        detail = service.get_history_detail_by_id(record_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.get("ideal_buy"), "125.5")
        self.assertEqual(detail.get("secondary_buy"), "120.0")
        self.assertEqual(detail.get("stop_loss"), "110.0")
        self.assertEqual(detail.get("take_profit"), "150.0")

    def test_history_detail_uses_fundamental_snapshot_fallback_when_context_missing(self) -> None:
        """When context_snapshot is disabled, detail API should fallback to fundamental_snapshot."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = self._build_result()
        query_id = "query_fundamental_fallback_001"
        saved = self.db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        self.db.save_fundamental_snapshot(
            query_id=query_id,
            code="600519",
            payload={
                "belong_boards": [{"name": "白酒", "type": "行业"}],
                "boards": {
                    "data": {
                        "top": [{"name": "白酒", "change_pct": 2.6}],
                        "bottom": [],
                    }
                },
                "concept_boards": {
                    "data": {
                        "top": [{"name": "机器人概念", "change_pct": 4.2}],
                        "bottom": [],
                    }
                },
                "earnings": {
                    "data": {
                        "financial_report": {"report_date": "2025-12-31", "revenue": 1000},
                        "dividend": {"ttm_dividend_yield_pct": 2.6, "ttm_cash_dividend_per_share": 1.3},
                    }
                }
            },
        )

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertEqual(report.details.financial_report["report_date"], "2025-12-31")
        self.assertEqual(report.details.dividend_metrics["ttm_dividend_yield_pct"], 2.6)
        self.assertEqual(report.details.belong_boards, [{"name": "白酒", "type": "行业"}])
        self.assertEqual(report.details.sector_rankings["top"][0]["name"], "白酒")
        self.assertEqual(report.details.concept_rankings["top"][0]["name"], "机器人概念")

    def test_history_detail_uses_raw_code_for_legacy_jp_kr_fundamental_snapshot(self) -> None:
        """Legacy bare JP/KR history rows should display suffixes but read snapshots by stored code."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = self._build_result()
        result.code = "005930"
        result.name = "Samsung Electronics"
        query_id = "query_kr_raw_fundamental_fallback"
        saved = self.db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="simple",
            news_content="news",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        self.db.save_fundamental_snapshot(
            query_id=query_id,
            code="005930",
            payload={
                "earnings": {
                    "data": {
                        "financial_report": {"report_date": "2025-12-31", "revenue": 1000},
                        "dividend": {"ttm_dividend_yield_pct": 2.6},
                    }
                }
            },
        )

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        with patch("src.services.history_service.resolve_index_stock_code", return_value="005930.KS"):
            report = get_history_detail(str(record_id), db_manager=self.db)

        self.assertEqual(report.meta.stock_code, "005930.KS")
        self.assertEqual(report.details.financial_report["report_date"], "2025-12-31")
        self.assertEqual(report.details.dividend_metrics["ttm_dividend_yield_pct"], 2.6)

    def test_history_detail_preserves_unavailable_board_rankings_state(self) -> None:
        """Failed board ranking blocks should remain unavailable in detail response."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        query_id = "query_fundamental_failed_boards_001"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        fallback_fundamental = {
            "belong_boards": [{"name": "白酒", "type": "行业"}],
            "boards": {
                "status": "failed",
                "data": {},
            },
        }
        saved_snapshot = self.db.save_fundamental_snapshot(
            query_id=query_id,
            code="600519",
            payload=fallback_fundamental,
        )
        self.assertGreater(saved_snapshot, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertEqual(report.details.belong_boards, [{"name": "白酒", "type": "行业"}])
        self.assertIsNone(report.details.sector_rankings)

    def test_history_detail_returns_null_fundamental_fields_when_snapshot_absent(self) -> None:
        """Detail API should keep new fields nullable when no context/fundamental snapshot exists."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        query_id = "query_fundamental_fallback_002"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertIsNone(report.details.financial_report)
        self.assertIsNone(report.details.dividend_metrics)
        self.assertEqual(report.details.belong_boards, [])
        self.assertIsNone(report.details.sector_rankings)

    def test_history_detail_returns_empty_related_boards_for_non_cn(self) -> None:
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = AnalysisResult(
            code="AAPL",
            name="Apple",
            sentiment_score=65,
            trend_prediction="Bullish",
            operation_advice="Hold",
            analysis_summary="US stock test",
        )
        query_id = "query_non_cn_board_001"
        saved = self.db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="simple",
            news_content="news",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertEqual(report.details.belong_boards, [])
        self.assertIsNone(report.details.sector_rankings)

    def test_history_detail_reads_agent_snapshot_related_boards_shape(self) -> None:
        """Agent-mode snapshots store fundamental_context/realtime_quote at the top level."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        context_snapshot = {
            "fundamental_context": {
                "belong_boards": [{"name": "白酒", "type": "行业"}],
                "boards": {
                    "data": {
                        "top": [{"name": "白酒", "change_pct": 2.8}],
                        "bottom": [],
                    }
                },
            },
            "realtime_quote": {
                "price": 1888.0,
                "change_pct": 1.56,
            },
        }
        query_id = "query_agent_snapshot_boards_001"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=context_snapshot,
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertEqual(report.meta.current_price, 1888.0)
        self.assertEqual(report.meta.change_pct, 1.56)
        self.assertEqual(report.details.belong_boards, [{"name": "白酒", "type": "行业"}])
        self.assertEqual(report.details.sector_rankings["top"][0]["name"], "白酒")

    def test_history_detail_returns_overview_and_sanitizes_snapshot(self) -> None:
        """History detail exposes the public overview separately from raw snapshot JSON."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        overview = _analysis_context_pack_overview()
        phase_summary = _market_phase_summary()
        query_id = "query_context_pack_overview_001"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot={
                "enhanced_context": {"code": "600519"},
                "analysis_context_pack_overview": overview,
                "market_phase_summary": {
                    **phase_summary,
                    "market_phase_context": {"raw": True},
                },
            },
            save_snapshot=True,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertEqual(
            report.details.analysis_context_pack_overview.metadata.trigger_source,
            "api",
        )
        self.assertEqual(
            report.details.analysis_context_pack_overview.data_quality.overall_score,
            100,
        )
        self.assertIsNotNone(report.meta.market_phase_summary)
        self.assertEqual(report.meta.market_phase_summary.phase, "intraday")
        self.assertEqual(report.meta.market_phase_summary.minutes_to_close, 300)
        self.assertEqual(report.details.analysis_context_pack_overview.metadata.news_result_count, 2)
        self.assertNotIn(
            "analysis_context_pack_overview",
            report.details.context_snapshot,
        )
        self.assertNotIn(
            "market_phase_summary",
            report.details.context_snapshot,
        )

    def test_history_detail_handles_missing_overview_when_snapshot_disabled(self) -> None:
        """SAVE_CONTEXT_SNAPSHOT=false style records should not require an overview."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        query_id = "query_context_pack_snapshot_disabled_001"
        saved = self.db.save_analysis_history(
            result=self._build_result(),
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot={
                "enhanced_context": {"code": "600519"},
                "analysis_context_pack_overview": _analysis_context_pack_overview(),
            },
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id
            self.assertIsNone(row.context_snapshot)

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertIsNone(report.meta.market_phase_summary)
        self.assertIsNone(report.details.analysis_context_pack_overview)
        self.assertIsNone(report.details.context_snapshot)

    def test_history_detail_restores_market_structure_from_raw_result_without_snapshot(self) -> None:
        """SAVE_CONTEXT_SNAPSHOT=false should still expose market_structure saved in raw_result."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        market_structure = {
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
        result = self._build_result()
        result.market_structure_context = market_structure
        query_id = "query_market_structure_snapshot_disabled_001"
        saved = self.db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot={"market_structure_context": {"ignored": True}},
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == query_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            self.assertIsNone(row.context_snapshot)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)
        self.assertIsNone(report.details.context_snapshot)
        self.assertEqual(
            report.details.market_structure["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )
        self.assertEqual(
            report.details.raw_result["market_structure_context"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )
        self.assertNotIn(
            "raw_result",
            report.details.raw_result,
        )

    def test_history_markdown_localizes_english_report_and_placeholder_name(self) -> None:
        """History markdown should preserve report_language for English reports."""
        result = AnalysisResult(
            code="AAPL",
            name="股票AAPL",
            sentiment_score=78,
            trend_prediction="Bullish",
            operation_advice="Buy",
            analysis_summary="Momentum remains constructive.",
            report_language="en",
            dashboard={
                "core_conclusion": {
                    "one_sentence": "Favor buying on pullbacks.",
                    "position_advice": {
                        "no_position": "Open a starter position.",
                        "has_position": "Hold and trail the stop.",
                    },
                },
                "intelligence": {
                    "risk_alerts": [],
                },
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": "180-182",
                        "stop_loss": "172",
                        "take_profit": "195",
                    }
                },
            },
        )

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_english_markdown_001",
            report_type="full",
            news_content="news",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_english_markdown_001"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        markdown = HistoryService(self.db).get_markdown_report(str(record_id))

        self.assertIsNotNone(markdown)
        self.assertIn("Stock Analysis Report", markdown)
        self.assertIn("Core Conclusion", markdown)
        self.assertIn("Unnamed Stock (AAPL)", markdown)
        self.assertNotIn("核心结论", markdown)

    def test_history_markdown_signal_metadata_uses_explicit_avoid_action(self) -> None:
        result = AnalysisResult(
            code="AAPL",
            name="Apple",
            sentiment_score=90,
            trend_prediction="Bullish",
            operation_advice="Hold",
            analysis_summary="Risk remains elevated.",
            report_language="en",
            action="avoid",
            action_label="Avoid",
        )

        markdown = HistoryService(self.db)._generate_single_stock_markdown(
            result,
            MagicMock(created_at=None),
        )

        self.assertIn("**🟡 Avoid** | Bullish", markdown)
        self.assertNotIn("Strong Buy", markdown)

    def test_history_markdown_handles_legacy_strategy_synthesis_shapes(self) -> None:
        service = HistoryService(self.db)
        record = MagicMock(created_at=None)

        for malformed in ("bad-shape", ["bad-shape"], 42, True):
            result = AnalysisResult(
                code="600519",
                name="贵州茅台",
                sentiment_score=50,
                trend_prediction="震荡",
                operation_advice="观望",
                report_language="zh",
                dashboard={
                    "core_conclusion": {"one_sentence": "测试"},
                    "intelligence": {},
                    "battle_plan": {},
                    "strategy_synthesis": malformed,
                },
            )

            markdown = service._generate_single_stock_markdown(result, record)

            self.assertNotIn("多策略综合", markdown)

        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="观望",
            report_language="zh",
            dashboard={
                "core_conclusion": {"one_sentence": "测试"},
                "intelligence": {},
                "battle_plan": {},
                "strategy_synthesis": {
                    "final_signal": "hold",
                    "consensus_level": "insufficient",
                    "conflict_severity": "none",
                    "conflict_count": 0,
                    "supporting_skills": "bad-shape",
                    "opposing_skills": ["bad-shape"],
                    "conflicts": "bad-shape",
                    "summary_params": {"invalid_opinion_count": "3"},
                },
            },
        )

        markdown = service._generate_single_stock_markdown(result, record)

        self.assertIn("多策略综合", markdown)
        self.assertIn("另有 3 个策略解析失败", markdown)

    def test_history_markdown_returns_persisted_market_review_report(self) -> None:
        """Market review history should return the saved Markdown without rebuilding a stock report."""
        result = AnalysisResult(
            code="MARKET",
            name="大盘复盘",
            sentiment_score=50,
            trend_prediction="大盘复盘",
            operation_advice="查看复盘",
            analysis_summary="今日大盘复盘",
            raw_response="# 🎯 大盘复盘\n\n## 今日大盘\n\n复盘正文",
        )

        saved = self.db.save_analysis_history(
            result=result,
            query_id="market_review_query_001",
            report_type="market_review",
            news_content="## 今日大盘\n\n复盘正文",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "market_review_query_001"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        markdown = HistoryService(self.db).get_markdown_report(str(record_id))

        self.assertEqual(markdown, "# 🎯 大盘复盘\n\n## 今日大盘\n\n复盘正文")

    def test_history_markdown_collapses_unavailable_chip_structure(self) -> None:
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=72,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="稳健",
            dashboard={
                "data_perspective": {
                    "chip_structure": {
                        "profit_ratio": "数据缺失，无法判断",
                        "avg_cost": "数据缺失，无法判断",
                        "concentration": "数据缺失，无法判断",
                        "chip_health": "数据缺失，无法判断",
                    }
                }
            },
        )

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_chip_unavailable_001",
            report_type="full",
            news_content="news",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_chip_unavailable_001"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        markdown = HistoryService(self.db).get_markdown_report(str(record_id))

        self.assertIsNotNone(markdown)
        self.assertIn("**筹码**: 筹码分布未启用或数据源暂不可用，未纳入筹码判断。", markdown)
        self.assertEqual(markdown.count("数据缺失，无法判断"), 0)

    def test_history_detail_returns_persisted_market_review_report(self) -> None:
        """Market review detail should surface the saved recap content for Web history clicks."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        report_content = "# 🎯 大盘复盘\n\n## 今日大盘\n\n复盘正文"
        result = AnalysisResult(
            code="MARKET",
            name="大盘复盘",
            sentiment_score=50,
            trend_prediction="大盘复盘",
            operation_advice="查看复盘",
            analysis_summary="今日大盘复盘",
            raw_response=report_content,
        )

        saved = self.db.save_analysis_history(
            result=result,
            query_id="market_review_query_detail_001",
            report_type="market_review",
            news_content="## 今日大盘\n\n复盘正文",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "market_review_query_detail_001"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)

        self.assertEqual(report.meta.report_type, "market_review")
        self.assertEqual(report.summary.analysis_summary, "今日大盘复盘")
        self.assertIsNone(report.summary.action)
        self.assertIsNone(report.summary.action_label)
        self.assertEqual(report.details.news_content, report_content)

    def test_market_review_summary_falls_back_to_sanitized_excerpt(self) -> None:
        service = HistoryService(self.db)
        markdown = (
            "[dsa-market-region]: # (cn)\n\n"
            "# 🎯 大盘复盘\n\n"
            "## 今日观点\n\n"
            "**成交活跃**，关注 [科技板块](https://example.com)。\n\n"
            "| 指标 | 数值 |\n| --- | --- |\n| 涨跌 | +1% |\n\n"
            "```json\n{\"internal\": true}\n```"
        )

        summary = service._market_review_summary("  ", markdown)

        self.assertEqual(summary, "🎯 大盘复盘 今日观点 成交活跃，关注 科技板块。 指标 数值 涨跌 +1%")
        self.assertNotIn("dsa-market-region", summary)
        self.assertNotIn("internal", summary)

    def test_market_review_summary_prefers_persisted_summary_and_truncates_fallback(self) -> None:
        service = HistoryService(self.db)

        self.assertEqual(
            service._market_review_summary(" 已保存的短摘要 ", "# 不应使用"),
            "已保存的短摘要",
        )
        self.assertEqual(
            service._market_review_summary(None, "# " + "复" * 130),
            "复" * 120 + "…",
        )
        self.assertIsNone(service._market_review_summary(None, "[dsa-market-region]: # (cn)"))

    def test_history_detail_localizes_english_summary_fields(self) -> None:
        """History detail should localize summary enums for English reports."""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        result = AnalysisResult(
            code="AAPL",
            name="股票AAPL",
            sentiment_score=78,
            trend_prediction="看多",
            operation_advice="买入",
            analysis_summary="Momentum remains constructive.",
            report_language="en",
        )

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_english_detail_001",
            report_type="full",
            news_content="news",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_english_detail_001"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        report = get_history_detail(str(record_id), db_manager=self.db)

        self.assertEqual(report.meta.report_language, "en")
        self.assertEqual(report.meta.stock_name, "Unnamed Stock")
        self.assertEqual(report.summary.operation_advice, "Buy")
        self.assertEqual(report.summary.action, "buy")
        self.assertEqual(report.summary.action_label, "Buy")
        self.assertEqual(report.summary.trend_prediction, "Bullish")
        self.assertEqual(report.summary.sentiment_label, "Bullish")

    def test_history_markdown_uses_safe_bias_emoji_for_english_status(self) -> None:
        """English bias status should keep the correct non-risk emoji in markdown."""
        result = AnalysisResult(
            code="AAPL",
            name="股票AAPL",
            sentiment_score=80,
            trend_prediction="Bullish",
            operation_advice="Buy",
            analysis_summary="Momentum remains constructive.",
            report_language="en",
            dashboard={
                "data_perspective": {
                    "price_position": {
                        "current_price": 190.5,
                        "ma5": 188.0,
                        "ma10": 184.5,
                        "ma20": 179.2,
                        "bias_ma5": 1.33,
                        "bias_status": "Safe",
                        "support_level": 184.5,
                        "resistance_level": 195.0,
                    }
                }
            },
        )

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_english_markdown_bias_001",
            report_type="full",
            news_content="news",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_english_markdown_bias_001"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.id, saved)
            record_id = row.id

        markdown = HistoryService(self.db).get_markdown_report(str(record_id))

        self.assertIsNotNone(markdown)
        self.assertIn("✅Safe", markdown)
        self.assertNotIn("🚨Safe", markdown)

    def test_delete_analysis_history_records_also_cleans_backtests_and_decision_signals(self) -> None:
        """删除历史记录时应一并清理关联回测结果和决策信号。"""
        record_id = self._save_history("query_delete_001")
        linked_signal_id = None

        with self.db.session_scope() as session:
            session.add(BacktestResult(
                analysis_history_id=record_id,
                code="600519",
                analysis_date=None,
                eval_window_days=10,
                engine_version="v1",
                eval_status="pending",
            ))
            linked_signal = DecisionSignalRecord(
                stock_code="600519",
                stock_name="贵州茅台",
                market="cn",
                source_type="analysis",
                source_report_id=record_id,
                trace_id="trace-delete-linked",
                market_phase="intraday",
                trigger_source="api",
                action="buy",
                action_label="买入",
                reason="linked",
                plan_quality="minimal",
                status="active",
            )
            session.add(linked_signal)
            session.flush()
            linked_signal_id = linked_signal.id
            session.add(DecisionSignalOutcomeRecord(
                signal_id=linked_signal_id,
                horizon="3d",
                engine_version="decision-signal-v1",
                eval_status="completed",
                outcome="hit",
                action="buy",
                market="cn",
                source_type="analysis",
                plan_quality="minimal",
                holding_state="holding",
            ))
            session.add(DecisionSignalFeedbackRecord(
                signal_id=linked_signal_id,
                feedback_value="useful",
                source="api",
            ))
            session.add(DecisionSignalRecord(
                stock_code="000001",
                stock_name="平安银行",
                market="cn",
                source_type="analysis",
                source_report_id=record_id + 999,
                trace_id="trace-delete-unrelated",
                market_phase="intraday",
                trigger_source="api",
                action="watch",
                action_label="观望",
                reason="unrelated",
                plan_quality="minimal",
                status="active",
            ))

        deleted = self.db.delete_analysis_history_records([record_id])
        self.assertEqual(deleted, 1)

        with self.db.get_session() as session:
            self.assertIsNone(session.query(AnalysisHistory).filter(AnalysisHistory.id == record_id).first())
            self.assertEqual(
                session.query(BacktestResult).filter(BacktestResult.analysis_history_id == record_id).count(),
                0,
            )
            self.assertEqual(
                session.query(DecisionSignalRecord).filter(DecisionSignalRecord.source_report_id == record_id).count(),
                0,
            )
            self.assertEqual(
                session.query(DecisionSignalOutcomeRecord).filter(
                    DecisionSignalOutcomeRecord.signal_id == linked_signal_id
                ).count(),
                0,
            )
            self.assertEqual(
                session.query(DecisionSignalFeedbackRecord).filter(
                    DecisionSignalFeedbackRecord.signal_id == linked_signal_id
                ).count(),
                0,
            )
            self.assertEqual(
                session.query(DecisionSignalRecord).filter(DecisionSignalRecord.trace_id == "trace-delete-unrelated").count(),
                1,
            )

    def test_delete_analysis_history_records_keeps_signals_for_nonexistent_history_id(self) -> None:
        """不存在的历史 ID 不应触发弱关联 DecisionSignal 清理。"""
        missing_id = 987654321

        with self.db.session_scope() as session:
            session.add(DecisionSignalRecord(
                stock_code="600519",
                stock_name="贵州茅台",
                market="cn",
                source_type="manual",
                source_report_id=missing_id,
                trace_id="trace-delete-missing-history",
                market_phase="intraday",
                trigger_source="api",
                action="watch",
                action_label="观望",
                reason="manual signal with unverified report id",
                plan_quality="minimal",
                status="active",
            ))

        deleted = self.db.delete_analysis_history_records([missing_id])
        self.assertEqual(deleted, 0)

        with self.db.get_session() as session:
            self.assertEqual(
                session.query(DecisionSignalRecord).filter(
                    DecisionSignalRecord.trace_id == "trace-delete-missing-history"
                ).count(),
                1,
            )

    def test_delete_analysis_history_records_keeps_manual_signal_with_same_report_id(self) -> None:
        """source_report_id 是弱引用，真实 history 删除不应误删 manual/pre-report 信号。"""
        record_id = self._save_history("query_delete_manual_collision")

        with self.db.session_scope() as session:
            session.add(DecisionSignalRecord(
                stock_code="600519",
                stock_name="贵州茅台",
                market="cn",
                source_type="analysis",
                source_report_id=record_id,
                trace_id="trace-delete-analysis-bound",
                market_phase="intraday",
                trigger_source="api",
                action="buy",
                action_label="买入",
                reason="history-bound signal",
                plan_quality="minimal",
                status="active",
            ))
            session.add(DecisionSignalRecord(
                stock_code="600519",
                stock_name="贵州茅台",
                market="cn",
                source_type="manual",
                source_report_id=record_id,
                trace_id="trace-delete-manual-weak-ref",
                market_phase="intraday",
                trigger_source="api",
                action="watch",
                action_label="观望",
                reason="manual signal with caller-supplied report id",
                plan_quality="minimal",
                status="active",
            ))

        deleted = self.db.delete_analysis_history_records([record_id])
        self.assertEqual(deleted, 1)

        with self.db.get_session() as session:
            self.assertEqual(
                session.query(DecisionSignalRecord).filter(
                    DecisionSignalRecord.trace_id == "trace-delete-analysis-bound"
                ).count(),
                0,
            )
            self.assertEqual(
                session.query(DecisionSignalRecord).filter(
                    DecisionSignalRecord.trace_id == "trace-delete-manual-weak-ref"
                ).count(),
                1,
            )

    def test_delete_analysis_history_records_cleans_only_existing_ids_in_mixed_batch(self) -> None:
        """混合存在/不存在 ID 时，只清理实际存在历史记录的关联数据。"""
        record_id = self._save_history("query_delete_mixed")
        missing_id = record_id + 987654

        with self.db.session_scope() as session:
            session.add(BacktestResult(
                analysis_history_id=record_id,
                code="600519",
                analysis_date=None,
                eval_window_days=10,
                engine_version="v1",
                eval_status="pending",
            ))
            session.add(DecisionSignalRecord(
                stock_code="600519",
                stock_name="贵州茅台",
                market="cn",
                source_type="analysis",
                source_report_id=record_id,
                trace_id="trace-delete-mixed-linked",
                market_phase="intraday",
                trigger_source="api",
                action="buy",
                action_label="买入",
                reason="linked",
                plan_quality="minimal",
                status="active",
            ))
            session.add(DecisionSignalRecord(
                stock_code="000001",
                stock_name="平安银行",
                market="cn",
                source_type="manual",
                source_report_id=missing_id,
                trace_id="trace-delete-mixed-missing",
                market_phase="intraday",
                trigger_source="api",
                action="watch",
                action_label="观望",
                reason="weak report id collision",
                plan_quality="minimal",
                status="active",
            ))

        deleted = self.db.delete_analysis_history_records([record_id, missing_id])
        self.assertEqual(deleted, 1)

        with self.db.get_session() as session:
            self.assertIsNone(session.query(AnalysisHistory).filter(AnalysisHistory.id == record_id).first())
            self.assertEqual(
                session.query(BacktestResult).filter(BacktestResult.analysis_history_id == record_id).count(),
                0,
            )
            self.assertEqual(
                session.query(DecisionSignalRecord).filter(
                    DecisionSignalRecord.trace_id == "trace-delete-mixed-linked"
                ).count(),
                0,
            )
            self.assertEqual(
                session.query(DecisionSignalRecord).filter(
                    DecisionSignalRecord.trace_id == "trace-delete-mixed-missing"
                ).count(),
                1,
            )

    @patch("src.auth.is_auth_enabled", return_value=False)
    def test_delete_history_api_deletes_selected_records(self, mock_auth) -> None:
        """DELETE /api/v1/history should remove only the requested records."""
        if TestClient is None or create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        record_id_1 = self._save_history("query_delete_api_001")
        record_id_2 = self._save_history("query_delete_api_002")

        static_dir = Path(self._temp_dir.name) / "empty-static"
        static_dir.mkdir(exist_ok=True)
        client = TestClient(create_app(static_dir=static_dir))

        response = client.request(
            "DELETE",
            "/api/v1/history",
            json={"record_ids": [record_id_1]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("deleted"), 1)

        with self.db.get_session() as session:
            self.assertIsNone(session.query(AnalysisHistory).filter(AnalysisHistory.id == record_id_1).first())
            self.assertIsNotNone(session.query(AnalysisHistory).filter(AnalysisHistory.id == record_id_2).first())

    def test_empty_news_state_round_trips_through_history_markdown(self) -> None:
        """持久化、重建和历史 Markdown 必须保留三态披露。"""
        no_channel = "⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。"
        zero_hit = "⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。"
        service = HistoryService(self.db)

        for suffix, count, expected in (
            ("none", None, no_channel),
            ("zero", 0, zero_hit),
            ("hits", 3, None),
        ):
            with self.subTest(state=suffix):
                result = self._build_result()
                result.news_result_count = count
                result.news_summary = ""
                query_id = f"query_empty_news_round_trip_{suffix}"
                record_id = self.db.save_analysis_history(
                    result=result,
                    query_id=query_id,
                    report_type="full",
                    news_content=None,
                    context_snapshot=None,
                    save_snapshot=False,
                )
                self.assertGreater(record_id, 0)

                with self.db.get_session() as session:
                    row = session.query(AnalysisHistory).filter(
                        AnalysisHistory.id == record_id
                    ).first()
                    if row is None:
                        self.fail("未找到保存的历史记录")
                    raw_result = json.loads(row.raw_result or "{}")
                    self.assertIn("news_result_count", raw_result)
                    self.assertEqual(raw_result["news_result_count"], count)
                    self.assertIs(raw_result["news_result_count_known"], True)
                    rebuilt = service._rebuild_analysis_result(raw_result, row)

                self.assertIsNotNone(rebuilt)
                self.assertEqual(rebuilt.news_result_count, count)
                self.assertTrue(rebuilt.news_result_count_known)
                markdown = service.get_markdown_report(str(record_id))
                self.assertIsNotNone(markdown)
                if expected is None:
                    self.assertNotIn(no_channel, markdown)
                    self.assertNotIn(zero_hit, markdown)
                else:
                    self.assertIn(expected, markdown)

                if get_history_detail is not None:
                    report = get_history_detail(str(record_id), db_manager=self.db)
                    self.assertEqual(report.details.empty_news_disclosure, expected)

    def test_legacy_history_without_news_count_stays_silent(self) -> None:
        """旧记录缺少计数字段时状态未知，不能倒推为未配置渠道。"""
        no_channel = "⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。"
        zero_hit = "⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。"
        record_id = self.db.save_analysis_history(
            result=self._build_result(),
            query_id="query_legacy_empty_news_unknown",
            report_type="full",
            news_content=None,
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(record_id, 0)

        with self.db.session_scope() as session:
            row = session.query(AnalysisHistory).filter(AnalysisHistory.id == record_id).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            raw_result = json.loads(row.raw_result or "{}")
            raw_result.pop("news_result_count", None)
            raw_result.pop("news_result_count_known", None)
            row.raw_result = json.dumps(raw_result, ensure_ascii=False)

        record = self.db.get_analysis_history_by_id(record_id)
        self.assertIsNotNone(record)
        rebuilt = HistoryService(self.db)._rebuild_analysis_result(raw_result, record)
        self.assertIsNotNone(rebuilt)
        self.assertFalse(rebuilt.news_result_count_known)

        markdown = HistoryService(self.db).get_markdown_report(str(record_id))
        self.assertNotIn(no_channel, markdown or "")
        self.assertNotIn(zero_hit, markdown or "")
        if get_history_detail is not None:
            report = get_history_detail(str(record_id), db_manager=self.db)
            self.assertIsNone(report.details.empty_news_disclosure)

    # ------------------------------------------------------------------
    # PR #2312: 指数 canonical 历史隔离（并入本类，避免子类重复继承放大测试）
    # ------------------------------------------------------------------
    def _save_result_with_code(self, code: str, query_id: str) -> int:
        result = self._build_result()
        result.code = code
        saved = self.db.save_analysis_history(
            result=result,
            query_id=query_id,
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=None,
            save_snapshot=False,
        )
        self.assertGreater(saved, 0)
        return saved

    def test_history_filter_isolates_index_from_same_code_stock(self):
        self._save_result_with_code("sh000016", "query_index")
        self._save_result_with_code("000016", "query_stock")

        index_listing = HistoryService(self.db).get_history_list(
            stock_code="sh000016", page=1, limit=10
        )
        stock_listing = HistoryService(self.db).get_history_list(
            stock_code="000016", page=1, limit=10
        )

        self.assertEqual(index_listing["total"], 1)
        self.assertEqual(
            {item["query_id"] for item in index_listing["items"]},
            {"query_index"},
        )
        self.assertEqual(stock_listing["total"], 1)
        self.assertEqual(
            {item["query_id"] for item in stock_listing["items"]},
            {"query_stock"},
        )

    def test_history_filter_reaches_legacy_uppercase_and_alias_index_records(self):
        self._save_result_with_code("sh000016", "query_canonical")
        self._save_result_with_code("SH000016", "query_upper")
        self._save_result_with_code("000016.SH", "query_alias")

        for code in ("sh000016", "SH000016", "000016.SH"):
            listing = HistoryService(self.db).get_history_list(
                stock_code=code, page=1, limit=10
            )
            self.assertEqual(listing["total"], 3)
            self.assertEqual(
                {item["query_id"] for item in listing["items"]},
                {"query_canonical", "query_upper", "query_alias"},
            )

        stock_listing = HistoryService(self.db).get_history_list(
            stock_code="000016", page=1, limit=10
        )
        self.assertEqual(stock_listing["total"], 0)

    def test_sz_index_history_filter_and_delete_isolate_from_same_code_stock(self):
        """I/O matrix INDEX_HISTORY 的 SZ 侧真实 SQL 路径：``sz399001``
        lowercase canonical 筛选、删除与计数均命中自身记录，不并入裸
        ``399001`` 股票。"""
        self._save_result_with_code("sz399001", "query_sz_index")
        self._save_result_with_code("399001", "query_sz_stock")

        sz_listing = HistoryService(self.db).get_history_list(
            stock_code="sz399001", page=1, limit=10
        )
        stock_listing = HistoryService(self.db).get_history_list(
            stock_code="399001", page=1, limit=10
        )
        self.assertEqual(sz_listing["total"], 1)
        self.assertEqual(
            {item["query_id"] for item in sz_listing["items"]},
            {"query_sz_index"},
        )
        self.assertEqual(stock_listing["total"], 1)
        self.assertEqual(
            {item["query_id"] for item in stock_listing["items"]},
            {"query_sz_stock"},
        )

        if delete_history_by_code is not None:
            response = delete_history_by_code("sz399001", db_manager=self.db)
            self.assertEqual(response.deleted, 1)
            remaining = HistoryService(self.db).get_history_list(
                stock_code="399001", page=1, limit=10
            )
            self.assertEqual(remaining["total"], 1)
            self.assertEqual(
                {item["query_id"] for item in remaining["items"]},
                {"query_sz_stock"},
            )

    def test_history_detail_displays_parser_canonical_for_legacy_index_record(self):
        """报告详情 meta 对旧 uppercase/alias 指数记录输出 parser canonical。"""
        if get_history_detail is None:
            self.skipTest("fastapi is not installed in this test environment")

        self._save_result_with_code("SZ399300", "query_sz399300_upper")
        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).filter(
                AnalysisHistory.query_id == "query_sz399300_upper"
            ).first()
            if row is None:
                self.fail("未找到保存的历史记录")

        report = get_history_detail(str(row.id), db_manager=self.db)
        self.assertEqual(report.meta.stock_code, "sh000300")
        self.assertEqual(report.meta.asset_type, "index")

    def test_history_list_displays_parser_canonical_for_legacy_index_records(self):
        """已登记指数旧记录（uppercase legacy / 显式 alias）的 API
        ``stock_code`` 输出 parser canonical（``sz399300``/``000300.CSI`` ->
        ``sh000300``），前端只做大小写折叠即可，无需前缀/后缀正则猜 canonical。"""
        self._save_result_with_code("SZ399300", "query_sz399300_upper")
        self._save_result_with_code("000300.CSI", "query_000300_csi")

        listing = HistoryService(self.db).get_history_list(page=1, limit=10)
        by_query = {item["query_id"]: item for item in listing["items"]}
        self.assertEqual(by_query["query_sz399300_upper"]["stock_code"], "sh000300")
        self.assertEqual(by_query["query_000300_csi"]["stock_code"], "sh000300")

    def test_sh300_uppercase_alias_filter_delete_and_stock_bar_count_real_sql(self):
        """sqlite ``IN`` 大小写敏感回归：``SZ399300``/``sz399300``/
        ``000300.CSI``/``sh000300`` 任一查询都命中全部显式形态旧记录（含
        uppercase alias 持久化记录），并与裸 ``000300`` 股票隔离。"""
        self._save_result_with_code("sh000300", "query_canonical")
        self._save_result_with_code("SZ399300", "query_uppercase_alias")
        self._save_result_with_code("000300.CSI", "query_dotted_alias")
        self._save_result_with_code("000300", "query_bare_stock")

        for code in ("sh000300", "sz399300", "SZ399300", "000300.CSI"):
            listing = HistoryService(self.db).get_history_list(
                stock_code=code, page=1, limit=10
            )
            self.assertEqual(listing["total"], 3)
            self.assertEqual(
                {item["query_id"] for item in listing["items"]},
                {"query_canonical", "query_uppercase_alias", "query_dotted_alias"},
            )

        stock_listing = HistoryService(self.db).get_history_list(
            stock_code="000300", page=1, limit=10
        )
        self.assertEqual(stock_listing["total"], 1)
        self.assertEqual(
            {item["query_id"] for item in stock_listing["items"]},
            {"query_bare_stock"},
        )

        if get_stock_bar is not None:
            stock_bar = get_stock_bar(
                start_date=None,
                end_date=None,
                limit=10,
                db_manager=self.db,
            )
            self.assertEqual(len(stock_bar.items), 2)
            index_item = next(
                item for item in stock_bar.items if item.asset_type == "index"
            )
            stock_item = next(
                item for item in stock_bar.items if item.asset_type == "stock"
            )
            self.assertEqual(index_item.stock_code, "sh000300")
            self.assertEqual(index_item.analysis_count, 3)
            self.assertEqual(stock_item.stock_code, "000300")
            self.assertEqual(stock_item.analysis_count, 1)

        if delete_history_by_code is not None:
            response = delete_history_by_code("SZ399300", db_manager=self.db)
            self.assertEqual(response.deleted, 3)
            remaining = HistoryService(self.db).get_history_list(
                stock_code="000300", page=1, limit=10
            )
            self.assertEqual(remaining["total"], 1)
            self.assertEqual(
                {item["query_id"] for item in remaining["items"]},
                {"query_bare_stock"},
            )

    def test_stock_bar_isolates_index_and_same_code_stock(self):
        if get_stock_bar is None:
            self.skipTest("fastapi is not installed in this test environment")

        self._save_result_with_code("sh000016", "query_index")
        self._save_result_with_code("000016", "query_stock")

        stock_bar = get_stock_bar(
            start_date=None,
            end_date=None,
            limit=10,
            db_manager=self.db,
        )

        self.assertEqual(len(stock_bar.items), 2)
        by_code = {item.stock_code: item for item in stock_bar.items}
        self.assertIn("sh000016", by_code)
        self.assertIn("000016", by_code)
        self.assertEqual(by_code["sh000016"].analysis_count, 1)
        self.assertEqual(by_code["000016"].analysis_count, 1)
        self.assertEqual(by_code["sh000016"].asset_type, "index")
        self.assertEqual(by_code["000016"].asset_type, "stock")

    def test_stock_bar_merges_index_explicit_forms_and_counts_them(self):
        if get_stock_bar is None:
            self.skipTest("fastapi is not installed in this test environment")

        self._save_result_with_code("sh000016", "query_canonical")
        self._save_result_with_code("SH000016", "query_upper")
        self._save_result_with_code("000016.SH", "query_alias")
        self._save_result_with_code("000016", "query_stock")

        stock_bar = get_stock_bar(
            start_date=None,
            end_date=None,
            limit=10,
            db_manager=self.db,
        )

        self.assertEqual(len(stock_bar.items), 2)
        index_item = next(
            item for item in stock_bar.items if item.asset_type == "index"
        )
        stock_item = next(
            item for item in stock_bar.items if item.asset_type == "stock"
        )
        self.assertEqual(index_item.analysis_count, 3)
        self.assertEqual(index_item.stock_code, "sh000016")
        self.assertEqual(stock_item.stock_code, "000016")
        self.assertEqual(stock_item.analysis_count, 1)

    def test_stock_bar_exposes_sz_index_canonical_row_with_independent_count(self):
        """``sz399001`` 在 stock-bar 以 canonical 单行展示，``analysis_count``
        只计自身记录，不与裸 ``399001`` 股票合并。"""
        if get_stock_bar is None:
            self.skipTest("fastapi is not installed in this test environment")

        self._save_result_with_code("sz399001", "query_sz_index")
        self._save_result_with_code("399001", "query_sz_stock")

        stock_bar = get_stock_bar(
            start_date=None,
            end_date=None,
            limit=10,
            db_manager=self.db,
        )

        self.assertEqual(len(stock_bar.items), 2)
        by_code = {item.stock_code: item for item in stock_bar.items}
        self.assertIn("sz399001", by_code)
        self.assertIn("399001", by_code)
        self.assertEqual(by_code["sz399001"].analysis_count, 1)
        self.assertEqual(by_code["sz399001"].asset_type, "index")
        self.assertEqual(by_code["399001"].analysis_count, 1)
        self.assertEqual(by_code["399001"].asset_type, "stock")

    def test_delete_index_by_code_deletes_all_explicit_forms_only(self):
        if delete_history_by_code is None:
            self.skipTest("fastapi is not installed in this test environment")

        self._save_result_with_code("sh000016", "query_canonical")
        self._save_result_with_code("SH000016", "query_upper")
        self._save_result_with_code("000016.SH", "query_alias")
        self._save_result_with_code("000016", "query_stock")

        response = delete_history_by_code("sh000016", db_manager=self.db)
        self.assertEqual(response.deleted, 3)

        remaining = HistoryService(self.db).get_history_list(
            stock_code="000016", page=1, limit=10
        )
        self.assertEqual(remaining["total"], 1)
        self.assertEqual(
            {item["query_id"] for item in remaining["items"]},
            {"query_stock"},
        )

    def test_delete_index_with_no_records_returns_zero(self):
        if delete_history_by_code is None:
            self.skipTest("fastapi is not installed in this test environment")

        response = delete_history_by_code("sh000016", db_manager=self.db)
        self.assertEqual(response.deleted, 0)

    def test_history_list_exposes_parser_asset_type(self):
        self._save_result_with_code("sh000016", "query_index")
        self._save_result_with_code("000016", "query_stock")
        self._save_result_with_code("600519", "query_stock2")

        listing = HistoryService(self.db).get_history_list(page=1, limit=10)
        by_query = {item["query_id"]: item for item in listing["items"]}
        self.assertEqual(by_query["query_index"]["asset_type"], "index")
        self.assertEqual(by_query["query_stock"]["asset_type"], "stock")
        self.assertEqual(by_query["query_stock2"]["asset_type"], "stock")

    def test_history_list_omits_asset_type_for_market_review(self):
        self._save_result_with_code("MARKET", "query_market_review")

        listing = HistoryService(self.db).get_history_list(page=1, limit=10)
        by_query = {item["query_id"]: item for item in listing["items"]}
        self.assertTrue(by_query["query_market_review"]["asset_type"] is None)


class HistoryItemSchemaNegativeSentimentTest(unittest.TestCase):
    """Regression: HistoryItem / ReportSummary must accept out-of-range sentiment_score from DB rows."""

    @classmethod
    def setUpClass(cls) -> None:
        """Import schema classes once for all tests, skipping gracefully when deps are missing."""
        try:
            from api.v1.schemas.history import HistoryItem, ReportSummary  # type: ignore
        except ModuleNotFoundError:
            cls.HistoryItem = None
            cls.ReportSummary = None
        else:
            cls.HistoryItem = HistoryItem
            cls.ReportSummary = ReportSummary

    def test_negative_sentiment_score_does_not_raise(self) -> None:
        """Bug #942: sentiment_score=-22 in DB should not cause Pydantic ValidationError."""
        if self.HistoryItem is None:
            self.skipTest("fastapi / pydantic not installed in this test environment")

        item = self.HistoryItem(query_id="q1", stock_code="600519", sentiment_score=-22)
        self.assertEqual(item.sentiment_score, -22)

    def test_out_of_range_high_sentiment_score_does_not_raise(self) -> None:
        """HistoryItem should also accept scores above 100 from legacy data."""
        if self.HistoryItem is None:
            self.skipTest("fastapi / pydantic not installed in this test environment")

        item = self.HistoryItem(query_id="q2", stock_code="600519", sentiment_score=150)
        self.assertEqual(item.sentiment_score, 150)

    def test_none_sentiment_score_is_allowed(self) -> None:
        """HistoryItem.sentiment_score=None should still be valid (optional field)."""
        if self.HistoryItem is None:
            self.skipTest("fastapi / pydantic not installed in this test environment")

        item = self.HistoryItem(query_id="q3", stock_code="600519", sentiment_score=None)
        self.assertIsNone(item.sentiment_score)

    def test_report_summary_negative_sentiment_score_does_not_raise(self) -> None:
        """ReportSummary.sentiment_score should also accept negative values from legacy DB rows."""
        if self.ReportSummary is None:
            self.skipTest("fastapi / pydantic not installed in this test environment")

        summary = self.ReportSummary(sentiment_score=-22)
        self.assertEqual(summary.sentiment_score, -22)

    def test_report_summary_out_of_range_high_sentiment_score_does_not_raise(self) -> None:
        """ReportSummary.sentiment_score should also accept scores above 100 from legacy data."""
        if self.ReportSummary is None:
            self.skipTest("fastapi / pydantic not installed in this test environment")

        summary = self.ReportSummary(sentiment_score=150)
        self.assertEqual(summary.sentiment_score, 150)

    def test_report_summary_none_sentiment_score_is_allowed(self) -> None:
        """ReportSummary.sentiment_score=None should still be valid (optional field)."""
        if self.ReportSummary is None:
            self.skipTest("fastapi / pydantic not installed in this test environment")

        summary = self.ReportSummary(sentiment_score=None)
        self.assertIsNone(summary.sentiment_score)


if __name__ == "__main__":
    unittest.main()
