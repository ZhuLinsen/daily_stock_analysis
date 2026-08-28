# -*- coding: utf-8 -*-
"""Virtual trader mean-reversion strategy engine.

纯函数策略引擎：输入标准化日线 DataFrame（date/open/high/low/close/volume），
输出买卖信号与预测目标。不依赖 LLM、不发网络请求，方便离线单测。

核心逻辑（均值回归 + 趋势过滤）：
- 买入：收盘价跌破布林带下轨且 RSI 超卖，同时 MA20 仍向上（避免接飞刀）；
  预测目标为回归中轨/MA20，horizon 默认 10 个交易日。
- 卖出：持仓期间触及布林上轨或 20 日乖离超阈值（回归兑现）、
  RSI 超买 + MACD 死叉（动量衰竭）、或触发止损。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from src.stock_analyzer import StockTrendAnalyzer

# 布林带参数
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0

# 信号阈值（可被配置覆盖）
RSI_OVERSOLD_DEFAULT = 30.0
RSI_OVERBOUGHT_DEFAULT = 70.0
BIAS_TAKE_PROFIT_PCT_DEFAULT = 8.0   # 20 日乖离超过该值视为回归兑现
STOP_LOSS_PCT_DEFAULT = 8.0          # 收盘价跌破成本该比例触发止损
TREND_SLOPE_MIN_BARS = 5             # 趋势过滤（MA60 斜率）回看 bars
DEFAULT_HORIZON_DAYS = 10


@dataclass
class StrategySignal:
    """一次策略评估的输出。action 为 hold 时其余字段为空。"""

    action: str  # buy / sell / hold
    reason: str = ""
    direction: str = "up"  # 预测方向：buy->up（回归上涨），sell->down
    target_price: Optional[float] = None
    horizon_days: int = DEFAULT_HORIZON_DAYS
    score: float = 0.0  # 信号强度 0-100，供仓位参考
    snapshot: Dict[str, Any] = field(default_factory=dict)


def compute_bollinger(
    df: pd.DataFrame, period: int = BOLLINGER_PERIOD, std_num: float = BOLLINGER_STD
) -> pd.DataFrame:
    """在 df 上追加 boll_mid/boll_upper/boll_lower/bias_mid 列。"""
    out = df.copy()
    mid = out["close"].rolling(window=period, min_periods=period).mean()
    std = out["close"].rolling(window=period, min_periods=period).std(ddof=0)
    out["boll_mid"] = mid
    out["boll_upper"] = mid + std_num * std
    out["boll_lower"] = mid - std_num * std
    out["bias_mid"] = (out["close"] - mid) / mid * 100.0
    return out


def _tail_value(series: pd.Series, offset: int = 1) -> Optional[float]:
    """取倒数第 offset 个有效值；不足返回 None。"""
    cleaned = series.dropna()
    if len(cleaned) < offset:
        return None
    return float(cleaned.iloc[-offset])


def upper_band_width_guard(mid: Optional[float], band_edge: Optional[float]) -> bool:
    """布林带带宽低于中轨 0.5% 时视为无效（零波动保护）。"""
    if mid is None or band_edge is None or mid <= 0:
        return True
    return abs(band_edge - mid) / mid < 0.005


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """统一追加 MA/RSI/MACD/布林带指标列。"""
    analyzer = StockTrendAnalyzer()
    out = analyzer._calculate_mas(df)
    out = analyzer._calculate_macd(out)
    out = analyzer._calculate_rsi(out)
    out = compute_bollinger(out)
    return out


def evaluate_buy(
    df: pd.DataFrame,
    *,
    rsi_oversold: float = RSI_OVERSOLD_DEFAULT,
) -> StrategySignal:
    """评估是否触发均值回归买入（用于备用金建仓/加仓）。"""
    ind = prepare_indicators(df)
    min_bars = max(BOLLINGER_PERIOD, 60) + TREND_SLOPE_MIN_BARS + 1
    if len(ind) < min_bars:
        return StrategySignal(action="hold", reason="历史数据不足")

    close = float(ind["close"].iloc[-1])
    lower = _tail_value(ind["boll_lower"])
    mid = _tail_value(ind["boll_mid"])
    rsi_short = _tail_value(ind.get("RSI_6"))
    ma60_now = _tail_value(ind.get("MA60"))
    ma60_prev = _tail_value(ind.get("MA60"), offset=1 + TREND_SLOPE_MIN_BARS)

    snapshot = {
        "close": round(close, 4),
        "boll_lower": round(lower, 4) if lower is not None else None,
        "boll_mid": round(mid, 4) if mid is not None else None,
        "RSI_6": round(rsi_short, 2) if rsi_short is not None else None,
        "MA60": round(ma60_now, 4) if ma60_now is not None else None,
    }

    if lower is None or mid is None or rsi_short is None or ma60_now is None or ma60_prev is None:
        return StrategySignal(action="hold", reason="指标未就绪", snapshot=snapshot)

    # 带宽过窄（近似零波动）时上下轨与价格重合，信号无意义
    if (upper_band_width_guard(mid, lower)):
        return StrategySignal(action="hold", reason="波动率不足", snapshot=snapshot)

    below_lower = close <= lower
    oversold = rsi_short <= rsi_oversold
    # 趋势过滤用 MA60 斜率：短促下跌不会立刻拉平长期均线，避免过滤条件自我失效
    trend_rising = ma60_now >= ma60_prev

    if not (below_lower and oversold and trend_rising):
        return StrategySignal(action="hold", reason="未满足买入条件", snapshot=snapshot)

    # 信号强度：跌破下轨深度 + 超卖程度的组合
    band_width = max(mid - lower, 1e-9)
    depth = (lower - close) / band_width * 100.0
    rsi_room = (rsi_oversold - rsi_short) / max(rsi_oversold, 1e-9) * 100.0
    score = max(0.0, min(100.0, depth * 0.6 + rsi_room * 0.4))
    snapshot["band_depth_pct"] = round(depth, 2)
    return StrategySignal(
        action="buy",
        reason=f"跌破布林下轨且RSI超卖({rsi_short:.1f})，长期趋势向上，预期回归中轨",
        direction="up",
        target_price=round(mid, 4),
        horizon_days=DEFAULT_HORIZON_DAYS,
        score=round(score, 1),
        snapshot=snapshot,
    )


def evaluate_sell(
    df: pd.DataFrame,
    *,
    avg_cost: float,
    rsi_overbought: float = RSI_OVERBOUGHT_DEFAULT,
    bias_take_profit_pct: float = BIAS_TAKE_PROFIT_PCT_DEFAULT,
    stop_loss_pct: float = STOP_LOSS_PCT_DEFAULT,
) -> StrategySignal:
    """评估持仓是否触发卖出：回归兑现 / 动量衰竭 / 止损。"""
    ind = prepare_indicators(df)
    if len(ind) < BOLLINGER_PERIOD + 1 or avg_cost <= 0:
        return StrategySignal(action="hold", reason="历史数据不足")

    close = float(ind["close"].iloc[-1])
    upper = _tail_value(ind["boll_upper"])
    mid = _tail_value(ind["boll_mid"])
    bias = _tail_value(ind["bias_mid"])
    rsi_short = _tail_value(ind.get("RSI_6"))
    macd = _tail_value(ind.get("MACD_DIF"))
    macd_signal = _tail_value(ind.get("MACD_DEA"))
    macd_prev = _tail_value(ind.get("MACD_DIF"), offset=2)
    macd_signal_prev = _tail_value(ind.get("MACD_DEA"), offset=2)

    snapshot = {
        "close": round(close, 4),
        "avg_cost": round(avg_cost, 4),
        "boll_upper": round(upper, 4) if upper is not None else None,
        "boll_mid": round(mid, 4) if mid is not None else None,
        "bias_mid": round(bias, 2) if bias is not None else None,
        "RSI_6": round(rsi_short, 2) if rsi_short is not None else None,
    }

    if upper is None or mid is None or bias is None or rsi_short is None:
        return StrategySignal(action="hold", reason="指标未就绪", snapshot=snapshot)

    # 带宽过窄（近似零波动）时上下轨与价格重合，信号无意义
    if (upper_band_width_guard(mid, upper)):
        return StrategySignal(action="hold", reason="波动率不足", snapshot=snapshot)

    # 1) 止损优先级最高
    loss_pct = (close - avg_cost) / avg_cost * 100.0
    if loss_pct <= -stop_loss_pct:
        snapshot["loss_pct"] = round(loss_pct, 2)
        return StrategySignal(
            action="sell",
            reason=f"止损：收盘亏损 {loss_pct:.1f}% 超过 -{stop_loss_pct:.0f}%",
            direction="down",
            target_price=round(avg_cost * (1 - stop_loss_pct / 100.0 * 0.5), 4),
            horizon_days=DEFAULT_HORIZON_DAYS,
            score=90.0,
            snapshot=snapshot,
        )

    # 2) 回归兑现：触及上轨或 20 日乖离超阈值
    if close >= upper or bias >= bias_take_profit_pct:
        trigger = "触及布林上轨" if close >= upper else f"20日乖离 {bias:.1f}%"
        snapshot["profit_pct"] = round(-loss_pct, 2)
        return StrategySignal(
            action="sell",
            reason=f"{trigger}，均值回归兑现（浮盈 {-loss_pct:.1f}%）",
            direction="down",
            target_price=round(mid, 4),
            horizon_days=DEFAULT_HORIZON_DAYS,
            score=75.0,
            snapshot=snapshot,
        )

    # 3) 动量衰竭：RSI 超买 + MACD 死叉
    macd_death_cross = (
        macd is not None
        and macd_signal is not None
        and macd_prev is not None
        and macd_signal_prev is not None
        and macd_prev >= macd_signal_prev
        and macd < macd_signal
    )
    if rsi_short >= rsi_overbought and macd_death_cross:
        return StrategySignal(
            action="sell",
            reason=f"RSI超买({rsi_short:.1f})且MACD死叉，动量衰竭",
            direction="down",
            target_price=round(mid, 4),
            horizon_days=DEFAULT_HORIZON_DAYS,
            score=60.0,
            snapshot=snapshot,
        )

    return StrategySignal(action="hold", reason="持仓条件未触发", snapshot=snapshot)


def estimate_buy_quantity(
    *,
    price: float,
    cash: float,
    position_value: float,
    total_asset: float,
    max_position_pct: float,
    reserve_floor_pct: float,
    market: str = "cn",
) -> float:
    """按单票上限与备用金下限估算可买数量（股）。A股/港股按 100 股整手取整。"""
    if price <= 0 or cash <= 0 or total_asset <= 0:
        return 0.0
    cap_value = total_asset * max_position_pct / 100.0
    allowed_budget = min(cash * (1.0 - reserve_floor_pct / 100.0), cap_value - position_value)
    if allowed_budget <= 0:
        return 0.0
    raw_qty = allowed_budget / price
    if market in ("cn", "hk"):
        lots = int(raw_qty // 100)
        # 整手取整可能向上超出预算（如预算 14 万、股价 1500 一手 15 万），逐手回退
        while lots > 0 and lots * 100 * price > min(allowed_budget, cash):
            lots -= 1
        qty = lots * 100.0
    else:
        qty = float(int(raw_qty))
    if qty * price > cash:
        return 0.0
    return qty


def compute_fee(*, side: str, price: float, quantity: float, market: str) -> float:
    """模拟交易成本：A股佣金万2.5(最低5元)+卖出印花税0.05%；港/美简化 0.1%。"""
    if quantity <= 0 or price <= 0:
        return 0.0
    amount = price * quantity
    if market == "cn":
        commission = max(amount * 0.00025, 5.0)
        stamp_tax = amount * 0.0005 if side == "sell" else 0.0
        return round(commission + stamp_tax, 2)
    return round(amount * 0.001, 2)
