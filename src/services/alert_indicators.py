# -*- coding: utf-8 -*-
"""Technical indicator alert helpers for AlertService P5 rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.kline_patterns import (
    ALLOWED_ALERT_PATTERN_TOKENS,
    VOLUME_DEPENDENT_PATTERN_IDS,
    detect_kline_patterns,
    parse_iso_date_value,
    required_bars_for_alert_patterns,
    resolve_alert_pattern_ids,
)
from src.core.trading_calendar import (
    _XCALS_AVAILABLE,
    get_effective_trading_date,
    get_market_for_stock,
    get_market_now,
    get_trading_dates,
)
from src.utils.rsi import wilder_rsi


TECHNICAL_ALERT_TYPES = frozenset({
    "ma_price_cross",
    "rsi_threshold",
    "macd_cross",
    "kdj_cross",
    "cci_threshold",
    "kline_pattern",
})

ABOVE_BELOW_DIRECTIONS = frozenset({"above", "below"})
CROSS_DIRECTIONS = frozenset({"bullish_cross", "bearish_cross"})
MAX_REQUESTED_DAYS = 365
_MARKET_CLOSE_TIMES = {
    "cn": time(15, 0),
    "hk": time(16, 0),
    "us": time(16, 0),
    "jp": time(15, 30),
    "kr": time(15, 30),
    "tw": time(13, 30),
}


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
    matched_patterns: Optional[List[str]] = None
    monitored_patterns: Optional[List[str]] = None
    unavailable_patterns: Optional[List[str]] = None


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
    if alert_type == "kline_pattern":
        normalized = {
            "patterns": _pattern_list(parameters.get("patterns")),
            "require_volume_confirm": _bool_flag(
                parameters.get("require_volume_confirm"),
                "require_volume_confirm",
                default=False,
            ),
        }
        return _ensure_required_bars_fetchable(alert_type, normalized)
    raise ValueError(f"unsupported technical alert_type: {alert_type}")


def compute_required_bars(alert_type: str, params: Dict[str, Any]) -> int:
    if alert_type == "ma_price_cross":
        return int(params["window"]) + 1
    if alert_type == "rsi_threshold":
        # period changes give the first RSI; one more bar gives a second real
        # value, so a crossing is never judged against a warm-up placeholder.
        return int(params["period"]) + 2
    if alert_type == "macd_cross":
        return int(params["slow_period"]) + int(params["signal_period"]) + 1
    if alert_type == "kdj_cross":
        return int(params["period"]) + int(params["k_period"]) + int(params["d_period"]) + 1
    if alert_type == "cci_threshold":
        return int(params["period"]) + 1
    if alert_type == "kline_pattern":
        return required_bars_for_alert_patterns(params["patterns"])
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
        if alert_type == "kline_pattern":
            normalized = _normalize_kline_ohlcv(df, stock_code=stock_code, now=now)
        else:
            normalized = normalize_ohlcv(
                df,
                required_columns=columns,
                stock_code=stock_code,
                now=now,
            )
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
    if alert_type == "kline_pattern":
        return _evaluate_kline_pattern(stock_code, params, normalized)
    raise ValueError(f"unsupported technical alert_type: {alert_type}")


def normalize_ohlcv(
    df: Any,
    *,
    required_columns: tuple[str, ...],
    stock_code: Optional[str] = None,
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
    output = _drop_partial_today(output, stock_code=stock_code, now=now)
    if output.empty:
        return output.reset_index(drop=True)
    output = output.sort_values(by="date", kind="stable", na_position="first").reset_index(drop=True)
    return output


def _effective_closed_date_for_stock(
    stock_code: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[date]:
    market = get_market_for_stock(stock_code) if stock_code else None
    if market in _MARKET_CLOSE_TIMES:
        market_now = get_market_now(market, current_time=now)
        if _XCALS_AVAILABLE:
            return get_effective_trading_date(market, current_time=now)
        close_time = _MARKET_CLOSE_TIMES[market]
        return (
            market_now.date() - timedelta(days=1)
            if market_now.time() < close_time
            else market_now.date()
        )
    current = now or datetime.now()
    if current.time() < time(16, 0):
        return current.date() - timedelta(days=1)
    return None


def _normalize_kline_ohlcv(
    df: Any,
    *,
    stock_code: Optional[str] = None,
    now: Optional[datetime] = None,
) -> pd.DataFrame:
    """Normalize OHLC(V) while preserving row positions and resolving duplicate dates."""
    if df is None or getattr(df, "empty", True) or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    attrs = dict(getattr(df, "attrs", {}) or {})
    output = pd.DataFrame(index=df.index.copy())
    date_col = _find_column(df, "date")
    if date_col is not None:
        raw_dates = [parse_iso_date_value(v) for v in df[date_col].tolist()]
        output["date"] = pd.to_datetime(raw_dates, errors="coerce")
    elif isinstance(df.index, pd.DatetimeIndex):
        raw_dates = [parse_iso_date_value(v) for v in df.index.to_pydatetime().tolist()]
        output["date"] = pd.to_datetime(raw_dates, errors="coerce")
    else:
        output["date"] = pd.Series([pd.NaT] * len(df), index=df.index)

    required_columns = ("open", "high", "low", "close")
    missing = []
    for canonical in required_columns:
        source = _find_column(df, canonical)
        if source is None:
            missing.append(canonical)
            continue
        output[canonical] = pd.to_numeric(df[source], errors="coerce")
    if missing:
        raise ValueError(f"daily data missing {', '.join(missing)} column")

    vol_col = _find_column(df, "volume")
    if vol_col is not None:
        output["volume"] = pd.to_numeric(df[vol_col], errors="coerce")

    attrs["raw_last_undated"] = bool(len(output) > 0 and pd.isna(output["date"].iloc[-1]))
    eff_closed = _effective_closed_date_for_stock(stock_code=stock_code, now=now)
    attrs["effective_closed_date"] = eff_closed.isoformat() if eff_closed is not None else None
    output.attrs.update(attrs)

    output = _drop_partial_today(output, stock_code=stock_code, now=now, drop_undated_last=False)
    if output.empty:
        return output.reset_index(drop=True)

    output = output.sort_values(by="date", kind="stable", na_position="last")
    valid_date_mask = output["date"].notna()
    dup_valid = valid_date_mask & output.duplicated(subset=["date"], keep="last")
    output = output.loc[~dup_valid].reset_index(drop=True)
    output.attrs.update(attrs)
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
    rsi = wilder_rsi(df["close"], period, fill_warmup=False)
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


def check_kline_session_continuity(
    dates: list[date],
    *,
    stock_code: Optional[str] = None,
    expected_latest: Optional[date] = None,
    require_latest_match: bool = False,
) -> Optional[str]:
    """Validate trading-session continuity across ``dates``.

    Returns an English degradation reason if an interior session is missing or
    (when ``require_latest_match=True``) the latest observed session is stale
    relative to ``expected_latest`` for known markets; returns ``None`` when valid.
    """
    if not dates:
        return "missing session dates"

    win_start = dates[0]
    win_end = dates[-1]
    market = get_market_for_stock(stock_code) if stock_code else None

    if require_latest_match and market in _MARKET_CLOSE_TIMES and expected_latest is not None:
        if expected_latest < win_start:
            return f"session dates ahead of effective closed session ({expected_latest.isoformat()})"
        expected_sessions = get_trading_dates(market, win_start, expected_latest)
        if expected_sessions is not None:
            if len(expected_sessions) == 0:
                return f"unexpected non-trading session in evaluation window: {dates[0].isoformat()}"
            expected_set = {ts.date() for ts in expected_sessions}
            observed_dates = set(dates)
            unexpected_sessions = sorted(d for d in observed_dates if d not in expected_set)
            if unexpected_sessions:
                return (
                    f"unexpected non-trading session in evaluation window: "
                    f"{unexpected_sessions[0].isoformat()}"
                )
            latest_expected = expected_sessions[-1].date()
            if win_end < latest_expected:
                return (
                    f"missing latest closed trading session: {latest_expected.isoformat()} "
                    f"(latest observed {win_end.isoformat()})"
                )
            missing_sessions = [ts.date() for ts in expected_sessions if ts.date() not in observed_dates]
            if missing_sessions:
                return f"missing trading session in evaluation window: {missing_sessions[0].isoformat()}"
            return None
        return f"trading calendar unavailable for {market} session validation"

    expected_sessions = get_trading_dates(market, win_start, win_end) if market else None
    if expected_sessions is not None:
        if len(expected_sessions) == 0:
            return f"unexpected non-trading session in evaluation window: {dates[0].isoformat()}"
        expected_set = {ts.date() for ts in expected_sessions}
        observed_dates = set(dates)
        unexpected_sessions = sorted(d for d in observed_dates if d not in expected_set)
        if unexpected_sessions:
            return (
                f"unexpected non-trading session in evaluation window: "
                f"{unexpected_sessions[0].isoformat()}"
            )
        missing_sessions = [ts.date() for ts in expected_sessions if ts.date() not in observed_dates]
        if missing_sessions:
            return f"missing trading session in evaluation window: {missing_sessions[0].isoformat()}"
        return None
    if market in _MARKET_CLOSE_TIMES:
        return f"trading calendar unavailable for {market} session validation"

    weekend_dates = sorted(d for d in set(dates) if d.weekday() >= 5)
    if weekend_dates:
        return f"unexpected non-trading session in evaluation window: {weekend_dates[0].isoformat()}"
    recent_dates = dates[-min(len(dates), 5):]
    for prev_day, curr_day in zip(recent_dates, recent_dates[1:]):
        probe_day = prev_day + timedelta(days=1)
        while probe_day < curr_day:
            if probe_day.weekday() < 5:
                return f"missing weekday session in evaluation window: {probe_day.isoformat()}"
            probe_day += timedelta(days=1)
    return None


def _evaluate_kline_pattern(stock_code: str, params: Dict[str, Any], df: pd.DataFrame) -> IndicatorEvaluation:
    ordered_target_ids = resolve_alert_pattern_ids(params["patterns"])
    require_volume = bool(params.get("require_volume_confirm", False))
    required_bars = compute_required_bars("kline_pattern", params)
    latest = _latest_timestamp(df)

    if bool(df.attrs.get("raw_last_undated")):
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=None,
            message="invalid or missing latest session date",
            data_timestamp=latest,
        )

    tail_win = df.iloc[-required_bars:]
    if tail_win["date"].isna().any():
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=None,
            message="invalid or missing session date in evaluation window",
            data_timestamp=latest,
        )

    dropped_undated = int(df.attrs.get("dropped_undated_count") or 0)
    if dropped_undated > 0:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=None,
            message="dropped undated invalid daily rows in fetch path",
            data_timestamp=latest,
        )

    tail_dates = [ts.date() for ts in pd.to_datetime(tail_win["date"]).tolist()]
    win_start = tail_dates[0]
    win_end = tail_dates[-1]
    eff_cutoff_iso = df.attrs.get("effective_closed_date")
    eff_cutoff = date.fromisoformat(eff_cutoff_iso) if eff_cutoff_iso else None
    upper_bound = max(win_end, eff_cutoff) if eff_cutoff is not None else win_end

    for raw_dropped in df.attrs.get("dropped_invalid_dates") or []:
        parsed_iso = parse_iso_date_value(raw_dropped)
        if parsed_iso is None:
            continue
        dropped_day = date.fromisoformat(parsed_iso)
        if win_start <= dropped_day <= upper_bound:
            return IndicatorEvaluation(
                status="degraded",
                observed_value=None,
                threshold=None,
                message=f"dropped invalid daily data in evaluation window ({parsed_iso})",
                data_timestamp=latest,
            )

    gap_error = check_kline_session_continuity(
        tail_dates,
        stock_code=stock_code,
        expected_latest=eff_cutoff,
        require_latest_match=True,
    )
    if gap_error is not None:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=None,
            message=gap_error,
            data_timestamp=latest,
        )

    for row_idx in range(len(tail_win)):
        row = tail_win.iloc[row_idx]
        o_v = float(row["open"])
        h_v = float(row["high"])
        l_v = float(row["low"])
        c_v = float(row["close"])
        if (
            not all(isfinite(val) and val > 0 for val in (o_v, h_v, l_v, c_v))
            or h_v < l_v
            or h_v < max(o_v, c_v)
            or l_v > min(o_v, c_v)
        ):
            return _indicator_unavailable("K-line pattern", latest)

    volume_window_valid = False
    if "volume" in df.columns and len(df) >= 7:
        vol_tail = [float(v) for v in df["volume"].iloc[-7:].tolist()]
        volume_window_valid = all(isfinite(v) and v > 0 for v in vol_tail)

    if volume_window_valid:
        evaluable_ids = ordered_target_ids
        unavailable_volume_ids: List[str] = []
    elif require_volume:
        evaluable_ids = []
        unavailable_volume_ids = list(ordered_target_ids)
    else:
        unavailable_volume_ids = [
            pid for pid in ordered_target_ids if pid in VOLUME_DEPENDENT_PATTERN_IDS
        ]
        evaluable_ids = [
            pid for pid in ordered_target_ids if pid not in VOLUME_DEPENDENT_PATTERN_IDS
        ]

    if not evaluable_ids:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=None,
            threshold=None,
            message="insufficient volume data for volume-dependent kline pattern",
            data_timestamp=latest,
            unavailable_patterns=unavailable_volume_ids,
        )

    latest_close = float(df["close"].iloc[-1])
    evaluable_set = set(evaluable_ids)

    def _shapes_on(frame: pd.DataFrame):
        return [
            item
            for item in detect_kline_patterns(
                frame,
                days=len(frame),
                single_candle_lookback=1,
                only_latest_bar=True,
                include_chart_patterns=False,
                legacy_compat_mode=False,
                allow_missing_volume_breakout=False,
            )
            if item.pattern_id in evaluable_set
        ]

    curr_shapes = _shapes_on(df)
    prev_shape_ids = {item.pattern_id for item in _shapes_on(df.iloc[:-1])}
    newly_completed = [item for item in curr_shapes if item.pattern_id not in prev_shape_ids]
    newly_triggered = [
        item for item in newly_completed if not require_volume or item.volume_confirmed is True
    ]

    if newly_triggered:
        matched_ids = [item.pattern_id for item in newly_triggered]
        pattern_ids = ", ".join(matched_ids[:3])
        extra = f" (+{len(matched_ids) - 3})" if len(matched_ids) > 3 else ""
        skipped_note = (
            f" (skipped volume-dependent: {', '.join(unavailable_volume_ids)})"
            if unavailable_volume_ids
            else ""
        )
        return IndicatorEvaluation(
            status="triggered",
            observed_value=latest_close,
            threshold=None,
            message=f"{stock_code} kline pattern triggered: {pattern_ids}{extra} at close {latest_close:.4f}{skipped_note}",
            data_timestamp=latest,
            matched_patterns=matched_ids,
            unavailable_patterns=unavailable_volume_ids or None,
        )

    if unavailable_volume_ids:
        return IndicatorEvaluation(
            status="degraded",
            observed_value=latest_close,
            threshold=None,
            message=(
                f"{stock_code} kline pattern partially degraded: missing volume for "
                f"{', '.join(unavailable_volume_ids)}; no price-only pattern triggered at close {latest_close:.4f}"
            ),
            data_timestamp=latest,
            monitored_patterns=list(params["patterns"]),
            unavailable_patterns=unavailable_volume_ids,
        )

    monitored = ", ".join(params["patterns"][:3])
    extra_monitored = f" (+{len(params['patterns']) - 3})" if len(params["patterns"]) > 3 else ""
    return IndicatorEvaluation(
        status="not_triggered",
        observed_value=latest_close,
        threshold=None,
        message=(
            f"{stock_code} did not trigger kline patterns ({monitored}{extra_monitored}) "
            f"at close {latest_close:.4f}"
        ),
        data_timestamp=latest,
        monitored_patterns=list(params["patterns"]),
    )


def _pattern_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) == 0:
        raise ValueError("patterns must be a non-empty list")
    normalized: list[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"invalid pattern identifier: {item}")
        token = item.strip().lower()
        if not token or token not in ALLOWED_ALERT_PATTERN_TOKENS:
            raise ValueError(f"unsupported kline_pattern token: {item}")
        if token not in seen:
            seen.add(token)
            normalized.append(token)
    return normalized


def _bool_flag(value: Any, field_name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean")


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
    # 与选股、个股分析报告共用同一 Wilder RSI（src/utils/rsi.py），口径一致。
    return wilder_rsi(close, period)


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


def _drop_partial_today(
    df: pd.DataFrame,
    *,
    stock_code: Optional[str] = None,
    now: Optional[datetime] = None,
    drop_undated_last: bool = True,
) -> pd.DataFrame:
    attrs = dict(getattr(df, "attrs", {}) or {})
    market = get_market_for_stock(stock_code) if stock_code else None
    if market in _MARKET_CLOSE_TIMES:
        market_now = get_market_now(market, current_time=now)
        if _XCALS_AVAILABLE:
            effective_date = get_effective_trading_date(market, current_time=now)
        else:
            close_time = _MARKET_CLOSE_TIMES[market]
            effective_date = (
                market_now.date() - timedelta(days=1)
                if market_now.time() < close_time
                else market_now.date()
            )
        if effective_date < market_now.date() and drop_undated_last:
            try:
                parsed_last = pd.to_datetime(df["date"].iloc[-1], errors="coerce")
            except (KeyError, IndexError, TypeError, ValueError, OverflowError):
                res = df.iloc[:-1].copy()
                res.attrs.update(attrs)
                return res
            if pd.isna(parsed_last):
                df = df.iloc[:-1].copy()
                if df.empty:
                    df.attrs.update(attrs)
                    return df
        parsed_dates = pd.to_datetime(df["date"], errors="coerce")
        if isinstance(parsed_dates.dtype, pd.DatetimeTZDtype):
            parsed_dates = parsed_dates.dt.tz_localize(None)
        mask = parsed_dates.isna() | (parsed_dates.dt.date <= effective_date)
        res = df.loc[mask].copy()
        res.attrs.update(attrs)
        return res

    current = now or datetime.now()
    if current.time() >= time(16, 0):
        return df
    try:
        parsed = pd.to_datetime(df["date"].iloc[-1], errors="coerce")
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        if not drop_undated_last:
            return df
        res = df.iloc[:-1].copy()
        res.attrs.update(attrs)
        return res
    if pd.isna(parsed):
        if not drop_undated_last:
            return df
        res = df.iloc[:-1].copy()
        res.attrs.update(attrs)
        return res
    last_date = parsed.date()
    if last_date == current.date():
        res = df.iloc[:-1].copy()
        res.attrs.update(attrs)
        return res
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
