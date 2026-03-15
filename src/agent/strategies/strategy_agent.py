# -*- coding: utf-8 -*-
"""
StrategyAgent — per-strategy analysis specialist.

Created dynamically by the orchestrator for each selected strategy.
Uses the strategy's YAML instructions as the core prompt, and the
strategy's ``required_tools`` to restrict tool access.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.runner import try_parse_json

logger = logging.getLogger(__name__)


class StrategyAgent(BaseAgent):
    """Agent that evaluates a single trading strategy for a stock.

    Instances are created dynamically by the orchestrator for each
    strategy selected by the :class:`StrategyRouter`.
    """

    max_steps = 4

    def __init__(self, strategy_id: str, **kwargs):
        super().__init__(**kwargs)
        self.strategy_id = strategy_id
        self.agent_name = f"strategy_{strategy_id}"
        self._skill = self._load_skill(strategy_id)

        # Restrict tools to what the strategy declares
        if self._skill and self._skill.required_tools:
            self.tool_names = list(self._skill.required_tools)

    @staticmethod
    def _load_skill(strategy_id: str):
        """Load the Skill definition for a strategy."""
        try:
            from src.agent.factory import get_skill_manager
            sm = get_skill_manager()
            for s in sm.list_skills():
                if s.name == strategy_id:
                    return s
        except Exception as exc:
            logger.warning("[StrategyAgent] failed to load skill '%s': %s", strategy_id, exc)
        return None

    def system_prompt(self, ctx: AgentContext) -> str:
        if self._skill:
            instructions = self._skill.instructions or self._skill.description
            display = self._skill.display_name
        else:
            instructions = f"Evaluate the '{self.strategy_id}' strategy."
            display = self.strategy_id

        return f"""\
You are a **Strategy Evaluation Agent** applying the **{display}** strategy.

## Strategy Instructions
{instructions}

## Task
Evaluate whether the current stock conditions satisfy this strategy's \
entry criteria.  Use tools if needed to verify data points.

## Output Format
Return **only** a JSON object:
{{
  "strategy_id": "{self.strategy_id}",
  "signal": "strong_buy|buy|hold|sell|strong_sell",
  "confidence": 0.0-1.0,
  "conditions_met": ["list of satisfied conditions"],
  "conditions_missed": ["list of unsatisfied conditions"],
  "score_adjustment": -20 to +20,
  "reasoning": "2-3 sentence strategy evaluation"
}}
"""

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = [
            f"Evaluate **{self.strategy_id}** strategy for stock "
            f"**{ctx.stock_code}** ({ctx.stock_name or 'unknown'}).",
        ]
        # Provide existing technical data summary
        if ctx.opinions:
            for op in ctx.opinions:
                if op.agent_name == "technical":
                    parts.append(f"\nTechnical summary: {op.reasoning}")
                    if op.key_levels:
                        parts.append(f"Key levels: {json.dumps(op.key_levels)}")
                    if op.raw_data:
                        parts.append(f"Technical data: {json.dumps(op.raw_data, ensure_ascii=False, default=str)[:2000]}")
        return "\n".join(parts)

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        parsed = try_parse_json(raw_text)
        if parsed is None:
            logger.warning("[StrategyAgent:%s] failed to parse JSON", self.strategy_id)
            return None

        return AgentOpinion(
            agent_name=self.agent_name,
            signal=parsed.get("signal", "hold"),
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=parsed.get("reasoning", ""),
            raw_data=parsed,
        )

