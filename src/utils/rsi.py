# -*- coding: utf-8 -*-
"""Shared Wilder RSI used by screening, alerts and the stock analysis report.

One implementation so the three entry points always classify the same bars the
same way. Wilder smoothing is seeded with the simple mean of the first
``period`` changes, as in TA-Lib and common charting tools (computed by
``fin-primitives`` when installed, with a bit-equivalent pure-NumPy fallback
so environments missing the compiled extension remain functional).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext
import logging

import numpy as np
import pandas as pd

try:
    import fin_primitives as fp
except ImportError:  # pragma: no cover - exercised via fallback tests
    fp = None

logger = logging.getLogger(__name__)
NEUTRAL_RSI = 50.0
_FALLBACK_WARNED = False
# rust_decimal::Decimal max integer mantissa (2**96 - 1) and max fractional scale (28).
_RUST_DECIMAL_MAX = Decimal("79228162514264337593543950335")


def _quantize_rust_decimal(value: Decimal, *, overflow_message: str) -> Decimal:
    """Round a Decimal to rust_decimal's 96-bit / <=28-decimal-place representation."""
    magnitude = abs(value)
    if magnitude > _RUST_DECIMAL_MAX:
        raise ValueError(overflow_message)
    if value == 0:
        return Decimal(0)
    adj = magnitude.adjusted()
    scale = 28 if adj < 0 else max(0, 28 - adj)
    if scale > 0 and (magnitude * Decimal(1).scaleb(scale)).to_integral_value(ROUND_HALF_EVEN) > _RUST_DECIMAL_MAX:
        scale -= 1
    return value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)


def _float_to_rust_decimal(val: float, *, idx: int) -> Decimal:
    """Convert a finite close price using rust_decimal input bounds (fail on underflow to zero)."""
    if val == 0.0:
        return Decimal(0)
    d = Decimal(str(float(val)))
    overflow_message = (
        f"close[{idx}] = {val!r} is out of the Decimal range (28 decimal places, |x| < 7.9e28)"
    )
    magnitude = abs(d)
    if magnitude > _RUST_DECIMAL_MAX:
        raise ValueError(overflow_message)
    adj = magnitude.adjusted()
    scale = 28 if adj < 0 else max(0, 28 - adj)
    if scale > 0 and (magnitude * Decimal(1).scaleb(scale)).to_integral_value(ROUND_HALF_UP) > _RUST_DECIMAL_MAX:
        scale -= 1
    quantized = d.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    if quantized == 0:
        raise ValueError(overflow_message)
    return quantized


def _warn_fallback_once() -> None:
    global _FALLBACK_WARNED
    if _FALLBACK_WARNED:
        return
    _FALLBACK_WARNED = True
    logger.warning(
        "fin_primitives is not installed; falling back to pure-NumPy Wilder RSI. "
        "Run 'pip install -r requirements.txt' to enable native acceleration."
    )


def _wilder_rsi_numpy_fallback(close: pd.Series, period: int) -> pd.Series:
    """Compute TA-Lib / fin-primitives compatible Wilder RSI without C extension drift."""
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    arr = close.to_numpy(dtype="float64", copy=False)
    n = len(arr)
    invalid = ~np.isfinite(arr)
    if invalid.any():
        bad = int(np.flatnonzero(invalid)[0])
        bad_val = arr[bad]
        label = "NaN" if np.isnan(bad_val) else ("inf" if bad_val > 0 else "-inf")
        raise ValueError(f"close[{bad}] is {label}; drop or fill missing values first")

    out = np.full(n, np.nan, dtype="float64")
    with localcontext() as ctx:
        ctx.prec = 60
        ctx.rounding = ROUND_HALF_EVEN
        prices = [
            _float_to_rust_decimal(float(val), idx=idx)
            for idx, val in enumerate(arr)
        ]
        if n <= period:
            return pd.Series(out, index=close.index, dtype="float64")
        zero = Decimal(0)
        one = Decimal(1)
        hundred = Decimal(100)
        dp = Decimal(period)
        keep = Decimal(period - 1)
        overflow_msg = "Arithmetic overflow in financial calculation"

        def _q(val: Decimal) -> Decimal:
            return _quantize_rust_decimal(val, overflow_message=overflow_msg)

        deltas = [_q(prices[i] - prices[i - 1]) for i in range(1, n)]
        gains = [d if d > zero else zero for d in deltas]
        losses = [-d if d < zero else zero for d in deltas]

        sum_gain = zero
        sum_loss = zero
        for g, l in zip(gains[:period], losses[:period]):
            sum_gain = _q(sum_gain + g)
            sum_loss = _q(sum_loss + l)
        avg_gain = _q(sum_gain / dp)
        avg_loss = _q(sum_loss / dp)
        if avg_loss == zero:
            out[period] = 100.0
        else:
            rs = _q(avg_gain / avg_loss)
            out[period] = float(_q(hundred - _q(hundred / _q(one + rs))))

        for i in range(period + 1, n):
            avg_gain = _q(_q(_q(avg_gain * keep) + gains[i - 1]) / dp)
            avg_loss = _q(_q(_q(avg_loss * keep) + losses[i - 1]) / dp)
            if avg_loss == zero:
                out[i] = 100.0
            else:
                rs = _q(avg_gain / avg_loss)
                out[i] = float(_q(hundred - _q(hundred / _q(one + rs))))

    return pd.Series(out, index=close.index, dtype="float64")


def wilder_rsi(close: pd.Series, period: int, *, fill_warmup: bool = True) -> pd.Series:
    """Wilder RSI aligned to ``close``.

    Bars where the price has not moved at all yet are ``50.0`` (neutral).
    Bars before the first full ``period`` of changes have no RSI: they are
    ``50.0`` when ``fill_warmup`` is true (the previous ``fillna(50)``
    behaviour, used for display and scoring) and ``NaN`` otherwise, so edge
    checks such as alert crossings never compare against a placeholder.
    """
    close = pd.Series(close, dtype="float64")
    if fp is not None:
        values = pd.Series(fp.rsi(close, period), dtype="float64")
    else:
        _warn_fallback_once()
        values = _wilder_rsi_numpy_fallback(close, period)
    values.index = close.index
    no_move_yet = close.diff().abs().fillna(0).cumsum().eq(0)
    values = values.mask(no_move_yet & values.notna(), NEUTRAL_RSI)
    return values.fillna(NEUTRAL_RSI) if fill_warmup else values
