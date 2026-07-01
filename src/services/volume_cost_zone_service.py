from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def build_volume_cost_zone_from_db(
    code: str,
    db_path: str | Path = "data/stock_analysis.db",
    lookback: int = 252,
    bins: int = 12,
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
            select date, close, volume
            from stock_daily
            where upper(code) = ?
            order by date desc
            limit ?
            """,
            (symbol, lookback),
        ).fetchall()

    bars: List[Dict[str, float]] = []
    for date_value, close_value, volume_value in rows:
        close = _safe_float(close_value)
        volume = _safe_float(volume_value)
        if close is None or volume is None or close <= 0 or volume <= 0:
            continue
        bars.append({"date": str(date_value), "close": close, "volume": volume})

    if len(bars) < 60:
        return {
            "status": "insufficient",
            "reason": f"历史成交数据不足，仅{len(bars)}条",
            "sample_days": len(bars),
        }

    bars = list(reversed(bars))
    current_price = bars[-1]["close"]
    min_price = min(item["close"] for item in bars)
    max_price = max(item["close"] for item in bars)
    total_volume = sum(item["volume"] for item in bars)

    if max_price <= min_price or total_volume <= 0:
        return {"status": "insufficient", "reason": "价格或成交量数据不足", "sample_days": len(bars)}

    bin_width = (max_price - min_price) / bins
    bucket_volume = [0.0 for _ in range(bins)]

    weighted_sum = 0.0
    for item in bars:
        idx = int((item["close"] - min_price) / bin_width)
        idx = max(0, min(bins - 1, idx))
        bucket_volume[idx] += item["volume"]
        weighted_sum += item["close"] * item["volume"]

    avg_cost = weighted_sum / total_volume
    ranked = sorted(range(bins), key=lambda i: bucket_volume[i], reverse=True)

    selected = []
    acc = 0.0
    for idx in ranked:
        selected.append(idx)
        acc += bucket_volume[idx]
        if acc / total_volume >= 0.70:
            break

    low_idx = min(selected)
    high_idx = max(selected)
    main_low = min_price + low_idx * bin_width
    main_high = min_price + (high_idx + 1) * bin_width

    support_candidates = [
        (i, bucket_volume[i])
        for i in range(bins)
        if min_price + (i + 1) * bin_width < current_price
    ]
    resistance_candidates = [
        (i, bucket_volume[i])
        for i in range(bins)
        if min_price + i * bin_width > current_price
    ]

    support = None
    if support_candidates:
        i = max(support_candidates, key=lambda x: x[1])[0]
        support = (min_price + i * bin_width, min_price + (i + 1) * bin_width)

    resistance = None
    if resistance_candidates:
        i = max(resistance_candidates, key=lambda x: x[1])[0]
        resistance = (min_price + i * bin_width, min_price + (i + 1) * bin_width)

    if current_price < main_low:
        position = "低于主要成交成本区，偏弱"
    elif current_price > main_high:
        position = "高于主要成交成本区，偏强但需防回落"
    else:
        position = "位于主要成交成本区内，震荡消化"

    return {
        "status": "ok",
        "method": "近一年日线成交量按价格区间加权估算",
        "sample_days": len(bars),
        "current_price": round(current_price, 2),
        "avg_cost": round(avg_cost, 2),
        "main_cost_low": round(main_low, 2),
        "main_cost_high": round(main_high, 2),
        "support_low": round(support[0], 2) if support else None,
        "support_high": round(support[1], 2) if support else None,
        "resistance_low": round(resistance[0], 2) if resistance else None,
        "resistance_high": round(resistance[1], 2) if resistance else None,
        "position": position,
        "note": "这是成交量成本区估算，不等同于A股筹码分布。",
    }
