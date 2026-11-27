# -*- coding: utf-8 -*-
"""
Analysis tools — wraps StockTrendAnalyzer as an agent-callable tool.

Tools:
- analyze_trend: comprehensive technical trend analysis
"""

import logging
import math
from typing import Optional

from src.agent.tools.registry import ToolParameter, ToolDefinition, ToolPolicy

logger = logging.getLogger(__name__)

_ANALYSIS_READ_POLICY = ToolPolicy.declared(
    read_only=True,
    side_effects=["network_read", "db_read"],
    permissions=["market_data:read"],
    scope_dimensions=["stock"],
    supported_asset_types=("stock", "index"),
)


def _fetch_trend_data(stock_code: str):
    """Fetch historical OHLCV (DataFrame) for trend analysis. DB first, then DataFetcher fallback."""
    from src.services.history_loader import load_history_df

    df, _ = load_history_df(stock_code, days=60)
    return df


def _closed_pattern_df(df, stock_code: str, *, scan_days: int = 60):
    """Apply frozen/closed-session cutoff and continuity checks for extended daily pattern evidence."""
    if df is None or getattr(df, "empty", True):
        return df

    import pandas as pd
    from datetime import date
    from src.core.kline_patterns import parse_iso_date_value
    from src.services.alert_indicators import (
        _drop_partial_today,
        _effective_closed_date_for_stock,
        _find_column,
        check_kline_session_continuity,
    )
    from src.services.history_loader import get_frozen_target_date

    date_col = _find_column(df, "date")
    if date_col is None and not isinstance(df.index, pd.DatetimeIndex):
        return df

    work = df.copy()
    attrs = dict(getattr(df, "attrs", {}) or {})
    if date_col is not None and date_col != "date":
        work["date"] = work[date_col]
    elif date_col is None and isinstance(work.index, pd.DatetimeIndex):
        work["date"] = work.index
    work["date"] = pd.to_datetime(
        [parse_iso_date_value(v) for v in work["date"].tolist()],
        errors="coerce",
    )
    work.attrs.update(attrs)

    frozen = get_frozen_target_date()
    eff_closed = _effective_closed_date_for_stock(stock_code)
    upper_date: Optional[date]
    if frozen is not None and eff_closed is not None:
        upper_date = min(frozen, eff_closed)
    else:
        upper_date = frozen if frozen is not None else eff_closed

    filtered = _drop_partial_today(work, stock_code=stock_code)
    if filtered.empty:
        return filtered

    if upper_date is not None:
        parsed_dates = pd.to_datetime(filtered["date"], errors="coerce")
        if isinstance(parsed_dates.dtype, pd.DatetimeTZDtype):
            parsed_dates = parsed_dates.dt.tz_localize(None)
        mask = parsed_dates.isna() | (parsed_dates.dt.date <= upper_date)
        filtered = filtered.loc[mask].copy()
        filtered.attrs.update(attrs)
        if filtered.empty:
            return filtered

    filtered = filtered.sort_values(by="date", kind="stable", na_position="last")
    valid_date_mask = filtered["date"].notna()
    dup_valid = valid_date_mask & filtered.duplicated(subset=["date"], keep="last")
    filtered = filtered.loc[~dup_valid].reset_index(drop=True)
    filtered.attrs.update(attrs)
    if filtered.empty:
        return filtered

    tail_len = min(len(filtered), max(int(scan_days), 28))
    tail_win = filtered.iloc[-tail_len:]
    if tail_win["date"].isna().any():
        return filtered.iloc[0:0].copy()

    dropped_undated = int(filtered.attrs.get("dropped_undated_count") or 0)
    if dropped_undated > 0:
        return filtered.iloc[0:0].copy()

    tail_dates = [ts.date() for ts in pd.to_datetime(tail_win["date"]).tolist()]
    win_start = tail_dates[0]
    win_end = tail_dates[-1]
    drop_upper = upper_date if (upper_date is not None and upper_date >= win_end) else win_end
    for raw_dropped in filtered.attrs.get("dropped_invalid_dates") or []:
        parsed_iso = parse_iso_date_value(raw_dropped)
        if parsed_iso is None:
            continue
        dropped_day = date.fromisoformat(parsed_iso)
        if win_start <= dropped_day <= drop_upper:
            return filtered.iloc[0:0].copy()

    if check_kline_session_continuity(tail_dates, stock_code=stock_code, require_latest_match=False) is not None:
        return filtered.iloc[0:0].copy()

    return filtered


def _handle_analyze_trend(stock_code: str) -> dict:
    """Run technical trend analysis on a stock."""
    from src.stock_analyzer import StockTrendAnalyzer

    if not (stock_code and str(stock_code).strip()):
        return {"error": "stock_code is required"}

    df = _fetch_trend_data(stock_code)
    if df is None or df.empty:
        return {"error": f"No historical data available for trend analysis on {stock_code}"}

    if len(df) < 20:
        return {"error": f"Insufficient data for trend analysis on {stock_code} (need >= 20 days)"}

    closed_df = _closed_pattern_df(df, stock_code)
    analyzer = StockTrendAnalyzer()
    try:
        result = analyzer.analyze(df, stock_code, pattern_df=closed_df)
    except Exception:
        logger.warning("analyze_trend(%s): Trend analysis failed", stock_code, exc_info=True)
        return {"error": f"Trend analysis failed for {stock_code}"}

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
        "kline_patterns": result.kline_patterns,
        "pattern_summary": result.pattern_summary,
    }


analyze_trend_tool = ToolDefinition(
    name="analyze_trend",
    description="Run comprehensive technical trend analysis on a stock. "
                "Fetches historical data from database or data source. "
                "Returns MA alignment, bias rates, MACD status, RSI levels, "
                "volume analysis, support/resistance levels, and a buy/sell signal "
                "with a score (0-100).",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code to analyze, e.g., '600519'",
        ),
    ],
    handler=_handle_analyze_trend,
    category="analysis",
    policy=_ANALYSIS_READ_POLICY,
)


# ============================================================
# calculate_ma — flexible moving average calculator
# ============================================================

def _handle_calculate_ma(stock_code: str, periods: Optional[str] = None, days: int = 120) -> dict:
    """Calculate moving averages for arbitrary periods from historical K-line data."""
    from src.services.history_loader import load_history_df

    df, source = load_history_df(stock_code, days=days)

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
    policy=_ANALYSIS_READ_POLICY,
)


# ============================================================
# get_volume_analysis — volume-price relationship analysis
# ============================================================

def _handle_get_volume_analysis(stock_code: str, days: int = 30) -> dict:
    """Analyse volume-price patterns over recent trading days."""
    from src.services.history_loader import load_history_df
    import pandas as pd

    df, source = load_history_df(stock_code, days=max(days + 20, 60))

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
    policy=_ANALYSIS_READ_POLICY,
)


# ============================================================
# analyze_pattern — candlestick / chart pattern recognition
# ============================================================

def _handle_analyze_pattern(
    stock_code: str,
    days: int = 60,
    pattern_filter: Optional[str] = None,
) -> dict:
    """Detect common candlestick and chart patterns in recent price history."""
    from src.core.kline_patterns import detect_kline_patterns, summarize_detected_patterns
    from src.services.history_loader import load_history_df

    try:
        scan_days = int(days)
    except (TypeError, ValueError):
        return {"error": f"Invalid days parameter: {days}"}
    if scan_days <= 0:
        return {"error": f"days must be positive (got {scan_days})"}

    df, source = load_history_df(stock_code, days=max(scan_days, 120))

    if df is None or df.empty:
        return {"error": f"No historical data for {stock_code}"}

    period_days = min(len(df), scan_days)
    if period_days < 10:
        return {"error": f"Insufficient data for pattern analysis (got {period_days} days, need >= 10)"}

    closed_df = _closed_pattern_df(df, stock_code, scan_days=scan_days)
    try:
        if pattern_filter is None:
            legacy_patterns = detect_kline_patterns(
                df,
                days=scan_days,
                single_candle_lookback=3,
                include_chart_patterns=True,
                legacy_compat_mode=True,
                allow_missing_volume_breakout=True,
            )
            detail_patterns = detect_kline_patterns(
                closed_df,
                days=scan_days,
                single_candle_lookback=3,
                include_chart_patterns=True,
                legacy_compat_mode=False,
                allow_missing_volume_breakout=False,
            )
        else:
            legacy_patterns = detect_kline_patterns(
                closed_df,
                days=scan_days,
                single_candle_lookback=3,
                include_chart_patterns=True,
                pattern_filter=pattern_filter,
                legacy_compat_mode=False,
                allow_missing_volume_breakout=False,
            )
            detail_patterns = legacy_patterns
    except ValueError as exc:
        return {"error": str(exc)}

    latest_close = df["close"].iloc[-1]
    try:
        latest_close_val = float(latest_close)
        current_price = round(latest_close_val, 2) if math.isfinite(latest_close_val) else None
    except (TypeError, ValueError):
        current_price = None

    legacy_summary = summarize_detected_patterns(legacy_patterns)
    detail_summary = summarize_detected_patterns(detail_patterns)

    return {
        "code": stock_code,
        "source": source,
        "period_days": period_days,
        "current_price": current_price,
        "patterns_count": len(legacy_patterns),
        "patterns": [p.to_legacy_dict() for p in legacy_patterns],
        "pattern_details": [p.to_detail_dict() for p in detail_patterns],
        "extended_patterns_count": len(detail_patterns),
        "bullish_count": detail_summary["bullish_count"],
        "bearish_count": detail_summary["bearish_count"],
        "neutral_count": detail_summary["neutral_count"],
        "dominant_bias": detail_summary["dominant_bias"],
        "extended_summary": detail_summary["summary"],
        "summary": legacy_summary["summary"],
    }


analyze_pattern_tool = ToolDefinition(
    name="analyze_pattern",
    description="Detect candlestick and chart patterns in recent price history. "
                "When pattern_filter is omitted, `patterns`/`patterns_count`/`summary` preserve "
                "legacy candlestick/chart compatibility while `pattern_details` returns the full "
                "extended catalog with metadata: Red Three Soldiers (红三兵), Immortal Guide (仙人指路), "
                "Rising Lotus (出水芙蓉), Bullish Cannon (多方炮), Three Black Crows (三只乌鸦), "
                "Guillotine (断头铡刀), Piercing Line, Dark Cloud Cover, MA Pullback Support, "
                "Double Top, plus all legacy patterns.",
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
        ToolParameter(
            name="pattern_filter",
            type="string",
            description="Optional filter: 'bullish', 'bearish', or comma-separated pattern IDs "
                        "(e.g., 'red_three_soldiers,immortal_guide')",
            required=False,
            default=None,
        ),
    ],
    handler=_handle_analyze_pattern,
    category="analysis",
    policy=_ANALYSIS_READ_POLICY,
)


ALL_ANALYSIS_TOOLS = [
    analyze_trend_tool,
    calculate_ma_tool,
    get_volume_analysis_tool,
    analyze_pattern_tool,
]
