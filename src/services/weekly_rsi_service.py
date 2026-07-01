from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isfinite(number):
            return number
    except Exception:
        pass
    return None


def _relation(value: float, threshold: float) -> str:
    diff = value - threshold
    if abs(diff) < 0.05:
        return f"接近 {threshold:.0f}"
    if diff > 0:
        return f"高于 {threshold:.0f}（+{diff:.2f}）"
    return f"低于 {threshold:.0f}（{diff:.2f}）"


def _interpret_rsi(value: float) -> str:
    if value < 30:
        return "周线RSI低于30，处于超卖区，反弹观察价值上升，但仍需价格止跌确认"
    if value < 50:
        return "周线RSI位于30-50之间，中期动能偏弱，属于弱势修复区"
    if value < 70:
        return "周线RSI位于50-70之间，中期动能中性偏强"
    return "周线RSI高于70，处于超买区，需防止高位回落"


def build_weekly_rsi_from_db(
    code: str,
    db_path: str | Path = "data/stock_analysis.db",
    period: int = 14,
    lookback_daily_rows: int = 520,
) -> Dict[str, Any]:
    symbol = str(code or "").strip().upper()
    if not symbol:
        return {"status": "missing", "reason": "empty_symbol"}

    path = Path(db_path)
    if not path.exists():
        return {"status": "missing", "reason": "database_not_found"}

    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute(
            """
            select date, close
            from stock_daily
            where upper(code) = ?
            order by date desc
            limit ?
            """,
            (symbol, lookback_daily_rows),
        ).fetchall()

    data = []
    for date_value, close_value in rows:
        close = _safe_float(close_value)
        if close is None or close <= 0:
            continue
        data.append({"date": str(date_value), "close": close})

    if len(data) < period * 5:
        return {
            "status": "insufficient",
            "reason": f"日线数据不足，仅{len(data)}条",
            "daily_rows": len(data),
        }

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")

    weekly_close = df["close"].resample("W-FRI").last().dropna()
    if len(weekly_close) < period + 2:
        return {
            "status": "insufficient",
            "reason": f"周线数据不足，仅{len(weekly_close)}条",
            "weekly_bars": len(weekly_close),
        }

    delta = weekly_close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.dropna()

    if rsi.empty:
        return {"status": "insufficient", "reason": "RSI计算结果为空"}

    current = float(rsi.iloc[-1])
    previous = float(rsi.iloc[-2]) if len(rsi) >= 2 else None
    trend = "持平"
    if previous is not None:
        if current > previous + 0.2:
            trend = "回升"
        elif current < previous - 0.2:
            trend = "回落"

    return {
        "status": "ok",
        "period": period,
        "week_date": weekly_close.index[-1].date().isoformat(),
        "weekly_bars": int(len(weekly_close)),
        "current_rsi": round(current, 2),
        "previous_rsi": round(previous, 2) if previous is not None else None,
        "trend": trend,
        "vs_30": _relation(current, 30),
        "vs_50": _relation(current, 50),
        "vs_70": _relation(current, 70),
        "interpretation": _interpret_rsi(current),
    }
