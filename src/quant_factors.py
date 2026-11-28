# -*- coding: utf-8 -*-
"""
===================================
Quantitative Multi-Factor Analysis Engine
===================================

Pure-numpy/pandas institutional factor computation over daily OHLCV history:
1. Volatility & Channel: Bollinger Bands (20, 2), Donchian Channels (20d/10d),
   ATR(14), 20-day annualized Historical Volatility (HV20), VCP contraction ratio
2. Oscillators & Trend Strength: KDJ(9, 3, 3), Wilder ADX(14) / +DI(14) / -DI(14)
3. Volume-Price & Money Flow: OBV & OBV divergence, 20-day VWAP & bias, MFI(14)
4. Cross-Horizon Momentum & Risk: 5/20/60d ROC, 60d max drawdown, distance from
   60d high, 60d annualized Sharpe (zero risk-free baseline)

All helpers handle short/flat/zero-volume series deterministically without
producing NaN/Inf values or modifying legacy TrendAnalysisResult signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def _finite_float(value: Any, decimals: int = 4) -> Optional[float]:
    """Convert value to a rounded finite float, or None if unavailable/non-finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return round(num, decimals)


@dataclass
class QuantFactorResult:
    """Structured multi-factor quantitative snapshot for a single equity or index."""

    code: str
    bars_analyzed: int = 0
    current_price: float = 0.0
    sufficient_data: bool = False

    # Bollinger Bands (20, 2)
    boll_upper: float = 0.0
    boll_mid: float = 0.0
    boll_lower: float = 0.0
    boll_pct_b: float = 0.5
    boll_bandwidth_pct: float = 0.0
    prev_boll_bandwidth_pct: Optional[float] = None
    boll_squeeze: bool = False
    boll_squeeze_prior: bool = False
    boll_squeeze_breakout: bool = False

    # Donchian Channels (prior N bars to eliminate lookahead bias)
    donchian_high_20: Optional[float] = None
    donchian_low_20: Optional[float] = None
    donchian_high_10: float = 0.0
    donchian_low_10: float = 0.0
    donchian_signal: str = "inside"

    # ATR(14), Risk Brackets & Volatility Compression
    atr_14: float = 0.0
    atr_pct: float = 0.0
    atr_stop_loss_long: float = 0.0
    atr_trailing_stop_long: Optional[float] = None
    atr_trailing_stop_breached: bool = False
    atr_take_profit_2r: float = 0.0
    hv_20_annualized_pct: Optional[float] = None
    vcp_contraction_ratio: Optional[float] = None

    # KDJ (9, 3, 3)
    kdj_k: float = 50.0
    kdj_d: float = 50.0
    kdj_j: float = 50.0
    kdj_status: str = "neutral"

    # ADX (14) / Directional Indicators
    adx_14: Optional[float] = None
    plus_di_14: Optional[float] = None
    minus_di_14: Optional[float] = None
    adx_regime: str = "unknown"
    adx_direction: str = "neutral"

    # Volume-Price & Money Flow
    obv: float = 0.0
    obv_ma20: float = 0.0
    obv_trend: str = "flat"
    obv_divergence: str = "none"
    vwap_20: Optional[float] = None
    vwap_bias_pct: Optional[float] = None
    mfi_14: Optional[float] = None
    mfi_status: str = "neutral"

    # Momentum & Drawdown Risk
    roc_5_pct: Optional[float] = None
    roc_20_pct: Optional[float] = None
    roc_60_pct: Optional[float] = None
    max_drawdown_60_pct: Optional[float] = None
    dist_from_high_60_pct: Optional[float] = None
    sharpe_60: Optional[float] = None

    # Composite View
    quant_regime: str = "insufficient_data"
    quant_composite_score: int = 50
    factor_signals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize quantitative factors into JSON-safe rounded primitives."""
        return {
            "code": self.code,
            "bars_analyzed": int(self.bars_analyzed),
            "current_price": _finite_float(self.current_price, 4) or 0.0,
            "sufficient_data": bool(self.sufficient_data),
            "boll_upper": _finite_float(self.boll_upper, 4) or 0.0,
            "boll_mid": _finite_float(self.boll_mid, 4) or 0.0,
            "boll_lower": _finite_float(self.boll_lower, 4) or 0.0,
            "boll_pct_b": _finite_float(self.boll_pct_b, 4) if _finite_float(self.boll_pct_b, 4) is not None else 0.5,
            "boll_bandwidth_pct": _finite_float(self.boll_bandwidth_pct, 2) or 0.0,
            "prev_boll_bandwidth_pct": _finite_float(self.prev_boll_bandwidth_pct, 2),
            "boll_squeeze": bool(self.boll_squeeze),
            "boll_squeeze_prior": bool(self.boll_squeeze_prior),
            "boll_squeeze_breakout": bool(self.boll_squeeze_breakout),
            "donchian_high_20": _finite_float(self.donchian_high_20, 4),
            "donchian_low_20": _finite_float(self.donchian_low_20, 4),
            "donchian_high_10": _finite_float(self.donchian_high_10, 4) or 0.0,
            "donchian_low_10": _finite_float(self.donchian_low_10, 4) or 0.0,
            "donchian_signal": self.donchian_signal,
            "atr_14": _finite_float(self.atr_14, 4) or 0.0,
            "atr_pct": _finite_float(self.atr_pct, 2) or 0.0,
            "atr_stop_loss_long": _finite_float(self.atr_stop_loss_long, 4) or 0.0,
            "atr_trailing_stop_long": _finite_float(self.atr_trailing_stop_long, 4),
            "atr_trailing_stop_breached": bool(self.atr_trailing_stop_breached),
            "atr_take_profit_2r": _finite_float(self.atr_take_profit_2r, 4) or 0.0,
            "hv_20_annualized_pct": _finite_float(self.hv_20_annualized_pct, 2),
            "vcp_contraction_ratio": _finite_float(self.vcp_contraction_ratio, 4),
            "kdj_k": _finite_float(self.kdj_k, 2) if _finite_float(self.kdj_k, 2) is not None else 50.0,
            "kdj_d": _finite_float(self.kdj_d, 2) if _finite_float(self.kdj_d, 2) is not None else 50.0,
            "kdj_j": _finite_float(self.kdj_j, 2) if _finite_float(self.kdj_j, 2) is not None else 50.0,
            "kdj_status": self.kdj_status,
            "adx_14": _finite_float(self.adx_14, 2),
            "plus_di_14": _finite_float(self.plus_di_14, 2),
            "minus_di_14": _finite_float(self.minus_di_14, 2),
            "adx_regime": self.adx_regime,
            "adx_direction": self.adx_direction,
            "obv": _finite_float(self.obv, 2) or 0.0,
            "obv_ma20": _finite_float(self.obv_ma20, 2) or 0.0,
            "obv_trend": self.obv_trend,
            "obv_divergence": self.obv_divergence,
            "vwap_20": _finite_float(self.vwap_20, 4),
            "vwap_bias_pct": _finite_float(self.vwap_bias_pct, 2),
            "mfi_14": _finite_float(self.mfi_14, 2),
            "mfi_status": self.mfi_status,
            "roc_5_pct": _finite_float(self.roc_5_pct, 2),
            "roc_20_pct": _finite_float(self.roc_20_pct, 2),
            "roc_60_pct": _finite_float(self.roc_60_pct, 2),
            "max_drawdown_60_pct": _finite_float(self.max_drawdown_60_pct, 2),
            "dist_from_high_60_pct": _finite_float(self.dist_from_high_60_pct, 2),
            "sharpe_60": _finite_float(self.sharpe_60, 2),
            "quant_regime": self.quant_regime,
            "quant_composite_score": int(self.quant_composite_score),
            "factor_signals": list(self.factor_signals),
        }

    def format_summary(self) -> str:
        """Render a concise text summary suitable for terminal/prompt context."""
        return format_quant_factors_summary(self.to_dict())


def format_quant_factors_summary(qf: Dict[str, Any]) -> str:
    """Format a serialized quant-factor dict into human-readable summary lines."""
    if not isinstance(qf, dict) or not qf.get("sufficient_data"):
        return ""

    adx_str = (
        f"ADX(14)={qf['adx_14']:.1f} ({qf.get('adx_regime', 'unknown')}, {qf.get('adx_direction', 'neutral')})"
        if qf.get("adx_14") is not None
        else "ADX(14)=N/A"
    )
    vwap_str = (
        f"VWAP20={qf['vwap_20']:.2f} ({qf.get('vwap_bias_pct', 0.0):+.2f}%)"
        if qf.get("vwap_20") is not None and qf.get("vwap_bias_pct") is not None
        else "VWAP20=N/A"
    )
    mfi_str = f"MFI(14)={qf['mfi_14']:.1f}" if qf.get("mfi_14") is not None else "MFI(14)=N/A"
    roc20_str = f"{qf['roc_20_pct']:+.2f}%" if qf.get("roc_20_pct") is not None else "N/A"
    mdd_str = f"{qf['max_drawdown_60_pct']:.2f}%" if qf.get("max_drawdown_60_pct") is not None else "N/A"
    sharpe_str = f"{qf['sharpe_60']:.2f}" if qf.get("sharpe_60") is not None else "N/A"
    vcp_str = f"{qf['vcp_contraction_ratio']:.2f}x" if qf.get("vcp_contraction_ratio") is not None else "N/A"
    trail_stop = qf.get("atr_trailing_stop_long")
    trail_str = (
        f", 2xATR追踪止损={trail_stop:.2f}"
        + (" [BREACHED]" if qf.get("atr_trailing_stop_breached") else "")
        if trail_stop is not None
        else ""
    )
    squeeze_flag = (
        " [SqueezeBreakout]"
        if qf.get("boll_squeeze_breakout")
        else (" [Squeeze]" if qf.get("boll_squeeze") else (" [PriorSqueeze]" if qf.get("boll_squeeze_prior") else ""))
    )

    lines = [
        f"   BOLL(20,2): {qf.get('boll_lower', 0.0):.2f} / {qf.get('boll_mid', 0.0):.2f} / "
        f"{qf.get('boll_upper', 0.0):.2f} (%B={qf.get('boll_pct_b', 0.5):.2f}, "
        f"BW={qf.get('boll_bandwidth_pct', 0.0):.2f}%{squeeze_flag})",
        f"   ATR(14): {qf.get('atr_14', 0.0):.2f} ({qf.get('atr_pct', 0.0):.2f}%), "
        f"2xATR止损={qf.get('atr_stop_loss_long', 0.0):.2f}{trail_str}, VCP={vcp_str}, "
        f"唐奇安={qf.get('donchian_signal', 'inside')}",
        f"   KDJ(9,3,3): K={qf.get('kdj_k', 50.0):.1f} D={qf.get('kdj_d', 50.0):.1f} "
        f"J={qf.get('kdj_j', 50.0):.1f} ({qf.get('kdj_status', 'neutral')}) | {adx_str}",
        f"   量价/动量: {vwap_str}, OBV={qf.get('obv_trend', 'flat')}, {mfi_str}, "
        f"ROC20={roc20_str}, 60日最大回撤={mdd_str}, Sharpe60={sharpe_str}",
        f"   量化状态: {qf.get('quant_regime', 'neutral')} | 因子综合分: {qf.get('quant_composite_score', 50)}/100",
    ]
    return "\n".join(lines)


def _prepare_ohlcv_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Validate, coerce, sort, and sanitize OHLCV rows for deterministic computation."""
    if df is None or df.empty or "close" not in df.columns:
        return pd.DataFrame()

    work = df.copy()
    if "date" in work.columns:
        work = work.sort_values("date").reset_index(drop=True)

    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work[np.isfinite(work["close"]) & (work["close"] > 0)].copy()
    if work.empty:
        return pd.DataFrame()

    # Replace non-finite or non-positive placeholders (e.g. missing low=0.0) with valid close
    for col in ("open", "high", "low"):
        if col in work.columns:
            vals = pd.to_numeric(work[col], errors="coerce")
            work[col] = np.where(np.isfinite(vals) & (vals > 0), vals, work["close"])
        else:
            work[col] = work["close"]

    # Ensure high >= max(open, close) and low <= min(open, close)
    work["high"] = np.maximum(work["high"], np.maximum(work["open"], work["close"]))
    work["low"] = np.minimum(work["low"], np.minimum(work["open"], work["close"]))

    if "volume" in work.columns:
        vol = pd.to_numeric(work["volume"], errors="coerce").fillna(0.0)
        work["volume"] = np.where(np.isfinite(vol) & (vol > 0), vol, 0.0)
    else:
        work["volume"] = 0.0

    return work.reset_index(drop=True)


def _wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Compute classic Wilder smoothing (sum of first `period` elements, then recursive)."""
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < period or period <= 0:
        return out
    first_sum = float(np.sum(values[:period]))
    out[period - 1] = first_sum
    for idx in range(period, len(values)):
        out[idx] = out[idx - 1] - (out[idx - 1] / period) + values[idx]
    return out


def compute_quant_factors(df: pd.DataFrame, code: str) -> QuantFactorResult:
    """
    Compute Bollinger, Donchian, ATR/VCP, KDJ, ADX, OBV/VWAP/MFI, and Momentum/Risk factors.

    Returns an empty `QuantFactorResult(sufficient_data=False)` when fewer than 20 valid
    OHLCV bars are available, never raising on sparse/flat/zero-volume data.
    """
    work = _prepare_ohlcv_frame(df)
    n = len(work)
    if n < 20:
        return QuantFactorResult(
            code=code,
            bars_analyzed=n,
            current_price=float(work["close"].iloc[-1]) if n > 0 else 0.0,
            sufficient_data=False,
        )

    close = work["close"].to_numpy(dtype=float)
    high = work["high"].to_numpy(dtype=float)
    low = work["low"].to_numpy(dtype=float)
    volume = work["volume"].to_numpy(dtype=float)
    curr_close = float(close[-1])

    result = QuantFactorResult(
        code=code,
        bars_analyzed=n,
        current_price=curr_close,
        sufficient_data=True,
    )
    signals: List[str] = []

    # 1. Bollinger Bands (20, 2)
    close_series = pd.Series(close)
    boll_mid_series = close_series.rolling(20, min_periods=20).mean()
    boll_std_series = close_series.rolling(20, min_periods=20).std(ddof=0).fillna(0.0)
    boll_upper_series = boll_mid_series + 2.0 * boll_std_series
    boll_lower_series = boll_mid_series - 2.0 * boll_std_series

    boll_mid = float(boll_mid_series.iloc[-1])
    boll_upper = float(boll_upper_series.iloc[-1])
    boll_lower = float(boll_lower_series.iloc[-1])
    band_span = boll_upper - boll_lower
    boll_bw_series = ((boll_upper_series - boll_lower_series) / boll_mid_series.replace(0.0, np.nan)) * 100.0
    curr_bw = float(boll_bw_series.iloc[-1]) if np.isfinite(boll_bw_series.iloc[-1]) else 0.0
    boll_pct_b = (curr_close - boll_lower) / band_span if band_span > 1e-12 else 0.5

    valid_bws = boll_bw_series.dropna().tail(60)
    if len(valid_bws) >= 5:
        q25_bw = float(np.percentile(valid_bws.to_numpy(dtype=float), 25))
        boll_squeeze = curr_bw <= max(6.0, q25_bw * 1.1) and curr_bw < 12.0
    else:
        boll_squeeze = curr_bw < 6.0

    # Prior-bar squeeze state (excludes current bar so breakout expansion doesn't mask setup)
    prev_boll_bw: Optional[float] = None
    boll_squeeze_prior = False
    if n >= 21:
        raw_prev_bw = boll_bw_series.iloc[-2]
        if np.isfinite(raw_prev_bw):
            prev_boll_bw = float(raw_prev_bw)
            prior_bws = boll_bw_series.iloc[:-1].dropna().tail(60)
            if len(prior_bws) >= 5:
                q25_prior_bw = float(np.percentile(prior_bws.to_numpy(dtype=float), 25))
                boll_squeeze_prior = prev_boll_bw <= max(6.0, q25_prior_bw * 1.1) and prev_boll_bw < 12.0
            else:
                boll_squeeze_prior = prev_boll_bw < 6.0

    result.boll_upper = boll_upper
    result.boll_mid = boll_mid
    result.boll_lower = boll_lower
    result.boll_pct_b = boll_pct_b
    result.boll_bandwidth_pct = curr_bw
    result.prev_boll_bandwidth_pct = prev_boll_bw
    result.boll_squeeze = boll_squeeze
    result.boll_squeeze_prior = boll_squeeze_prior
    if boll_squeeze:
        signals.append("Bollinger bandwidth squeeze (volatility breakout setup)")
    elif boll_pct_b >= 1.0:
        signals.append("Price broke above upper Bollinger Band")
    elif boll_pct_b <= 0.0:
        signals.append("Price stretched below lower Bollinger Band")

    # 2. Donchian Channels (exclude current bar to eliminate lookahead; 20d requires >= 21 bars)
    prior_highs_10 = high[max(0, n - 11):n - 1]
    prior_lows_10 = low[max(0, n - 11):n - 1]
    d_high_10 = float(np.max(prior_highs_10))
    d_low_10 = float(np.min(prior_lows_10))
    result.donchian_high_10 = d_high_10
    result.donchian_low_10 = d_low_10

    if n >= 21:
        prior_highs_20 = high[n - 21:n - 1]
        prior_lows_20 = low[n - 21:n - 1]
        d_high_20 = float(np.max(prior_highs_20))
        d_low_20 = float(np.min(prior_lows_20))
        result.donchian_high_20 = d_high_20
        result.donchian_low_20 = d_low_20
        if curr_close > d_high_20:
            result.donchian_signal = "breakout_20_high"
            signals.append("20-day Donchian high breakout")
        elif curr_close < d_low_20:
            result.donchian_signal = "breakdown_20_low"
            signals.append("20-day Donchian low breakdown")
        elif curr_close < d_low_10:
            result.donchian_signal = "breakdown_10_low"
            signals.append("10-day Donchian trailing stop breach")
        else:
            result.donchian_signal = "inside"
    elif curr_close < d_low_10:
        result.donchian_signal = "breakdown_10_low"
        signals.append("10-day Donchian trailing stop breach")
    else:
        result.donchian_signal = "inside"

    if (
        boll_squeeze_prior
        and prev_boll_bw is not None
        and curr_bw > prev_boll_bw * 1.05
        and ((band_span > 1e-12 and curr_close > boll_upper) or result.donchian_signal == "breakout_20_high")
    ):
        result.boll_squeeze_breakout = True
        signals.append("Bollinger squeeze release breakout")

    # 3. ATR(14), Chandelier Trailing Stop, HV20 & Lookahead-Free VCP Contraction Ratio
    prev_close = np.empty_like(close)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    atr_series = pd.Series(tr).ewm(alpha=1.0 / 14.0, adjust=False, min_periods=14).mean()
    atr_14 = float(atr_series.iloc[-1]) if np.isfinite(atr_series.iloc[-1]) else float(np.mean(tr[-14:]))
    result.atr_14 = max(0.0, atr_14)
    result.atr_pct = (result.atr_14 / curr_close * 100.0) if curr_close > 0 else 0.0
    result.atr_stop_loss_long = max(0.0, curr_close - 2.0 * result.atr_14)
    result.atr_take_profit_2r = curr_close + 4.0 * result.atr_14

    if n >= 21:
        raw_prev_atr = atr_series.iloc[-2]
        prev_atr = float(raw_prev_atr) if np.isfinite(raw_prev_atr) else float(np.mean(tr[-15:-1]))
        prev_atr = max(0.0, prev_atr)
        prior_peak_20 = float(np.max(high[n - 21:n - 1]))
        trailing_stop = max(0.0, prior_peak_20 - 2.0 * prev_atr)
        result.atr_trailing_stop_long = trailing_stop
        if trailing_stop > 0 and curr_close < trailing_stop:
            result.atr_trailing_stop_breached = True
            signals.append("Chandelier 2xATR trailing stop breached")

    if n >= 21:
        log_ret = np.diff(np.log(close[-21:]))
        hv_20 = float(np.std(log_ret, ddof=1) * math.sqrt(252.0) * 100.0) if len(log_ret) >= 2 else 0.0
        result.hv_20_annualized_pct = hv_20

    if n >= 31:
        # Exclude current bar so breakout-day expansion does not mask pre-breakout VCP tightness
        recent_mean = float(np.mean(close[-11:-1]))
        prior_mean = float(np.mean(close[-31:-11]))
        recent_range = (
            (float(np.max(high[-11:-1])) - float(np.min(low[-11:-1]))) / recent_mean
            if recent_mean > 0
            else 0.0
        )
        prior_range = (
            (float(np.max(high[-31:-11])) - float(np.min(low[-31:-11]))) / prior_mean
            if prior_mean > 0
            else 0.0
        )
        if prior_range > 1e-9:
            ratio = recent_range / prior_range
            result.vcp_contraction_ratio = ratio
            if ratio < 0.65:
                signals.append(f"VCP volatility contraction ({ratio:.2f}x vs prior 20d)")

    # 4. KDJ (9, 3, 3)
    low_9 = pd.Series(low).rolling(9, min_periods=1).min().to_numpy(dtype=float)
    high_9 = pd.Series(high).rolling(9, min_periods=1).max().to_numpy(dtype=float)
    span_9 = high_9 - low_9
    rsv = np.divide(
        (close - low_9) * 100.0,
        span_9,
        out=np.full(n, 50.0, dtype=float),
        where=span_9 > 1e-12,
    )

    k_arr = np.empty(n, dtype=float)
    d_arr = np.empty(n, dtype=float)
    k_val, d_val = 50.0, 50.0
    for idx in range(n):
        k_val = (2.0 / 3.0) * k_val + (1.0 / 3.0) * float(rsv[idx])
        d_val = (2.0 / 3.0) * d_val + (1.0 / 3.0) * k_val
        k_arr[idx] = k_val
        d_arr[idx] = d_val

    curr_k, curr_d = float(k_arr[-1]), float(d_arr[-1])
    curr_j = 3.0 * curr_k - 2.0 * curr_d
    prev_k, prev_d = float(k_arr[-2]), float(d_arr[-2])
    result.kdj_k = curr_k
    result.kdj_d = curr_d
    result.kdj_j = curr_j

    if prev_k <= prev_d and curr_k > curr_d:
        result.kdj_status = "golden_cross_low" if curr_d < 35.0 else "golden_cross"
        signals.append(f"KDJ bullish cross ({result.kdj_status})")
    elif prev_k >= prev_d and curr_k < curr_d:
        result.kdj_status = "death_cross_high" if curr_d > 70.0 else "death_cross"
        signals.append(f"KDJ bearish cross ({result.kdj_status})")
    elif curr_j > 90.0 or (curr_k > 80.0 and curr_d > 80.0):
        result.kdj_status = "overbought"
    elif curr_j < 15.0 or (curr_k < 20.0 and curr_d < 20.0):
        result.kdj_status = "oversold"
        signals.append("KDJ oversold zone")
    else:
        result.kdj_status = "neutral"

    # 5. Wilder ADX(14) / +DI(14) / -DI(14) (requires >= 28 bars for stable DX smoothing)
    if n >= 28:
        up_move = np.diff(high, prepend=high[0])
        down_move = -np.diff(low, prepend=low[0])
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # Exclude bar 0 diff artifact in DM/TR sums by starting at index 1
        tr_diff = tr[1:]
        pdm_diff = plus_dm[1:]
        mdm_diff = minus_dm[1:]
        atr_w = _wilder_smooth(tr_diff, 14)
        pdm_w = _wilder_smooth(pdm_diff, 14)
        mdm_w = _wilder_smooth(mdm_diff, 14)

        with np.errstate(divide="ignore", invalid="ignore"):
            pdi = np.where(atr_w > 1e-12, (pdm_w / atr_w) * 100.0, 0.0)
            mdi = np.where(atr_w > 1e-12, (mdm_w / atr_w) * 100.0, 0.0)
            di_sum = pdi + mdi
            dx = np.where(di_sum > 1e-12, (np.abs(pdi - mdi) / di_sum) * 100.0, 0.0)

        dx_valid = dx[13:]
        adx_arr = np.full(len(dx_valid), np.nan, dtype=float)
        if len(dx_valid) >= 14:
            adx_arr[13] = float(np.mean(dx_valid[:14]))
            for idx in range(14, len(dx_valid)):
                adx_arr[idx] = ((adx_arr[idx - 1] * 13.0) + dx_valid[idx]) / 14.0

        last_adx = float(adx_arr[-1])
        last_pdi = float(pdi[-1])
        last_mdi = float(mdi[-1])
        if math.isfinite(last_adx) and math.isfinite(last_pdi) and math.isfinite(last_mdi):
            result.adx_14 = last_adx
            result.plus_di_14 = last_pdi
            result.minus_di_14 = last_mdi
            if last_adx >= 25.0:
                result.adx_regime = "strong_trend"
            elif last_adx >= 18.0:
                result.adx_regime = "emerging_trend"
            else:
                result.adx_regime = "range_bound"

            if last_pdi > last_mdi + 1.0:
                result.adx_direction = "bullish"
            elif last_mdi > last_pdi + 1.0:
                result.adx_direction = "bearish"
            else:
                result.adx_direction = "neutral"

            if result.adx_regime == "strong_trend":
                signals.append(f"Strong {result.adx_direction} trend (ADX={last_adx:.1f})")

    # 6. OBV, VWAP(20), MFI(14)
    has_volume = bool(np.sum(volume) > 0)
    close_diff = np.diff(close, prepend=close[0])
    signed_vol = np.where(close_diff > 0, volume, np.where(close_diff < 0, -volume, 0.0))
    signed_vol[0] = 0.0
    obv_series = np.cumsum(signed_vol)
    obv_val = float(obv_series[-1])
    obv_ma20_series = pd.Series(obv_series).rolling(20, min_periods=1).mean()
    obv_ma20_val = float(obv_ma20_series.iloc[-1])

    result.obv = obv_val
    result.obv_ma20 = obv_ma20_val
    if has_volume:
        vol_scale = max(float(np.mean(volume[-20:])), 1.0)
        obv_delta = obv_val - obv_ma20_val
        obv_5d_change = obv_val - float(obv_series[-6]) if n >= 6 else obv_delta
        if obv_delta > vol_scale * 0.25 and obv_5d_change >= 0:
            result.obv_trend = "rising"
        elif obv_delta < -vol_scale * 0.25 and obv_5d_change <= 0:
            result.obv_trend = "falling"
        else:
            result.obv_trend = "flat"

        if n >= 20:
            c_prior = close[-20:-10]
            c_recent = close[-10:]
            o_prior = obv_series[-20:-10]
            o_recent = obv_series[-10:]
            if float(np.min(c_recent)) < float(np.min(c_prior)) * 0.99 and float(np.min(o_recent)) > float(np.min(o_prior)):
                result.obv_divergence = "bullish_divergence"
                signals.append("OBV bullish divergence")
            elif float(np.max(c_recent)) > float(np.max(c_prior)) * 1.01 and float(np.max(o_recent)) < float(np.max(o_prior)):
                result.obv_divergence = "bearish_divergence"
                signals.append("OBV bearish divergence")

        # 20-day VWAP & bias
        typical_price = (high + low + close) / 3.0
        vol_20 = volume[-20:]
        tp_20 = typical_price[-20:]
        vol_sum_20 = float(np.sum(vol_20))
        if vol_sum_20 > 0:
            vwap_20 = float(np.sum(tp_20 * vol_20) / vol_sum_20)
            if vwap_20 > 0:
                result.vwap_20 = vwap_20
                result.vwap_bias_pct = (curr_close / vwap_20 - 1.0) * 100.0

        # MFI(14) over trailing 14 price transitions
        tp_15 = typical_price[-15:]
        vol_15 = volume[-15:]
        raw_mf = tp_15[1:] * vol_15[1:]
        tp_delta = np.diff(tp_15)
        pos_mf = float(np.sum(np.where(tp_delta > 0, raw_mf, 0.0)))
        neg_mf = float(np.sum(np.where(tp_delta < 0, raw_mf, 0.0)))
        if pos_mf + neg_mf > 0:
            if neg_mf <= 1e-12:
                mfi_14 = 100.0
            else:
                mf_ratio = pos_mf / neg_mf
                mfi_14 = 100.0 - (100.0 / (1.0 + mf_ratio))
            result.mfi_14 = mfi_14
            if mfi_14 >= 80.0:
                result.mfi_status = "overbought"
            elif mfi_14 <= 20.0:
                result.mfi_status = "oversold"
            elif mfi_14 > 55.0:
                result.mfi_status = "bullish"
            elif mfi_14 < 45.0:
                result.mfi_status = "bearish"
            else:
                result.mfi_status = "neutral"

    # 7. Momentum & Drawdown Risk (60-day metrics require >= 60 bars)
    if n >= 6:
        result.roc_5_pct = (curr_close / float(close[-6]) - 1.0) * 100.0
    if n >= 21:
        result.roc_20_pct = (curr_close / float(close[-21]) - 1.0) * 100.0
    if n >= 61:
        result.roc_60_pct = (curr_close / float(close[-61]) - 1.0) * 100.0

    if n >= 60:
        win_close = close[-60:]
        win_high = high[-60:]
        running_max = np.maximum.accumulate(win_close)
        drawdowns = (win_close / running_max - 1.0) * 100.0
        result.max_drawdown_60_pct = float(np.min(drawdowns))
        peak_high_60 = float(np.max(win_high))
        if peak_high_60 > 0:
            result.dist_from_high_60_pct = (curr_close / peak_high_60 - 1.0) * 100.0

        win_ret = np.diff(win_close) / win_close[:-1]
        if len(win_ret) >= 2:
            std_ret = float(np.std(win_ret, ddof=1))
            if std_ret > 1e-12:
                result.sharpe_60 = float(np.mean(win_ret) / std_ret * math.sqrt(252.0))
            else:
                result.sharpe_60 = 0.0

    # 8. Composite Regime & Score (0-100)
    score = 50.0
    if result.adx_regime in ("strong_trend", "emerging_trend"):
        score += 10.0 if result.adx_direction == "bullish" else (-10.0 if result.adx_direction == "bearish" else 0.0)
    if result.donchian_signal == "breakout_20_high":
        score += 12.0
    elif result.donchian_signal == "breakdown_20_low":
        score -= 12.0
    elif result.donchian_signal == "breakdown_10_low":
        score -= 6.0

    if result.kdj_status == "golden_cross_low":
        score += 10.0
    elif result.kdj_status == "golden_cross":
        score += 5.0
    elif result.kdj_status == "death_cross_high":
        score -= 10.0
    elif result.kdj_status == "death_cross":
        score -= 5.0

    if result.obv_trend == "rising":
        score += 6.0
    elif result.obv_trend == "falling":
        score -= 6.0

    if result.obv_divergence == "bullish_divergence":
        score += 7.0
    elif result.obv_divergence == "bearish_divergence":
        score -= 7.0

    if result.vwap_bias_pct is not None:
        if 0.0 <= result.vwap_bias_pct <= 5.0:
            score += 4.0
        elif result.vwap_bias_pct < -2.0:
            score -= 4.0

    if result.mfi_status == "bullish":
        score += 4.0
    elif result.mfi_status == "bearish":
        score -= 4.0

    if result.roc_20_pct is not None:
        if result.roc_20_pct > 5.0:
            score += 6.0
        elif result.roc_20_pct < -8.0:
            score -= 6.0

    if result.max_drawdown_60_pct is not None and result.max_drawdown_60_pct < -20.0:
        score -= 5.0

    if boll_squeeze or result.boll_squeeze_breakout:
        score += 3.0

    result.quant_composite_score = max(0, min(100, int(round(score))))

    if result.adx_regime == "strong_trend" and result.adx_direction == "bullish":
        result.quant_regime = "trending_bullish"
    elif result.adx_regime == "strong_trend" and result.adx_direction == "bearish":
        result.quant_regime = "trending_bearish"
    elif boll_squeeze or (result.vcp_contraction_ratio is not None and result.vcp_contraction_ratio < 0.65):
        result.quant_regime = "volatility_squeeze"
    elif boll_pct_b <= 0.1 or result.kdj_status in ("oversold", "golden_cross_low"):
        result.quant_regime = "oversold_rebound"
    elif boll_pct_b >= 0.95 and (result.kdj_status == "overbought" or result.mfi_status == "overbought"):
        result.quant_regime = "overbought_extension"
    else:
        result.quant_regime = "range_bound"

    result.factor_signals = signals
    return result
