# -*- coding: utf-8 -*-
"""
Analysis tools — wraps StockTrendAnalyzer as an agent-callable tool.

Tools:
- analyze_trend: comprehensive technical trend analysis
"""

import logging
from typing import Optional

from src.agent.tools.registry import ToolParameter, ToolDefinition

logger = logging.getLogger(__name__)


def _handle_analyze_trend(stock_code: str) -> dict:
    """Run technical trend analysis on a stock."""
    from src.stock_analyzer import StockTrendAnalyzer
    from src.storage import get_db

    db = get_db()
    analyzer = StockTrendAnalyzer()

    # Fetch raw data from DB context
    context = db.get_analysis_context(stock_code)
    if context is None or "raw_data" not in context:
        return {"error": f"No historical data available for trend analysis on {stock_code}"}

    raw_data = context["raw_data"]
    if not isinstance(raw_data, list) or len(raw_data) < 5:
        return {"error": f"Insufficient data for trend analysis on {stock_code} (need >= 5 days)"}

    import pandas as pd
    df = pd.DataFrame(raw_data)

    result = analyzer.analyze(df, stock_code)

    return {
        "code": result.code,
        "trend_status": result.trend_status.value,
        "ma_alignment": result.ma_alignment,
        "trend_strength": result.trend_strength,
        "ma5": result.ma5,
        "ma10": result.ma10,
        "ma20": result.ma20,
        "ma60": result.ma60,
        "current_price": result.current_price,
        "bias_ma5": round(result.bias_ma5, 2),
        "bias_ma10": round(result.bias_ma10, 2),
        "bias_ma20": round(result.bias_ma20, 2),
        "volume_status": result.volume_status.value,
        "volume_ratio_5d": round(result.volume_ratio_5d, 2),
        "volume_trend": result.volume_trend,
        "support_ma5": result.support_ma5,
        "support_ma10": result.support_ma10,
        "resistance_levels": result.resistance_levels,
        "support_levels": result.support_levels,
        "macd_dif": round(result.macd_dif, 4),
        "macd_dea": round(result.macd_dea, 4),
        "macd_bar": round(result.macd_bar, 4),
        "macd_status": result.macd_status.value,
        "macd_signal": result.macd_signal,
        "rsi_6": round(result.rsi_6, 2),
        "rsi_12": round(result.rsi_12, 2),
        "rsi_24": round(result.rsi_24, 2),
        "rsi_status": result.rsi_status.value,
        "rsi_signal": result.rsi_signal,
        "buy_signal": result.buy_signal.value,
        "signal_score": result.signal_score,
        "signal_reasons": result.signal_reasons,
        "risk_factors": result.risk_factors,
    }


analyze_trend_tool = ToolDefinition(
    name="analyze_trend",
    description="Run comprehensive technical trend analysis on a stock. "
                "Returns MA alignment, bias rates, MACD status, RSI levels, "
                "volume analysis, support/resistance levels, and a buy/sell signal "
                "with a score (0-100). Requires historical data in the database.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code to analyze, e.g., '600519'",
        ),
    ],
    handler=_handle_analyze_trend,
    category="analysis",
)


# ============================================================
# calculate_ma — flexible moving average calculator
# ============================================================

def _handle_calculate_ma(stock_code: str, periods: Optional[str] = None, days: int = 120) -> dict:
    """Calculate moving averages for arbitrary periods from historical K-line data."""
    from data_provider import DataFetcherManager
    import pandas as pd

    manager = DataFetcherManager()
    df, source = manager.get_daily_data(stock_code, days=days)

    if df is None or df.empty:
        return {"error": f"No historical data for {stock_code}"}

    # Parse requested periods (default: 5,10,20,30,60,120,250)
    default_periods = [5, 10, 20, 30, 60, 120, 250]
    if periods:
        try:
            requested = [int(p.strip()) for p in periods.split(",") if p.strip().isdigit()]
            period_list = sorted(set(requested)) if requested else default_periods
        except Exception:
            period_list = default_periods
    else:
        period_list = default_periods

    close = df["close"]
    current_price = float(close.iloc[-1])
    result: dict = {
        "code": stock_code,
        "source": source,
        "current_price": round(current_price, 2),
        "data_points": len(df),
        "ma": {},
    }

    for period in period_list:
        if len(close) < period:
            result["ma"][f"ma{period}"] = None
            continue
        ma_val = float(close.rolling(window=period).mean().iloc[-1])
        bias = round((current_price - ma_val) / ma_val * 100, 2) if ma_val else None
        result["ma"][f"ma{period}"] = {
            "value": round(ma_val, 2),
            "bias_pct": bias,
            "price_above": current_price > ma_val,
        }

    # Summary: how many MAs is the price above?
    ma_values = [v for v in result["ma"].values() if v is not None]
    above_count = sum(1 for v in ma_values if v["price_above"])
    result["above_ma_count"] = above_count
    result["total_ma_count"] = len(ma_values)
    result["ma_alignment"] = (
        "多头排列" if above_count == len(ma_values)
        else "空头排列" if above_count == 0
        else f"混合({above_count}/{len(ma_values)}条均线上方)"
    )
    return result


calculate_ma_tool = ToolDefinition(
    name="calculate_ma",
    description="Calculate moving averages (MA5/10/20/30/60/120/250 or custom periods) "
                "for a stock. Returns each MA value, price bias %, and whether price "
                "is above each MA. Also returns overall MA alignment (多头/空头/混合).",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519'",
        ),
        ToolParameter(
            name="periods",
            type="string",
            description="Comma-separated MA periods to calculate (default: '5,10,20,30,60,120,250'). "
                        "E.g., '5,10,20,60'",
            required=False,
            default="5,10,20,30,60,120,250",
        ),
        ToolParameter(
            name="days",
            type="integer",
            description="Number of trading days to fetch history for (default: 120)",
            required=False,
            default=120,
        ),
    ],
    handler=_handle_calculate_ma,
    category="analysis",
)


# ============================================================
# get_volume_analysis — volume-price relationship analysis
# ============================================================

def _handle_get_volume_analysis(stock_code: str, days: int = 30) -> dict:
    """Analyse volume-price patterns over recent trading days."""
    from data_provider import DataFetcherManager
    import pandas as pd

    manager = DataFetcherManager()
    df, source = manager.get_daily_data(stock_code, days=max(days + 20, 60))

    if df is None or df.empty:
        return {"error": f"No historical data for {stock_code}"}

    df = df.tail(days).copy()
    if len(df) < 5:
        return {"error": f"Insufficient data for volume analysis (got {len(df)} days, need >= 5)"}

    close = df["close"]
    volume = df["volume"]

    # Average volumes
    avg_vol_5 = float(volume.tail(5).mean())
    avg_vol_10 = float(volume.tail(10).mean())
    avg_vol_20 = float(volume.tail(20).mean()) if len(df) >= 20 else avg_vol_10
    latest_vol = float(volume.iloc[-1])
    vol_ratio_5d = round(latest_vol / avg_vol_5, 2) if avg_vol_5 > 0 else None
    vol_ratio_20d = round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else None

    # Price direction for each day
    price_up = close.diff() > 0  # True = up day

    # Volume-price correlation (last N days)
    try:
        import numpy as np
        vp_corr = float(pd.Series(volume.values, dtype=float).corr(pd.Series(close.values, dtype=float)))
        vp_corr = round(vp_corr, 3)
    except Exception:
        vp_corr = None

    # Detect shrinking volume on up days (bearish divergence) vs expanding on up days (healthy)
    up_days = df[price_up]
    down_days = df[~price_up]
    avg_up_vol = float(up_days["volume"].mean()) if len(up_days) > 0 else 0
    avg_down_vol = float(down_days["volume"].mean()) if len(down_days) > 0 else 0

    # Volume trend: compare last 5 days vs prior 5 days
    if len(volume) >= 10:
        recent_5_avg = float(volume.tail(5).mean())
        prior_5_avg = float(volume.iloc[-10:-5].mean())
        vol_trend_pct = round((recent_5_avg - prior_5_avg) / prior_5_avg * 100, 1) if prior_5_avg > 0 else 0
        vol_trend = "放量" if vol_trend_pct > 20 else "缩量" if vol_trend_pct < -20 else "量能平稳"
    else:
        vol_trend_pct = 0
        vol_trend = "数据不足"

    # High-volume days (> 2x 20d avg)
    high_vol_days = int((volume > avg_vol_20 * 2).sum()) if avg_vol_20 > 0 else 0

    # Volume-price pattern interpretation
    pattern = "未知"
    if avg_up_vol > avg_down_vol * 1.3:
        pattern = "量价配合良好（上涨放量、下跌缩量）"
    elif avg_down_vol > avg_up_vol * 1.3:
        pattern = "量价背离（下跌放量、上涨缩量，偏空）"
    elif vol_ratio_5d and vol_ratio_5d > 1.5:
        pattern = "近期明显放量"
    elif vol_ratio_5d and vol_ratio_5d < 0.6:
        pattern = "近期明显缩量"
    else:
        pattern = "量价关系中性"

    return {
        "code": stock_code,
        "source": source,
        "period_days": len(df),
        "latest_volume": latest_vol,
        "avg_volume_5d": round(avg_vol_5, 0),
        "avg_volume_20d": round(avg_vol_20, 0),
        "volume_ratio_vs_5d": vol_ratio_5d,
        "volume_ratio_vs_20d": vol_ratio_20d,
        "avg_up_day_volume": round(avg_up_vol, 0),
        "avg_down_day_volume": round(avg_down_vol, 0),
        "volume_trend": vol_trend,
        "volume_trend_pct": vol_trend_pct,
        "high_volume_days": high_vol_days,
        "volume_price_corr": vp_corr,
        "pattern": pattern,
    }


get_volume_analysis_tool = ToolDefinition(
    name="get_volume_analysis",
    description="Analyse volume-price relationship for a stock. Returns volume ratios, "
                "average volume on up vs down days, volume trend (expanding/shrinking), "
                "and pattern interpretation (量价配合/背离). Useful for confirming trend "
                "strength and detecting distribution or accumulation phases.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519'",
        ),
        ToolParameter(
            name="days",
            type="integer",
            description="Number of recent trading days to analyse (default: 30)",
            required=False,
            default=30,
        ),
    ],
    handler=_handle_get_volume_analysis,
    category="analysis",
)


# ============================================================
# analyze_pattern — candlestick / chart pattern recognition
# ============================================================

def _handle_analyze_pattern(stock_code: str, days: int = 60) -> dict:
    """Detect common candlestick and chart patterns in recent price history."""
    from data_provider import DataFetcherManager
    import pandas as pd

    manager = DataFetcherManager()
    df, source = manager.get_daily_data(stock_code, days=max(days, 120))

    if df is None or df.empty:
        return {"error": f"No historical data for {stock_code}"}

    df = df.tail(days).copy().reset_index(drop=True)
    if len(df) < 10:
        return {"error": f"Insufficient data for pattern analysis (got {len(df)} days, need >= 10)"}

    o = df["open"].values
    h = df["high"].values
    l = df["low"].values   # noqa: E741
    c = df["close"].values
    v = df["volume"].values if "volume" in df.columns else None

    patterns_detected = []
    n = len(c)

    # ---- Helpers ----
    def body(i):
        return abs(c[i] - o[i])

    def upper_shadow(i):
        return h[i] - max(c[i], o[i])

    def lower_shadow(i):
        return min(c[i], o[i]) - l[i]

    def is_bullish(i):
        return c[i] > o[i]

    def is_bearish(i):
        return c[i] < o[i]

    avg_body = sum(body(i) for i in range(n)) / n if n > 0 else 1

    # --- Single-candle patterns (last 3 days) ---
    for i in range(max(0, n - 3), n):
        bd = body(i)
        us = upper_shadow(i)
        ls = lower_shadow(i)

        # Doji
        if bd < avg_body * 0.1 and (us + ls) > bd * 3:
            patterns_detected.append({
                "pattern": "十字星 (Doji)", "type": "reversal_signal",
                "day_offset": -(n - 1 - i),
                "strength": "弱", "desc": "多空平衡，可能变盘信号"
            })

        # Hammer / Hanging Man
        if ls > body(i) * 2 and us < body(i) * 0.5:
            label = "锤子线 (Hammer)" if i == 0 or c[i] >= c[i - 1] else "上吊线 (Hanging Man)"
            patterns_detected.append({
                "pattern": label, "type": "reversal_signal",
                "day_offset": -(n - 1 - i),
                "strength": "中", "desc": "下影线长，潜在支撑/反转"
            })

        # Shooting Star / Inverted Hammer
        if us > body(i) * 2 and ls < body(i) * 0.5:
            label = "流星线 (Shooting Star)" if is_bearish(i) else "倒锤子"
            patterns_detected.append({
                "pattern": label, "type": "bearish_signal",
                "day_offset": -(n - 1 - i),
                "strength": "中", "desc": "上影线长，潜在压力/反转"
            })

        # Big bullish / bearish candle
        if bd > avg_body * 2.5:
            label = "大阳线" if is_bullish(i) else "大阴线"
            t = "bullish" if is_bullish(i) else "bearish"
            patterns_detected.append({
                "pattern": label, "type": t,
                "day_offset": -(n - 1 - i),
                "strength": "强", "desc": "实体大，方向明确"
            })

    # --- Multi-candle patterns (use last 10 days) ---
    if n >= 3:
        i = n - 1
        # Morning Star (早晨之星) — bottom reversal
        if (is_bearish(i - 2) and body(i - 2) > avg_body * 1.5
                and body(i - 1) < avg_body * 0.4
                and is_bullish(i) and body(i) > avg_body * 1.5
                and c[i] > (o[i - 2] + c[i - 2]) / 2):
            patterns_detected.append({
                "pattern": "早晨之星 (Morning Star)", "type": "bullish_reversal",
                "day_offset": -2, "strength": "强", "desc": "三根K线底部反转形态"
            })

        # Evening Star (黄昏之星) — top reversal
        if (is_bullish(i - 2) and body(i - 2) > avg_body * 1.5
                and body(i - 1) < avg_body * 0.4
                and is_bearish(i) and body(i) > avg_body * 1.5
                and c[i] < (o[i - 2] + c[i - 2]) / 2):
            patterns_detected.append({
                "pattern": "黄昏之星 (Evening Star)", "type": "bearish_reversal",
                "day_offset": -2, "strength": "强", "desc": "三根K线顶部反转形态"
            })

        # Engulfing (吞没形态)
        if (is_bullish(i) and is_bearish(i - 1)
                and o[i] < c[i - 1] and c[i] > o[i - 1]):
            patterns_detected.append({
                "pattern": "看涨吞没 (Bullish Engulfing)", "type": "bullish_reversal",
                "day_offset": -1, "strength": "强", "desc": "阳线完全覆盖前一阴线"
            })
        elif (is_bearish(i) and is_bullish(i - 1)
              and o[i] > c[i - 1] and c[i] < o[i - 1]):
            patterns_detected.append({
                "pattern": "看跌吞没 (Bearish Engulfing)", "type": "bearish_reversal",
                "day_offset": -1, "strength": "强", "desc": "阴线完全覆盖前一阳线"
            })

    # --- Chart patterns over the window ---
    # Double bottom detection (简化版: 两个相近低点 + 中间高点)
    recent_lows_idx = sorted(range(n), key=lambda i: l[i])[:5]
    if len(recent_lows_idx) >= 2:
        lo1, lo2 = sorted(recent_lows_idx[:2])
        if lo2 - lo1 >= 5 and abs(l[lo1] - l[lo2]) / max(l[lo1], l[lo2]) < 0.03:
            mid_high = max(h[lo1:lo2 + 1])
            if mid_high > l[lo1] * 1.03:
                patterns_detected.append({
                    "pattern": "双底 (Double Bottom)", "type": "bullish_reversal",
                    "day_offset": -(n - 1 - lo2),
                    "strength": "强", "desc": "两个相近低点，W型底部形态"
                })

    # Upward breakout: closes above 20d high (excluding last day itself)
    if n >= 21:
        high_20d = max(h[n - 21:n - 1])
        if c[-1] > high_20d and (v is None or v[-1] > sum(v[n - 6:n - 1]) / 5 * 1.5):
            patterns_detected.append({
                "pattern": "放量突破20日高点", "type": "bullish_breakout",
                "day_offset": 0, "strength": "强", "desc": "收盘突破近20日最高，量能配合"
            })

    # Price in consolidation box (box oscillation)
    if n >= 10:
        recent_high = max(h[n - 10:])
        recent_low = min(l[n - 10:])
        box_range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 0
        if box_range_pct < 8:
            patterns_detected.append({
                "pattern": "箱体震荡", "type": "consolidation",
                "day_offset": 0, "strength": "中",
                "desc": f"近10日波幅 {box_range_pct:.1f}%，价格在区间内震荡"
            })

    # Deduplicate by pattern name, keep most recent
    seen = set()
    unique_patterns = []
    for p in reversed(patterns_detected):
        if p["pattern"] not in seen:
            seen.add(p["pattern"])
            unique_patterns.append(p)
    unique_patterns = list(reversed(unique_patterns))

    return {
        "code": stock_code,
        "source": source,
        "period_days": len(df),
        "current_price": round(float(c[-1]), 2),
        "patterns_count": len(unique_patterns),
        "patterns": unique_patterns,
        "summary": (
            "未发现明显形态" if not unique_patterns
            else "、".join(p["pattern"] for p in unique_patterns)
        ),
    }


analyze_pattern_tool = ToolDefinition(
    name="analyze_pattern",
    description="Detect candlestick and chart patterns in recent price history. "
                "Identifies: Doji, Hammer, Shooting Star, Morning/Evening Star, Engulfing, "
                "Double Bottom, upward breakout, box oscillation, and more. "
                "Returns pattern list with type (bullish/bearish/reversal) and strength.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519'",
        ),
        ToolParameter(
            name="days",
            type="integer",
            description="Number of recent trading days to scan (default: 60)",
            required=False,
            default=60,
        ),
    ],
    handler=_handle_analyze_pattern,
    category="analysis",
)


ALL_ANALYSIS_TOOLS = [
    analyze_trend_tool,
    calculate_ma_tool,
    get_volume_analysis_tool,
    analyze_pattern_tool,
]
