# -*- coding: utf-8 -*-
"""
PortfolioAgent — analyses a *set* of stocks as a whole portfolio,
rather than one-by-one.

Responsibilities:
- Position sizing suggestions (equal-weight / volatility-adjusted)
- Correlation & sector concentration warnings
- Portfolio-level risk metrics (beta, drawdown, sector exposure)
- Cross-market linkage (A-share ↔ HK ↔ US spillover)

The PortfolioAgent consumes pre-computed per-stock opinions
(from the normal orchestrator pipeline) and overlays portfolio
analytics.

Typical usage::

    from src.agent.agents.portfolio_agent import PortfolioAgent
    agent = PortfolioAgent(model=model, registry=registry)
    result = agent.run(ctx)
"""

from __future__ import annotations

import logging
from typing import Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.runner import try_parse_json

logger = logging.getLogger(__name__)


class PortfolioAgent(BaseAgent):
    """Portfolio-level analysis agent.

    This agent operates *after* per-stock analysis is already done.
    It reads per-stock opinions from ``ctx.data["stock_opinions"]``
    (a dict of stock_code → opinion) and produces a portfolio-level
    assessment.
    """

    agent_name = "portfolio"
    description = "Portfolio-level risk and allocation analysis"

    tool_names = [
        "get_realtime_quote",
        "get_stock_info",
    ]

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def system_prompt(self, ctx: AgentContext) -> str:
        return (
            "You are a professional **portfolio analyst** specializing in "
            "multi-asset allocation for A-share, HK, and US equity portfolios.\n\n"
            "## Your task\n"
            "Given individual stock analysis opinions, produce a **Portfolio Assessment** "
            "that covers:\n"
            "1. **Position Sizing** — suggested weight per stock (equal-weight baseline, "
            "adjusted by conviction and volatility).\n"
            "2. **Sector Concentration** — warn if > 40% in one sector.\n"
            "3. **Correlation Risk** — flag highly correlated pairs.\n"
            "4. **Cross-Market Linkage** — note HK/US spill-over effects on A-shares.\n"
            "5. **Portfolio Risk Score** — 1-10 scale.\n"
            "6. **Rebalance Suggestions** — trim/add recommendations.\n\n"
            "## Output format\n"
            "Return a single JSON object:\n"
            "```json\n"
            "{\n"
            '  "portfolio_risk_score": 6,\n'
            '  "total_stocks": 5,\n'
            '  "positions": [\n'
            '    {"code": "600519", "suggested_weight": 0.25, "signal": "buy", "note": "..."},\n'
            "    ...\n"
            "  ],\n"
            '  "sector_warnings": ["Consumer sector > 40%"],\n'
            '  "correlation_warnings": ["600519 & 000858 high correlation"],\n'
            '  "cross_market_notes": ["US tariff risk may impact export-heavy positions"],\n'
            '  "rebalance_suggestions": ["Trim 000858, add defensive sector exposure"],\n'
            '  "summary": "Portfolio is moderately concentrated ..."\n'
            "}\n"
            "```\n"
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        # Gather per-stock opinions from context
        stock_opinions = ctx.data.get("stock_opinions", {})
        stock_list = ctx.data.get("stock_list", [])

        parts = [f"Analyze the following portfolio of {len(stock_list) or len(stock_opinions)} stocks:\n"]

        if stock_opinions:
            for code, opinion in stock_opinions.items():
                if isinstance(opinion, AgentOpinion):
                    parts.append(
                        f"- **{code}**: signal={opinion.signal}, "
                        f"confidence={opinion.confidence:.0%}, "
                        f"summary={opinion.reasoning[:200]}"
                    )
                elif isinstance(opinion, dict):
                    parts.append(
                        f"- **{code}**: signal={opinion.get('signal', 'unknown')}, "
                        f"confidence={opinion.get('confidence', 'N/A')}, "
                        f"summary={str(opinion.get('summary', ''))[:200]}"
                    )
        elif stock_list:
            for code in stock_list:
                parts.append(f"- {code}")

        # Include risk flags if any
        if ctx.risk_flags:
            parts.append("\n### Risk Flags from Individual Analysis:")
            for flag in ctx.risk_flags:
                parts.append(f"- ⚠️ {flag}")

        if ctx.query:
            parts.append(f"\nUser request: {ctx.query}")

        return "\n".join(parts)

    def post_process(self, ctx: AgentContext, raw_response: str) -> Optional[AgentOpinion]:
        """Extract portfolio assessment and store in context."""
        data = try_parse_json(raw_response)
        if data is None:
            logger.debug("[PortfolioAgent] post_process: failed to parse JSON")
            return AgentOpinion(
                agent_name="portfolio",
                signal="hold",
                confidence=0.3,
                reasoning=raw_response[:500],
                raw_data={"raw": raw_response[:1000]},
            )

        # Store portfolio assessment in context
        ctx.data["portfolio_assessment"] = data

        risk_score = data.get("portfolio_risk_score", 5)
        signal = "hold"
        if risk_score <= 3:
            signal = "buy"
        elif risk_score >= 7:
            signal = "sell"

        return AgentOpinion(
            agent_name="portfolio",
            signal=signal,
            confidence=0.6,
            reasoning=data.get("summary", raw_response[:300]),
            raw_data=data,
        )
