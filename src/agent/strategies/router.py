# -*- coding: utf-8 -*-
"""
StrategyRouter — rule-based strategy selection.

Selects which strategies to apply based on:
1. User-explicit request (highest priority — bypass router)
2. Market regime detection from technical data in ``AgentContext``
3. Default fallback set

No LLM calls — pure rule evaluation for speed and predictability.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.agent.protocols import AgentContext

logger = logging.getLogger(__name__)

# Mapping from detected market regime → preferred strategy IDs.
# Multiple strategies per regime to allow aggregation.
_REGIME_STRATEGIES: Dict[str, List[str]] = {
    "trending_up": ["bull_trend", "volume_breakout", "ma_golden_cross"],
    "trending_down": ["shrink_pullback", "bottom_volume"],
    "sideways": ["box_oscillation", "shrink_pullback"],
    "volatile": ["chan_theory", "wave_theory"],
    "sector_hot": ["dragon_head", "emotion_cycle"],
}

# Fallback when regime can't be determined
_DEFAULT_STRATEGIES = ["bull_trend", "shrink_pullback"]


class StrategyRouter:
    """Select applicable strategies for a given analysis context.

    Priority order:
    1. ``ctx.meta["strategies_requested"]`` — user explicitly chosen
    2. Market-regime based selection from technical opinions
    3. Default fallback
    """

    def select_strategies(
        self,
        ctx: AgentContext,
        max_count: int = 3,
    ) -> List[str]:
        """Return a list of strategy IDs to evaluate.

        Args:
            ctx: The shared pipeline context (with opinions from prior stages).
            max_count: Maximum number of strategies to return.

        Returns:
            Ordered list of strategy IDs.
        """
        # Priority 1: User-explicit
        user_requested = ctx.meta.get("strategies_requested", [])
        if user_requested:
            logger.info("[StrategyRouter] user-requested strategies: %s", user_requested)
            return user_requested[:max_count]

        # If routing mode is "manual", only use AGENT_SKILLS (already in user_requested);
        # since no explicit request was made, fall back to defaults without regime detection.
        routing_mode = self._get_routing_mode()
        if routing_mode == "manual":
            selected = self._get_manual_strategies(max_count=max_count)
            logger.info("[StrategyRouter] manual mode — using strategies: %s", selected)
            return selected

        # Priority 2: Infer from technical opinion (auto mode)
        regime = self._detect_regime(ctx)
        if regime:
            candidates = _REGIME_STRATEGIES.get(regime, _DEFAULT_STRATEGIES)
            # Filter to only available strategies
            available = self._get_available_ids()
            selected = [s for s in candidates if s in available][:max_count]
            if selected:
                logger.info("[StrategyRouter] regime=%s → strategies: %s", regime, selected)
                return selected

        # Fallback
        logger.info("[StrategyRouter] using default strategies")
        return _DEFAULT_STRATEGIES[:max_count]

    def _detect_regime(self, ctx: AgentContext) -> Optional[str]:
        """Infer market regime from technical agent's opinion data."""
        for op in ctx.opinions:
            if op.agent_name != "technical":
                continue
            raw = op.raw_data or {}

            ma_alignment = raw.get("ma_alignment", "").lower()
            try:
                trend_score = float(raw.get("trend_score", 50))
            except (TypeError, ValueError):
                trend_score = 50.0
            volume_status = raw.get("volume_status", "").lower()

            if ma_alignment == "bullish" and trend_score >= 70:
                return "trending_up"
            if ma_alignment == "bearish" and trend_score <= 30:
                return "trending_down"
            if ma_alignment == "neutral" or 35 <= trend_score <= 65:
                return "sideways"
            if volume_status == "heavy" and 30 < trend_score < 70:
                return "volatile"

        # Check sector context in meta
        if ctx.meta.get("sector_hot"):
            return "sector_hot"

        return None

    @staticmethod
    def _get_routing_mode() -> str:
        """Read the strategy routing mode from config (default: 'auto')."""
        try:
            from src.config import get_config
            config = get_config()
            return getattr(config, "agent_strategy_routing", "auto")
        except Exception:
            return "auto"

    @staticmethod
    def _get_available_ids() -> set:
        """Get the set of strategy IDs available from SkillManager.

        Reads from the cached prototype directly to avoid an unnecessary
        ``deepcopy`` — we only need the skill names (read-only).
        """
        try:
            from src.agent.factory import _SKILL_MANAGER_PROTOTYPE
            if _SKILL_MANAGER_PROTOTYPE is not None:
                return {s.name for s in _SKILL_MANAGER_PROTOTYPE.list_skills()}
            # Prototype not yet initialised — build via get_skill_manager
            from src.agent.factory import get_skill_manager
            sm = get_skill_manager()
            return {s.name for s in sm.list_skills()}
        except Exception:
            return set(_DEFAULT_STRATEGIES)

    @classmethod
    def _get_manual_strategies(cls, max_count: int) -> List[str]:
        """Return strategies configured for manual routing mode."""
        configured: List[str] = []
        try:
            from src.config import get_config
            config = get_config()
            configured = [
                strategy_id
                for strategy_id in getattr(config, "agent_skills", []) or []
                if isinstance(strategy_id, str) and strategy_id
            ]
        except Exception:
            configured = []

        available = cls._get_available_ids()
        selected = [strategy_id for strategy_id in configured if strategy_id in available][:max_count]
        if selected:
            return selected

        fallback = [strategy_id for strategy_id in _DEFAULT_STRATEGIES if strategy_id in available][:max_count]
        return fallback or _DEFAULT_STRATEGIES[:max_count]
