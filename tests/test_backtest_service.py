# -*- coding: utf-8 -*-
"""Integration tests for backtest service and repository.

These tests run against a temporary SQLite DB (same approach as other tests)
and validate idempotency/force semantics, result field correctness,
summary creation, and query methods.
"""

import json
import os
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import patch

import pandas as pd

from data_provider.base import normalize_stock_code
from src.config import Config
from src.core.backtest_engine import OVERALL_SENTINEL_CODE
from src.repositories.backtest_repo import BacktestRepository
from src.services.backtest_service import BacktestService
from src.storage import AnalysisHistory, BacktestResult, BacktestSummary, DatabaseManager, StockDaily


class BacktestServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_backtest_service.db")
        self._original_env = {
            key: os.environ.get(key)
            for key in (
                "ENV_FILE",
                "DATABASE_PATH",
                "BACKTEST_EVAL_WINDOW_DAYS",
            )
        }
        self._env_path = os.path.join(self._temp_dir.name, ".env")
        with open(self._env_path, "w", encoding="utf-8") as env_file:
            env_file.write("STOCK_LIST=600519,000001\n")

        os.environ["ENV_FILE"] = self._env_path
        os.environ["DATABASE_PATH"] = self._db_path
        os.environ["BACKTEST_EVAL_WINDOW_DAYS"] = "3"

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

        # Ensure analysis is old enough for default min_age_days=14
        old_created_at = datetime(2024, 1, 1, 0, 0, 0)

        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q1",
                    code="600519",
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=80,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="test",
                    stop_loss=95.0,
                    take_profit=110.0,
                    created_at=old_created_at,
                    context_snapshot=json.dumps(
                        {
                            "enhanced_context": {"date": "2024-01-01"},
                            "market_phase_summary": {
                                "phase": "premarket",
                                "market": "cn",
                                "trigger_source": "api",
                            },
                        }
                    ),
                )
            )

            # Analysis day close
            session.add(
                StockDaily(
                    code="600519",
                    date=date(2024, 1, 1),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.0,
                )
            )

            # Forward bars (3 days) that hit take-profit on day1
            session.add_all(
                [
                    StockDaily(code="600519", date=date(2024, 1, 2), high=111.0, low=100.0, close=105.0),
                    StockDaily(code="600519", date=date(2024, 1, 3), high=108.0, low=103.0, close=106.0),
                    StockDaily(code="600519", date=date(2024, 1, 4), high=109.0, low=104.0, close=107.0),
                ]
            )
            session.commit()

    def _seed_analysis(
        self,
        *,
        query_id: str,
        code: str = "600519",
        analysis_date: date,
        created_at: datetime,
        operation_advice: str,
        trend_prediction: str,
        start_close: float,
        forward_bars: list[StockDaily],
        phase: str = "intraday",
    ) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id=query_id,
                    code=code,
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice=operation_advice,
                    trend_prediction=trend_prediction,
                    analysis_summary="extra-test",
                    stop_loss=None,
                    take_profit=None,
                    created_at=created_at,
                    context_snapshot=json.dumps(
                        {
                            "enhanced_context": {"date": analysis_date.isoformat()},
                            "market_phase_summary": {
                                "phase": phase,
                                "market": "cn",
                                "trigger_source": "api",
                            },
                        }
                    ),
                )
            )
            session.add(
                StockDaily(
                    code=code,
                    date=analysis_date,
                    open=start_close,
                    high=start_close,
                    low=start_close,
                    close=start_close,
                )
            )
            session.add_all([
                StockDaily(
                    code=code,
                    date=bar.date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                ) for bar in forward_bars
            ])
            session.commit()

    def tearDown(self) -> None:
        Config._instance = None
        DatabaseManager.reset_instance()
        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temp_dir.cleanup()

    def _count_results(self) -> int:
        with self.db.get_session() as session:
            return session.query(BacktestResult).count()

    def _make_backtest_result(
        self,
        *,
        analysis_history_id: int,
        analysis_date: date,
        eval_window_days: int = 1,
        engine_version: str = "v1",
    ) -> BacktestResult:
        return BacktestResult(
            analysis_history_id=analysis_history_id,
            code="600519",
            analysis_date=analysis_date,
            eval_window_days=eval_window_days,
            engine_version=engine_version,
            eval_status="completed",
            evaluated_at=datetime(2024, 1, 20, 0, 0, 0),
            operation_advice="买入",
            position_recommendation="long",
            start_price=100.0,
            end_close=101.0,
            stock_return_pct=1.0,
            direction_expected="up",
            direction_correct=True,
            outcome="win",
            simulated_return_pct=1.0,
        )

    def test_force_semantics(self) -> None:
        service = BacktestService(self.db)

        stats1 = service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats1["saved"], 1)
        self.assertEqual(self._count_results(), 1)

        # Non-force should be idempotent
        stats2 = service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats2["saved"], 0)
        self.assertEqual(self._count_results(), 1)
        self.assertEqual(stats2["diagnostics"]["empty_reason"], "no_new_results")
        self.assertIn("历史分析记录已存在", stats2["message"] or "")

        # Force should replace existing result without unique constraint errors
        stats3 = service.run_backtest(code="600519", force=True, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats3["saved"], 1)
        self.assertEqual(self._count_results(), 1)

    def test_run_backtest_accepts_dotted_exchange_prefix_and_filters_analysis_date_range(self) -> None:
        service = BacktestService(self.db)

        stats = service.run_backtest(
            code="SH.600519",
            force=False,
            eval_window_days=3,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)
        self.assertIsNone(stats["message"])
        self.assertEqual(stats["diagnostics"]["code"], "600519")
        self.assertEqual(stats["diagnostics"]["analysis_date_from"], "2024-01-01")
        self.assertEqual(stats["diagnostics"]["analysis_date_to"], "2024-01-01")

        data = service.get_recent_evaluations(code="SH.600519", eval_window_days=3, limit=10, page=1)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["code"], "600519")

        summary = service.get_summary(scope="stock", code="SH.600519", eval_window_days=3)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["code"], "600519")
        self.assertEqual(summary["completed_count"], 1)

    def test_run_backtest_keeps_dotted_cn_code_match_when_analysis_history_is_dotted(self) -> None:
        self._seed_analysis(
            query_id="q_dot_cn",
            code="600519.SH",
            analysis_date=date(2024, 1, 2),
            created_at=datetime(2024, 1, 2, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519.SH", date=date(2024, 1, 3), high=111.0, low=100.0, close=105.0),
                StockDaily(code="600519.SH", date=date(2024, 1, 4), high=108.0, low=102.0, close=106.0),
                StockDaily(code="600519.SH", date=date(2024, 1, 5), high=109.0, low=102.0, close=107.0),
            ],
        )

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="600519.SH",
            force=False,
            eval_window_days=3,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 2),
            analysis_date_to=date(2024, 1, 2),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(code="600519.SH", eval_window_days=3, limit=10, page=1)
        self.assertEqual(data["items"][0]["code"], "600519.SH")

        summary = service.get_summary(scope="stock", code="600519.SH", eval_window_days=3)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["code"], "600519")

    def test_run_backtest_matches_compact_prefixed_analysis_history_with_canonical_query(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_compact_history_sh",
                    code="SH600519",
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="compact history code with canonical query",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 2, 15, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-02-15"}}',
                )
            )
            session.add(
                StockDaily(
                    code="SH600519",
                    date=date(2024, 2, 15),
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                )
            )
            session.add_all(
                [
                    StockDaily(code="SH600519", date=date(2024, 2, 16), high=102.0, low=99.0, close=101.0),
                    StockDaily(code="SH600519", date=date(2024, 2, 17), high=104.0, low=100.0, close=103.0),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="600519",
            force=False,
            eval_window_days=2,
            min_age_days=0,
            analysis_date_from=date(2024, 2, 15),
            analysis_date_to=date(2024, 2, 15),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(code="SH600519", eval_window_days=2, limit=10, page=1)
        self.assertEqual(data["total"], 1)

    def test_run_backtest_matches_compact_ss_alias_after_request_normalization(self) -> None:
        self._seed_analysis(
            query_id="q_compact_history_ss",
            code="SS600519",
            analysis_date=date(2024, 2, 20),
            created_at=datetime(2024, 2, 20, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="SS600519", date=date(2024, 2, 21), high=102.0, low=99.0, close=101.0),
                StockDaily(code="SS600519", date=date(2024, 2, 22), high=104.0, low=100.0, close=103.0),
            ],
        )

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="SS600519",
            force=False,
            eval_window_days=2,
            min_age_days=0,
            analysis_date_from=date(2024, 2, 20),
            analysis_date_to=date(2024, 2, 20),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(code="SS600519", eval_window_days=2, limit=10, page=1)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["code"], "SS600519")

    def test_run_backtest_uses_bare_daily_bars_and_summary_for_compact_ss_history(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_compact_ss_history_bare_daily",
                    code="SS600519",
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="compact ss history with bare daily data",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 2, 25, 0, 0, 0),
                    context_snapshot=json.dumps({"enhanced_context": {"date": "2024-02-25"}}),
                )
            )
            session.add(
                StockDaily(
                    code="600519",
                    date=date(2024, 2, 25),
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                )
            )
            session.add(
                StockDaily(code="600519", date=date(2024, 2, 26), high=104.0, low=99.0, close=103.0)
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="600519",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 2, 25),
            limit=10,
        )

        self.assertEqual(stats["processed"], 2)
        self.assertEqual(stats["saved"], 2)
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["insufficient"], 0)

        summary = service.get_summary(scope="stock", code="600519", eval_window_days=1)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["code"], "600519")
        self.assertEqual(summary["total_evaluations"], 2)

        matched = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 2, 25),
        )
        self.assertEqual({row["code"] for row in matched["items"]}, {"600519", "SS600519"})

    def test_run_backtest_uses_compact_forward_bars_when_analysis_history_is_bare_code(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_compact_forward_sh",
                    code="600519",
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="bare history with compact forward bars",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 3, 1, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-03-01"}}',
                )
            )
            session.add(
                StockDaily(
                    code="SH600519",
                    date=date(2024, 3, 1),
                    open=110.0,
                    high=110.0,
                    low=110.0,
                    close=110.0,
                )
            )
            session.add_all(
                [
                    StockDaily(code="SH600519", date=date(2024, 3, 2), high=112.0, low=109.0, close=111.0),
                    StockDaily(code="SH600519", date=date(2024, 3, 3), high=113.0, low=110.0, close=112.0),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="600519",
            force=False,
            eval_window_days=2,
            min_age_days=0,
            analysis_date_from=date(2024, 3, 1),
            analysis_date_to=date(2024, 3, 1),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["insufficient"], 0)

    def test_run_backtest_matches_compact_bj_code_shape_with_no_prefix_query(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_compact_history_bj",
                    code="BJ920748",
                    name="可转债",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="BJ compact history code without query prefix",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 4, 1, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-04-01"}}',
                )
            )
            session.add(
                StockDaily(
                    code="BJ920748",
                    date=date(2024, 4, 1),
                    open=200.0,
                    high=200.0,
                    low=200.0,
                    close=200.0,
                )
            )
            session.add_all(
                [
                    StockDaily(code="BJ920748", date=date(2024, 4, 2), high=210.0, low=198.0, close=205.0),
                    StockDaily(code="BJ920748", date=date(2024, 4, 3), high=215.0, low=202.0, close=210.0),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="920748",
            force=False,
            eval_window_days=2,
            min_age_days=0,
            analysis_date_from=date(2024, 4, 1),
            analysis_date_to=date(2024, 4, 1),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(code="BJ920748", eval_window_days=2, limit=10, page=1)
        self.assertEqual(data["total"], 1)

    def test_build_market_code_variants_includes_compact_prefix_and_bj_forms(self) -> None:
        sh_variants = BacktestRepository._build_market_code_variants("600519", "600519")
        self.assertIn("SH600519", sh_variants)
        self.assertIn("SH.600519", sh_variants)
        self.assertIn("SS600519", sh_variants)

        bj_variants = BacktestRepository._build_market_code_variants("920748", "920748")
        self.assertIn("BJ920748", bj_variants)
        self.assertIn("920748.BJ", bj_variants)

        us_bare_variants = BacktestRepository._build_market_code_variants("AAPL", "AAPL")
        self.assertIn("AAPL.US", us_bare_variants)
        us_suffix_variants = BacktestRepository._build_market_code_variants("AAPL.US", "AAPL.US")
        self.assertIn("AAPL", us_suffix_variants)

    def test_daily_refill_codes_normalize_legacy_ss_aliases_once(self) -> None:
        candidates = BacktestService._build_daily_code_candidates("605066.SH")

        self.assertIn("SS605066", candidates)
        self.assertEqual(normalize_stock_code("SS605066"), "605066")
        for alias in ("605066.SH", "605066", "SH605066", "SH.605066", "605066.SS", "SS.605066"):
            with self.subTest(alias=alias):
                self.assertEqual(BacktestService._normalize_daily_refill_code(alias), "605066")
        self.assertEqual(
            BacktestService._ordered_daily_refill_codes(
                code_candidates=candidates,
                preferred_code="605066.SH",
            ),
            ["605066"],
        )

    def test_try_fill_daily_data_uses_normalized_a_share_code_for_legacy_ss_alias(self) -> None:
        requested_codes = []

        class FakeDataFetcherManager:
            def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
                requested_codes.append(stock_code)
                return (
                    pd.DataFrame(
                        [
                            {
                                "date": date(2024, 7, 1),
                                "open": 10.0,
                                "high": 11.0,
                                "low": 9.0,
                                "close": 10.5,
                                "volume": 1000,
                            }
                        ]
                    ),
                    "FakeFetcher",
                )

        service = BacktestService(self.db)
        with patch("data_provider.base.DataFetcherManager", FakeDataFetcherManager):
            service._try_fill_daily_data(
                code="SS605066",
                analysis_date=date(2024, 7, 1),
                eval_window_days=1,
            )

        self.assertEqual(requested_codes, ["605066"])
        self.assertEqual(
            [row.code for row in self.db.get_data_range("605066", date(2024, 7, 1), date(2024, 7, 1))],
            ["605066"],
        )
        self.assertEqual(self.db.get_data_range("SS605066", date(2024, 7, 1), date(2024, 7, 1)), [])

    def test_build_market_code_variants_rejects_hk_suffix_with_6_digit_base(self) -> None:
        invalid_variants = BacktestRepository._build_market_code_variants("600519.HK", "600519.HK")
        self.assertNotIn("600519", invalid_variants)
        self.assertNotIn("600519.HK", invalid_variants)

        valid_variants = BacktestRepository._build_market_code_variants("1810.HK", "01810")
        self.assertIn("01810.HK", valid_variants)
        self.assertIn("HK01810", valid_variants)
        self.assertIn("HK.01810", valid_variants)

    def test_build_market_code_variants_rejects_wrong_explicit_exchange_for_bse_code(self) -> None:
        self.assertEqual(
            BacktestRepository._build_market_code_variants("920748.SH", "920748"),
            [],
        )
        self.assertEqual(
            BacktestRepository._build_market_code_variants("SH920748", "920748"),
            [],
        )

    def test_get_candidates_does_not_match_invalid_a_share_hk_cross_input(self) -> None:
        repo = BacktestRepository(self.db)
        matches = repo.get_candidates(
            code="600519.HK",
            min_age_days=0,
            limit=10,
            eval_window_days=3,
            engine_version="v1",
            force=True,
        )

        self.assertEqual(len(matches), 0)

    def test_get_candidates_does_not_match_explicit_wrong_a_share_market(self) -> None:
        repo = BacktestRepository(self.db)
        for invalid_code in ("600519.SZ", "SH000001", "000001.SH", "920748.SH", "SH920748"):
            with self.subTest(invalid_code=invalid_code):
                matches = repo.get_candidates(
                    code=invalid_code,
                    min_age_days=0,
                    limit=10,
                    eval_window_days=3,
                    engine_version="v1",
                    force=True,
                )
                self.assertEqual(matches, [])

    def test_run_backtest_rejects_invalid_market_suffix_length_input(self) -> None:
        service = BacktestService(self.db)
        with self.assertRaisesRegex(ValueError, "非法股票代码格式"):
            service.run_backtest(
                code="600519.HK",
                force=False,
                eval_window_days=3,
                min_age_days=0,
                analysis_date_from=date(2024, 1, 1),
                analysis_date_to=date(2024, 1, 1),
                limit=10,
            )

    def test_run_backtest_rejects_explicit_wrong_a_share_market(self) -> None:
        service = BacktestService(self.db)
        for invalid_code in ("600519.SZ", "SH000001", "000001.SH", "920748.SH", "SH920748"):
            with self.subTest(invalid_code=invalid_code):
                with self.assertRaisesRegex(ValueError, "非法股票代码格式"):
                    service.run_backtest(
                        code=invalid_code,
                        force=False,
                        eval_window_days=3,
                        min_age_days=0,
                        analysis_date_from=date(2024, 1, 1),
                        analysis_date_to=date(2024, 1, 1),
                        limit=10,
                    )

    def test_get_recent_evaluations_rejects_explicit_wrong_a_share_market(self) -> None:
        service = BacktestService(self.db)
        for invalid_code in ("600519.SZ", "SH000001", "000001.SH", "920748.SH", "SH920748"):
            with self.subTest(invalid_code=invalid_code):
                with self.assertRaisesRegex(ValueError, "非法股票代码格式"):
                    service.get_recent_evaluations(
                        code=invalid_code,
                        eval_window_days=3,
                        limit=10,
                        page=1,
                        analysis_date_from=date(2024, 1, 1),
                        analysis_date_to=date(2024, 1, 1),
                    )

    def test_get_summary_rejects_explicit_wrong_a_share_market(self) -> None:
        service = BacktestService(self.db)
        for invalid_code in ("600519.SZ", "SH000001", "000001.SH", "920748.SH", "SH920748"):
            with self.subTest(invalid_code=invalid_code):
                with self.assertRaisesRegex(ValueError, "非法股票代码格式"):
                    service.get_summary(
                        scope="stock",
                        code=invalid_code,
                        eval_window_days=3,
                        analysis_date_from=date(2024, 1, 1),
                        analysis_date_to=date(2024, 1, 1),
                    )

    def test_run_backtest_bare_code_query_matches_dotted_history_records(self) -> None:
        self._seed_analysis(
            query_id="q_match_dot",
            code="600519.SH",
            analysis_date=date(2024, 2, 1),
            created_at=datetime(2024, 2, 1, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519.SH", date=date(2024, 2, 2), high=101.0, low=95.0, close=96.0),
            ],
        )

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="600519",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 2, 1),
            limit=20,
        )

        self.assertEqual(stats["processed"], 2)
        self.assertEqual(stats["saved"], 2)
        self.assertEqual(stats["completed"], 2)
        summary = service.get_summary(scope="stock", code="600519", eval_window_days=1)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["code"], "600519")
        self.assertEqual(summary["total_evaluations"], 2)
        self.assertEqual(summary["completed_count"], 2)

        matched = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=20,
            page=1,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 2, 1),
        )
        self.assertEqual({row["code"] for row in matched["items"]}, {"600519", "600519.SH"})

    def test_run_backtest_uses_bare_daily_bars_for_dotted_history_record(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_dot_history_bare_daily",
                    code="600519.SH",
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="dotted history with bare daily data",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 2, 5, 0, 0, 0),
                    context_snapshot=json.dumps({"enhanced_context": {"date": "2024-02-05"}}),
                )
            )
            session.add(
                StockDaily(
                    code="600519",
                    date=date(2024, 2, 5),
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                )
            )
            session.add(
                StockDaily(code="600519", date=date(2024, 2, 6), high=106.0, low=99.0, close=105.0)
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="600519",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 2, 5),
            analysis_date_to=date(2024, 2, 5),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["insufficient"], 0)

        with self.db.get_session() as session:
            result = session.query(BacktestResult).filter(BacktestResult.code == "600519.SH").one()
            self.assertEqual(result.analysis_date, date(2024, 2, 5))
            self.assertEqual(result.start_price, 100.0)
            self.assertEqual(result.end_close, 105.0)

    def test_run_backtest_uses_forward_bars_from_other_code_shape_when_start_daily_shape_differs(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_shape_split",
                    code="600519",
                    name="贵州茅台",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="split code shape with start on dotted daily",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 2, 10, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-02-10"}}',
                )
            )
            session.add(
                StockDaily(
                    code="600519.SH",
                    date=date(2024, 2, 10),
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                )
            )
            session.add_all(
                [
                    StockDaily(code="600519", date=date(2024, 2, 11), high=106.0, low=99.0, close=105.0),
                    StockDaily(code="600519", date=date(2024, 2, 12), high=110.0, low=100.0, close=108.0),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="600519",
            force=False,
            eval_window_days=2,
            min_age_days=0,
            analysis_date_from=date(2024, 2, 10),
            analysis_date_to=date(2024, 2, 10),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["insufficient"], 0)

        with self.db.get_session() as session:
            result = session.query(BacktestResult).filter(BacktestResult.code == "600519").one()
            self.assertEqual(result.analysis_date, date(2024, 2, 10))
            self.assertEqual(result.start_price, 100.0)
            self.assertEqual(result.end_close, 108.0)

    def test_run_backtest_supports_us_suffix_code_shape_when_run_with_suffix(self) -> None:
        self._seed_analysis(
            query_id="q_aapl",
            code="AAPL.US",
            analysis_date=date(2024, 1, 3),
            created_at=datetime(2024, 1, 3, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="AAPL.US", date=date(2024, 1, 4), high=101.0, low=95.0, close=96.0),
            ],
        )

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="AAPL.US",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 3),
            analysis_date_to=date(2024, 1, 3),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)

        data = service.get_recent_evaluations(code="AAPL.US", eval_window_days=1, limit=10, page=1)
        self.assertEqual(data["items"][0]["code"], "AAPL.US")
        self.assertEqual(data["items"][0]["analysis_date"], "2024-01-03")

    def test_run_backtest_us_suffix_query_matches_bare_history_and_summary(self) -> None:
        self._seed_analysis(
            query_id="q_aapl_bare_history",
            code="AAPL",
            analysis_date=date(2024, 1, 6),
            created_at=datetime(2024, 1, 6, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="AAPL", date=date(2024, 1, 7), high=104.0, low=99.0, close=103.0),
            ],
        )

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="AAPL.US",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 6),
            analysis_date_to=date(2024, 1, 6),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(
            code="AAPL.US",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 6),
            analysis_date_to=date(2024, 1, 6),
        )
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["code"], "AAPL")

        summary = service.get_summary(scope="stock", code="AAPL.US", eval_window_days=1)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["code"], "AAPL")
        self.assertEqual(summary["completed_count"], 1)

    def test_run_backtest_bare_us_query_matches_us_suffix_history_and_summary(self) -> None:
        self._seed_analysis(
            query_id="q_aapl_suffix_history",
            code="AAPL.US",
            analysis_date=date(2024, 1, 8),
            created_at=datetime(2024, 1, 8, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="AAPL.US", date=date(2024, 1, 9), high=104.0, low=99.0, close=103.0),
            ],
        )

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="AAPL",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 8),
            analysis_date_to=date(2024, 1, 8),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(
            code="AAPL",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 8),
            analysis_date_to=date(2024, 1, 8),
        )
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["code"], "AAPL.US")

        summary = service.get_summary(scope="stock", code="AAPL", eval_window_days=1)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["code"], "AAPL.US")
        self.assertEqual(summary["completed_count"], 1)

    def test_us_code_queries_match_legacy_results_without_rerun(self) -> None:
        with self.db.get_session() as session:
            bare_history = AnalysisHistory(
                query_id="q_legacy_aapl_bare",
                code="AAPL",
                name="Apple",
                report_type="simple",
                sentiment_score=60,
                operation_advice="买入",
                trend_prediction="看多",
                analysis_summary="legacy bare result",
                created_at=datetime(2024, 1, 10, 0, 0, 0),
                context_snapshot=json.dumps({"enhanced_context": {"date": "2024-01-10"}}),
            )
            suffix_history = AnalysisHistory(
                query_id="q_legacy_aapl_suffix",
                code="AAPL.US",
                name="Apple",
                report_type="simple",
                sentiment_score=60,
                operation_advice="买入",
                trend_prediction="看多",
                analysis_summary="legacy suffix result",
                created_at=datetime(2024, 1, 11, 0, 0, 0),
                context_snapshot=json.dumps({"enhanced_context": {"date": "2024-01-11"}}),
            )
            session.add_all([bare_history, suffix_history])
            session.flush()
            session.add_all(
                [
                    BacktestResult(
                        analysis_history_id=bare_history.id,
                        code="AAPL",
                        analysis_date=date(2024, 1, 10),
                        eval_window_days=1,
                        engine_version="v1",
                        eval_status="completed",
                        evaluated_at=datetime(2024, 1, 20, 0, 0, 0),
                        operation_advice="买入",
                        position_recommendation="long",
                        start_price=100.0,
                        end_close=103.0,
                        stock_return_pct=3.0,
                        direction_expected="up",
                        direction_correct=True,
                        outcome="win",
                        simulated_return_pct=3.0,
                    ),
                    BacktestResult(
                        analysis_history_id=suffix_history.id,
                        code="AAPL.US",
                        analysis_date=date(2024, 1, 11),
                        eval_window_days=1,
                        engine_version="v1",
                        eval_status="completed",
                        evaluated_at=datetime(2024, 1, 21, 0, 0, 0),
                        operation_advice="买入",
                        position_recommendation="long",
                        start_price=103.0,
                        end_close=105.0,
                        stock_return_pct=1.94,
                        direction_expected="up",
                        direction_correct=True,
                        outcome="win",
                        simulated_return_pct=1.94,
                    ),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        suffix_query = service.get_recent_evaluations(
            code="AAPL.US",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 10),
            analysis_date_to=date(2024, 1, 10),
        )
        self.assertEqual(suffix_query["total"], 1)
        self.assertEqual(suffix_query["items"][0]["code"], "AAPL")

        suffix_summary = service.get_summary(
            scope="stock",
            code="AAPL.US",
            eval_window_days=1,
            analysis_date_from=date(2024, 1, 10),
            analysis_date_to=date(2024, 1, 10),
        )
        self.assertIsNotNone(suffix_summary)
        assert suffix_summary is not None
        self.assertEqual(suffix_summary["code"], "AAPL.US")
        self.assertEqual(suffix_summary["total_evaluations"], 1)

        bare_query = service.get_recent_evaluations(
            code="AAPL",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 11),
            analysis_date_to=date(2024, 1, 11),
        )
        self.assertEqual(bare_query["total"], 1)
        self.assertEqual(bare_query["items"][0]["code"], "AAPL.US")

        bare_summary = service.get_summary(
            scope="stock",
            code="AAPL",
            eval_window_days=1,
            analysis_date_from=date(2024, 1, 11),
            analysis_date_to=date(2024, 1, 11),
        )
        self.assertIsNotNone(bare_summary)
        assert bare_summary is not None
        self.assertEqual(bare_summary["code"], "AAPL")
        self.assertEqual(bare_summary["total_evaluations"], 1)

    def test_run_backtest_matches_hk_different_code_shapes_in_analysis_history_and_daily(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_hk_history_dot",
                    code="01810.HK",
                    name="恒生指数成份股",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="HK history is dotted, daily is canonical",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot=json.dumps({"enhanced_context": {"date": "2024-01-01"}}),
                )
            )
            session.add(
                StockDaily(
                    code="HK01810",
                    date=date(2024, 1, 1),
                    open=100.0,
                    high=100.0,
                    low=100.0,
                    close=100.0,
                )
            )
            session.add(
                StockDaily(
                    code="HK01810",
                    date=date(2024, 1, 2),
                    high=102.0,
                    low=95.0,
                    close=101.0,
                )
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="1810.HK",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(code="1810.HK", eval_window_days=1, limit=10, page=1)
        self.assertEqual(data["total"], 1)

        query_by_bare = service.get_recent_evaluations(code="01810", eval_window_days=1, limit=10, page=1)
        self.assertEqual(query_by_bare["total"], 1)

    def test_run_backtest_matches_hk_daily_shape_variants_for_prefixed_history(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_hk_history_prefixed",
                    code="HK01810",
                    name="恒生指数成份股",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="HK history is prefixed, daily is dotted",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot=json.dumps({"enhanced_context": {"date": "2024-01-01"}}),
                )
            )
            session.add(
                StockDaily(
                    code="01810.HK",
                    date=date(2024, 1, 1),
                    open=120.0,
                    high=120.0,
                    low=120.0,
                    close=120.0,
                )
            )
            session.add(
                StockDaily(
                    code="01810.HK",
                    date=date(2024, 1, 2),
                    high=122.0,
                    low=118.0,
                    close=121.0,
                )
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="01810",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        data = service.get_recent_evaluations(code="01810.HK", eval_window_days=1, limit=10, page=1)
        self.assertEqual(data["total"], 1)

        query_by_prefixed = service.get_recent_evaluations(code="HK01810", eval_window_days=1, limit=10, page=1)
        self.assertEqual(query_by_prefixed["total"], 1)

    def test_run_backtest_supports_dotted_hk_prefix_query_shape(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q_hk_query_dot",
                    code="HK01810",
                    name="恒生指数成份股",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="HK prefixed history with dotted query",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot=json.dumps({"enhanced_context": {"date": "2024-01-01"}}),
                )
            )
            session.add(
                StockDaily(
                    code="HK01810",
                    date=date(2024, 1, 1),
                    open=90.0,
                    high=90.0,
                    low=90.0,
                    close=90.0,
                )
            )
            session.add_all(
                [
                    StockDaily(
                        code="HK01810",
                        date=date(2024, 1, 2),
                        high=92.0,
                        low=88.0,
                        close=91.0,
                    ),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="HK.01810",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
            limit=10,
        )
        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)

        results = service.get_recent_evaluations(
            code="HK.01810",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
        )
        self.assertEqual(results["total"], 1)

        summary = service.get_summary(
            scope="stock",
            code="HK.01810",
            eval_window_days=1,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
        )
        self.assertIsNotNone(summary)
        self.assertEqual(summary["code"], "01810")

    def test_run_backtest_filters_by_snapshot_analysis_date_not_created_at(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q-created-at-mismatch",
                    code="000003",
                    name="测试股票",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="created_at differs from analysis date",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 10, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.add(
                StockDaily(code="000003", date=date(2024, 1, 1), open=10.0, high=10.0, low=10.0, close=10.0)
            )
            session.add_all(
                [
                    StockDaily(code="000003", date=date(2024, 1, 2), high=10.5, low=9.8, close=10.2),
                    StockDaily(code="000003", date=date(2024, 1, 3), high=10.8, low=10.1, close=10.5),
                    StockDaily(code="000003", date=date(2024, 1, 4), high=11.0, low=10.4, close=10.8),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="000003",
            force=False,
            eval_window_days=3,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["completed"], 1)
        with self.db.get_session() as session:
            result = session.query(BacktestResult).filter(BacktestResult.code == "000003").one()
            self.assertEqual(result.analysis_date, date(2024, 1, 1))

    def test_run_backtest_persists_snapshot_date_when_start_daily_falls_back(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q-non-trading-analysis-date",
                    code="000004",
                    name="测试股票",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="snapshot date is a non-trading day",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 7, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-07"}}',
                )
            )
            session.add(
                StockDaily(code="000004", date=date(2024, 1, 5), open=10.0, high=10.0, low=10.0, close=10.0)
            )
            session.add(
                StockDaily(code="000004", date=date(2024, 1, 8), open=10.0, high=10.7, low=9.8, close=10.5)
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="000004",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 7),
            analysis_date_to=date(2024, 1, 7),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 1)
        with self.db.get_session() as session:
            result = session.query(BacktestResult).filter(BacktestResult.code == "000004").one()
            self.assertEqual(result.analysis_date, date(2024, 1, 7))
            self.assertAlmostEqual(result.start_price, 10.0)
            self.assertAlmostEqual(result.end_close, 10.5)

        data = service.get_recent_evaluations(
            code="000004",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 7),
            analysis_date_to=date(2024, 1, 7),
        )
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["analysis_date"], "2024-01-07")

        summary = service.get_summary(
            scope="stock",
            code="000004",
            eval_window_days=1,
            analysis_date_from=date(2024, 1, 7),
            analysis_date_to=date(2024, 1, 7),
        )
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["total_evaluations"], 1)
        self.assertEqual(summary["completed_count"], 1)

    def test_date_filtered_rerun_aligns_legacy_result_date_to_snapshot_date(self) -> None:
        with self.db.get_session() as session:
            history = AnalysisHistory(
                query_id="q-legacy-result-date",
                code="000005",
                name="测试股票",
                report_type="simple",
                sentiment_score=60,
                operation_advice="买入",
                trend_prediction="看多",
                analysis_summary="legacy result stores fallback trading date",
                stop_loss=None,
                take_profit=None,
                created_at=datetime(2024, 1, 7, 0, 0, 0),
                context_snapshot='{"enhanced_context": {"date": "2024-01-07"}}',
            )
            session.add(history)
            session.flush()
            session.add(
                BacktestResult(
                    analysis_history_id=history.id,
                    code="000005",
                    analysis_date=date(2024, 1, 5),
                    eval_window_days=1,
                    engine_version="v1",
                    eval_status="completed",
                    evaluated_at=datetime(2024, 1, 8, 0, 0, 0),
                    operation_advice="买入",
                    position_recommendation="long",
                    start_price=10.0,
                    end_close=10.5,
                    stock_return_pct=5.0,
                    direction_expected="up",
                    direction_correct=True,
                    outcome="win",
                    simulated_return_pct=5.0,
                )
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="000005",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 7),
            analysis_date_to=date(2024, 1, 7),
            limit=10,
        )

        self.assertEqual(stats["processed"], 0)
        self.assertEqual(stats["saved"], 0)
        self.assertEqual(stats["diagnostics"]["empty_reason"], "no_new_results")
        self.assertEqual(stats["diagnostics"]["aligned_existing_result_dates"], 1)
        with self.db.get_session() as session:
            result = session.query(BacktestResult).filter(BacktestResult.code == "000005").one()
            self.assertEqual(result.analysis_date, date(2024, 1, 7))

        data = service.get_recent_evaluations(
            code="000005",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 7),
            analysis_date_to=date(2024, 1, 7),
        )
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["analysis_date"], "2024-01-07")

    def test_date_filtered_rerun_aligns_legacy_result_date_when_new_candidates_process(self) -> None:
        with self.db.get_session() as session:
            legacy_history = AnalysisHistory(
                query_id="q-legacy-result-date-mixed",
                code="000006",
                name="测试股票",
                report_type="simple",
                sentiment_score=60,
                operation_advice="买入",
                trend_prediction="看多",
                analysis_summary="legacy result stores fallback trading date in mixed rerun",
                stop_loss=None,
                take_profit=None,
                created_at=datetime(2024, 1, 7, 0, 0, 0),
                context_snapshot='{"enhanced_context": {"date": "2024-01-07"}}',
            )
            new_history = AnalysisHistory(
                query_id="q-new-result-date-mixed",
                code="000006",
                name="测试股票",
                report_type="simple",
                sentiment_score=62,
                operation_advice="买入",
                trend_prediction="看多",
                analysis_summary="new matching analysis should not prevent legacy alignment",
                stop_loss=None,
                take_profit=None,
                created_at=datetime(2024, 1, 7, 1, 0, 0),
                context_snapshot='{"enhanced_context": {"date": "2024-01-07"}}',
            )
            session.add_all([legacy_history, new_history])
            session.flush()
            legacy_history_id = legacy_history.id
            session.add(
                BacktestResult(
                    analysis_history_id=legacy_history_id,
                    code="000006",
                    analysis_date=date(2024, 1, 5),
                    eval_window_days=1,
                    engine_version="v1",
                    eval_status="completed",
                    evaluated_at=datetime(2024, 1, 8, 0, 0, 0),
                    operation_advice="买入",
                    position_recommendation="long",
                    start_price=10.0,
                    end_close=10.5,
                    stock_return_pct=5.0,
                    direction_expected="up",
                    direction_correct=True,
                    outcome="win",
                    simulated_return_pct=5.0,
                )
            )
            session.add_all(
                [
                    StockDaily(
                        code="000006",
                        date=date(2024, 1, 7),
                        open=10.0,
                        high=10.0,
                        low=10.0,
                        close=10.0,
                    ),
                    StockDaily(code="000006", date=date(2024, 1, 8), high=10.6, low=9.9, close=10.5),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code="000006",
            force=False,
            eval_window_days=1,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 7),
            analysis_date_to=date(2024, 1, 7),
            limit=10,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["diagnostics"]["aligned_existing_result_dates"], 1)
        with self.db.get_session() as session:
            legacy_result = (
                session.query(BacktestResult)
                .filter(BacktestResult.analysis_history_id == legacy_history_id)
                .one()
            )
            self.assertEqual(legacy_result.analysis_date, date(2024, 1, 7))

        data = service.get_recent_evaluations(
            code="000006",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 7),
            analysis_date_to=date(2024, 1, 7),
        )
        self.assertEqual(data["total"], 2)
        self.assertEqual({item["analysis_date"] for item in data["items"]}, {"2024-01-07"})

    def test_run_backtest_pages_candidates_before_analysis_date_filter(self) -> None:
        with self.db.get_session() as session:
            for index in range(5):
                session.add(
                    AnalysisHistory(
                        query_id=f"q-newer-outside-date-{index}",
                        code=f"00010{index}",
                        name="测试股票",
                        report_type="simple",
                        sentiment_score=50,
                        operation_advice="持有",
                        trend_prediction="震荡",
                        analysis_summary="newer created_at but outside analysis date range",
                        stop_loss=None,
                        take_profit=None,
                        created_at=datetime(2024, 2, 10, index, 0, 0),
                        context_snapshot=json.dumps({"enhanced_context": {"date": "2024-02-01"}}),
                    )
                )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(
            code=None,
            force=False,
            eval_window_days=3,
            min_age_days=0,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
            limit=1,
        )

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["completed"], 1)
        self.assertIsNone(stats["message"])
        with self.db.get_session() as session:
            result = session.query(BacktestResult).one()
            self.assertEqual(result.code, "600519")
            self.assertEqual(result.analysis_date, date(2024, 1, 1))

    def test_run_backtest_reports_no_matching_candidates(self) -> None:
        service = BacktestService(self.db)

        stats = service.run_backtest(
            code="600519",
            force=False,
            eval_window_days=3,
            min_age_days=0,
            analysis_date_from=date(2024, 2, 1),
            analysis_date_to=date(2024, 2, 2),
            limit=10,
        )

        self.assertEqual(stats["processed"], 0)
        self.assertEqual(stats["saved"], 0)
        self.assertEqual(stats["diagnostics"]["empty_reason"], "no_matching_analysis")
        self.assertIn("未找到符合条件的历史分析记录", stats["message"])

    def test_run_backtest_reports_insufficient_daily_data(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q-insufficient",
                    code="000002",
                    name="万科A",
                    report_type="simple",
                    sentiment_score=60,
                    operation_advice="买入",
                    trend_prediction="看多",
                    analysis_summary="insufficient daily bars",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 1, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.add(
                StockDaily(code="000002", date=date(2024, 1, 1), open=10.0, high=10.0, low=10.0, close=10.0)
            )
            session.commit()

        service = BacktestService(self.db)
        with patch.object(BacktestService, "_try_fill_daily_data", return_value=None):
            stats = service.run_backtest(code="000002", force=False, eval_window_days=3, min_age_days=0, limit=10)

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(stats["completed"], 0)
        self.assertEqual(stats["insufficient"], 1)
        self.assertEqual(stats["diagnostics"]["empty_reason"], "insufficient_daily_data")
        self.assertIn("可用日线行情不足", stats["message"])

    def _run_and_get_result(self) -> BacktestResult:
        """Helper: run backtest and return the single BacktestResult row."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)
        with self.db.get_session() as session:
            return session.query(BacktestResult).one()

    def test_result_fields_correct(self) -> None:
        """Verify BacktestResult row contains correct evaluation values."""
        result = self._run_and_get_result()

        self.assertEqual(result.eval_status, "completed")
        self.assertEqual(result.code, "600519")
        self.assertEqual(result.analysis_date, date(2024, 1, 1))
        self.assertEqual(result.operation_advice, "买入")
        self.assertEqual(result.position_recommendation, "long")
        self.assertEqual(result.direction_expected, "up")

        # Prices
        self.assertAlmostEqual(result.start_price, 100.0)
        self.assertAlmostEqual(result.end_close, 107.0)
        self.assertAlmostEqual(result.stock_return_pct, 7.0)

        # Direction & outcome
        self.assertEqual(result.outcome, "win")
        self.assertTrue(result.direction_correct)

        # Target hits -- day2 high=111 >= take_profit=110
        self.assertTrue(result.hit_take_profit)
        self.assertFalse(result.hit_stop_loss)
        self.assertEqual(result.first_hit, "take_profit")
        self.assertEqual(result.first_hit_trading_days, 1)
        self.assertEqual(result.first_hit_date, date(2024, 1, 2))

        # Simulated execution
        self.assertAlmostEqual(result.simulated_entry_price, 100.0)
        self.assertAlmostEqual(result.simulated_exit_price, 110.0)
        self.assertEqual(result.simulated_exit_reason, "take_profit")
        self.assertAlmostEqual(result.simulated_return_pct, 10.0)

    def test_summaries_created_after_run(self) -> None:
        """Verify both overall and per-stock BacktestSummary rows are created."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        with self.db.get_session() as session:
            # Overall summary uses sentinel code
            overall = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "overall",
                BacktestSummary.code == OVERALL_SENTINEL_CODE,
            ).first()
            self.assertIsNotNone(overall)
            self.assertEqual(overall.total_evaluations, 1)
            self.assertEqual(overall.completed_count, 1)
            self.assertEqual(overall.win_count, 1)
            self.assertEqual(overall.loss_count, 0)
            self.assertAlmostEqual(overall.win_rate_pct, 100.0)

            # Stock-level summary
            stock = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "stock",
                BacktestSummary.code == "600519",
            ).first()
            self.assertIsNotNone(stock)
            self.assertEqual(stock.total_evaluations, 1)
            self.assertEqual(stock.completed_count, 1)
            self.assertEqual(stock.win_count, 1)

    def test_get_summary_overall_returns_sentinel_as_none(self) -> None:
        """Verify get_summary translates __overall__ sentinel back to None."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        summary = service.get_summary(scope="overall", code=None)
        self.assertIsNotNone(summary)
        self.assertIsNone(summary["code"])
        self.assertEqual(summary["scope"], "overall")
        self.assertEqual(summary["win_count"], 1)

    def test_agent_learning_summary_helpers_keep_skill_rollups_neutral_until_supported(self) -> None:
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        global_summary = service.get_global_summary(eval_window_days=3)
        stock_summary = service.get_stock_summary("600519", eval_window_days=3)
        skill_summary = service.get_skill_summary("bull_trend", eval_window_days=3)
        strategy_summary = service.get_strategy_summary("bull_trend", eval_window_days=3)

        self.assertIsNotNone(global_summary)
        self.assertEqual(global_summary["total_evaluations"], 1)
        self.assertAlmostEqual(global_summary["win_rate"], 1.0)
        self.assertAlmostEqual(global_summary["direction_accuracy"], 1.0)
        self.assertAlmostEqual(global_summary["avg_return"], 0.10)

        self.assertIsNotNone(stock_summary)
        self.assertEqual(stock_summary["code"], "600519")
        self.assertAlmostEqual(stock_summary["win_rate"], 1.0)

        self.assertIsNone(skill_summary)
        self.assertIsNone(strategy_summary)

    def test_get_recent_evaluations(self) -> None:
        """Verify get_recent_evaluations returns correct paginated results."""
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        data = service.get_recent_evaluations(code="600519", limit=10, page=1)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["limit"], 10)
        self.assertEqual(len(data["items"]), 1)

        item = data["items"][0]
        self.assertEqual(item["code"], "600519")
        self.assertEqual(item["outcome"], "win")
        self.assertEqual(item["direction_expected"], "up")
        self.assertTrue(item["direction_correct"])

    def test_get_recent_evaluations_aligns_neutral_advice_with_score(self) -> None:
        service = BacktestService(self.db)
        with self.db.get_session() as session:
            history = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "q1").one()
            history.operation_advice = "持有"
            history.sentiment_score = 78
            history.raw_result = None
            result = self._make_backtest_result(
                analysis_history_id=history.id,
                analysis_date=date(2024, 1, 1),
                eval_window_days=1,
            )
            result.operation_advice = "持有"
            session.add(result)
            session.commit()

        data = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=10,
            page=1,
        )

        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["operation_advice"], "持有")
        self.assertEqual(item["action"], "buy")
        self.assertEqual(item["action_label"], "买入")

    def test_get_recent_evaluations_prefers_persisted_raw_action(self) -> None:
        service = BacktestService(self.db)

        with self.db.get_session() as session:
            history = session.query(AnalysisHistory).filter(AnalysisHistory.query_id == "q1").one()
            history.operation_advice = "持有观察"
            history.raw_result = json.dumps(
                {
                    "operation_advice": "持有观察",
                    "action": "watch",
                    "action_label": "观望",
                    "guardrail_reason": "市场风险较高，建议观望",
                },
                ensure_ascii=False,
            )
            result = self._make_backtest_result(
                analysis_history_id=history.id,
                analysis_date=date(2024, 1, 1),
                eval_window_days=1,
            )
            result.operation_advice = "持有观察"
            result.position_recommendation = "long"
            session.add(result)
            session.commit()

        data = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=10,
            page=1,
        )

        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["operation_advice"], "持有观察")
        self.assertEqual(item["action"], "watch")
        self.assertEqual(item["action_label"], "观望")
        self.assertEqual(item["position_recommendation"], "long")

    def test_get_recent_evaluations_supports_tracking_fields_and_analysis_date_filters(self) -> None:
        self._seed_analysis(
            query_id="q2",
            analysis_date=date(2024, 1, 10),
            created_at=datetime(2024, 1, 10, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519", date=date(2024, 1, 11), high=101.0, low=95.0, close=96.0),
            ],
        )

        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=1, min_age_days=0, limit=20)

        data = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 10),
            analysis_date_to=date(2024, 1, 10),
        )
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["stock_name"], "贵州茅台")
        self.assertEqual(item["trend_prediction"], "看多")
        self.assertEqual(item["actual_movement"], "down")
        self.assertAlmostEqual(item["actual_return_pct"], -4.0)
        self.assertFalse(item["direction_correct"])

    def test_get_summary_supports_analysis_date_range(self) -> None:
        self._seed_analysis(
            query_id="q2",
            analysis_date=date(2024, 1, 10),
            created_at=datetime(2024, 1, 10, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519", date=date(2024, 1, 11), high=101.0, low=95.0, close=96.0),
            ],
        )

        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=1, min_age_days=0, limit=20)

        summary = service.get_summary(
            scope="stock",
            code="600519",
            eval_window_days=1,
            analysis_date_from=date(2024, 1, 10),
            analysis_date_to=date(2024, 1, 10),
        )
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["total_evaluations"], 1)
        self.assertEqual(summary["completed_count"], 1)
        self.assertEqual(summary["win_count"], 0)
        self.assertEqual(summary["loss_count"], 1)
        self.assertAlmostEqual(summary["direction_accuracy_pct"], 0.0)

    def test_get_summary_date_range_filters_to_single_window_and_engine(self) -> None:
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        with self.db.get_session() as session:
            base_result = session.query(BacktestResult).filter(
                BacktestResult.code == "600519",
                BacktestResult.eval_window_days == 3,
                BacktestResult.engine_version == "v1",
            ).one()
            session.add_all([
                BacktestResult(
                    analysis_history_id=base_result.analysis_history_id,
                    code=base_result.code,
                    analysis_date=base_result.analysis_date,
                    eval_window_days=1,
                    engine_version="v1",
                    eval_status="completed",
                    evaluated_at=datetime(2024, 1, 5, 0, 0, 0),
                    operation_advice="买入",
                    position_recommendation="long",
                    start_price=100.0,
                    end_close=96.0,
                    stock_return_pct=-4.0,
                    direction_expected="up",
                    direction_correct=False,
                    outcome="loss",
                    simulated_return_pct=-4.0,
                ),
                BacktestResult(
                    analysis_history_id=base_result.analysis_history_id,
                    code=base_result.code,
                    analysis_date=base_result.analysis_date,
                    eval_window_days=3,
                    engine_version="v2",
                    eval_status="completed",
                    evaluated_at=datetime(2024, 1, 6, 0, 0, 0),
                    operation_advice="买入",
                    position_recommendation="long",
                    start_price=100.0,
                    end_close=96.0,
                    stock_return_pct=-4.0,
                    direction_expected="up",
                    direction_correct=False,
                    outcome="loss",
                    simulated_return_pct=-4.0,
                ),
            ])
            session.commit()

        rows = service.repo.list_results(
            code="600519",
            eval_window_days=3,
            engine_version="v1",
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
        )
        self.assertEqual(len(rows), 1)

        evaluations = service.get_recent_evaluations(
            code="600519",
            eval_window_days=3,
            limit=10,
            page=1,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
        )
        self.assertEqual(evaluations["total"], 1)
        self.assertEqual(len(evaluations["items"]), 1)
        self.assertEqual(evaluations["items"][0]["engine_version"], "v1")
        self.assertEqual(evaluations["items"][0]["operation_advice"], "买入")
        self.assertEqual(evaluations["items"][0]["action"], "buy")
        self.assertEqual(evaluations["items"][0]["action_label"], "买入")
        self.assertEqual(evaluations["items"][0]["position_recommendation"], "long")

        # Without explicit eval_window_days, summary infers the smallest
        # window from matched rows (window=1 in this dataset) instead of
        # falling back to the config default.
        summary_inferred = service.get_summary(
            scope="stock",
            code="600519",
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
        )
        self.assertIsNotNone(summary_inferred)
        assert summary_inferred is not None
        self.assertEqual(summary_inferred["eval_window_days"], 1)
        self.assertEqual(summary_inferred["engine_version"], "v1")
        self.assertEqual(summary_inferred["total_evaluations"], 1)
        self.assertEqual(summary_inferred["completed_count"], 1)
        self.assertEqual(summary_inferred["win_count"], 0)
        self.assertEqual(summary_inferred["loss_count"], 1)
        self.assertAlmostEqual(summary_inferred["direction_accuracy_pct"], 0.0)

        # With explicit eval_window_days=3, summary filters to that window only.
        summary_explicit = service.get_summary(
            scope="stock",
            code="600519",
            eval_window_days=3,
            analysis_date_from=date(2024, 1, 1),
            analysis_date_to=date(2024, 1, 1),
        )
        self.assertIsNotNone(summary_explicit)
        assert summary_explicit is not None
        self.assertEqual(summary_explicit["eval_window_days"], 3)
        self.assertEqual(summary_explicit["engine_version"], "v1")
        self.assertEqual(summary_explicit["total_evaluations"], 1)
        self.assertEqual(summary_explicit["completed_count"], 1)
        self.assertEqual(summary_explicit["win_count"], 1)
        self.assertEqual(summary_explicit["loss_count"], 0)
        self.assertAlmostEqual(summary_explicit["direction_accuracy_pct"], 100.0)

    def test_get_summary_date_range_rejects_excessive_row_counts(self) -> None:
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        with patch.object(BacktestService, "MAX_DYNAMIC_SUMMARY_ROWS", 0):
            with self.assertRaisesRegex(ValueError, "Date-filtered summary matches too many rows"):
                service.get_summary(
                    scope="stock",
                    code="600519",
                    analysis_date_from=date(2024, 1, 1),
                    analysis_date_to=date(2024, 1, 1),
                )

    def test_get_summary_phase_filter_cap_uses_phase_candidate_message(self) -> None:
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        with patch.object(BacktestService, "MAX_DYNAMIC_SUMMARY_ROWS", 0):
            with self.assertRaisesRegex(ValueError, "Phase-filtered summary candidate set matches too many rows"):
                service.get_summary(
                    scope="stock",
                    code="600519",
                    analysis_phase="intraday",
                )

    def test_phase_filter_results_allows_exact_dynamic_cap(self) -> None:
        service = BacktestService(self.db)
        phase_snapshot = json.dumps({"market_phase_summary": {"phase": "intraday", "market": "cn"}})
        raw_result = json.dumps(
            {
                "operation_advice": "持有观察",
                "action": "watch",
                "action_label": "观望",
                "guardrail_reason": "模型判定观望，保留原始动作",
            },
            ensure_ascii=False,
        )
        rows = [
            (
                self._make_backtest_result(analysis_history_id=idx + 1, analysis_date=date(2024, 1, idx + 1)),
                "贵州茅台",
                "看多",
                datetime(2024, 1, idx + 1, 0, 0, 0),
                phase_snapshot,
                raw_result,
                "simple",
                78,
            )
            for idx in range(2)
        ]

        class RepoStub:
            def get_results_with_context_batch(self, **kwargs):
                offset = int(kwargs["offset"])
                limit = int(kwargs["limit"])
                return rows[offset: offset + limit]

        service.repo = RepoStub()

        with patch.object(BacktestService, "MAX_DYNAMIC_SUMMARY_ROWS", 2):
            data = service.get_recent_evaluations(
                code="600519",
                eval_window_days=1,
                limit=10,
                page=1,
                analysis_phase="intraday",
            )

        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["items"][0]["action"], "watch")
        self.assertEqual(data["items"][0]["action_label"], "观望")

    def test_phase_filter_without_window_matches_summary_window(self) -> None:
        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=3, min_age_days=0, limit=10)

        with self.db.get_session() as session:
            base_result = session.query(BacktestResult).filter(
                BacktestResult.code == "600519",
                BacktestResult.eval_window_days == 3,
                BacktestResult.engine_version == "v1",
            ).one()
            session.add(
                BacktestResult(
                    analysis_history_id=base_result.analysis_history_id,
                    code=base_result.code,
                    analysis_date=base_result.analysis_date,
                    eval_window_days=1,
                    engine_version="v1",
                    eval_status="completed",
                    evaluated_at=datetime(2024, 1, 5, 0, 0, 0),
                    operation_advice="买入",
                    position_recommendation="long",
                    start_price=100.0,
                    end_close=96.0,
                    stock_return_pct=-4.0,
                    direction_expected="up",
                    direction_correct=False,
                    outcome="loss",
                    simulated_return_pct=-4.0,
                )
            )
            session.commit()

        evaluations = service.get_recent_evaluations(
            code="600519",
            limit=10,
            page=1,
            analysis_phase="premarket",
        )
        self.assertEqual(evaluations["total"], 1)
        self.assertEqual(evaluations["items"][0]["eval_window_days"], 1)

        summary = service.get_summary(
            scope="stock",
            code="600519",
            analysis_phase="premarket",
        )
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["eval_window_days"], 1)
        self.assertEqual(summary["total_evaluations"], 1)

    def test_phase_filter_overfetches_before_pagination_and_updates_summary_breakdown(self) -> None:
        self._seed_analysis(
            query_id="q2",
            analysis_date=date(2024, 1, 10),
            created_at=datetime(2024, 1, 10, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519", date=date(2024, 1, 11), high=101.0, low=95.0, close=96.0),
            ],
            phase="intraday",
        )

        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=1, min_age_days=0, limit=20)

        intraday = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=1,
            page=1,
            analysis_phase="intraday",
        )
        self.assertEqual(intraday["total"], 1)
        self.assertEqual(len(intraday["items"]), 1)
        self.assertEqual(intraday["items"][0]["market_phase"], "intraday")
        self.assertEqual(intraday["items"][0]["market_phase_summary"]["phase"], "intraday")

        premarket = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=1,
            page=1,
            analysis_phase="premarket",
        )
        self.assertEqual(premarket["total"], 1)
        self.assertEqual(premarket["items"][0]["market_phase"], "premarket")

        summary = service.get_summary(
            scope="stock",
            code="600519",
            eval_window_days=1,
            analysis_phase="intraday",
        )
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["total_evaluations"], 1)
        self.assertEqual(summary["diagnostics"]["phase_breakdown"]["intraday"], 1)
        self.assertEqual(summary["diagnostics"]["phase_breakdown"]["premarket"], 0)
        self.assertNotIn("premarket", summary["diagnostics"]["raw_phase_counts"])
        self.assertEqual(summary["diagnostics"]["raw_phase_counts"]["intraday"], 1)

    def test_phase_filter_buckets_detailed_internal_phases(self) -> None:
        self._seed_analysis(
            query_id="q2",
            analysis_date=date(2024, 1, 10),
            created_at=datetime(2024, 1, 10, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519", date=date(2024, 1, 11), high=101.0, low=95.0, close=96.0),
            ],
            phase="lunch_break",
        )
        self._seed_analysis(
            query_id="q3",
            analysis_date=date(2024, 1, 12),
            created_at=datetime(2024, 1, 12, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519", date=date(2024, 1, 13), high=101.0, low=95.0, close=96.0),
            ],
            phase="closing_auction",
        )
        self._seed_analysis(
            query_id="q4",
            analysis_date=date(2024, 1, 14),
            created_at=datetime(2024, 1, 14, 0, 0, 0),
            operation_advice="买入",
            trend_prediction="看多",
            start_close=100.0,
            forward_bars=[
                StockDaily(code="600519", date=date(2024, 1, 15), high=101.0, low=95.0, close=96.0),
            ],
            phase="non_trading",
        )

        service = BacktestService(self.db)
        service.run_backtest(code="600519", force=False, eval_window_days=1, min_age_days=0, limit=20)

        intraday = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_phase="intraday",
        )
        self.assertEqual(intraday["total"], 2)
        self.assertEqual(
            {item["market_phase_summary"]["phase"] for item in intraday["items"]},
            {"lunch_break", "closing_auction"},
        )
        self.assertTrue(all(item["market_phase"] == "intraday" for item in intraday["items"]))

        unknown = service.get_recent_evaluations(
            code="600519",
            eval_window_days=1,
            limit=10,
            page=1,
            analysis_phase="unknown",
        )
        self.assertEqual(unknown["total"], 1)
        self.assertEqual(unknown["items"][0]["market_phase"], "unknown")
        self.assertEqual(unknown["items"][0]["market_phase_summary"]["phase"], "non_trading")

    def test_phase_filter_rejects_values_outside_public_query_contract(self) -> None:
        service = BacktestService(self.db)

        with self.assertRaisesRegex(ValueError, "analysis_phase must be one of"):
            service.get_recent_evaluations(code=None, analysis_phase="lunch_break")

        with self.assertRaisesRegex(ValueError, "analysis_phase must be one of"):
            service.get_summary(code=None, scope="overall", analysis_phase="banana")

    def test_multi_stock_summaries(self) -> None:
        """Verify separate summaries for multiple stocks + correct overall aggregate."""
        old_created_at = datetime(2024, 1, 1, 0, 0, 0)

        with self.db.get_session() as session:
            # Second stock with sell advice -- price drops (win for cash/down)
            session.add(
                AnalysisHistory(
                    query_id="q2",
                    code="000001",
                    name="平安银行",
                    report_type="simple",
                    sentiment_score=30,
                    operation_advice="卖出",
                    trend_prediction="看空",
                    analysis_summary="test2",
                    stop_loss=None,
                    take_profit=None,
                    created_at=old_created_at,
                    context_snapshot='{"enhanced_context": {"date": "2024-01-01"}}',
                )
            )
            session.add(
                StockDaily(code="000001", date=date(2024, 1, 1), open=10.0, high=10.2, low=9.8, close=10.0)
            )
            session.add_all([
                StockDaily(code="000001", date=date(2024, 1, 2), high=10.0, low=9.5, close=9.6),
                StockDaily(code="000001", date=date(2024, 1, 3), high=9.7, low=9.3, close=9.4),
                StockDaily(code="000001", date=date(2024, 1, 4), high=9.5, low=9.0, close=9.1),
            ])
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(code=None, force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertEqual(stats["saved"], 2)
        self.assertEqual(stats["completed"], 2)

        with self.db.get_session() as session:
            # Each stock has its own summary
            s1 = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "stock", BacktestSummary.code == "600519"
            ).first()
            s2 = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "stock", BacktestSummary.code == "000001"
            ).first()
            self.assertIsNotNone(s1)
            self.assertIsNotNone(s2)
            self.assertEqual(s1.win_count, 1)
            self.assertEqual(s2.win_count, 1)

            # Overall aggregates both
            overall = session.query(BacktestSummary).filter(
                BacktestSummary.scope == "overall",
                BacktestSummary.code == OVERALL_SENTINEL_CODE,
            ).first()
            self.assertIsNotNone(overall)
            self.assertEqual(overall.total_evaluations, 2)
            self.assertEqual(overall.completed_count, 2)
            self.assertEqual(overall.win_count, 2)

    def test_run_backtest_excludes_market_review_records(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q-market-review",
                    code="MARKET",
                    name="大盘复盘",
                    report_type="market_review",
                    sentiment_score=50,
                    operation_advice="查看复盘",
                    trend_prediction="大盘复盘",
                    analysis_summary="market review summary",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 3, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-03"}}',
                )
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(code=None, force=False, eval_window_days=3, min_age_days=0, limit=10)

        self.assertEqual(stats["processed"], 1)
        self.assertEqual(stats["saved"], 1)
        self.assertEqual(self._count_results(), 1)
        with self.db.get_session() as session:
            self.assertEqual(
                session.query(BacktestResult).filter(BacktestResult.code == "MARKET").count(),
                0,
            )

    def test_run_backtest_includes_null_report_type_records(self) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="q-null-report-type",
                    code="000858",
                    name="五粮液",
                    report_type=None,
                    sentiment_score=60,
                    operation_advice="持有",
                    trend_prediction="震荡",
                    analysis_summary="legacy null report_type row",
                    stop_loss=None,
                    take_profit=None,
                    created_at=datetime(2024, 1, 3, 0, 0, 0),
                    context_snapshot='{"enhanced_context": {"date": "2024-01-03"}}',
                )
            )
            session.add_all(
                [
                    StockDaily(code="000858", date=date(2024, 1, 3), open=12.0, high=12.8, low=11.5, close=12.2),
                    StockDaily(code="000858", date=date(2024, 1, 4), open=12.2, high=13.0, low=12.0, close=12.6),
                    StockDaily(code="000858", date=date(2024, 1, 5), open=12.6, high=12.9, low=11.9, close=12.4),
                ]
            )
            session.commit()

        service = BacktestService(self.db)
        stats = service.run_backtest(code=None, force=False, eval_window_days=3, min_age_days=0, limit=10)
        self.assertGreaterEqual(stats["processed"], 2)
        self.assertGreaterEqual(stats["saved"], 2)
        with self.db.get_session() as session:
            self.assertEqual(
                session.query(BacktestResult).filter(BacktestResult.code == "000858").count(),
                1,
            )


if __name__ == "__main__":
    unittest.main()
