# -*- coding: utf-8 -*-
"""
AgentMemory — persistent structured memory for agent learning.

Provides:
1. **Analysis memory** — stores past analysis results with outcomes,
   enabling agents to learn from their own track record.
2. **Confidence calibration** — adjusts agent confidence based on
   historical accuracy (only after sufficient sample count).
3. **Skill performance tracking** — per-skill win-rate and
   signal accuracy for auto-weighting.

Storage uses the existing SQLAlchemy database layer
(``AnalysisHistory`` + ``BacktestResult`` tables) rather than
introducing a new store.

.. note::
   Memory features are gated behind ``AGENT_MEMORY_ENABLED=true``.
   When disabled, all methods return neutral/default values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default minimum samples before calibration kicks in
_MIN_CALIBRATION_SAMPLES = 30
# Rolling window size for recent accuracy calculation
_ROLLING_WINDOW = 50


@dataclass
class CalibrationResult:
    """Confidence calibration data for an agent or skill."""
    agent_name: str = ""
    total_samples: int = 0
    historical_accuracy: float = 0.5  # 0.0–1.0
    direction_accuracy: float = 0.5
    avg_confidence: float = 0.5
    calibrated: bool = False  # True if samples >= threshold
    calibration_factor: float = 1.0  # multiply raw confidence by this


@dataclass
class AnalysisMemoryEntry:
    """A remembered past analysis for context injection."""
    stock_code: str = ""
    date: str = ""
    signal: str = ""
    sentiment_score: int = 50
    price_at_analysis: float = 0.0
    outcome_5d: Optional[float] = None  # % change after 5 days
    outcome_20d: Optional[float] = None  # % change after 20 days
    was_correct: Optional[bool] = None


@dataclass
class DecisionSignalReview:
    """Pre-summarized decision-signal review for one stock (read-only).

    Consumed from the service-layer ReviewMemory aggregation; never mixes
    into the ``AnalysisHistory`` text section.  ``confidence_adjustment`` of
    ``observe`` means the evidence base is too weak for any confidence shift
    and the payload is a caution note only.
    """
    stock_code: str = ""
    sample_size: int = 0
    completed: int = 0
    hit_rate_pct: Optional[float] = None
    avg_return_pct: Optional[float] = None
    common_miss_reasons: List[str] = field(default_factory=list)
    confidence_adjustment: str = "observe"
    notes: str = ""

    def to_prompt_line(self) -> str:
        """Render one compact line for prompt injection."""
        parts = [
            f"stock={self.stock_code}",
            f"completed={self.completed}",
            f"sample={self.sample_size}",
        ]
        if self.confidence_adjustment != "observe" and self.hit_rate_pct is not None:
            parts.append(f"hit_rate={self.hit_rate_pct}%")
            if self.avg_return_pct is not None:
                parts.append(f"avg_return={self.avg_return_pct}%")
        parts.append(f"adjustment={self.confidence_adjustment}")
        if self.common_miss_reasons:
            parts.append("miss_reasons=" + "/".join(self.common_miss_reasons))
        if self.notes:
            parts.append(f"note={self.notes}")
        return ", ".join(parts)


class AgentMemory:
    """Structured memory system for agent self-improvement.

    Usage::

        memory = AgentMemory()
        # Get past analyses for context
        past = memory.get_stock_history("600519", limit=5)
        # Calibrate confidence
        cal = memory.get_calibration("technical", stock_code="600519")
    """

    def __init__(self, enabled: bool = False, min_samples: int = _MIN_CALIBRATION_SAMPLES):
        self.enabled = enabled
        self.min_samples = min_samples

    @classmethod
    def from_config(cls) -> "AgentMemory":
        """Create an AgentMemory from the current config."""
        try:
            from src.config import get_config
            config = get_config()
            enabled = getattr(config, "agent_memory_enabled", False)
            return cls(enabled=enabled)
        except Exception:
            return cls(enabled=False)

    # -----------------------------------------------------------------
    # Analysis history retrieval
    # -----------------------------------------------------------------

    def get_stock_history(
        self,
        stock_code: str,
        limit: int = 5,
    ) -> List[AnalysisMemoryEntry]:
        """Retrieve recent analysis results for a stock.

        Returns structured entries that can be injected into agent
        context for learning from past predictions.
        """
        if not self.enabled:
            return []

        try:
            from src.storage import get_db
            db = get_db()
            records = db.get_analysis_history(code=stock_code, limit=limit)
            entries = []
            for r in records:
                raw_result: Dict[str, Any] = {}
                if isinstance(getattr(r, "raw_result", None), str) and r.raw_result:
                    try:
                        parsed = json.loads(r.raw_result)
                        if isinstance(parsed, dict):
                            raw_result = parsed
                    except (TypeError, ValueError):
                        raw_result = {}
                elif isinstance(getattr(r, "raw_result", None), dict):
                    raw_result = dict(r.raw_result)

                signal = raw_result.get("decision_type") or getattr(r, "operation_advice", "") or "hold"
                price_at_analysis = raw_result.get("current_price")
                if price_at_analysis is None:
                    price_at_analysis = 0.0

                entries.append(AnalysisMemoryEntry(
                    stock_code=stock_code,
                    date=(r.created_at.date().isoformat() if getattr(r, "created_at", None) else ""),
                    signal=signal,
                    sentiment_score=getattr(r, "sentiment_score", 50) or 50,
                    price_at_analysis=float(price_at_analysis or 0.0),
                    was_correct=None,
                ))
            return entries
        except Exception as exc:
            logger.debug("[AgentMemory] get_stock_history failed: %s", exc)
            return []

    # -----------------------------------------------------------------
    # Decision-signal review (read-only feedback loop, Issue #1903)
    # -----------------------------------------------------------------

    def get_decision_signal_review(self, stock_code: str) -> Optional[DecisionSignalReview]:
        """Return the pre-summarized decision-signal review for one stock.

        The aggregation lives in the service layer (ReviewMemory contract);
        this method only maps the payload for agent consumption.  Returns
        ``None`` when memory is disabled, the stock code is missing, or the
        review cannot be computed — callers must treat ``None`` as "no review
        section", preserving pre-existing behaviour.
        """
        if not self.enabled or not stock_code:
            return None
        try:
            from src.services.decision_signal_outcome_service import (
                DecisionSignalOutcomeService,
            )
            payload = DecisionSignalOutcomeService().get_stock_review(stock_code)
            return DecisionSignalReview(
                stock_code=str(payload.get("stock_code") or stock_code),
                sample_size=int(payload.get("sample_size") or 0),
                completed=int(payload.get("completed") or 0),
                hit_rate_pct=payload.get("hit_rate_pct"),
                avg_return_pct=payload.get("avg_return_pct"),
                common_miss_reasons=list(payload.get("common_miss_reasons") or []),
                confidence_adjustment=str(payload.get("confidence_adjustment") or "observe"),
                notes=str(payload.get("notes") or ""),
            )
        except Exception as exc:
            logger.debug("[AgentMemory] get_decision_signal_review failed: %s", exc)
            return None

    # -----------------------------------------------------------------
    # Confidence calibration
    # -----------------------------------------------------------------

    def get_calibration(
        self,
        agent_name: str,
        stock_code: Optional[str] = None,
        skill_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
    ) -> CalibrationResult:
        """Compute confidence calibration for an agent or skill.

        When ``AGENT_MEMORY_ENABLED=false`` or insufficient samples,
        returns a neutral calibration (factor = 1.0).
        """
        result = CalibrationResult(agent_name=agent_name)

        if not self.enabled:
            return result

        try:
            resolved_skill_id = skill_id or strategy_id
            stats = self._get_accuracy_stats(agent_name, stock_code, resolved_skill_id)
            result.total_samples = stats.get("total", 0)
            result.historical_accuracy = stats.get("accuracy", 0.5)
            result.direction_accuracy = stats.get("direction_accuracy", 0.5)
            result.avg_confidence = stats.get("avg_confidence", 0.5)

            if result.total_samples >= self.min_samples:
                result.calibrated = True
                # Calibration: scale confidence towards historical accuracy
                # If agent is overconfident: factor < 1
                # If agent is underconfident: factor > 1
                if result.avg_confidence > 0:
                    result.calibration_factor = min(
                        1.5,
                        max(0.5, result.historical_accuracy / result.avg_confidence),
                    )
                else:
                    result.calibration_factor = 1.0
            else:
                result.calibrated = False
                result.calibration_factor = 1.0

        except Exception as exc:
            logger.debug("[AgentMemory] calibration failed for %s: %s", agent_name, exc)

        return result

    def calibrate_confidence(self, agent_name: str, raw_confidence: float, stock_code: Optional[str] = None) -> float:
        """Apply calibration to a raw confidence value.

        Returns the adjusted confidence, clamped to [0.0, 1.0].
        """
        cal = self.get_calibration(agent_name, stock_code=stock_code)
        if not cal.calibrated:
            return raw_confidence
        adjusted = raw_confidence * cal.calibration_factor
        return max(0.0, min(1.0, adjusted))

    # -----------------------------------------------------------------
    # Skill performance
    # -----------------------------------------------------------------

    def get_skill_performance(self, skill_id: str) -> Dict[str, Any]:
        """Get performance metrics for a skill.

        Used by :class:`SkillAggregator` for weight computation.
        """
        if not self.enabled:
            return {"available": False}

        try:
            from src.services.backtest_service import BacktestService
            service = BacktestService()
            summary = service.get_skill_summary(skill_id)
            if summary:
                return {
                    "available": True,
                    "win_rate": summary.get("win_rate", 0.5),
                    "total_evaluations": summary.get("total_evaluations", 0),
                    "avg_return": summary.get("avg_return", 0.0),
                    "direction_accuracy": summary.get("direction_accuracy", 0.5),
                    "sufficient_samples": summary.get("total_evaluations", 0) >= self.min_samples,
                }
            return {"available": False}
        except Exception:
            return {"available": False}

    def get_strategy_performance(self, strategy_id: str) -> Dict[str, Any]:
        """Compatibility wrapper for legacy strategy-based callers."""
        return self.get_skill_performance(strategy_id)

    # -----------------------------------------------------------------
    # Auto-weighting
    # -----------------------------------------------------------------

    def compute_skill_weights(
        self,
        skill_ids: List[str],
        use_backtest: bool = True,
    ) -> Dict[str, float]:
        """Compute normalized weights for a set of skills.

        Skills with higher historical performance get higher weights.
        Skills with insufficient samples get neutral weight (1.0).

        Returns:
            Dict mapping skill_id → weight (normalized so mean ≈ 1.0)
        """
        if not self.enabled or not use_backtest:
            return {sid: 1.0 for sid in skill_ids}

        raw_weights: Dict[str, float] = {}
        for sid in skill_ids:
            perf = self.get_skill_performance(sid)
            if perf.get("sufficient_samples"):
                # Weight = 0.5 + win_rate (range: 0.5 to 1.5)
                raw_weights[sid] = 0.5 + perf.get("win_rate", 0.5)
            else:
                raw_weights[sid] = 1.0

        # Normalize so mean = 1.0
        if raw_weights:
            mean_w = sum(raw_weights.values()) / len(raw_weights)
            if mean_w > 0:
                return {sid: w / mean_w for sid, w in raw_weights.items()}

        return {sid: 1.0 for sid in skill_ids}

    def compute_strategy_weights(
        self,
        strategy_ids: List[str],
        use_backtest: bool = True,
    ) -> Dict[str, float]:
        """Compatibility wrapper for legacy strategy-based callers."""
        return self.compute_skill_weights(strategy_ids, use_backtest=use_backtest)

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _get_accuracy_stats(
        self,
        agent_name: str,
        stock_code: Optional[str],
        skill_id: Optional[str],
    ) -> Dict[str, Any]:
        """Aggregate accuracy statistics from backtest history."""
        try:
            from src.services.backtest_service import BacktestService
            service = BacktestService()

            if skill_id:
                summary = service.get_skill_summary(skill_id)
            elif stock_code:
                summary = service.get_stock_summary(stock_code)
            else:
                # Global summary across all analyses
                summary = service.get_global_summary() if hasattr(service, "get_global_summary") else None

            if summary:
                return {
                    "total": summary.get("total_evaluations", 0),
                    "accuracy": summary.get("win_rate", 0.5),
                    "direction_accuracy": summary.get("direction_accuracy", 0.5),
                    "avg_confidence": 0.6,  # approximate from historical data
                }
        except Exception:
            pass
        return {"total": 0, "accuracy": 0.5, "direction_accuracy": 0.5, "avg_confidence": 0.5}
