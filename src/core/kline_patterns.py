# -*- coding: utf-8 -*-
"""Unified deterministic K-line candlestick and chart pattern engine.

Shared across:
- Agent tools (`analyze_pattern`)
- Trend analyzer (`StockTrendAnalyzer` / report prompts)
- Technical alert monitoring (`AlertService` / `alert_indicators`)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


@dataclass(frozen=True)
class PatternSpec:
    """Static definition and metadata for a supported candlestick/chart pattern."""

    pattern_id: str
    name: str
    name_zh: str
    name_en: str
    type: str
    direction: str  # bullish | bearish | neutral
    category: str   # single_candle | multi_candle | ma_pattern | chart
    default_strength: str  # 强 | 中 | 弱
    alertable: bool
    min_bars: int
    description_zh: str
    description_en: str


@dataclass
class DetectedPattern:
    """Concrete pattern occurrence detected on a price history series."""

    pattern_id: str
    pattern: str
    name_zh: str
    name_en: str
    type: str
    direction: str
    category: str
    day_offset: int
    completed_bar_offset: int
    strength: str
    desc: str
    trigger_date: Optional[str] = None
    volume_confirmed: Optional[bool] = None
    volume_ratio: Optional[float] = None
    key_levels: Dict[str, float] = field(default_factory=dict)
    invalidation_level: Optional[float] = None

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Preserve the 5-key item shape expected by legacy analyze_pattern consumers."""
        return {
            "pattern": self.pattern,
            "type": self.type,
            "day_offset": int(self.day_offset),
            "strength": self.strength,
            "desc": self.desc,
        }

    def to_detail_dict(self) -> Dict[str, Any]:
        """Return structured JSON-safe metadata with native Python primitives."""
        payload = self.to_legacy_dict()
        payload.update({
            "pattern_id": self.pattern_id,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "direction": self.direction,
            "category": self.category,
            "completed_bar_offset": int(self.completed_bar_offset),
            "trigger_date": self.trigger_date,
            "volume_confirmed": (
                None if self.volume_confirmed is None else bool(self.volume_confirmed)
            ),
            "volume_ratio": (
                None if self.volume_ratio is None else round(float(self.volume_ratio), 2)
            ),
            "key_levels": {
                str(k): round(float(v), 4)
                for k, v in self.key_levels.items()
                if _is_finite_positive(v)
            },
            "invalidation_level": (
                None
                if self.invalidation_level is None or not math.isfinite(float(self.invalidation_level))
                else round(float(self.invalidation_level), 4)
            ),
        })
        return payload


_PATTERN_SPEC_LIST: Tuple[PatternSpec, ...] = (
    # ---- Alertable bullish patterns ----
    PatternSpec(
        pattern_id="red_three_soldiers",
        name="红三兵 (Three White Soldiers)",
        name_zh="红三兵",
        name_en="Three White Soldiers",
        type="bullish_continuation",
        direction="bullish",
        category="multi_candle",
        default_strength="强",
        alertable=True,
        min_bars=8,
        description_zh="连续三根实体阳线步步高收且上影受控，多头动能稳步推进",
        description_en="Three consecutive solid bullish candles closing progressively higher",
    ),
    PatternSpec(
        pattern_id="immortal_guide",
        name="仙人指路 (Immortal Guide)",
        name_zh="仙人指路",
        name_en="Immortal Guide",
        type="bullish_continuation",
        direction="bullish",
        category="single_candle",
        default_strength="强",
        alertable=True,
        min_bars=26,
        description_zh="上升趋势且 MA20 上行背景下放量长上影试盘回落，关注后续突破确认",
        description_en="High-volume upper-shadow upside probe above rising MA20 in an advance",
    ),
    PatternSpec(
        pattern_id="rising_lotus",
        name="出水芙蓉 (Rising Lotus)",
        name_zh="出水芙蓉",
        name_en="Rising Lotus",
        type="bullish_breakout",
        direction="bullish",
        category="ma_pattern",
        default_strength="强",
        alertable=True,
        min_bars=20,
        description_zh="阳线实体自下而上一举上穿 MA5/MA10/MA20 三条均线，短中期结构转强",
        description_en="Strong bullish body crossing upward through MA5, MA10, and MA20",
    ),
    PatternSpec(
        pattern_id="bullish_cannon",
        name="多方炮 (Bullish Cannon)",
        name_zh="多方炮",
        name_en="Bullish Cannon",
        type="bullish_continuation",
        direction="bullish",
        category="multi_candle",
        default_strength="强",
        alertable=True,
        min_bars=8,
        description_zh="两阳夹一阴洗盘蓄势后再放阳上攻，多头反包突破结构",
        description_en="Two strong bullish bars bracketing a bounded bearish pullback",
    ),
    PatternSpec(
        pattern_id="morning_star",
        name="早晨之星 (Morning Star)",
        name_zh="早晨之星",
        name_en="Morning Star",
        type="bullish_reversal",
        direction="bullish",
        category="multi_candle",
        default_strength="强",
        alertable=True,
        min_bars=8,
        description_zh="三根K线底部反转形态",
        description_en="Three-candle bullish bottom reversal pattern",
    ),
    PatternSpec(
        pattern_id="bullish_engulfing",
        name="看涨吞没 (Bullish Engulfing)",
        name_zh="看涨吞没",
        name_en="Bullish Engulfing",
        type="bullish_reversal",
        direction="bullish",
        category="multi_candle",
        default_strength="强",
        alertable=True,
        min_bars=4,
        description_zh="阳线完全覆盖前一阴线",
        description_en="Bullish candle completely engulfs prior bearish body",
    ),
    PatternSpec(
        pattern_id="piercing_line",
        name="曙光初现 (Piercing Line)",
        name_zh="曙光初现",
        name_en="Piercing Line",
        type="bullish_reversal",
        direction="bullish",
        category="multi_candle",
        default_strength="中",
        alertable=True,
        min_bars=12,
        description_zh="下跌后低开于前阴收盘下方并高走收复前阴实体半数以上，潜在止跌信号",
        description_en="After a decline, bullish candle opens below prior close and closes past prior midpoint",
    ),
    PatternSpec(
        pattern_id="hammer",
        name="锤子线 (Hammer)",
        name_zh="锤子线",
        name_en="Hammer",
        type="reversal_signal",
        direction="bullish",
        category="single_candle",
        default_strength="中",
        alertable=True,
        min_bars=11,
        description_zh="下影线长，潜在支撑/反转",
        description_en="Long lower shadow after a decline signaling potential support/reversal",
    ),
    PatternSpec(
        pattern_id="breakout_20d_high",
        name="放量突破20日高点",
        name_zh="放量突破20日高点",
        name_en="20D High Volume Breakout",
        type="bullish_breakout",
        direction="bullish",
        category="chart",
        default_strength="强",
        alertable=True,
        min_bars=21,
        description_zh="收盘突破近20日最高，量能配合",
        description_en="Close breaks above 20-day high with volume expansion",
    ),
    PatternSpec(
        pattern_id="ma_pullback_support",
        name="缩量回踩均线 (MA Pullback Support)",
        name_zh="缩量回踩均线",
        name_en="Low-Volume MA Pullback",
        type="bullish_continuation",
        direction="bullish",
        category="ma_pattern",
        default_strength="中",
        alertable=True,
        min_bars=20,
        description_zh="多头均线排列下缩量精准回踩 MA10/MA20 区间并守住支撑",
        description_en="Shrinking-volume pullback to MA10/MA20 support band in an uptrend",
    ),
    # ---- Alertable bearish / risk patterns ----
    PatternSpec(
        pattern_id="three_black_crows",
        name="三只乌鸦 (Three Black Crows)",
        name_zh="三只乌鸦",
        name_en="Three Black Crows",
        type="bearish_reversal",
        direction="bearish",
        category="multi_candle",
        default_strength="强",
        alertable=True,
        min_bars=13,
        description_zh="上涨趋势或高位阶段出现连续三根实体阴线逐日走低，警惕见顶转弱",
        description_en="Three consecutive solid bearish candles after an advance signaling top reversal",
    ),
    PatternSpec(
        pattern_id="guillotine",
        name="断头铡刀 (Guillotine)",
        name_zh="断头铡刀",
        name_en="Guillotine",
        type="bearish_signal",
        direction="bearish",
        category="ma_pattern",
        default_strength="强",
        alertable=True,
        min_bars=20,
        description_zh="阴线实体自上而下一举跌破 MA5/MA10/MA20 三条均线，警惕中期破位风险",
        description_en="Heavy bearish body slicing downward through MA5, MA10, and MA20",
    ),
    PatternSpec(
        pattern_id="evening_star",
        name="黄昏之星 (Evening Star)",
        name_zh="黄昏之星",
        name_en="Evening Star",
        type="bearish_reversal",
        direction="bearish",
        category="multi_candle",
        default_strength="强",
        alertable=True,
        min_bars=8,
        description_zh="三根K线顶部反转形态",
        description_en="Three-candle bearish top reversal pattern",
    ),
    PatternSpec(
        pattern_id="bearish_engulfing",
        name="看跌吞没 (Bearish Engulfing)",
        name_zh="看跌吞没",
        name_en="Bearish Engulfing",
        type="bearish_reversal",
        direction="bearish",
        category="multi_candle",
        default_strength="强",
        alertable=True,
        min_bars=4,
        description_zh="阴线完全覆盖前一阳线",
        description_en="Bearish candle completely engulfs prior bullish body",
    ),
    PatternSpec(
        pattern_id="dark_cloud_cover",
        name="乌云盖顶 (Dark Cloud Cover)",
        name_zh="乌云盖顶",
        name_en="Dark Cloud Cover",
        type="bearish_reversal",
        direction="bearish",
        category="multi_candle",
        default_strength="中",
        alertable=True,
        min_bars=12,
        description_zh="上涨后高开于前阳收盘上方并低走深入前阳实体二分之一以下，警惕见顶",
        description_en="After an advance, bearish candle opens above prior close and closes past prior midpoint",
    ),
    PatternSpec(
        pattern_id="shooting_star",
        name="流星线 (Shooting Star)",
        name_zh="流星线",
        name_en="Shooting Star",
        type="bearish_signal",
        direction="bearish",
        category="single_candle",
        default_strength="中",
        alertable=True,
        min_bars=11,
        description_zh="上影线长，潜在压力/反转",
        description_en="Long upper shadow after an advance signaling potential resistance/top reversal",
    ),
    PatternSpec(
        pattern_id="hanging_man",
        name="上吊线 (Hanging Man)",
        name_zh="上吊线",
        name_en="Hanging Man",
        type="reversal_signal",
        direction="bearish",
        category="single_candle",
        default_strength="中",
        alertable=True,
        min_bars=11,
        description_zh="下影线长，上涨后的潜在见顶",
        description_en="Long lower shadow after an advance signaling potential topping risk",
    ),
    # ---- Context-only / chart patterns ----
    PatternSpec(
        pattern_id="inverted_hammer",
        name="倒锤子",
        name_zh="倒锤子",
        name_en="Inverted Hammer",
        type="reversal_signal",
        direction="bullish",
        category="single_candle",
        default_strength="中",
        alertable=False,
        min_bars=11,
        description_zh="上影线长，下跌后的潜在反转",
        description_en="Long upper shadow after a decline signaling potential bottom reversal",
    ),
    PatternSpec(
        pattern_id="doji",
        name="十字星 (Doji)",
        name_zh="十字星",
        name_en="Doji",
        type="reversal_signal",
        direction="neutral",
        category="single_candle",
        default_strength="弱",
        alertable=False,
        min_bars=3,
        description_zh="多空平衡，可能变盘信号",
        description_en="Small body balancing buyers and sellers; watch next bar direction",
    ),
    PatternSpec(
        pattern_id="big_bullish_candle",
        name="大阳线",
        name_zh="大阳线",
        name_en="Big Bullish Candle",
        type="bullish",
        direction="bullish",
        category="single_candle",
        default_strength="强",
        alertable=False,
        min_bars=3,
        description_zh="实体大，方向明确",
        description_en="Large bullish candle body indicating strong upward momentum",
    ),
    PatternSpec(
        pattern_id="big_bearish_candle",
        name="大阴线",
        name_zh="大阴线",
        name_en="Big Bearish Candle",
        type="bearish",
        direction="bearish",
        category="single_candle",
        default_strength="强",
        alertable=False,
        min_bars=3,
        description_zh="实体大，方向明确",
        description_en="Large bearish candle body indicating strong downward momentum",
    ),
    PatternSpec(
        pattern_id="double_bottom",
        name="双底 (Double Bottom)",
        name_zh="双底",
        name_en="Double Bottom",
        type="bullish_reversal",
        direction="bullish",
        category="chart",
        default_strength="强",
        alertable=False,
        min_bars=10,
        description_zh="两个相近低点，W型底部形态",
        description_en="Two comparable troughs forming a W-shaped bottom structure",
    ),
    PatternSpec(
        pattern_id="double_top",
        name="双顶 (Double Top)",
        name_zh="双顶",
        name_en="Double Top",
        type="bearish_reversal",
        direction="bearish",
        category="chart",
        default_strength="强",
        alertable=False,
        min_bars=10,
        description_zh="两个相近高点且中间回撤后有效跌破颈线，M头破位反转形态",
        description_en="Two comparable peaks separated by a trough followed by neckline breakdown",
    ),
    PatternSpec(
        pattern_id="box_consolidation",
        name="箱体震荡",
        name_zh="箱体震荡",
        name_en="Box Consolidation",
        type="consolidation",
        direction="neutral",
        category="chart",
        default_strength="中",
        alertable=False,
        min_bars=10,
        description_zh="近10日波幅较窄，价格在区间内震荡",
        description_en="Narrow 10-day range consolidation",
    ),
)

PATTERN_SPECS: Dict[str, PatternSpec] = {spec.pattern_id: spec for spec in _PATTERN_SPEC_LIST}
ALL_PATTERN_IDS: frozenset[str] = frozenset(PATTERN_SPECS.keys())
LEGACY_PATTERN_IDS: frozenset[str] = frozenset({
    "doji",
    "hammer",
    "hanging_man",
    "inverted_hammer",
    "shooting_star",
    "big_bullish_candle",
    "big_bearish_candle",
    "morning_star",
    "evening_star",
    "bullish_engulfing",
    "bearish_engulfing",
    "double_bottom",
    "breakout_20d_high",
    "box_consolidation",
})
VOLUME_DEPENDENT_PATTERN_IDS: frozenset[str] = frozenset({
    "immortal_guide",
    "breakout_20d_high",
    "ma_pullback_support",
})
ALERTABLE_PATTERN_IDS: Tuple[str, ...] = tuple(
    spec.pattern_id for spec in _PATTERN_SPEC_LIST if spec.alertable
)
ALERTABLE_BULLISH_PATTERN_IDS: Tuple[str, ...] = tuple(
    spec.pattern_id for spec in _PATTERN_SPEC_LIST if spec.alertable and spec.direction == "bullish"
)
ALERTABLE_BEARISH_PATTERN_IDS: Tuple[str, ...] = tuple(
    spec.pattern_id for spec in _PATTERN_SPEC_LIST if spec.alertable and spec.direction == "bearish"
)
ALERT_PATTERN_PRESETS: Dict[str, Tuple[str, ...]] = {
    "any_bullish": ALERTABLE_BULLISH_PATTERN_IDS,
    "any_bearish": ALERTABLE_BEARISH_PATTERN_IDS,
}
ALLOWED_ALERT_PATTERN_TOKENS: frozenset[str] = (
    frozenset(ALERTABLE_PATTERN_IDS) | frozenset(ALERT_PATTERN_PRESETS.keys())
)
BULLISH_PATTERN_IDS: frozenset[str] = frozenset(
    spec.pattern_id for spec in _PATTERN_SPEC_LIST if spec.direction == "bullish"
)
BEARISH_PATTERN_IDS: frozenset[str] = frozenset(
    spec.pattern_id for spec in _PATTERN_SPEC_LIST if spec.direction == "bearish"
)
_SINGLE_BAR_PATTERN_IDS: frozenset[str] = frozenset(
    spec.pattern_id for spec in _PATTERN_SPEC_LIST if spec.category in {"single_candle", "ma_pattern"}
)
_MULTI_BAR_PATTERN_IDS: frozenset[str] = frozenset(
    spec.pattern_id for spec in _PATTERN_SPEC_LIST if spec.category == "multi_candle"
)


def _is_finite_positive(value: Any) -> bool:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(num) and num > 0.0


def _valid_ohlc(oi: float, hi: float, li: float, ci: float) -> bool:
    return (
        _is_finite_positive(oi)
        and _is_finite_positive(hi)
        and _is_finite_positive(li)
        and _is_finite_positive(ci)
        and hi >= li
        and hi >= max(oi, ci)
        and li <= min(oi, ci)
    )


def _find_col(df: pd.DataFrame, canonical: str) -> Optional[Any]:
    aliases = {
        "date": ("date", "trade_date", "datetime", "time", "日期", "交易日期"),
        "open": ("open", "open_price", "开盘", "开盘价"),
        "high": ("high", "high_price", "最高", "最高价"),
        "low": ("low", "low_price", "最低", "最低价"),
        "close": ("close", "close_price", "收盘", "收盘价"),
        "volume": ("volume", "vol", "成交量"),
    }
    by_norm = {str(col).strip().lower(): col for col in df.columns}
    for candidate in aliases[canonical]:
        found = by_norm.get(candidate.lower())
        if found is not None:
            return found
    return None


def _to_float_array(series: pd.Series) -> List[float]:
    numeric = pd.to_numeric(series, errors="coerce")
    return [float(val) if pd.notna(val) else float("nan") for val in numeric.tolist()]


def parse_iso_date_value(raw: Any) -> Optional[str]:
    """Parse a scalar date-like value strictly into ``YYYY-MM-DD`` or ``None``."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        if pd.isna(raw):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()

    if isinstance(raw, (int, float)):
        if not math.isfinite(float(raw)):
            return None
        if isinstance(raw, float) and not raw.is_integer():
            return None
        text_num = str(int(raw))
        if not re.fullmatch(r"\d{8}", text_num):
            return None
        try:
            return datetime.strptime(text_num, "%Y%m%d").date().isoformat()
        except ValueError:
            return None

    text = str(raw).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _extract_dates(df: pd.DataFrame) -> List[Optional[str]]:
    date_col = _find_col(df, "date")
    if date_col is not None:
        raw_values = df[date_col].tolist()
    elif isinstance(df.index, pd.DatetimeIndex):
        raw_values = df.index.to_pydatetime().tolist()
    else:
        return [None] * len(df)
    return [parse_iso_date_value(raw) for raw in raw_values]


def _trend_direction_before(history_close: Sequence[float], end_idx: int) -> Tuple[bool, bool]:
    """Check strictly finite 10-bar MA5 vs MA10 trend before ``end_idx``."""
    if end_idx < 10:
        return False, False
    before = history_close[end_idx - 10:end_idx]
    if len(before) < 10 or not all(math.isfinite(float(x)) for x in before):
        return False, False
    ma5 = sum(before[5:]) / 5.0
    ma10 = sum(before) / 10.0
    prev_close = float(before[-1])
    if math.isclose(ma5, ma10) or math.isclose(prev_close, ma5):
        return False, False
    return (ma5 < ma10 and prev_close < ma5), (ma5 > ma10 and prev_close > ma5)


def _rolling_sma_at(values: Sequence[float], idx: int, window: int) -> Optional[float]:
    if idx + 1 < window or idx >= len(values):
        return None
    segment = values[idx + 1 - window:idx + 1]
    if not all(_is_finite_positive(v) for v in segment):
        return None
    return sum(float(v) for v in segment) / float(window)


def _trailing_avg_body(
    full_o: Sequence[float],
    full_h: Sequence[float],
    full_l: Sequence[float],
    full_c: Sequence[float],
    ref_idx: int,
    *,
    window: int = 20,
    min_samples: int = 5,
) -> Optional[float]:
    """Compute causal mean body size strictly over valid bars before ``ref_idx``."""
    if ref_idx <= 0:
        return None
    start = max(0, ref_idx - window)
    bodies = [
        abs(full_c[k] - full_o[k])
        for k in range(start, ref_idx)
        if _valid_ohlc(full_o[k], full_h[k], full_l[k], full_c[k])
    ]
    if len(bodies) < min_samples:
        return None
    return sum(bodies) / float(len(bodies))


def _volume_ratio_at(
    full_v: Optional[Sequence[float]],
    full_idx: int,
    window: int = 5,
    *,
    strict: bool = False,
) -> Optional[float]:
    if full_v is None or full_idx < 1 or full_idx >= len(full_v):
        return None
    curr_vol = float(full_v[full_idx])
    if not _is_finite_positive(curr_vol):
        return None
    if strict:
        if full_idx < window:
            return None
        prev_window = full_v[full_idx - window:full_idx]
        if len(prev_window) < window or not all(_is_finite_positive(x) for x in prev_window):
            return None
        avg_prev = sum(float(x) for x in prev_window) / float(window)
        return curr_vol / avg_prev if avg_prev > 0.0 else None

    start = max(0, full_idx - window)
    prev_slice = [float(x) for x in full_v[start:full_idx] if _is_finite_positive(x)]
    if not prev_slice:
        return None
    avg_prev = sum(prev_slice) / float(len(prev_slice))
    return curr_vol / avg_prev if avg_prev > 0.0 else None


def _build_detected(
    pattern_id: str,
    *,
    day_offset: int,
    completed_bar_offset: int,
    trigger_date: Optional[str],
    desc: Optional[str] = None,
    strength: Optional[str] = None,
    type_override: Optional[str] = None,
    volume_confirmed: Optional[bool] = None,
    volume_ratio: Optional[float] = None,
    key_levels: Optional[Dict[str, float]] = None,
    invalidation_level: Optional[float] = None,
) -> DetectedPattern:
    spec = PATTERN_SPECS[pattern_id]
    return DetectedPattern(
        pattern_id=spec.pattern_id,
        pattern=spec.name,
        name_zh=spec.name_zh,
        name_en=spec.name_en,
        type=type_override or spec.type,
        direction=spec.direction,
        category=spec.category,
        day_offset=int(day_offset),
        completed_bar_offset=int(completed_bar_offset),
        strength=strength or spec.default_strength,
        desc=desc or spec.description_zh,
        trigger_date=trigger_date,
        volume_confirmed=volume_confirmed,
        volume_ratio=volume_ratio,
        key_levels=dict(key_levels or {}),
        invalidation_level=invalidation_level,
    )


def resolve_alert_pattern_ids(patterns: Sequence[str]) -> List[str]:
    """Expand preset names and validate alert pattern identifiers."""
    if not isinstance(patterns, (list, tuple)) or len(patterns) == 0:
        raise ValueError("patterns must be a non-empty list")

    resolved: List[str] = []
    seen = set()
    for raw in patterns:
        if not isinstance(raw, str):
            raise ValueError(f"invalid pattern identifier: {raw}")
        token = raw.strip().lower()
        if token not in ALLOWED_ALERT_PATTERN_TOKENS:
            raise ValueError(f"unsupported kline_pattern token: {raw}")
        expanded = ALERT_PATTERN_PRESETS.get(token, (token,))
        for item in expanded:
            if item not in seen:
                seen.add(item)
                resolved.append(item)
    return resolved


def required_bars_for_alert_patterns(patterns: Sequence[str]) -> int:
    """Compute closed bars required so both sides of a daily edge can be evaluated."""
    resolved = resolve_alert_pattern_ids(patterns)
    max_min_bars = max(PATTERN_SPECS[pid].min_bars for pid in resolved)
    return max(22, max_min_bars + 1)


def normalize_pattern_filter(raw_filter: Optional[Any]) -> Optional[frozenset[str]]:
    """Parse optional pattern_filter argument into canonical pattern_ids.

    Supports ``"bullish"``, ``"bearish"``, ``"any_bullish"``, ``"any_bearish"``,
    comma-separated pattern_ids, or a sequence of strings.
    """
    if raw_filter is None:
        return None
    if isinstance(raw_filter, str):
        stripped = raw_filter.strip()
        if not stripped or stripped.lower() in {"all", "*"}:
            return None
        tokens = [part.strip().lower() for part in stripped.split(",") if part.strip()]
    elif isinstance(raw_filter, Iterable):
        tokens = [str(part).strip().lower() for part in raw_filter if str(part).strip()]
    else:
        raise ValueError(f"invalid pattern_filter: {raw_filter}")

    if not tokens:
        return None

    selected: set[str] = set()
    for token in tokens:
        if token == "bullish":
            selected.update(BULLISH_PATTERN_IDS)
        elif token == "bearish":
            selected.update(BEARISH_PATTERN_IDS)
        elif token in ALERT_PATTERN_PRESETS:
            selected.update(ALERT_PATTERN_PRESETS[token])
        elif token in PATTERN_SPECS:
            selected.add(token)
        else:
            raise ValueError(f"unsupported pattern_filter token: {token}")
    return frozenset(selected)


def summarize_detected_patterns(patterns: Sequence[DetectedPattern]) -> Dict[str, Any]:
    """Compute counts, dominant bias, and concise summary string."""
    bullish_count = sum(1 for p in patterns if p.direction == "bullish")
    bearish_count = sum(1 for p in patterns if p.direction == "bearish")
    neutral_count = sum(1 for p in patterns if p.direction == "neutral")
    if bullish_count > bearish_count:
        dominant_bias = "bullish"
    elif bearish_count > bullish_count:
        dominant_bias = "bearish"
    elif bullish_count > 0 or bearish_count > 0 or neutral_count > 0:
        dominant_bias = "neutral"
    else:
        dominant_bias = "none"

    summary = "未发现明显形态" if not patterns else "、".join(p.pattern for p in patterns)
    return {
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "dominant_bias": dominant_bias,
        "summary": summary,
    }


def _find_local_peak_pivots(
    h: Sequence[float],
    valid_bar: Any,
    n: int,
) -> List[Tuple[int, int]]:
    """Collect separated local peak plateaus as ``(start_idx, end_idx)`` intervals."""
    pivots: List[Tuple[int, int]] = []
    k = 1
    while k < n - 1:
        if not valid_bar(k):
            k += 1
            continue
        run_end = k
        while (
            run_end + 1 < n - 1
            and valid_bar(run_end + 1)
            and math.isclose(h[run_end + 1], h[k], rel_tol=1e-6)
        ):
            run_end += 1
        left_idx = k - 1
        right_idx = run_end + 1
        if (
            valid_bar(left_idx)
            and valid_bar(right_idx)
            and h[k] > h[left_idx]
            and h[run_end] > h[right_idx]
        ):
            pivots.append((k, run_end))
        k = run_end + 1
    return pivots


def detect_kline_patterns(
    df: Any,
    *,
    days: int = 60,
    single_candle_lookback: int = 3,
    only_latest_bar: bool = False,
    include_chart_patterns: bool = True,
    pattern_filter: Optional[Any] = None,
    legacy_compat_mode: bool = False,
    allow_missing_volume_breakout: bool = False,
) -> List[DetectedPattern]:
    """Detect candlestick, MA, and chart patterns in an OHLC(V) DataFrame."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []

    open_col = _find_col(df, "open")
    high_col = _find_col(df, "high")
    low_col = _find_col(df, "low")
    close_col = _find_col(df, "close")
    if None in (open_col, high_col, low_col, close_col):
        return []

    allowed_ids = normalize_pattern_filter(pattern_filter)

    full_o = _to_float_array(df[open_col])
    full_h = _to_float_array(df[high_col])
    full_l = _to_float_array(df[low_col])
    full_c = _to_float_array(df[close_col])
    vol_col = _find_col(df, "volume")
    full_v = _to_float_array(df[vol_col]) if vol_col is not None else None
    full_dates = _extract_dates(df)

    total_len = len(full_c)
    if total_len < 3:
        return []

    scan_len = min(total_len, max(1, int(days)))
    offset = total_len - scan_len
    o = full_o[offset:]
    h = full_h[offset:]
    l = full_l[offset:]  # noqa: E741
    c = full_c[offset:]
    v = full_v[offset:] if full_v is not None else None
    dates = full_dates[offset:]
    n = scan_len

    def valid_bar(idx: int) -> bool:
        if idx < 0 or idx >= n:
            return False
        return _valid_ohlc(o[idx], h[idx], l[idx], c[idx])

    def body(idx: int) -> float:
        return abs(c[idx] - o[idx])

    def upper_shadow(idx: int) -> float:
        return h[idx] - max(c[idx], o[idx])

    def lower_shadow(idx: int) -> float:
        return min(c[idx], o[idx]) - l[idx]

    def total_range(idx: int) -> float:
        return h[idx] - l[idx]

    def is_bullish(idx: int) -> bool:
        return c[idx] > o[idx]

    def is_bearish(idx: int) -> bool:
        return c[idx] < o[idx]

    if legacy_compat_mode:
        legacy_avg_body = sum(abs(c[k] - o[k]) for k in range(n)) / float(n) if n > 0 else 1.0
    else:
        legacy_avg_body = None

    def baseline_body(ref_full_idx: int, *, min_samples: int = 5) -> Optional[float]:
        if legacy_compat_mode:
            if legacy_avg_body is None or not math.isfinite(legacy_avg_body):
                return None
            return legacy_avg_body
        return _trailing_avg_body(
            full_o, full_h, full_l, full_c, ref_full_idx, window=20, min_samples=min_samples,
        )

    bar_indices = (
        [n - 1]
        if only_latest_bar
        else list(range(max(0, n - max(1, single_candle_lookback)), n))
    )
    multi_bar_indices = [n - 1] if legacy_compat_mode else bar_indices
    detected: List[DetectedPattern] = []

    def wants(pattern_id: str) -> bool:
        if legacy_compat_mode and pattern_id not in LEGACY_PATTERN_IDS:
            return False
        return allowed_ids is None or pattern_id in allowed_ids

    def wants_any(pattern_ids: frozenset[str]) -> bool:
        if allowed_ids is None:
            return not legacy_compat_mode or bool(pattern_ids & LEGACY_PATTERN_IDS)
        effective = allowed_ids & LEGACY_PATTERN_IDS if legacy_compat_mode else allowed_ids
        return bool(pattern_ids & effective)

    def append_if_allowed(item: DetectedPattern) -> None:
        if legacy_compat_mode and item.pattern_id not in LEGACY_PATTERN_IDS:
            return
        if allowed_ids is None or item.pattern_id in allowed_ids:
            detected.append(item)

    # ---- 1. Single-candle & MA-interaction patterns ----
    for i in (bar_indices if wants_any(_SINGLE_BAR_PATTERN_IDS) else ()):
        if not valid_bar(i):
            continue
        full_idx = offset + i
        bar_date = dates[i]
        completed_offset = -(n - 1 - i)
        bd = body(i)
        us = upper_shadow(i)
        ls = lower_shadow(i)
        rng = total_range(i)
        strict_vol_ratio = _volume_ratio_at(full_v, full_idx, window=5, strict=True)
        soft_vol_ratio = _volume_ratio_at(full_v, full_idx, window=5, strict=False)
        vol_ratio = strict_vol_ratio if strict_vol_ratio is not None else soft_vol_ratio
        falling, rising = _trend_direction_before(full_c, full_idx)
        ma5 = _rolling_sma_at(full_c, full_idx, 5)
        ma10 = _rolling_sma_at(full_c, full_idx, 10)
        ma20 = _rolling_sma_at(full_c, full_idx, 20)
        base_1bar = baseline_body(full_idx, min_samples=5)

        # Doji
        if base_1bar is not None and bd < base_1bar * 0.1 and (us + ls) > bd * 3:
            append_if_allowed(
                _build_detected(
                    "doji",
                    day_offset=completed_offset,
                    completed_bar_offset=completed_offset,
                    trigger_date=bar_date,
                    volume_ratio=vol_ratio,
                )
            )

        # Hammer / Hanging Man (preserve legacy trend-before-candle logic)
        if ls > bd * 2 and us < bd * 0.5 and (falling or rising):
            pattern_id = "hammer" if falling else "hanging_man"
            key_lv = {"support": round(l[i], 2)} if falling else {"resistance": round(h[i], 2)}
            inval = round(l[i], 2) if falling else round(h[i], 2)
            append_if_allowed(
                _build_detected(
                    pattern_id,
                    day_offset=completed_offset,
                    completed_bar_offset=completed_offset,
                    trigger_date=bar_date,
                    volume_confirmed=(
                        None if strict_vol_ratio is None else (strict_vol_ratio >= 1.15)
                    ),
                    volume_ratio=vol_ratio,
                    key_levels=key_lv,
                    invalidation_level=inval,
                )
            )

        # Inverted Hammer / Shooting Star (preserve legacy trend-before-candle logic)
        if us > bd * 2 and ls < bd * 0.5 and (falling or rising):
            pattern_id = "inverted_hammer" if falling else "shooting_star"
            key_lv = {"support": round(l[i], 2)} if falling else {"resistance": round(h[i], 2)}
            inval = round(l[i], 2) if falling else round(h[i], 2)
            append_if_allowed(
                _build_detected(
                    pattern_id,
                    day_offset=completed_offset,
                    completed_bar_offset=completed_offset,
                    trigger_date=bar_date,
                    volume_confirmed=(
                        None if strict_vol_ratio is None else (strict_vol_ratio >= 1.15)
                    ),
                    volume_ratio=vol_ratio,
                    key_levels=key_lv,
                    invalidation_level=inval,
                )
            )

        # Immortal Guide (仙人指路): requires >= 26 bars, prior-bar rising MA20, strict 5-bar volume >= 1.15x
        if (
            not legacy_compat_mode
            and full_idx >= 25
            and rng > 0.0
            and _is_finite_positive(full_c[full_idx - 1])
            and strict_vol_ratio is not None
            and strict_vol_ratio >= 1.15
        ):
            prev_ma5 = _rolling_sma_at(full_c, full_idx - 1, 5)
            prev_ma20 = _rolling_sma_at(full_c, full_idx - 1, 20)
            prev_ma20_5d_ago = _rolling_sma_at(full_c, full_idx - 6, 20)
            prev_c = full_c[full_idx - 1]
            prior_10_base = full_c[full_idx - 11]
            prior_10_gain = (
                (prev_c - prior_10_base) / prior_10_base
                if _is_finite_positive(prior_10_base)
                else 0.0
            )
            if (
                prev_ma5 is not None
                and prev_ma20 is not None
                and prev_ma20_5d_ago is not None
                and prev_c >= prev_ma20
                and prev_ma5 > prev_ma20
                and prev_ma20 > prev_ma20_5d_ago * 1.002
                and prior_10_gain <= 0.30
            ):
                bias_ma20 = (c[i] - prev_ma20) / prev_ma20 * 100.0
                if (
                    us >= max(bd * 2.0, rng * 0.45)
                    and us / o[i] >= 0.02
                    and ls <= rng * 0.25
                    and ls < us * 0.4
                    and bd <= rng * 0.45
                    and (c[i] >= o[i] or c[i] >= prev_c * 0.995)
                    and c[i] >= prev_ma20
                    and bias_ma20 <= 15.0
                ):
                    append_if_allowed(
                        _build_detected(
                            "immortal_guide",
                            day_offset=completed_offset,
                            completed_bar_offset=completed_offset,
                            trigger_date=bar_date,
                            volume_confirmed=True,
                            volume_ratio=strict_vol_ratio,
                            key_levels={"probe_high": round(h[i], 2), "support": round(l[i], 2)},
                            invalidation_level=round(l[i], 2),
                        )
                    )

        # Big bullish / bearish candle
        if base_1bar is not None and base_1bar > 0.0 and bd > base_1bar * 2.5:
            pattern_id = "big_bullish_candle" if is_bullish(i) else "big_bearish_candle"
            append_if_allowed(
                _build_detected(
                    pattern_id,
                    day_offset=completed_offset,
                    completed_bar_offset=completed_offset,
                    trigger_date=bar_date,
                    volume_confirmed=(
                        None if strict_vol_ratio is None else (strict_vol_ratio >= 1.2)
                    ),
                    volume_ratio=vol_ratio,
                    key_levels={"open": round(o[i], 2), "close": round(c[i], 2)},
                    invalidation_level=round(o[i], 2),
                )
            )

        # Rising Lotus / Guillotine / MA Pullback Support
        if (
            not legacy_compat_mode
            and ma5 is not None
            and ma10 is not None
            and ma20 is not None
            and full_idx >= 1
            and _is_finite_positive(full_c[full_idx - 1])
        ):
            ma_min = min(ma5, ma10, ma20)
            ma_max = max(ma5, ma10, ma20)
            prev_c = full_c[full_idx - 1]
            pct_chg = (c[i] - prev_c) / prev_c
            strong_body = base_1bar is not None and base_1bar > 0.0 and bd >= base_1bar * 1.5

            # Rising Lotus: candle body itself spans [ma_min, ma_max] upward
            if (
                is_bullish(i)
                and o[i] <= ma_min * 1.005
                and c[i] > ma_max * 1.005
                and (pct_chg >= 0.03 or strong_body)
            ):
                append_if_allowed(
                    _build_detected(
                        "rising_lotus",
                        day_offset=completed_offset,
                        completed_bar_offset=completed_offset,
                        trigger_date=bar_date,
                        volume_confirmed=(
                            None if strict_vol_ratio is None else (strict_vol_ratio >= 1.3)
                        ),
                        volume_ratio=vol_ratio,
                        key_levels={"breakout_ma": round(ma_max, 2), "support": round(o[i], 2)},
                        invalidation_level=round(o[i], 2),
                    )
                )

            # Guillotine: candle body itself spans [ma_min, ma_max] downward
            if (
                is_bearish(i)
                and o[i] >= ma_max * 0.995
                and c[i] < ma_min * 0.995
                and (pct_chg <= -0.03 or strong_body)
            ):
                append_if_allowed(
                    _build_detected(
                        "guillotine",
                        day_offset=completed_offset,
                        completed_bar_offset=completed_offset,
                        trigger_date=bar_date,
                        volume_confirmed=(
                            None if strict_vol_ratio is None else (strict_vol_ratio >= 1.2)
                        ),
                        volume_ratio=vol_ratio,
                        key_levels={"breakdown_ma": round(ma_min, 2), "resistance": round(o[i], 2)},
                        invalidation_level=round(o[i], 2),
                    )
                )

            # Low-volume MA pullback support: two-sided touch band on MA10 or MA20 + strict contraction
            if (
                ma5 > ma10 > ma20
                and c[i] <= ma5 * 1.03
                and strict_vol_ratio is not None
                and strict_vol_ratio <= 0.75
            ):
                touched_ma10 = (ma10 * 0.985 <= l[i] <= ma10 * 1.015) and (c[i] >= ma10 * 0.995)
                touched_ma20 = (ma20 * 0.985 <= l[i] <= ma20 * 1.015) and (c[i] >= ma20 * 0.995)
                if touched_ma10 or touched_ma20:
                    tested_name = "MA10" if touched_ma10 else "MA20"
                    tested_val = ma10 if touched_ma10 else ma20
                    append_if_allowed(
                        _build_detected(
                            "ma_pullback_support",
                            day_offset=completed_offset,
                            completed_bar_offset=completed_offset,
                            trigger_date=bar_date,
                            desc=f"多头均线排列下缩量回踩 {tested_name}({tested_val:.2f}) 支撑区并企稳",
                            volume_confirmed=True,
                            volume_ratio=strict_vol_ratio,
                            key_levels={
                                "tested_ma": round(tested_val, 2),
                                "ma10_support": round(ma10, 2),
                                "ma20_support": round(ma20, 2),
                            },
                            invalidation_level=round(ma20 * 0.99, 2),
                        )
                    )

    # ---- 2. Multi-candle patterns ----
    for i in (multi_bar_indices if wants_any(_MULTI_BAR_PATTERN_IDS) else ()):
        bar_date = dates[i]
        completed_offset = -(n - 1 - i)
        full_idx = offset + i
        strict_vol_ratio = _volume_ratio_at(full_v, full_idx, window=5, strict=True)
        soft_vol_ratio = _volume_ratio_at(full_v, full_idx, window=5, strict=False)
        vol_ratio = strict_vol_ratio if strict_vol_ratio is not None else soft_vol_ratio

        # 3-bar patterns evaluated in legacy precedence order first (Morning/Evening Star)
        if i >= 2 and valid_bar(i - 2) and valid_bar(i - 1) and valid_bar(i):
            start_offset = -(n - 1 - (i - 2))
            b2, b1, b0 = body(i - 2), body(i - 1), body(i)
            base_3bar = baseline_body(full_idx - 2, min_samples=5)

            # Morning Star
            if (
                base_3bar is not None
                and base_3bar > 0.0
                and is_bearish(i - 2)
                and b2 > base_3bar * 1.5
                and b1 < base_3bar * 0.4
                and is_bullish(i)
                and b0 > base_3bar * 1.5
                and c[i] > (o[i - 2] + c[i - 2]) / 2.0
            ):
                append_if_allowed(
                    _build_detected(
                        "morning_star",
                        day_offset=start_offset,
                        completed_bar_offset=completed_offset,
                        trigger_date=bar_date,
                        volume_confirmed=(
                            None if strict_vol_ratio is None else (strict_vol_ratio >= 1.1)
                        ),
                        volume_ratio=vol_ratio,
                        key_levels={"support": round(min(l[i - 2], l[i - 1], l[i]), 2)},
                        invalidation_level=round(min(l[i - 2], l[i - 1], l[i]), 2),
                    )
                )

            # Evening Star
            if (
                base_3bar is not None
                and base_3bar > 0.0
                and is_bullish(i - 2)
                and b2 > base_3bar * 1.5
                and b1 < base_3bar * 0.4
                and is_bearish(i)
                and b0 > base_3bar * 1.5
                and c[i] < (o[i - 2] + c[i - 2]) / 2.0
            ):
                append_if_allowed(
                    _build_detected(
                        "evening_star",
                        day_offset=start_offset,
                        completed_bar_offset=completed_offset,
                        trigger_date=bar_date,
                        volume_confirmed=(
                            None if strict_vol_ratio is None else (strict_vol_ratio >= 1.1)
                        ),
                        volume_ratio=vol_ratio,
                        key_levels={"resistance": round(max(h[i - 2], h[i - 1], h[i]), 2)},
                        invalidation_level=round(max(h[i - 2], h[i - 1], h[i]), 2),
                    )
                )

        # 2-bar patterns (i-1, i): Engulfing (legacy + extended), Piercing Line, Dark Cloud Cover
        if i >= 1 and valid_bar(i - 1) and valid_bar(i):
            start_offset = -(n - 1 - (i - 1))
            base_2bar = baseline_body(full_idx - 1, min_samples=1)
            if (
                is_bullish(i)
                and is_bearish(i - 1)
                and o[i] < c[i - 1]
                and c[i] > o[i - 1]
            ):
                append_if_allowed(
                    _build_detected(
                        "bullish_engulfing",
                        day_offset=start_offset,
                        completed_bar_offset=completed_offset,
                        trigger_date=bar_date,
                        volume_confirmed=(
                            None if strict_vol_ratio is None else (strict_vol_ratio >= 1.1)
                        ),
                        volume_ratio=vol_ratio,
                        key_levels={"support": round(min(l[i - 1], l[i]), 2)},
                        invalidation_level=round(min(l[i - 1], l[i]), 2),
                    )
                )
            elif (
                is_bearish(i)
                and is_bullish(i - 1)
                and o[i] > c[i - 1]
                and c[i] < o[i - 1]
            ):
                append_if_allowed(
                    _build_detected(
                        "bearish_engulfing",
                        day_offset=start_offset,
                        completed_bar_offset=completed_offset,
                        trigger_date=bar_date,
                        volume_confirmed=(
                            None if strict_vol_ratio is None else (strict_vol_ratio >= 1.1)
                        ),
                        volume_ratio=vol_ratio,
                        key_levels={"resistance": round(max(h[i - 1], h[i]), 2)},
                        invalidation_level=round(max(h[i - 1], h[i]), 2),
                    )
                )

            if not legacy_compat_mode and base_2bar is not None and full_idx >= 11:
                prev_falling, prev_rising = _trend_direction_before(full_c, full_idx - 1)
                if (
                    prev_falling
                    and is_bearish(i - 1)
                    and body(i - 1) >= max(base_2bar * 1.1, o[i - 1] * 0.015)
                    and is_bullish(i)
                    and o[i] < c[i - 1]
                    and (o[i - 1] + c[i - 1]) / 2.0 < c[i] <= o[i - 1]
                ):
                    append_if_allowed(
                        _build_detected(
                            "piercing_line",
                            day_offset=start_offset,
                            completed_bar_offset=completed_offset,
                            trigger_date=bar_date,
                            volume_confirmed=(
                                None if strict_vol_ratio is None else (strict_vol_ratio >= 1.1)
                            ),
                            volume_ratio=vol_ratio,
                            key_levels={"support": round(l[i], 2)},
                            invalidation_level=round(l[i], 2),
                        )
                    )
                if (
                    prev_rising
                    and is_bullish(i - 1)
                    and body(i - 1) >= max(base_2bar * 1.1, o[i - 1] * 0.015)
                    and is_bearish(i)
                    and o[i] > c[i - 1]
                    and o[i - 1] <= c[i] < (o[i - 1] + c[i - 1]) / 2.0
                ):
                    append_if_allowed(
                        _build_detected(
                            "dark_cloud_cover",
                            day_offset=start_offset,
                            completed_bar_offset=completed_offset,
                            trigger_date=bar_date,
                            volume_confirmed=(
                                None if strict_vol_ratio is None else (strict_vol_ratio >= 1.1)
                            ),
                            volume_ratio=vol_ratio,
                            key_levels={"resistance": round(h[i], 2)},
                            invalidation_level=round(h[i], 2),
                        )
                    )

        # Extended 3-bar patterns (i-2, i-1, i)
        if i >= 2 and valid_bar(i - 2) and valid_bar(i - 1) and valid_bar(i):
            start_offset = -(n - 1 - (i - 2))
            b2, b1, b0 = body(i - 2), body(i - 1), body(i)
            base_3bar = baseline_body(full_idx - 2, min_samples=5)

            if not legacy_compat_mode and base_3bar is not None and full_idx >= 7:
                # Red Three Soldiers (红三兵): requires 5-bar causal baseline (full_idx >= 7)
                prior_base_idx = max(0, full_idx - 12)
                prior_ref_idx = full_idx - 3
                prior_surge = (
                    (full_c[prior_ref_idx] - full_c[prior_base_idx]) / full_c[prior_base_idx]
                    if (
                        _is_finite_positive(full_c[prior_base_idx])
                        and _is_finite_positive(full_c[prior_ref_idx])
                    )
                    else 0.0
                )
                if (
                    is_bullish(i - 2)
                    and is_bullish(i - 1)
                    and is_bullish(i)
                    and c[i - 1] > c[i - 2]
                    and c[i] > c[i - 1]
                    and o[i - 1] >= o[i - 2] * 0.998
                    and o[i - 1] <= c[i - 2] * 1.005
                    and o[i] >= o[i - 1] * 0.998
                    and o[i] <= c[i - 1] * 1.005
                    and all(
                        total_range(k) > 0.0
                        and body(k) >= max(base_3bar * 0.6, o[k] * 0.008)
                        and body(k) / total_range(k) >= 0.50
                        and upper_shadow(k) < body(k) * 0.6
                        for k in (i - 2, i - 1, i)
                    )
                    and prior_surge <= 0.25
                ):
                    vol_ok: Optional[bool] = None
                    if (
                        v is not None
                        and strict_vol_ratio is not None
                        and all(_is_finite_positive(v[k]) for k in (i - 2, i - 1, i))
                    ):
                        vol_ok = bool(strict_vol_ratio >= 1.1 or (v[i] > v[i - 1] > v[i - 2]))
                    append_if_allowed(
                        _build_detected(
                            "red_three_soldiers",
                            day_offset=start_offset,
                            completed_bar_offset=completed_offset,
                            trigger_date=bar_date,
                            volume_confirmed=vol_ok,
                            volume_ratio=vol_ratio,
                            key_levels={"support": round(l[i - 2], 2), "entry_low": round(o[i - 2], 2)},
                            invalidation_level=round(o[i - 2], 2),
                        )
                    )

                # Three Black Crows (三只乌鸦): requires prior advancing context before bar i-2
                _, crows_prior_rising = _trend_direction_before(full_c, full_idx - 2)
                if (
                    full_idx >= 12
                    and crows_prior_rising
                    and is_bearish(i - 2)
                    and is_bearish(i - 1)
                    and is_bearish(i)
                    and c[i - 1] < c[i - 2]
                    and c[i] < c[i - 1]
                    and o[i - 1] <= o[i - 2] * 1.002
                    and o[i - 1] >= c[i - 2] * 0.995
                    and o[i] <= o[i - 1] * 1.002
                    and o[i] >= c[i - 1] * 0.995
                    and all(
                        total_range(k) > 0.0
                        and body(k) >= max(base_3bar * 0.6, o[k] * 0.008)
                        and body(k) / total_range(k) >= 0.50
                        and lower_shadow(k) < body(k) * 0.6
                        for k in (i - 2, i - 1, i)
                    )
                ):
                    vol_ok_bear: Optional[bool] = None
                    if (
                        v is not None
                        and strict_vol_ratio is not None
                        and all(_is_finite_positive(v[k]) for k in (i - 2, i - 1, i))
                    ):
                        vol_ok_bear = bool(strict_vol_ratio >= 1.1 or (v[i] > v[i - 2]))
                    append_if_allowed(
                        _build_detected(
                            "three_black_crows",
                            day_offset=start_offset,
                            completed_bar_offset=completed_offset,
                            trigger_date=bar_date,
                            volume_confirmed=vol_ok_bear,
                            volume_ratio=vol_ratio,
                            key_levels={"resistance": round(h[i - 2], 2)},
                            invalidation_level=round(o[i - 2], 2),
                        )
                    )

                # Bullish Cannon (多方炮): Yang -> bounded retracement Yin -> decisive Yang
                if (
                    is_bullish(i - 2)
                    and b2 >= max(base_3bar, o[i - 2] * 0.015)
                    and is_bearish(i - 1)
                    and b1 < b2 * 0.85
                    and o[i - 1] <= h[i - 2] * 1.01
                    and c[i - 1] < c[i - 2]
                    and c[i - 1] >= o[i - 2] * 0.995
                    and l[i - 1] >= l[i - 2] * 0.99
                    and is_bullish(i)
                    and b0 >= max(base_3bar * 0.9, b1 * 1.2, o[i] * 0.015)
                    and c[i] > max(c[i - 2], o[i - 1])
                ):
                    cannon_vol_ok: Optional[bool] = None
                    if (
                        v is not None
                        and strict_vol_ratio is not None
                        and all(_is_finite_positive(v[k]) for k in (i - 2, i - 1, i))
                    ):
                        cannon_vol_ok = bool(v[i] > v[i - 1] and v[i - 1] <= v[i - 2] * 1.1)
                    low_min = min(l[i - 2], l[i - 1], l[i])
                    append_if_allowed(
                        _build_detected(
                            "bullish_cannon",
                            day_offset=start_offset,
                            completed_bar_offset=completed_offset,
                            trigger_date=bar_date,
                            volume_confirmed=cannon_vol_ok,
                            volume_ratio=vol_ratio,
                            key_levels={"support": round(low_min, 2), "platform_top": round(c[i], 2)},
                            invalidation_level=round(low_min, 2),
                        )
                    )

    # ---- 3. Window-wide chart patterns (before breakout/box for legacy order parity) ----
    need_chart = (
        include_chart_patterns
        and valid_bar(n - 1)
        and (wants("double_bottom") or wants("double_top"))
    )
    if need_chart:
        if wants("double_bottom"):
            valid_indices = [idx for idx in range(n) if valid_bar(idx)]
            if len(valid_indices) >= 2:
                lowest_sorted = sorted(valid_indices, key=lambda idx: l[idx])[:2]
                lo1, lo2 = sorted(lowest_sorted)
                denom = max(l[lo1], l[lo2])
                if lo2 - lo1 >= 5 and denom > 0.0 and abs(l[lo1] - l[lo2]) / denom < 0.03:
                    mid_high = max(h[k] for k in range(lo1, lo2 + 1) if _is_finite_positive(h[k]))
                    if mid_high > l[lo1] * 1.03:
                        append_if_allowed(
                            _build_detected(
                                "double_bottom",
                                day_offset=-(n - 1 - lo2),
                                completed_bar_offset=0,
                                trigger_date=dates[-1],
                                key_levels={"neckline": round(mid_high, 2), "bottom": round(min(l[lo1], l[lo2]), 2)},
                                invalidation_level=round(min(l[lo1], l[lo2]), 2),
                            )
                        )

        if not legacy_compat_mode and wants("double_top") and n >= 10:
            # Confirmed Double Top: full equal-high plateaus collapsed + pruned O(N) lookback/interior checks
            pivots = _find_local_peak_pivots(h, valid_bar, n)
            lookback_start = max(0, n - max(1, single_candle_lookback))
            valid_mask = [valid_bar(idx) for idx in range(n)]
            lookback_closes = [c[k] for k in range(lookback_start, n) if valid_mask[k]]
            if len(pivots) >= 2 and lookback_closes:
                lookback_min_close = min(lookback_closes)
                before_lb_max_h = [0.0] * lookback_start
                before_lb_min_c = [float("inf")] * lookback_start
                run_max_h = 0.0
                run_min_c = float("inf")
                for pos in range(lookback_start - 1, -1, -1):
                    before_lb_max_h[pos] = run_max_h
                    before_lb_min_c[pos] = run_min_c
                    if valid_mask[pos]:
                        if h[pos] > run_max_h:
                            run_max_h = h[pos]
                        if c[pos] < run_min_c:
                            run_min_c = c[pos]

                best_brk_idx: Optional[int] = None
                best_pair: Optional[Tuple[int, int, float]] = None
                for idx_b in range(1, len(pivots)):
                    s2, e2 = pivots[idx_b]
                    if s2 < 5:
                        continue
                    peak2 = h[s2]
                    if lookback_min_close >= peak2 * 0.97:
                        continue
                    max_possible_denom = peak2 / 0.97
                    if e2 < lookback_start:
                        if before_lb_max_h[e2] > max_possible_denom * 1.011:
                            continue
                        if before_lb_min_c[e2] <= lookback_min_close:
                            continue

                    k_cur = s2 - 1
                    int_has_valid = False
                    int_max_h = 0.0
                    int_min_l = float("inf")
                    for idx_a in range(idx_b - 1, -1, -1):
                        _s1, e1 = pivots[idx_a]
                        while k_cur > e1:
                            if valid_mask[k_cur]:
                                int_has_valid = True
                                if h[k_cur] > int_max_h:
                                    int_max_h = h[k_cur]
                                if l[k_cur] < int_min_l:
                                    int_min_l = l[k_cur]
                            k_cur -= 1
                        if int_max_h > max_possible_denom * 1.011:
                            break
                        if int_min_l <= lookback_min_close:
                            break
                        if s2 - e1 < 5 or not int_has_valid:
                            continue
                        peak1 = h[e1]
                        peak_denom = max(peak1, peak2)
                        if peak_denom <= 0.0 or abs(peak1 - peak2) / peak_denom >= 0.03:
                            continue
                        if int_max_h > peak_denom * 1.01:
                            continue
                        neckline = int_min_l
                        if neckline >= min(peak1, peak2) * 0.97:
                            continue
                        if e2 < lookback_start:
                            if before_lb_max_h[e2] > peak_denom * 1.01 or before_lb_min_c[e2] < neckline:
                                continue
                            scan_start = lookback_start
                        else:
                            scan_start = e2 + 1
                        for brk in range(scan_start, n):
                            if not valid_mask[brk]:
                                continue
                            if h[brk] > peak_denom * 1.01 or c[brk] > peak_denom * 1.01:
                                break
                            if c[brk] < neckline:
                                if brk >= lookback_start and (best_brk_idx is None or brk > best_brk_idx):
                                    best_brk_idx = brk
                                    best_pair = (e1, s2, neckline)
                                break
                if best_brk_idx is not None and best_pair is not None:
                    e1, s2, neckline = best_pair
                    brk_offset = -(n - 1 - best_brk_idx)
                    append_if_allowed(
                        _build_detected(
                            "double_top",
                            day_offset=brk_offset,
                            completed_bar_offset=brk_offset,
                            trigger_date=dates[best_brk_idx],
                            key_levels={"neckline": round(neckline, 2), "peak": round(max(h[e1], h[s2]), 2)},
                            invalidation_level=round(max(h[e1], h[s2]), 2),
                        )
                    )

    # ---- 4. 20D High Breakout ----
    if wants("breakout_20d_high") and legacy_compat_mode:
        if n >= 21 and valid_bar(n - 1):
            prior_highs = [h[k] for k in range(n - 21, n - 1)]
            if all(math.isfinite(x) for x in prior_highs):
                high_20d = max(prior_highs)
                if v is None:
                    vol_passes = True
                else:
                    prev_v5 = v[n - 6:n - 1]
                    vol_passes = (
                        len(prev_v5) == 5
                        and all(math.isfinite(x) for x in prev_v5)
                        and math.isfinite(v[n - 1])
                        and v[n - 1] > (sum(prev_v5) / 5.0) * 1.5
                    )
                strict_vol_latest = _volume_ratio_at(full_v, total_len - 1, window=5, strict=True)
                if c[-1] > high_20d and vol_passes:
                    append_if_allowed(
                        _build_detected(
                            "breakout_20d_high",
                            day_offset=0,
                            completed_bar_offset=0,
                            trigger_date=dates[-1],
                            volume_confirmed=(
                                None if strict_vol_latest is None else (strict_vol_latest > 1.5)
                            ),
                            volume_ratio=strict_vol_latest,
                            key_levels={"breakout_level": round(high_20d, 2)},
                            invalidation_level=round(high_20d, 2),
                        )
                    )
    elif wants("breakout_20d_high"):
        for i in bar_indices:
            full_idx = offset + i
            if full_idx < 20 or not valid_bar(i):
                continue
            prior_highs = [
                full_h[k] for k in range(full_idx - 20, full_idx) if _is_finite_positive(full_h[k])
            ]
            if len(prior_highs) < 20:
                continue
            high_20d = max(prior_highs)
            strict_vol = _volume_ratio_at(full_v, full_idx, window=5, strict=True)
            if allow_missing_volume_breakout:
                vol_passes = v is None or (strict_vol is not None and strict_vol > 1.5)
            else:
                vol_passes = strict_vol is not None and strict_vol > 1.5
            if c[i] > high_20d and vol_passes:
                brk_offset = -(n - 1 - i)
                append_if_allowed(
                    _build_detected(
                        "breakout_20d_high",
                        day_offset=brk_offset,
                        completed_bar_offset=brk_offset,
                        trigger_date=dates[i],
                        volume_confirmed=(
                            None if strict_vol is None else (strict_vol > 1.5)
                        ),
                        volume_ratio=strict_vol,
                        key_levels={"breakout_level": round(high_20d, 2)},
                        invalidation_level=round(high_20d, 2),
                    )
                )

    # ---- 5. Box Consolidation ----
    if include_chart_patterns and wants("box_consolidation") and valid_bar(n - 1) and n >= 10:
        recent_bars = [idx for idx in range(n - 10, n) if valid_bar(idx)]
        if len(recent_bars) == 10:
            recent_high = max(h[idx] for idx in recent_bars)
            recent_low = min(l[idx] for idx in recent_bars)
            box_range_pct = (recent_high - recent_low) / recent_low * 100.0 if recent_low > 0.0 else 0.0
            box_match = (box_range_pct < 8.0) if legacy_compat_mode else (0.0 < box_range_pct < 8.0)
            if box_match:
                append_if_allowed(
                    _build_detected(
                        "box_consolidation",
                        day_offset=0,
                        completed_bar_offset=0,
                        trigger_date=dates[-1],
                        desc=f"近10日波幅 {box_range_pct:.1f}%，价格在区间内震荡",
                        key_levels={"box_high": round(recent_high, 2), "box_low": round(recent_low, 2)},
                    )
                )

    # Deduplicate by pattern_id, keeping most recent occurrence and preserving order
    seen_ids = set()
    unique_reversed: List[DetectedPattern] = []
    for item in reversed(detected):
        if item.pattern_id not in seen_ids:
            seen_ids.add(item.pattern_id)
            unique_reversed.append(item)
    return list(reversed(unique_reversed))
