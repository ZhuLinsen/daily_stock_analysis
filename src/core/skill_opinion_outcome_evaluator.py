# -*- coding: utf-8 -*-
"""Pure forward-outcome evaluation for persisted skill opinions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from typing import Any, Dict, Optional, Sequence

from src.agent.protocols import normalize_strategy_signal


SUPPORTED_SKILL_OUTCOME_HORIZONS = {
    "1d": 1,
    "3d": 3,
    "5d": 5,
    "10d": 10,
}

_BULLISH_SIGNALS = frozenset({"strong_buy", "buy"})


@dataclass(frozen=True)
class SkillOpinionOutcomeEvaluation:
    """One deterministic sample-by-horizon evaluation result."""

    eval_status: str
    outcome: Optional[str] = None
    direction_correct: Optional[bool] = None
    unable_reason: Optional[str] = None
    analysis_date: Optional[date] = None
    start_trade_date: Optional[date] = None
    end_trade_date: Optional[date] = None
    start_price: Optional[float] = None
    end_close: Optional[float] = None
    stock_return_pct: Optional[float] = None
    directional_return_pct: Optional[float] = None

    def to_fields(self) -> Dict[str, Any]:
        return asdict(self)


class SkillOpinionOutcomeEvaluator:
    """Evaluate one immutable skill signal against locally stored daily bars."""

    @classmethod
    def evaluate(
        cls,
        *,
        signal: Any,
        horizon: str,
        analysis_date: Optional[date],
        start_bar: Any = None,
        forward_bars: Sequence[Any] = (),
    ) -> SkillOpinionOutcomeEvaluation:
        canonical_signal, invalid_signal, _ = normalize_strategy_signal(signal)
        if invalid_signal:
            return cls._unable("invalid_signal", analysis_date=analysis_date)

        eval_days = SUPPORTED_SKILL_OUTCOME_HORIZONS.get(str(horizon or "").strip())
        if eval_days is None:
            return cls._unable("unsupported_horizon", analysis_date=analysis_date)
        if analysis_date is None:
            return cls._unable("missing_analysis_date")
        if start_bar is None:
            return cls._pending("missing_start_bar", analysis_date=analysis_date)

        raw_start_price = getattr(start_bar, "close", None)
        start_price = cls._positive_finite_float(raw_start_price)
        start_trade_date = cls._bar_date(start_bar)
        if start_price is None:
            reason = "missing_start_close" if raw_start_price is None else "invalid_start_price"
            return cls._pending(
                reason,
                analysis_date=analysis_date,
                start_trade_date=start_trade_date,
            )

        bars = list(forward_bars)
        if len(bars) < eval_days:
            return cls._pending(
                "insufficient_future_data",
                analysis_date=analysis_date,
                start_trade_date=start_trade_date,
                start_price=start_price,
            )

        end_bar = bars[eval_days - 1]
        raw_end_close = getattr(end_bar, "close", None)
        end_close = cls._positive_finite_float(raw_end_close)
        end_trade_date = cls._bar_date(end_bar)
        if end_close is None:
            reason = "missing_end_close" if raw_end_close is None else "invalid_end_close"
            return cls._pending(
                reason,
                analysis_date=analysis_date,
                start_trade_date=start_trade_date,
                end_trade_date=end_trade_date,
                start_price=start_price,
            )

        stock_return_pct = (end_close - start_price) / start_price * 100.0
        common = {
            "analysis_date": analysis_date,
            "start_trade_date": start_trade_date,
            "end_trade_date": end_trade_date,
            "start_price": start_price,
            "end_close": end_close,
            "stock_return_pct": stock_return_pct,
        }

        if canonical_signal == "hold":
            return SkillOpinionOutcomeEvaluation(
                eval_status="observational",
                outcome="observational",
                **common,
            )

        multiplier = 1.0 if canonical_signal in _BULLISH_SIGNALS else -1.0
        directional_return_pct = stock_return_pct * multiplier
        direction_correct = directional_return_pct > 0.0
        return SkillOpinionOutcomeEvaluation(
            eval_status="evaluated",
            outcome="hit" if direction_correct else "miss",
            direction_correct=direction_correct,
            directional_return_pct=directional_return_pct,
            **common,
        )

    @staticmethod
    def _pending(reason: str, **fields: Any) -> SkillOpinionOutcomeEvaluation:
        return SkillOpinionOutcomeEvaluation(
            eval_status="pending",
            unable_reason=reason,
            **fields,
        )

    @staticmethod
    def _unable(reason: str, **fields: Any) -> SkillOpinionOutcomeEvaluation:
        return SkillOpinionOutcomeEvaluation(
            eval_status="unable",
            unable_reason=reason,
            **fields,
        )

    @staticmethod
    def _positive_finite_float(value: Any) -> Optional[float]:
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None

    @staticmethod
    def _bar_date(bar: Any) -> Optional[date]:
        value = getattr(bar, "date", None)
        return value if isinstance(value, date) else None
