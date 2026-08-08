from datetime import date

from src.services.screening_performance_service import ScreeningPerformanceService


def test_screening_performance_calculates_stock_and_benchmark_excess_return() -> None:
    result = ScreeningPerformanceService._evaluate_one(
        run_id="run-1",
        strategy="dual_low",
        market="cn",
        candidate={"code": "000001", "name": "平安银行", "rank": 1, "price": 10.0},
        code="000001",
        analysis_date=date(2026, 8, 1),
        horizon=1,
        stock_rows=[
            {"date": date(2026, 8, 1), "close": 10.0, "low": 9.8},
            {"date": date(2026, 8, 2), "close": 10.5, "low": 10.0},
        ],
        stock_source="test_stock",
        benchmark_rows={
            date(2026, 8, 1): {"date": date(2026, 8, 1), "close": 100.0},
            date(2026, 8, 2): {"date": date(2026, 8, 2), "close": 101.0},
        },
        benchmark_source="test_benchmark",
        benchmark_code="sh000300",
    )

    assert result["eval_status"] == "evaluated"
    assert round(result["stock_return_pct"], 2) == 5.0
    assert round(result["benchmark_return_pct"], 2) == 1.0
    assert round(result["excess_return_pct"], 2) == 4.0
    assert round(result["max_drawdown_pct"], 2) == -2.0


def test_screening_performance_keeps_incomplete_forward_window_pending() -> None:
    result = ScreeningPerformanceService._evaluate_one(
        run_id="run-1",
        strategy="dual_low",
        market="cn",
        candidate={"code": "000001", "name": "平安银行", "rank": 1, "price": 10.0},
        code="000001",
        analysis_date=date(2026, 8, 1),
        horizon=5,
        stock_rows=[
            {"date": date(2026, 8, 1), "close": 10.0, "low": 9.8},
            {"date": date(2026, 8, 2), "close": 10.5, "low": 10.0},
        ],
        stock_source="test_stock",
        benchmark_rows={},
        benchmark_source="unavailable",
        benchmark_code="sh000300",
    )

    assert result["eval_status"] == "pending"
    assert result["stock_return_pct"] is None
    assert "等待" in result["message"]
