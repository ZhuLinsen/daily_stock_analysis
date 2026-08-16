from src.services.intraday_picker.metrics import calculate_intraday_metrics, calculate_rvol_time


def test_rvol_time_uses_same_time_median():
    rvol, confidence = calculate_rvol_time(300.0, [100, 100, 100, 100, 100, 100, 100, 100, 100, 100])
    assert rvol == 3.0
    assert confidence == 1.0


def test_rvol_time_fails_open_with_short_history():
    rvol, confidence = calculate_rvol_time(300.0, [100, 100, 100, 100])
    assert rvol is None
    assert confidence == 0.0


def test_intraday_price_metrics():
    metrics = calculate_intraday_metrics(
        {
            "price": 10.8,
            "open": 10.0,
            "high": 11.0,
            "low": 9.8,
            "cumulative_amount": 300.0,
        },
        [{"cumulative_amount": 100.0} for _ in range(10)],
    )
    assert metrics.rvol_time == 3.0
    assert round(metrics.price_strength, 2) == 8.0
    assert 0.0 <= metrics.high_position <= 1.0
    assert metrics.pullback_from_high_pct > 0
