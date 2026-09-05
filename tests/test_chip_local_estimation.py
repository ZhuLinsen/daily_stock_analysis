# -*- coding: utf-8 -*-
"""单元测试：本地 CYQ 筹码估算算法（data_provider/akshare_fetcher._compute_cyq_metrics）。

东财 push2his 接口不可达时的降级路径。测试不依赖网络，使用构造 K 线数据。
"""

import pytest

from data_provider.akshare_fetcher import _compute_cyq_metrics


def _bars(price, n=120, turn=0.5, drift=0.0):
    """构造 n 根一字板行情（开高低收相同），换手率 turn。"""
    bars = []
    for i in range(n):
        p = round(price + drift * i, 2)
        bars.append(
            {
                "date": f"2026-01-{i + 1:02d}",
                "open": p,
                "high": p,
                "low": p,
                "close": p,
                "turn": turn,
            }
        )
    return bars


def test_single_price_limit_board():
    """一字板：全部筹码堆在同一价格，平均成本收敛到该价格。"""
    bars = _bars(price=10.0, turn=0.5)
    result = _compute_cyq_metrics(bars)
    assert result is not None
    profit_ratio, avg_cost, lo90, hi90, con90, lo70, hi70, con70, date = result
    assert 0 <= profit_ratio <= 1
    assert date == "2026-01-120"
    # 全部筹码在同一格：90/70 成本区间接近单点、集中度接近 0
    assert abs(avg_cost - 10.0) < 0.05
    assert abs(lo90 - hi90) < 0.05
    assert abs(lo70 - hi70) < 0.05
    assert con90 < 0.01
    assert con70 < 0.01


def test_uptrend_bars_produce_reasonable_range():
    """趋势行情：输出应在合理数值区间内。"""
    bars = _bars(price=10.0, n=120, turn=0.5, drift=0.05)
    result = _compute_cyq_metrics(bars)
    assert result is not None
    profit_ratio, avg_cost, lo90, hi90, con90, lo70, hi70, con70, _ = result
    # 区间单调性
    assert 0 < lo70 <= hi70
    assert 0 < lo90 <= hi90
    assert lo70 >= lo90
    assert hi70 <= hi90
    assert 0 <= con70 <= con90 <= 1
    # 平均成本应在价格范围内（10.0 ~ 15.95）
    assert 10.0 < avg_cost < 17.0


def test_insufficient_bars():
    """空输入或单根 K 线时返回 None（算法层最小前置条件）。"""
    assert _compute_cyq_metrics([]) is None
    assert _compute_cyq_metrics(_bars(price=10.0, n=1)) is None
    # 两根及以上即可计算（日常调用方会保证 >=60 根的有效窗口）
    assert _compute_cyq_metrics(_bars(price=10.0, n=2)) is not None


def test_zero_turnover_is_math_degenerate():
    """换手率恒为 0 时筹码既不衰减也不累积，总量为 0，按 None 处理。"""
    bars = _bars(price=10.0, n=120, turn=0.0)
    assert _compute_cyq_metrics(bars) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))