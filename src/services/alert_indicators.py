# -*- coding: utf-8 -*-
"""Technical indicator alert helpers for AlertService P5 rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from math import isfinite
from typing import Any, Dict, Optional

import pandas as pd


TECHNICAL_ALERT_TYPES = frozenset({
    "ma_price_cross",
    "rsi_threshold",
    "macd_cross",
    "kdj_cross",
    "cci_threshold",
})

ABOVE_BELOW_DIRECTIONS = frozenset({"above", "below"})
CROSS_DIRECTIONS = frozenset({"bullish_cross", "bearish_cross"})
MAX_REQUESTED_DAYS = 365


@dataclass
class TechnicalIndicatorAlert:
    stock_code: str
    alert_type: str
    indicator_params: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IndicatorEvaluation:
    status: str
    observed_value: Optional[float]
    threshold: Optional[float]
    message: str
    data_timestamp: Optional[datetime] = None


def normalize_indicator_parameters(alert_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")

    if alert_type == "ma_price_cross":
        normalized = {
            "direction": _direction(parameters.get("direction"), ABOVE_BELOW_DIRECTIONS, default="above"),
            "window": _int_in_range(parameters.get("window"), "window", default=20),
        }
        return _ensure_required_bars_fetchable(alert_type, normalized)
    if alert_type == "rsi_threshold":
        normalized = {
            "direction": _direction(parameters.get("direction"), ABOVE_BELOW_DIRECTIONS, default="above"),
            "period": _int_in_range(parameters.get("period"), "period", default=12),
            "threshold": _float_in_range(parameters.get("threshold"), "threshold", minimum=0.0, maximum=100.0),
        }
        return _ensure_required_bars_fetchable(alert_type, normalized)
    if alert_type == "macd_cross":
        fast_period = _int_in_range(parameters.get("fast_period"), "fast_period", default=12)
        slow_period = _int_in_range(parameters.get("slow_period"), "slow_period", default=26)
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        normalized = {
            "direction": _direction(parameters.get("direction"), CROSS_DIRECTIONS, default="bullish_cross"),
            "fast_period": fast_period,
            "slow_period": slow_period,
            "signal_period": _int_in_range(parameters.get("signal_period"), "signal_period", default=9),
        }
        return _ensure_required_bars_fetchable(alert_type, normalized)
    if alert_type == "kdj_cross":
        normalized = {
            "direction": _direction(parameters.get("direction"), CROSS_DIRECTIONS, default="bullish_cross"),
            "period": _int_in_range(parameters.get("period"), "period", default=9),
            "k_period": _int_in_range(parameters.get("k_period"), "k_period", default=3),
            "d_period": _int_in_range(parameters.get("d_period"), "d_period", default=3),
        }
        return _ensure_required_bars_fetchable(alert_type, normalized)
    if alert_type == "cci_threshold":
        normalized = {
            "direction": _direction(parameters.get("direction"), ABOVE_BELOW_DIRECTIONS, default="above"),
            "period": _int_in_range(parameters.get("period"), "period", default=14),
            "threshold": _finite_float(parameters.get("threshold"), "threshold"),
        }
        return _ensure_required_bars_fetchable(alert_type, normalized)
    raise ValueError(f"unsupported technical alert_type: {alert_type}")


def compute_required_bars(alert_type: str, params: Dict[str, Any]) -> int:
    if alert_type == "ma_price_cross":
        return int(params["window"]) + 1
    if alert_type == "rsi_threshold":
        return int(params["period"]) + 1
    if alert_type == "macd_cross":
        return int(params["slow_period"]) + int(params["signal_period"]) + 1
    if alert_type == "kdj_cross":
        return int(params["period"]) + int(params["k_period"]) + int(params["d_period"]) + 1
    if alert_type == "cci_threshold":
        return int(params["period"]) + 1
    raise ValueError(f"unsupported technical alert_type: {alert_type}")


def compute_requested_days(alert_type: str, params: Dict[str, Any]) -> int:
    required_bars = compute_required_bars(alert_type, params)
    return min(max(required_bars * 3, required_bars + 30), MAX_REQUESTED_DAYS)


def threshold_for_indicator(alert_type: str, params: Dict[str, Any]) -> Optional[float]:
    if alert_type in {"rsi_threshold", "cci_threshold"}:
        return float(params["threshold"])
    if alert_type in {"macd_cross", "kdj_cross"}:
        return 0.0
    return None


def evaluate_indicator_alert(
    alert_type: str,
    stock_code: str,
    params: Dict[str, Any],
    df: Any,
    *,
    now: Optional[datetime] = None,
) -> IndicatorEvaluation:
    columns = ("close",)
    if alert_type in {"kdj_cross", "cci_threshold"}:
        columns = ("high", "low", "close")

    try:
        normalized = normalize_ohlcv(df, required_columns=columns, now=now)
    except ValueError as exc:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=threshold_for_indicator(alert_type, params),
            message=str(exc),
        )
    if normalized.empty:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=threshold_for_indicator(alert_type, params),
            message="No closed daily data available",
        )
    if len(normalized) < 2:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=threshold_for_indicator(alert_type, params),
            message="insufficient closed bars for edge evaluation",
            data_timestamp=_latest_timestamp(normalized),
        )

    required_bars = compute_required_bars(alert_type, params)
    if len(normalized) < required_bars:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=threshold_for_indicator(alert_type, params),
            message=f"insufficient data: need {required_bars} bars, got {len(normalized)}",
            data_timestamp=_latest_timestamp(normalized),
        )

    if alert_type == "ma_price_cross":
        return _evaluate_ma(stock_code, params, normalized)
    if alert_type == "rsi_threshold":
        return _evaluate_rsi(stock_code, params, normalized)
    if alert_type == "macd_cross":
        return _evaluate_macd(stock_code, params, normalized)
    if alert_type == "kdj_cross":
        return _evaluate_kdj(stock_code, params, normalized)
    if alert_type == "cci_threshold":
        return _evaluate_cci(stock_code, params, normalized)
    raise ValueError(f"unsupported technical alert_type: {alert_type}")


def normalize_ohlcv(
    df: Any,
    *,
    required_columns: tuple[str, ...],
    now: Optional[datetime] = None,
) -> pd.DataFrame:
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    output = pd.DataFrame(index=df.index.copy())
    output["date"] = _date_series(df)

    missing = []
    for canonical in required_columns:
        source = _find_column(df, canonical)
        if source is None:
            missing.append(canonical)
            continue
        output[canonical] = pd.to_numeric(df[source], errors="coerce")
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"daily data missing {missing_text} column")

    output = output.dropna(subset=list(required_columns)).copy()
    if output.empty:
        return output
    output = _drop_partial_today(output, now=now)
    if output.empty:
        return output.reset_index(drop=True)
    output = output.sort_values(by="date", kind="stable", na_position="first").reset_index(drop=True)
    return output


def _evaluate_ma(stock_code: str, params: Dict[str, Any], df: pd.DataFrame) -> IndicatorEvaluation:
    window = int(params["window"])
    direction = str(params["direction"])
    series = df["close"].rolling(window=window).mean()
    latest = _latest_timestamp(df)
    prev_close, curr_close = float(df["close"].iloc[-2]), float(df["close"].iloc[-1])
    prev_ma, curr_ma = float(series.iloc[-2]), float(series.iloc[-1])
    if not all(isfinite(value) for value in (prev_ma, curr_ma)):
        return _indicator_unavailable("MA", latest)

    prev_delta = prev_close - prev_ma
    curr_delta = curr_close - curr_ma
    triggered = _crossed_zero(prev_delta, curr_delta, direction)
    message = (
        f"{stock_code} close {curr_close:.4f} crossed {direction} MA{window} {curr_ma:.4f}"
        if triggered
        else f"{stock_code} close {curr_close:.4f} did not edge-cross {direction} MA{window} {curr_ma:.4f}"
    )
    return IndicatorEvaluation(
        status="triggered" if triggered else "not_triggered",
        observed_value=curr_close,
        threshold=curr_ma,
        message=message,
        data_timestamp=latest,
    )


def _evaluate_rsi(stock_code: str, params: Dict[str, Any], df: pd.DataFrame) -> IndicatorEvaluation:
    period = int(params["period"])
    threshold = float(params["threshold"])
    direction = str(params["direction"])
    rsi = _calculate_rsi(df["close"], period)
    latest = _latest_timestamp(df)
    prev_value, curr_value = float(rsi.iloc[-2]), float(rsi.iloc[-1])
    if not all(isfinite(value) for value in (prev_value, curr_value)):
        return _indicator_unavailable("RSI", latest, threshold=threshold)

    triggered = _crossed_threshold(prev_value, curr_value, threshold, direction)
    message = (
        f"{stock_code} RSI{period} {curr_value:.2f} crossed {direction} {threshold:.2f}"
        if triggered
        else f"{stock_code} RSI{period} {curr_value:.2f} did not edge-cross {direction} {threshold:.2f}"
    )
    return IndicatorEvaluation(
        status="triggered" if triggered else "not_triggered",
        observed_value=curr_value,
        threshold=threshold,
        message=message,
        data_timestamp=latest,
    )


def _evaluate_macd(stock_code: str, params: Dict[str, Any], df: pd.DataFrame) -> IndicatorEvaluation:
    fast_period = int(params["fast_period"])
    slow_period = int(params["slow_period"])
    signal_period = int(params["signal_period"])
    direction = str(params["direction"])
    ema_fast = df["close"].ewm(span=fast_period, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow_period, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal_period, adjust=False).mean()
    delta = dif - dea
    latest = _latest_timestamp(df)
    prev_delta, curr_delta = float(delta.iloc[-2]), float(delta.iloc[-1])
    if not all(isfinite(value) for value in (prev_delta, curr_delta)):
        return _indicator_unavailable("MACD", latest, threshold=0.0)

    triggered = _crossed_cross_direction(prev_delta, curr_delta, direction)
    message = (
        f"{stock_code} MACD DIF/DEA {direction}: delta = {curr_delta:.4f}"
        if triggered
        else f"{stock_code} MACD delta {curr_delta:.4f} did not edge-cross {direction}"
    )
    return IndicatorEvaluation(
        status="triggered" if triggered else "not_triggered",
        observed_value=curr_delta,
        threshold=0.0,
        message=message,
        data_timestamp=latest,
    )


def _evaluate_kdj(stock_code: str, params: Dict[str, Any], df: pd.DataFrame) -> IndicatorEvaluation:
    period = int(params["period"])
    k_period = int(params["k_period"])
    d_period = int(params["d_period"])
    direction = str(params["direction"])
    lowest_low = df["low"].rolling(window=period).min()
    highest_high = df["high"].rolling(window=period).max()
    denominator = highest_high - lowest_low
    rsv = ((df["close"] - lowest_low) / denominator.mask(denominator == 0) * 100).fillna(50)
    k_value = rsv.ewm(alpha=1 / k_period, adjust=False).mean()
    d_value = k_value.ewm(alpha=1 / d_period, adjust=False).mean()
    delta = k_value - d_value
    latest = _latest_timestamp(df)
    prev_delta, curr_delta = float(delta.iloc[-2]), float(delta.iloc[-1])
    if not all(isfinite(value) for value in (prev_delta, curr_delta)):
        return _indicator_unavailable("KDJ", latest, threshold=0.0)

    triggered = _crossed_cross_direction(prev_delta, curr_delta, direction)
    message = (
        f"{stock_code} KDJ K/D {direction}: delta = {curr_delta:.4f}"
        if triggered
        else f"{stock_code} KDJ delta {curr_delta:.4f} did not edge-cross {direction}"
    )
    return IndicatorEvaluation(
        status="triggered" if triggered else "not_triggered",
        observed_value=curr_delta,
        threshold=0.0,
        message=message,
        data_timestamp=latest,
    )


def _evaluate_cci(stock_code: str, params: Dict[str, Any], df: pd.DataFrame) -> IndicatorEvaluation:
    period = int(params["period"])
    threshold = float(params["threshold"])
    direction = str(params["direction"])
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_ma = typical_price.rolling(window=period).mean()
    mean_deviation = typical_price.rolling(window=period).apply(
        lambda values: float(abs(values - values.mean()).mean()),
        raw=False,
    )
    cci = (typical_price - tp_ma) / (0.015 * mean_deviation.mask(mean_deviation == 0))
    latest = _latest_timestamp(df)
    prev_value, curr_value = float(cci.iloc[-2]), float(cci.iloc[-1])
    if not all(isfinite(value) for value in (prev_value, curr_value)):
        return _indicator_unavailable("CCI", latest, threshold=threshold)

    triggered = _crossed_threshold(prev_value, curr_value, threshold, direction)
    message = (
        f"{stock_code} CCI{period} {curr_value:.2f} crossed {direction} {threshold:.2f}"
        if triggered
        else f"{stock_code} CCI{period} {curr_value:.2f} did not edge-cross {direction} {threshold:.2f}"
    )
    return IndicatorEvaluation(
        status="triggered" if triggered else "not_triggered",
        observed_value=curr_value,
        threshold=threshold,
        message=message,
        data_timestamp=latest,
    )


def _ensure_required_bars_fetchable(alert_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    required_bars = compute_required_bars(alert_type, params)
    if required_bars > MAX_REQUESTED_DAYS:
        raise ValueError(
            f"{alert_type} periods require {required_bars} bars, "
            f"but at most {MAX_REQUESTED_DAYS} days can be requested"
        )
    return params


def _direction(value: Any, allowed: frozenset[str], *, default: str) -> str:
    direction = str(value or default).strip().lower()
    if direction not in allowed:
        raise ValueError(f"invalid direction: {direction}")
    return direction


def _int_in_range(value: Any, field_name: str, *, default: int, minimum: int = 2, maximum: int = 250) -> int:
    raw_value = default if value is None or value == "" else value
    try:
        number = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc
    if str(raw_value).strip() not in {str(number), f"{number}.0"}:
        raise ValueError(f"{field_name} must be an integer")
    if number < minimum or number > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return number


def _finite_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _float_in_range(
    value: Any,
    field_name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    number = _finite_float(value, field_name)
    if number < minimum or number > maximum:
        raise ValueError(f"{field_name} must be between {minimum:g} and {maximum:g}")
    return number


def _calculate_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    # 使用 Wilder's EMA / SMMA 口径，不使用 rolling SMA。
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).fillna(50)


def _crossed_threshold(prev_value: float, curr_value: float, threshold: float, direction: str) -> bool:
    if direction == "above":
        return prev_value <= threshold < curr_value
    if direction == "below":
        return prev_value >= threshold > curr_value
    return False


def _crossed_zero(prev_delta: float, curr_delta: float, direction: str) -> bool:
    if direction == "above":
        return prev_delta <= 0 < curr_delta
    if direction == "below":
        return prev_delta >= 0 > curr_delta
    return False


def _crossed_cross_direction(prev_delta: float, curr_delta: float, direction: str) -> bool:
    if direction == "bullish_cross":
        return prev_delta <= 0 < curr_delta
    if direction == "bearish_cross":
        return prev_delta >= 0 > curr_delta
    return False


def _indicator_unavailable(
    indicator_name: str,
    data_timestamp: Optional[datetime],
    *,
    threshold: Optional[float] = None,
) -> IndicatorEvaluation:
    return IndicatorEvaluation(
        status="degraded",
        observed_value=None,
        threshold=threshold,
        message=f"{indicator_name} value is not available",
        data_timestamp=data_timestamp,
    )


def _find_column(df: pd.DataFrame, canonical: str) -> Optional[Any]:
    candidates = {
        "date": ("date", "trade_date", "datetime", "time", "日期", "交易日期"),
        "open": ("open", "open_price", "开盘", "开盘价"),
        "high": ("high", "high_price", "最高", "最高价"),
        "low": ("low", "low_price", "最低", "最低价"),
        "close": ("close", "close_price", "收盘", "收盘价"),
        "volume": ("volume", "vol", "成交量"),
    }
    by_normalized = {str(column).strip().lower(): column for column in df.columns}
    for candidate in candidates[canonical]:
        column = by_normalized.get(candidate.lower())
        if column is not None:
            return column
    return None


def _date_series(df: pd.DataFrame) -> pd.Series:
    date_column = _find_column(df, "date")
    if date_column is not None:
        return pd.to_datetime(df[date_column], errors="coerce")
    index = df.index
    if isinstance(index, pd.DatetimeIndex):
        return pd.Series(index.to_pydatetime(), index=df.index)
    return pd.Series([pd.NaT] * len(df), index=df.index)


def _drop_partial_today(df: pd.DataFrame, *, now: Optional[datetime] = None) -> pd.DataFrame:
    current = now or datetime.now()
    if current.time() >= time(16, 0):
        return df
    try:
        parsed = pd.to_datetime(df["date"].iloc[-1], errors="coerce")
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return df.iloc[:-1].copy()
    if pd.isna(parsed):
        return df.iloc[:-1].copy()
    last_date = parsed.date()
    if last_date == current.date():
        return df.iloc[:-1].copy()
    return df


def _latest_timestamp(df: pd.DataFrame) -> Optional[datetime]:
    try:
        raw_value = df["date"].iloc[-1]
        if pd.isna(raw_value):
            return None
        parsed = pd.to_datetime(raw_value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None
