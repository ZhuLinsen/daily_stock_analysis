# -*- coding: utf-8 -*-
"""Unit & compatibility tests for BacktestEngine quantitative risk telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import math
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from api.v1.schemas.backtest import PerformanceMetrics
from src.core.backtest_engine import OVERALL_SENTINEL_CODE, BacktestEngine
from src.services.backtest_service import BacktestService
from src.storage import BacktestSummary


@dataclass
class _QuantRow:
    eval_status: str = "completed"
    position_recommendation: str = "long"
    outcome: str = "win"
    direction_correct: bool | None = True
    stock_return_pct: float | None = 0.0
    simulated_return_pct: float | None = 0.0
    hit_stop_loss: bool | None = False
    hit_take_profit: bool | None = False
    first_hit: str | None = "neither"
    first_hit_trading_days: int | None = None
    operation_advice: str | None = "买入"
    simulated_exit_reason: str | None = "window_end"
    analysis_date: date | None = None
    evaluated_at: datetime | None = None
    analysis_history_id: int | None = None
    code: str | None = "600519"
    eval_window_days: int = 10
    engine_version: str = "v1.1"


class BacktestQuantMetricsTestCase(unittest.TestCase):
    def test_computes_profit_factor_drawdown_ratios_and_chronological_equity(self) -> None:
        rows = [
            # Out of chronological order intentionally; engine must sort by analysis_date
            _QuantRow(
                analysis_date=date(2026, 2, 10),
                analysis_history_id=3,
                outcome="win",
                simulated_return_pct=15.0,
                stock_return_pct=15.0,
                simulated_exit_reason="take_profit",
                operation_advice="买入",
            ),
            _QuantRow(
                analysis_date=date(2025, 11, 2),
                analysis_history_id=1,
                outcome="win",
                simulated_return_pct=10.0,
                stock_return_pct=10.0,
                simulated_exit_reason="take_profit",
                operation_advice="买入",
            ),
            _QuantRow(
                analysis_date=date(2025, 12, 5),
                analysis_history_id=2,
                outcome="loss",
                direction_correct=False,
                simulated_return_pct=-5.0,
                stock_return_pct=-5.0,
                simulated_exit_reason="stop_loss",
                operation_advice="加仓",
            ),
            _QuantRow(
                analysis_date=date(2026, 3, 12),
                analysis_history_id=4,
                position_recommendation="cash",
                outcome="neutral",
                direction_correct=None,
                simulated_return_pct=0.0,
                stock_return_pct=-1.0,
                simulated_exit_reason="cash",
                operation_advice="观望",
            ),
        ]

        summary = BacktestEngine.compute_summary(
            results=rows,
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )
        qm = summary["quant_metrics"]
        self.assertIsNotNone(qm)
        self.assertEqual(qm, summary["diagnostics"]["quant_metrics"])
        self.assertEqual(qm["sample_count"], 4)
        self.assertEqual(qm["active_trade_count"], 3)
        self.assertEqual(qm["profit_factor"], 5.0)
        self.assertEqual(qm["avg_win_pct"], 12.5)
        self.assertEqual(qm["avg_loss_pct"], -5.0)
        self.assertEqual(qm["payoff_ratio"], 2.5)
        self.assertEqual(qm["expectancy_pct"], 5.0)
        # (1.10) * (0.95) * (1.15) * (1.0) - 1 = 0.20174999999999987 -> 20.17%
        self.assertEqual(qm["cumulative_return_pct"], 20.17)
        self.assertEqual(qm["max_drawdown_pct"], 5.0)
        self.assertIsNotNone(qm["sharpe_ratio"])
        self.assertGreater(qm["sharpe_ratio"], 0.0)
        self.assertIsNotNone(qm["sortino_ratio"])
        self.assertGreater(qm["sortino_ratio"], 0.0)
        # 130 calendar days -> CAGR = ((1.20175 ** (365.25 / 130)) - 1) * 100 / 5.0 = 13.52
        self.assertEqual(qm["calmar_ratio"], 13.52)
        self.assertEqual(qm["best_trade_pct"], 15.0)
        self.assertEqual(qm["worst_trade_pct"], -5.0)
        self.assertEqual(qm["max_consecutive_wins"], 1)
        self.assertEqual(qm["max_consecutive_losses"], 1)
        self.assertEqual(
            qm["exit_reason_breakdown"],
            {"cash": 1, "stop_loss": 1, "take_profit": 2},
        )
        self.assertEqual([pt["date"] for pt in qm["equity_curve"]], [
            "2025-11-02",
            "2025-12-05",
            "2026-02-10",
            "2026-03-12",
        ])

    def test_edge_cases_all_wins_constant_empty_and_curve_cap(self) -> None:
        empty_summary = BacktestEngine.compute_summary(
            results=[],
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )
        self.assertEqual(empty_summary["quant_metrics"]["sample_count"], 0)
        self.assertIsNone(empty_summary["quant_metrics"]["profit_factor"])
        self.assertEqual(empty_summary["quant_metrics"]["equity_curve"], [])

        # Constant positive returns: no losses and zero stdev -> None profit_factor/sharpe
        rows = [
            _QuantRow(
                analysis_date=date(2026, 1, 1),
                analysis_history_id=i,
                simulated_return_pct=2.0,
                stock_return_pct=2.0,
            )
            for i in range(1, 51)
        ]
        rows.append(
            _QuantRow(
                analysis_date=date(2026, 2, 28),
                analysis_history_id=99,
                simulated_return_pct=math.nan,
                stock_return_pct=1.0,
            )
        )
        qm = BacktestEngine.compute_summary(
            results=rows,
            scope="stock",
            code="AAPL",
            eval_window_days=5,
            engine_version="v1.1",
        )["quant_metrics"]
        self.assertEqual(qm["sample_count"], 50)
        self.assertEqual(len(qm["equity_curve"]), 40)
        self.assertEqual(qm["equity_curve"][-1]["equity_pct"], qm["cumulative_return_pct"])
        self.assertIsNone(qm["profit_factor"])
        self.assertIsNone(qm["sharpe_ratio"])
        self.assertIsNone(qm["sortino_ratio"])
        self.assertEqual(qm["max_drawdown_pct"], 0.0)
        self.assertEqual(qm["max_consecutive_wins"], 50)

    def test_legacy_and_quant_summary_roundtrip_via_service_and_schema(self) -> None:
        legacy_row = BacktestSummary(
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
            total_evaluations=5,
            completed_count=5,
            insufficient_count=0,
            long_count=3,
            cash_count=2,
            win_count=3,
            loss_count=1,
            neutral_count=1,
            advice_breakdown_json=json.dumps({"买入": {"total": 3, "win": 2, "loss": 1, "neutral": 0, "win_rate_pct": 66.67}}),
            diagnostics_json=json.dumps({"eval_status": {"completed": 5}}),
        )
        legacy_dict = BacktestService._summary_to_dict(legacy_row)
        self.assertIsNone(legacy_dict["quant_metrics"])
        legacy_schema = PerformanceMetrics(**legacy_dict)
        self.assertIsNone(legacy_schema.quant_metrics)

        summary_data = BacktestEngine.compute_summary(
            results=[
                _QuantRow(simulated_return_pct=8.0, outcome="win", simulated_exit_reason="take_profit"),
                _QuantRow(simulated_return_pct=-3.0, outcome="loss", simulated_exit_reason="stop_loss"),
            ],
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )
        model = BacktestService._build_summary_model(summary_data)
        hydrated = BacktestService._summary_to_dict(model)
        self.assertIsNotNone(hydrated["quant_metrics"])
        schema_obj = PerformanceMetrics(**hydrated)
        self.assertEqual(schema_obj.quant_metrics["profit_factor"], 2.67)

    def test_50_trade_equity_curve_window_starts_at_index_11(self) -> None:
        base_day = date(2026, 1, 1)
        rows = [
            _QuantRow(
                analysis_date=base_day + timedelta(days=idx),
                analysis_history_id=idx + 1,
                outcome="win",
                simulated_return_pct=1.0,
                stock_return_pct=1.0,
                simulated_exit_reason="take_profit",
            )
            for idx in range(50)
        ]

        quant = BacktestEngine.compute_summary(
            results=rows,
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )["quant_metrics"]
        curve = quant["equity_curve"]
        self.assertEqual(len(curve), 40)
        self.assertEqual(curve[0]["index"], 11)
        self.assertEqual(curve[-1]["index"], 50)

    def test_sub_001_pct_micro_drawdown_guards_calmar_ratio(self) -> None:
        rows = [
            _QuantRow(
                analysis_date=date(2025, 12, 1),
                analysis_history_id=1,
                outcome="win",
                simulated_return_pct=10.0,
                stock_return_pct=10.0,
                simulated_exit_reason="take_profit",
            ),
            _QuantRow(
                analysis_date=date(2026, 1, 15),
                analysis_history_id=2,
                outcome="loss",
                direction_correct=False,
                simulated_return_pct=-0.006,
                stock_return_pct=-0.006,
                simulated_exit_reason="window_end",
            ),
            _QuantRow(
                analysis_date=date(2026, 3, 10),
                analysis_history_id=3,
                outcome="win",
                simulated_return_pct=5.0,
                stock_return_pct=5.0,
                simulated_exit_reason="take_profit",
            ),
        ]

        quant = BacktestEngine.compute_summary(
            results=rows,
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )["quant_metrics"]
        self.assertEqual(quant["max_drawdown_pct"], 0.01)
        self.assertIsNone(quant["calmar_ratio"])

    def test_dynamic_filtered_summary_includes_quant_metrics(self) -> None:
        rows = [
            _QuantRow(
                analysis_date=date(2026, 3, 2),
                analysis_history_id=11,
                outcome="win",
                simulated_return_pct=8.0,
                stock_return_pct=8.0,
                simulated_exit_reason="take_profit",
            ),
            _QuantRow(
                analysis_date=date(2026, 3, 6),
                analysis_history_id=12,
                outcome="loss",
                direction_correct=False,
                simulated_return_pct=-3.0,
                stock_return_pct=-3.0,
                simulated_exit_reason="stop_loss",
            ),
        ]
        service = BacktestService.__new__(BacktestService)
        service.repo = MagicMock()
        service.repo.count_results.return_value = len(rows)
        service.repo.list_results.return_value = rows

        mock_config = SimpleNamespace(
            backtest_engine_version="v1.1",
            backtest_eval_window_days=10,
        )
        with patch("src.services.backtest_service.get_config", return_value=mock_config):
            summary = service.get_summary(
                scope="overall",
                code=None,
                eval_window_days=10,
                analysis_date_from=date(2026, 3, 1),
                analysis_date_to=date(2026, 3, 15),
            )

        self.assertIsNotNone(summary)
        self.assertIsNotNone(summary["quant_metrics"])
        self.assertEqual(summary["quant_metrics"]["profit_factor"], 2.67)
        validated = PerformanceMetrics(**summary)
        self.assertEqual(validated.quant_metrics["profit_factor"], 2.67)

    def test_compound_overflow_stays_json_safe_and_preserves_drawdown(self) -> None:
        base_day = date(2020, 1, 1)
        rows = [
            _QuantRow(
                analysis_date=base_day + timedelta(days=idx % 365),
                analysis_history_id=idx + 1,
                outcome="win",
                simulated_return_pct=50.0,
                stock_return_pct=50.0,
                simulated_exit_reason="take_profit",
            )
            for idx in range(1800)
        ]
        summary = BacktestEngine.compute_summary(
            results=rows,
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )
        json.dumps(summary, allow_nan=False)
        qm = summary["quant_metrics"]
        self.assertIsNone(qm["cumulative_return_pct"])
        self.assertIsNone(qm["calmar_ratio"])
        self.assertEqual(qm["max_drawdown_pct"], 0.0)
        self.assertEqual(qm["expectancy_pct"], 50.0)
        self.assertTrue(all(pt["equity_pct"] is None for pt in qm["equity_curve"]))
        validated = PerformanceMetrics(**summary)
        self.assertIsNone(validated.quant_metrics["cumulative_return_pct"])

    def test_invalid_targets_never_fall_back_to_stock_return(self) -> None:
        invalid_row = _QuantRow(
            analysis_date=date(2026, 3, 2),
            analysis_history_id=1,
            position_recommendation="long",
            outcome="win",
            simulated_return_pct=None,
            stock_return_pct=10.0,
            simulated_exit_reason="invalid_targets",
        )
        only_invalid = BacktestEngine.compute_summary(
            results=[invalid_row],
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )["quant_metrics"]
        self.assertEqual(only_invalid["sample_count"], 0)
        self.assertEqual(only_invalid["active_trade_count"], 0)
        self.assertIsNone(only_invalid["cumulative_return_pct"])
        self.assertEqual(only_invalid["exit_reason_breakdown"], {"invalid_targets": 1})

        cash_row = _QuantRow(
            analysis_date=date(2026, 3, 5),
            analysis_history_id=2,
            position_recommendation="cash",
            outcome="neutral",
            simulated_return_pct=0.0,
            stock_return_pct=-2.0,
            simulated_exit_reason="cash",
        )
        with_cash = BacktestEngine.compute_summary(
            results=[invalid_row, cash_row],
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )["quant_metrics"]
        self.assertEqual(with_cash["sample_count"], 1)
        self.assertEqual(with_cash["active_trade_count"], 0)
        self.assertEqual(with_cash["cumulative_return_pct"], 0.0)

    def test_same_day_rerun_does_not_change_drawdown_or_streaks(self) -> None:
        day = date(2026, 3, 10)
        base_time = datetime(2026, 3, 20, 10, 0, 0)
        returns = [-20.0, -20.0, 25.0, 25.0]
        rows_initial = [
            _QuantRow(
                analysis_date=day,
                analysis_history_id=idx + 1,
                evaluated_at=base_time + timedelta(seconds=idx),
                outcome="loss" if ret < 0 else "win",
                simulated_return_pct=ret,
                stock_return_pct=ret,
            )
            for idx, ret in enumerate(returns)
        ]
        rows_rerun = [
            _QuantRow(
                analysis_date=day,
                analysis_history_id=idx + 1,
                evaluated_at=base_time + timedelta(days=5) if idx == 1 else base_time + timedelta(seconds=idx),
                outcome="loss" if ret < 0 else "win",
                simulated_return_pct=ret,
                stock_return_pct=ret,
            )
            for idx, ret in enumerate(returns)
        ]

        q_initial = BacktestEngine.compute_summary(
            results=rows_initial,
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )["quant_metrics"]
        q_rerun = BacktestEngine.compute_summary(
            results=rows_rerun,
            scope="overall",
            code=OVERALL_SENTINEL_CODE,
            eval_window_days=10,
            engine_version="v1.1",
        )["quant_metrics"]
        self.assertEqual(q_initial["max_drawdown_pct"], 36.0)
        self.assertEqual(q_initial["max_consecutive_losses"], 2)
        self.assertEqual(q_rerun["max_drawdown_pct"], q_initial["max_drawdown_pct"])
        self.assertEqual(q_rerun["max_consecutive_losses"], q_initial["max_consecutive_losses"])

    def test_calmar_ratio_annualizes_cagr_across_spans_and_omits_short_windows(self) -> None:
        # 1.20 * 0.90 = 1.08 (+8% cumulative return) with 10% max drawdown over 6 months vs 2 years.
        six_months = [
            _QuantRow(analysis_date=date(2025, 1, 1), analysis_history_id=1, simulated_return_pct=20.0),
            _QuantRow(analysis_date=date(2025, 7, 3), analysis_history_id=2, simulated_return_pct=-10.0),
        ]
        two_years = [
            _QuantRow(analysis_date=date(2024, 1, 1), analysis_history_id=1, simulated_return_pct=20.0),
            _QuantRow(analysis_date=date(2026, 1, 1), analysis_history_id=2, simulated_return_pct=-10.0),
        ]
        short_span = [
            _QuantRow(analysis_date=date(2026, 3, 1), analysis_history_id=1, simulated_return_pct=20.0),
            _QuantRow(analysis_date=date(2026, 3, 11), analysis_history_id=2, simulated_return_pct=-10.0),
        ]

        q_6m = BacktestEngine.compute_summary(
            results=six_months, scope="overall", code=OVERALL_SENTINEL_CODE, eval_window_days=10, engine_version="v1.1",
        )["quant_metrics"]
        q_2y = BacktestEngine.compute_summary(
            results=two_years, scope="overall", code=OVERALL_SENTINEL_CODE, eval_window_days=10, engine_version="v1.1",
        )["quant_metrics"]
        q_short = BacktestEngine.compute_summary(
            results=short_span, scope="overall", code=OVERALL_SENTINEL_CODE, eval_window_days=10, engine_version="v1.1",
        )["quant_metrics"]

        self.assertEqual(q_6m["cumulative_return_pct"], 8.0)
        self.assertEqual(q_2y["cumulative_return_pct"], 8.0)
        self.assertGreater(q_6m["calmar_ratio"], q_2y["calmar_ratio"])
        self.assertEqual(q_6m["calmar_ratio"], 1.66)
        self.assertEqual(q_2y["calmar_ratio"], 0.39)
        self.assertIsNone(q_short["calmar_ratio"])

    def test_dated_run_aligning_existing_dates_recomputes_cached_summaries(self) -> None:
        service = BacktestService.__new__(BacktestService)
        call_order: list[str] = []

        def fake_align(**kwargs):
            call_order.append("align")
            codes_out = kwargs.get("aligned_codes_out")
            if codes_out is not None:
                codes_out.add("600519")
            return 1

        def fake_recompute(**kwargs):
            call_order.append("recompute")
            self.assertEqual(kwargs["touched_codes"], ["600519"])

        service.repo = MagicMock()
        service.repo.get_candidates.return_value = []
        service.repo.align_existing_result_dates.side_effect = fake_align
        service._recompute_summaries = fake_recompute
        service._has_matching_analysis_for_run = MagicMock(return_value=True)

        mock_config = SimpleNamespace(
            backtest_engine_version="v1.1",
            backtest_eval_window_days=10,
            backtest_min_age_days=14,
            backtest_neutral_band_pct=2.0,
        )
        with patch("src.services.backtest_service.get_config", return_value=mock_config):
            res = service.run_backtest(
                code=None,
                force=False,
                eval_window_days=10,
                analysis_date_from=date(2026, 3, 1),
                analysis_date_to=date(2026, 3, 15),
            )

        self.assertEqual(res["saved"], 0)
        self.assertEqual(call_order, ["align", "recompute"])


if __name__ == "__main__":
    unittest.main()
