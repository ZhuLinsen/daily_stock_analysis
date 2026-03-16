# -*- coding: utf-8 -*-
"""
Strategy sub-system for multi-agent architecture.

Provides:
- :class:`StrategyAgent` — per-strategy specialist agent
- :class:`StrategyRouter` — rule-based strategy selection
- :class:`StrategyAggregator` — weighted opinion aggregation
"""

from src.agent.strategies.strategy_agent import StrategyAgent
from src.agent.strategies.router import StrategyRouter
from src.agent.strategies.aggregator import StrategyAggregator

__all__ = [
    "StrategyAgent",
    "StrategyRouter",
    "StrategyAggregator",
]
