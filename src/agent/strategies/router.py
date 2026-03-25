"""Compatibility wrapper for the legacy strategy router import path."""

from src.agent.skills.router import SkillRouter, StrategyRouter, _DEFAULT_STRATEGIES, _DEFAULT_SKILLS

__all__ = ["SkillRouter", "StrategyRouter", "_DEFAULT_SKILLS", "_DEFAULT_STRATEGIES"]
