# -*- coding: utf-8 -*-
"""Backtesting evaluation engine (pure logic).

This module is intentionally DB-agnostic: it operates on plain values or
objects that look like daily OHLC bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence


OVERALL_SENTINEL_CODE = "__overall__"


class DailyBarLike(Protocol):
    """Protocol for objects representing a daily OHLC bar."""

    date: date
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]


class BacktestResultLike(Protocol):
    """Protocol for objects that behave like a stored BacktestResult."""

    eval_status: str
    position_recommendation: Optional[str]
    outcome: Optional[str]
    direction_correct: Optional[bool]
    stock_return_pct: Optional[float]
    simulated_return_pct: Optional[float]
    hit_stop_loss: Optional[bool]
    hit_take_profit: Optional[bool]
    first_hit: Optional[str]
    first_hit_trading_days: Optional[int]
    operation_advice: Optional[str]


@dataclass(frozen=True)
class EvaluationConfig:
    eval_window_days: int
    neutral_band_pct: float = 2.0
    engine_version: str = "v1"


class BacktestEngine:
    """Long-only daily-bar backtesting engine."""

    # Operation advice keywords (Chinese + English)
    _BULLISH_KEYWORDS = (
        "买入",
        "加仓",
        "强烈买入",
        "增持",
        "建仓",
        "strong buy",
        "buy",
        "add",
    )
    _BEARISH_KEYWORDS = (
        "卖出",
        "减仓",
        "强烈卖出",
        "清仓",
        "strong sell",
        "sell",
        "reduce",
    )
    _HOLD_KEYWORDS = (
        "持有",
        "hold",
    )
    _WAIT_KEYWORDS = (
        "观望",
        "等待",
        "wait",
    )

    # Negation prefixes (trailing spaces stripped for suffix-matching against prefix text).
    # English patterns include trailing space in their canonical form; rstrip is
    # applied during matching so "do not" matches prefix "do not " or "do not".
    _NEGATION_PATTERNS = (
        "not", "don't", "do not", "no", "never", "avoid",  # English
        "不要", "不", "别", "勿", "没有",  # Chinese
    )

    @classmethod
    def infer_direction_expected(cls, operation_advice: Optional[str]) -> str:
        """Infer expected direction: up/down/not_down/flat."""
        text = cls._normalize_text(operation_advice)
        if cls._matches_intent(text, cls._BEARISH_KEYWORDS):
            return "down"
        if cls._matches_intent(text, cls._WAIT_KEYWORDS):
            return "flat"
        if cls._matches_intent(text, cls._BULLISH_KEYWORDS):
            return "up"
        if cls._matches_intent(text, cls._HOLD_KEYWORDS):
            return "not_down"
        return "flat"

    @classmethod
    def infer_position_recommendation(cls, operation_advice: Optional[str]) -> str:
        """Infer recommended position: long/cash (long-only system).

        Priority: bearish/wait -> cash, bullish/hold -> long, unrecognized -> cash.
        """
        text = cls._normalize_text(operation_advice)
        if cls._matches_intent(text, cls._BEARISH_KEYWORDS) or cls._matches_intent(text, cls._WAIT_KEYWORDS):
            return "cash"
        if cls._matches_intent(text, cls._BULLISH_KEYWORDS) or cls._matches_intent(text, cls._HOLD_KEYWORDS):
            return "long"
        return "cash"

    @classmethod
    def evaluate_single(
        cls,
        *,
        operation_advice: Optional[str],
        analysis_date: date,
        start_price: float,
        forward_bars: Sequence[DailyBarLike],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        config: EvaluationConfig,
    ) -> Dict[str, Any]:
        """Evaluate one historical analysis against forward daily bars.

        Notes:
        - Daily bars cannot determine intraday ordering. If stop-loss and
          take-profit are both touched in the same bar, we record
          first_hit="ambiguous" and assume stop-loss first for simulated exit.
        """

        if start_price is None or start_price <= 0:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": cls.infer_position_recommendation(operation_advice),
                "direction_expected": cls.infer_direction_expected(operation_advice),
                "eval_status": "error",
            }

        eval_days = int(config.eval_window_days)
        if eval_days <= 0:
            raise ValueError("eval_window_days must be positive")

        if len(forward_bars) < eval_days:
            return {
                "analysis_date": analysis_date,
                "operation_advice": operation_advice,
                "position_recommendation": cls.infer_position_recommendation(operation_advice),
                "direction_expected": cls.infer_direction_expected(operation_advice),
                "eval_status": "insufficient_data",
                "eval_window_days": eval_days,
            }

        window_bars = list(forward_bars[:eval_days])
        end_close = window_bars[-1].close
        highs = [b.high for b in window_bars if b.high is not None]
        lows = [b.low for b in window_bars if b.low is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None

        stock_return_pct: Optional[float]
        if end_close is None:
            stock_return_pct = None
        else:
            stock_return_pct = (end_close - start_price) / start_price * 100

        direction_expected = cls.infer_direction_expected(operation_advice)
        position = cls.infer_position_recommendation(operation_advice)

        outcome, direction_correct = cls._classify_outcome(
            stock_return_pct=stock_return_pct,
            direction_expected=direction_expected,
            neutral_band_pct=config.neutral_band_pct,
        )

        (
            hit_stop_loss,
            hit_take_profit,
            first_hit,
            first_hit_date,
            first_hit_days,
            simulated_exit_price,
            simulated_exit_reason,
        ) = cls._evaluate_targets(
            position=position,
            stop_loss=stop_loss,
            take_profit=take_profit,
            window_bars=window_bars,
            end_close=end_close,
        )

        simulated_entry_price = start_price if position == "long" else None
        simulated_return_pct: Optional[float]
        if position != "long":
            simulated_return_pct = 0.0
        elif simulated_exit_price is None:
            simulated_return_pct = None
        else:
            simulated_return_pct = (simulated_exit_price - start_price) / start_price * 100

        return {
            "analysis_date": analysis_date,
            "eval_window_days": eval_days,
            "engine_version": config.engine_version,
            "eval_status": "completed",
            "operation_advice": operation_advice,
            "position_recommendation": position,
            "start_price": start_price,
            "end_close": end_close,
            "max_high": max_high,
            "min_low": min_low,
            "stock_return_pct": stock_return_pct,
            "direction_expected": direction_expected,
            "direction_correct": direction_correct,
            "outcome": outcome,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "hit_stop_loss": hit_stop_loss,
            "hit_take_profit": hit_take_profit,
            "first_hit": first_hit,
            "first_hit_date": first_hit_date,
            "first_hit_trading_days": first_hit_days,
            "simulated_entry_price": simulated_entry_price,
            "simulated_exit_price": simulated_exit_price,
            "simulated_exit_reason": simulated_exit_reason,
            "simulated_return_pct": simulated_return_pct,
        }

    @classmethod
    def compute_summary(
        cls,
        *,
        results: Iterable[BacktestResultLike],
        scope: str,
        code: Optional[str],
        eval_window_days: int,
        engine_version: str,
    ) -> Dict[str, Any]:
        """Aggregate BacktestResult rows into summary metrics."""
        results_list = list(results)

        total = len(results_list)
        completed = [r for r in results_list if (r.eval_status or "") == "completed"]
        insufficient_count = sum(1 for r in results_list if (r.eval_status or "") == "insufficient_data")

        long_count = sum(1 for r in completed if (r.position_recommendation or "") == "long")
        cash_count = sum(1 for r in completed if (r.position_recommendation or "") == "cash")

        win_count = sum(1 for r in completed if (r.outcome or "") == "win")
        loss_count = sum(1 for r in completed if (r.outcome or "") == "loss")
        neutral_count = sum(1 for r in completed if (r.outcome or "") == "neutral")

        direction_denominator = sum(1 for r in completed if r.direction_correct is not None)
        direction_numerator = sum(1 for r in completed if r.direction_correct is True)
        direction_accuracy_pct = (
            round(direction_numerator / direction_denominator * 100, 2) if direction_denominator else None
        )

        win_loss_denominator = win_count + loss_count
        win_rate_pct = round(win_count / win_loss_denominator * 100, 2) if win_loss_denominator else None
        neutral_rate_pct = round(neutral_count / len(completed) * 100, 2) if completed else None

        avg_stock_return_pct = cls._average([r.stock_return_pct for r in completed])
        avg_simulated_return_pct = cls._average([r.simulated_return_pct for r in completed])

        stop_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long" and r.hit_stop_loss is not None
        ]
        stop_loss_trigger_rate = (
            round(sum(1 for r in stop_applicable if r.hit_stop_loss is True) / len(stop_applicable) * 100, 2)
            if stop_applicable
            else None
        )

        take_profit_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long" and r.hit_take_profit is not None
        ]
        take_profit_trigger_rate = (
            round(
                sum(1 for r in take_profit_applicable if r.hit_take_profit is True) / len(take_profit_applicable) * 100,
                2,
            )
            if take_profit_applicable
            else None
        )

        any_target_applicable = [
            r
            for r in completed
            if (r.position_recommendation or "") == "long"
            and (r.hit_stop_loss is not None or r.hit_take_profit is not None)
        ]
        ambiguous_rate = (
            round(
                sum(1 for r in any_target_applicable if (r.first_hit or "") == "ambiguous")
                / len(any_target_applicable)
                * 100,
                2,
            )
            if any_target_applicable
            else None
        )
        avg_days_to_first_hit = cls._average(
            [
                float(r.first_hit_trading_days)
                for r in any_target_applicable
                if r.first_hit_trading_days is not None and (r.first_hit or "") in ("stop_loss", "take_profit", "ambiguous")
            ]
        )

        advice_breakdown = cls._compute_advice_breakdown(completed)
        diagnostics = cls._compute_diagnostics(results_list)

        return {
            "scope": scope,
            "code": code,
            "eval_window_days": int(eval_window_days),
            "engine_version": engine_version,
            "total_evaluations": total,
            "completed_count": len(completed),
            "insufficient_count": insufficient_count,
            "long_count": long_count,
            "cash_count": cash_count,
            "win_count": win_count,
            "loss_count": loss_count,
            "neutral_count": neutral_count,
            "direction_accuracy_pct": direction_accuracy_pct,
            "win_rate_pct": win_rate_pct,
            "neutral_rate_pct": neutral_rate_pct,
            "avg_stock_return_pct": avg_stock_return_pct,
            "avg_simulated_return_pct": avg_simulated_return_pct,
            "stop_loss_trigger_rate": stop_loss_trigger_rate,
            "take_profit_trigger_rate": take_profit_trigger_rate,
            "ambiguous_rate": ambiguous_rate,
            "avg_days_to_first_hit": avg_days_to_first_hit,
            "advice_breakdown": advice_breakdown,
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _normalize_text(value: Optional[str]) -> str:
        return str(value or "").strip().lower()

    @classmethod
    def _matches_intent(cls, text: str, keywords: Sequence[str]) -> bool:
        """Check if text expresses the intent of any keyword, accounting for negation.

        Tier 1: exact match (covers clean labels like "买入", "hold").
        Tier 2: substring match with negation guard.
        Keywords are assumed to be lowercase (matching _normalize_text output).
        """
        if not text:
            return False
        for kw in keywords:
            if text == kw:
                return True
        for kw in keywords:
            idx = text.find(kw)
            if idx == -1:
                continue
            if not cls._is_negated(text[:idx]):
                return True
        return False

    @classmethod
    def _is_negated(cls, prefix: str) -> bool:
        """Check if the prefix text ends with a negation pattern."""
        stripped = prefix.rstrip()
        return any(stripped.endswith(neg) for neg in cls._NEGATION_PATTERNS)

    @classmethod
    def _classify_outcome(
        cls,
        *,
        stock_return_pct: Optional[float],
        direction_expected: str,
        neutral_band_pct: float,
    ) -> tuple[Optional[str], Optional[bool]]:
        if stock_return_pct is None:
            return None, None

        band = abs(float(neutral_band_pct))
        r = float(stock_return_pct)

        if direction_expected == "up":
            if r >= band:
                return "win", True
            if r <= -band:
                return "loss", False
            return "neutral", None

        if direction_expected == "down":
            if r <= -band:
                return "win", True
            if r >= band:
                return "loss", False
            return "neutral", None

        if direction_expected == "not_down":
            if r >= 0:
                return "win", True
            if r <= -band:
                return "loss", False
            return "neutral", None

        # flat
        if abs(r) <= band:
            return "win", True
        return "loss", False

    @classmethod
    def _evaluate_targets(
        cls,
        *,
        position: str,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        window_bars: List[DailyBarLike],
        end_close: Optional[float],
    ) -> tuple[
        Optional[bool],
        Optional[bool],
        str,
        Optional[date],
        Optional[int],
        Optional[float],
        str,
    ]:
        if position != "long":
            return (
                None,
                None,
                "not_applicable",
                None,
                None,
                None,
                "cash",
            )

        has_any_target = stop_loss is not None or take_profit is not None
        if not has_any_target:
            return (
                None,
                None,
                "neither",
                None,
                None,
                end_close,
                "window_end",
            )

        hit_sl: Optional[bool] = None if stop_loss is None else False
        hit_tp: Optional[bool] = None if take_profit is None else False
        first_hit = "neither"
        first_hit_date: Optional[date] = None
        first_hit_days: Optional[int] = None
        exit_price: Optional[float] = end_close
        exit_reason = "window_end"

        for idx, bar in enumerate(window_bars, start=1):
            low = bar.low
            high = bar.high
            stop_hit = stop_loss is not None and low is not None and low <= stop_loss
            tp_hit = take_profit is not None and high is not None and high >= take_profit

            if stop_hit:
                hit_sl = True
            if tp_hit:
                hit_tp = True

            if not stop_hit and not tp_hit:
                continue

            first_hit_date = bar.date
            first_hit_days = idx

            if stop_hit and tp_hit:
                first_hit = "ambiguous"
                exit_price = stop_loss
                exit_reason = "ambiguous_stop_loss"
                break

            if stop_hit:
                first_hit = "stop_loss"
                exit_price = stop_loss
                exit_reason = "stop_loss"
                break

            first_hit = "take_profit"
            exit_price = take_profit
            exit_reason = "take_profit"
            break

        return (
            hit_sl,
            hit_tp,
            first_hit,
            first_hit_date,
            first_hit_days,
            exit_price,
            exit_reason,
        )

    @staticmethod
    def _average(values: Iterable[Optional[float]]) -> Optional[float]:
        items = [float(v) for v in values if v is not None]
        if not items:
            return None
        return round(sum(items) / len(items), 4)

    @staticmethod
    def _compute_advice_breakdown(results: List[BacktestResultLike]) -> Dict[str, Any]:
        breakdown: Dict[str, Dict[str, int]] = {}
        for row in results:
            advice = (row.operation_advice or "").strip() or "(unknown)"
            bucket = breakdown.setdefault(advice, {"total": 0, "win": 0, "loss": 0, "neutral": 0})
            bucket["total"] += 1
            outcome = (row.outcome or "").strip()
            if outcome in ("win", "loss", "neutral"):
                bucket[outcome] += 1

        enriched: Dict[str, Any] = {}
        for advice, bucket in breakdown.items():
            win = bucket["win"]
            loss = bucket["loss"]
            denom = win + loss
            win_rate = round(win / denom * 100, 2) if denom else None
            enriched[advice] = {**bucket, "win_rate_pct": win_rate}
        return enriched

    @staticmethod
    def _compute_diagnostics(results: List[BacktestResultLike]) -> Dict[str, Any]:
        status_counts: Dict[str, int] = {}
        first_hit_counts: Dict[str, int] = {}
        for row in results:
            status = (row.eval_status or "").strip() or "(unknown)"
            status_counts[status] = status_counts.get(status, 0) + 1
            first_hit = (row.first_hit or "").strip() or "(none)"
            first_hit_counts[first_hit] = first_hit_counts.get(first_hit, 0) + 1
        return {
            "eval_status": status_counts,
            "first_hit": first_hit_counts,
        }
