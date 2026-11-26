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
                analysis_date=date(2026, 3, 10),
                analysis_history_id=3,
                outcome="win",
                simulated_return_pct=15.0,
                stock_return_pct=15.0,
                simulated_exit_reason="take_profit",
                operation_advice="买入",
            ),
            _QuantRow(
                analysis_date=date(2026, 3, 2),
                analysis_history_id=1,
                outcome="win",
                simulated_return_pct=10.0,
                stock_return_pct=10.0,
                simulated_exit_reason="take_profit",
                operation_advice="买入",
            ),
            _QuantRow(
                analysis_date=date(2026, 3, 5),
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
        self.assertIsNotNone(qm["calmar_ratio"])
        self.assertEqual(qm["best_trade_pct"], 15.0)
        self.assertEqual(qm["worst_trade_pct"], -5.0)
        self.assertEqual(qm["max_consecutive_wins"], 1)
        self.assertEqual(qm["max_consecutive_losses"], 1)
        self.assertEqual(
            qm["exit_reason_breakdown"],
            {"cash": 1, "stop_loss": 1, "take_profit": 2},
        )
        self.assertEqual([pt["date"] for pt in qm["equity_curve"]], [
            "2026-03-02",
            "2026-03-05",
            "2026-03-10",
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
                analysis_date=date(2026, 3, 1),
                analysis_history_id=1,
                outcome="win",
                simulated_return_pct=10.0,
                stock_return_pct=10.0,
                simulated_exit_reason="take_profit",
            ),
            _QuantRow(
                analysis_date=date(2026, 3, 5),
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


if __name__ == "__main__":
    unittest.main()
