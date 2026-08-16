from src.services.intraday_picker.models import IntradayCandidate, IntradayMetrics, StrategyHit
from src.services.intraday_picker.scoring import rank_candidates, score_candidate, score_rvol


def _candidate(change=3.0, rvol=3.0, pullback=0.5, hit_count=2):
    hits = [
        StrategyHit(stock_code="600000", strategy_id=f"s{i}", strategy_score=80.0)
        for i in range(hit_count)
    ]
    return IntradayCandidate(
        stock_code="600000",
        change_pct=change,
        strategy_hits=hits,
        strategy_score=80.0,
        metrics=IntradayMetrics(
            rvol_time=rvol,
            rvol_confidence=1.0,
            price_strength=2.0,
            high_position=0.8,
            pullback_from_high_pct=pullback,
            sector_score=80.0,
            breakout_score=75.0,
            risk_quality_score=70.0,
        ),
    )


def test_rvol_mapping_is_capped():
    assert score_rvol(0.5) == 10
    assert score_rvol(2.5) == 80
    assert score_rvol(10) == 100


def test_overheat_and_pullback_reduce_score():
    healthy = _candidate(change=3.0, pullback=0.5)
    overheated = _candidate(change=9.0, pullback=4.5)
    assert score_candidate(healthy) > score_candidate(overheated)


def test_multi_strategy_resonance_helps_rank():
    single = _candidate(hit_count=1)
    triple = _candidate(hit_count=3)
    ranked = rank_candidates([single, triple])
    assert ranked[0] is triple
