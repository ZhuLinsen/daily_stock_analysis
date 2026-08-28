# -*- coding: utf-8 -*-
"""Tests for the virtual trader mean-reversion strategy engine."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.services.virtual_trader.strategy import (
    compute_bollinger,
    compute_fee,
    estimate_buy_quantity,
    evaluate_buy,
    evaluate_sell,
)


def _mk_df(closes) -> pd.DataFrame:
    closes = list(closes)
    return pd.DataFrame(
        {
            "date": [date(2026, 1, 1) + timedelta(days=i) for i in range(len(closes))],
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        }
    )


def _uptrend_then_dip(base=100.0, days=75, dip=(0.96, 0.885, 0.80)):
    closes = list(base * (1.003 ** np.arange(days)))
    last = closes[-1]
    factor = 1.0
    for ratio in dip:
        factor *= ratio
        closes.append(last * factor)
    return closes


class TestBollinger:
    def test_columns_and_band_order(self):
        closes = list(100 + np.random.default_rng(1).normal(0, 2, 40))
        out = compute_bollinger(_mk_df(closes))
        assert {"boll_mid", "boll_upper", "boll_lower", "bias_mid"} <= set(out.columns)
        tail = out.iloc[-1]
        assert tail["boll_upper"] > tail["boll_mid"] > tail["boll_lower"]
        expected_bias = (tail["close"] - tail["boll_mid"]) / tail["boll_mid"] * 100
        assert abs(tail["bias_mid"] - expected_bias) < 1e-9

    def test_insufficient_history_is_nan(self):
        out = compute_bollinger(_mk_df([100, 101, 102]))
        assert out["boll_mid"].isna().all()


class TestEvaluateBuy:
    def test_uptrend_oversold_dip_triggers_buy(self):
        sig = evaluate_buy(_mk_df(_uptrend_then_dip()))
        assert sig.action == "buy"
        assert sig.direction == "up"
        assert sig.target_price is not None and sig.target_price > 0
        assert 0 < sig.score <= 100
        assert "跌破布林下轨" in sig.reason

    def test_downtrend_rejects_buy(self):
        closes = list(100 * (0.997 ** np.arange(78)))
        sig = evaluate_buy(_mk_df(closes))
        assert sig.action == "hold"

    def test_flat_no_signal(self):
        sig = evaluate_buy(_mk_df([100.0] * 80))
        assert sig.action == "hold"

    def test_short_history_holds(self):
        sig = evaluate_buy(_mk_df(_uptrend_then_dip(days=20)))
        assert sig.action == "hold"
        assert sig.reason == "历史数据不足"


class TestEvaluateSell:
    def test_touch_upper_band_sells(self):
        closes = list(100 * (0.997 ** np.arange(57)))
        closes += [closes[-1] * 1.05, closes[-1] * 1.05 * 1.12, closes[-1] * 1.05 * 1.12 * 1.18]
        sig = evaluate_sell(_mk_df(closes), avg_cost=closes[0])
        assert sig.action == "sell"
        assert "均值回归兑现" in sig.reason

    def test_stop_loss_triggers(self):
        closes = _uptrend_then_dip()
        sig = evaluate_sell(_mk_df(closes), avg_cost=closes[-1] * 1.2)
        assert sig.action == "sell"
        assert "止损" in sig.reason

    def test_hold_when_no_condition(self):
        closes = list(100 * (1.001 ** np.arange(80)))
        sig = evaluate_sell(_mk_df(closes), avg_cost=closes[-1])
        assert sig.action == "hold"


class TestSizingAndFees:
    def test_cn_lot_rounding_and_caps(self):
        qty = estimate_buy_quantity(
            price=10.0,
            cash=100_000.0,
            position_value=0.0,
            total_asset=1_000_000.0,
            max_position_pct=15.0,
            reserve_floor_pct=10.0,
            market="cn",
        )
        assert qty > 0 and qty % 100 == 0
        assert qty * 10.0 <= 1_000_000.0 * 0.15

    def test_position_cap_blocks_addition(self):
        qty = estimate_buy_quantity(
            price=10.0,
            cash=500_000.0,
            position_value=149_500.0,
            total_asset=1_000_000.0,
            max_position_pct=15.0,
            reserve_floor_pct=10.0,
            market="cn",
        )
        assert qty == 0

    def test_us_fractional_shares(self):
        qty = estimate_buy_quantity(
            price=1000.0,
            cash=100_000.0,
            position_value=0.0,
            total_asset=1_000_000.0,
            max_position_pct=15.0,
            reserve_floor_pct=10.0,
            market="us",
        )
        assert qty > 0
        assert qty == int(qty)

    def test_cn_fee_min_commission_and_stamp_tax(self):
        buy_fee = compute_fee(side="buy", price=10.0, quantity=100, market="cn")
        assert buy_fee == 5.0  # 1000 元 * 万2.5 = 0.25 < 最低 5 元
        sell_fee = compute_fee(side="sell", price=10.0, quantity=10_000, market="cn")
        assert sell_fee == 75.0  # 佣金 100000*0.00025=25 + 印花税 100000*0.0005=50

    def test_us_fee_flat_rate(self):
        assert compute_fee(side="buy", price=100.0, quantity=10, market="us") == 1.0
