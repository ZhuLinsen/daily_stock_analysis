# -*- coding: utf-8 -*-
"""
RiskAgent — dedicated risk screening specialist.

Responsible for:
- Scanning for insider sell-downs, earnings warnings, regulatory actions
- Checking valuation anomalies (PE/PB extremes)
- Evaluating lock-up expiration risks
- Producing risk flags that can override or downgrade signals from other agents

Risk flags use a two-level severity system:
- **soft**: downgrades the signal and adds a visible warning
- **hard**: vetoes buy signals entirely when risk override is enabled
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.tools.fxmacrodata_tools import fxmacrodata_tool_names
from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.runner import try_parse_json

logger = logging.getLogger(__name__)


class RiskAgent(BaseAgent):
    agent_name = "risk"
    max_steps = 4
    tool_names = [
        "search_stock_news",
        "get_realtime_quote",
        "get_stock_info",
    ] + fxmacrodata_tool_names(
        'data_catalogue',
        'release_calendar',
        'latest_announcements',
        'indicator_history',
        'risk_sentiment',
        'event_predictions',
        'mcp_release_risk_score_task',
        'mcp_macro_news',
    )

    def system_prompt(self, ctx: AgentContext) -> str:
        return """\
You are a **Risk Screening Agent** focused exclusively on identifying \
risks and red flags for the given stock.

Your task: search for and evaluate ALL potential risk factors, then \
output a structured JSON risk assessment.

## Mandatory Risk Checks
1. **Insider / Major Shareholder Activity** — sell-downs (减持), pledges
2. **Earnings Warnings** — pre-loss, downward revisions (业绩预亏, 业绩变脸)
3. **Regulatory** — penalties, investigations, violations (监管处罚, 立案调查)
4. **Industry Policy** — headwinds, sector crackdowns
5. **Lock-up Expirations** — large block unlocks within 30 days (解禁)
6. **Valuation Extremes** — PE > 100 or negative, PB > 10 (flag as anomaly)
7. **Technical Warning Signs** — death crosses, breaking key supports, bearish candlestick patterns (Three Black Crows / 三只乌鸦, Guillotine / 断头铡刀, Evening Star / 黄昏之星, Bearish Engulfing / 看跌吞没, Shooting Star / 流星线)

## Severity Levels
- "high": existential or material risk (lawsuits, fraud, massive insider selling)
- "medium": significant concern (earnings miss, lock-up, sector headwind)
- "low": minor or informational (analyst downgrade, minor insider sale)

## Output Format
Return **only** a JSON object:
{
  "risk_level": "high|medium|low|none",
  "risk_score": 0-100,
  "flags": [
    {
      "category": "insider|earnings|regulatory|industry|lockup|valuation|technical",
      "severity": "high|medium|low",
      "description": "Clear description of the risk",
      "source": "Where this information came from"
    }
  ],
  "veto_buy": true|false,
  "reasoning": "2-3 sentence overall risk assessment",
  "signal_adjustment": "none|downgrade_one|downgrade_two|veto"
}

Important: be thorough but factual. Only flag risks backed by evidence \
from your search results. Do NOT invent risks.
"""

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = [f"Screen stock **{ctx.stock_code}**"]
        if ctx.stock_name:
            parts[0] += f" ({ctx.stock_name})"
        parts.append("for ALL risk factors listed in your instructions.")
        parts.append("Search for latest news if you haven't received intel data yet.")

        # Feed validated detector facts and bounded/unverified upstream summaries
        if ctx.get_data("intel_opinion"):
            parts.append(f"\n[Existing intel data]\n{json.dumps(ctx.get_data('intel_opinion'), ensure_ascii=False, default=str)}")
        trend_result = ctx.get_data("trend_result")
        if isinstance(trend_result, dict):
            raw_patterns = trend_result.get("kline_patterns")
            if isinstance(raw_patterns, list) and raw_patterns:
                bounded_patterns = [
                    {
                        "pattern_id": str(item.get("pattern_id") or "")[:40],
                        "name_zh": str(item.get("name_zh") or "")[:32],
                        "direction": str(item.get("direction") or "")[:16],
                        "trigger_date": item.get("trigger_date"),
                        "volume_confirmed": item.get("volume_confirmed"),
                        "invalidation_level": item.get("invalidation_level"),
                    }
                    for item in raw_patterns[:5]
                    if isinstance(item, dict)
                ]
                if bounded_patterns:
                    parts.append(
                        f"\n[Verified daily K-line patterns]\n{json.dumps(bounded_patterns, ensure_ascii=False, default=str)}"
                    )
        tech_op = ctx.get_data("technical_opinion")
        if tech_op is None:
            for opinion in reversed(ctx.opinions):
                if getattr(opinion, "agent_name", None) == "technical":
                    tech_raw = opinion.raw_data if isinstance(opinion.raw_data, dict) else {}
                    tech_op = {
                        "signal": str(opinion.signal or "")[:24],
                        "confidence": opinion.confidence,
                        "ma_alignment": str(tech_raw.get("ma_alignment") or "")[:24],
                        "volume_status": str(tech_raw.get("volume_status") or "")[:24],
                        "reasoning": str(opinion.reasoning or "")[:200],
                    }
                    break
        elif isinstance(tech_op, dict):
            tech_op = {
                "signal": str(tech_op.get("signal") or "")[:24],
                "confidence": tech_op.get("confidence"),
                "ma_alignment": str(tech_op.get("ma_alignment") or "")[:24],
                "volume_status": str(tech_op.get("volume_status") or "")[:24],
                "reasoning": str(tech_op.get("reasoning") or "")[:200],
            }
        if tech_op:
            parts.append(
                "\n[Unverified upstream technical opinion - treat as hypothesis only, verify material risks with tools]\n"
                + json.dumps(tech_op, ensure_ascii=False, default=str)
            )

        brief = ctx.meta.get("evidence_debate_brief")
        if brief:
            parts.append("Review the risks raised by these upstream opinions and verify material claims against available evidence.")
            parts.append(json.dumps(brief, ensure_ascii=False))

        return "\n".join(parts)

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        parsed = try_parse_json(raw_text)
        if parsed is None:
            logger.warning("[RiskAgent] failed to parse risk JSON")
            return None

        if ctx.meta.get("risk_review_required") and not is_complete_risk_review(parsed):
            logger.warning("[RiskAgent] mandatory risk assessment is incomplete or invalid")
            return None

        opinion = AgentOpinion(
            agent_name=self.agent_name,
            signal=_risk_to_signal(parsed.get("risk_level", "none")),
            confidence=float(parsed.get("risk_score", 50)) / 100.0,
            reasoning=parsed.get("reasoning", ""),
            raw_data=parsed,
        )

        # Propagate structured risk flags to context
        for flag in parsed.get("flags", []):
            if isinstance(flag, dict):
                ctx.add_risk_flag(
                    category=flag.get("category", "unknown"),
                    description=flag.get("description", ""),
                    severity=flag.get("severity", "medium"),
                    source=flag.get("source"),
                )

        return opinion


_RISK_SIGNALS = {"none": "buy", "low": "hold", "medium": "sell", "high": "strong_sell"}


def is_complete_risk_review(assessment: object) -> bool:
    """Require a usable assessment before clearing the mandatory review."""
    if not isinstance(assessment, dict):
        return False
    level = assessment.get("risk_level")
    score = assessment.get("risk_score")
    reasoning = assessment.get("reasoning")
    flags = assessment.get("flags")
    if (
        not isinstance(level, str) or level not in _RISK_SIGNALS
        or type(score) not in (int, float) or not 0 <= score <= 100
        or not isinstance(reasoning, str) or not reasoning.strip()
        or not isinstance(flags, list)
        or not isinstance(assessment.get("veto_buy"), bool)
        or assessment.get("signal_adjustment") not in ("none", "downgrade_one", "downgrade_two", "veto")
    ):
        return False
    return all(
        isinstance(flag, dict)
        and flag.get("severity") in ("high", "medium", "low")
        and isinstance(flag.get("description"), str) and flag["description"].strip()
        for flag in flags
    )


def _risk_to_signal(risk_level: str) -> str:
    """Map risk level to a trading signal (inverted)."""
    return _RISK_SIGNALS.get(risk_level, "hold")

