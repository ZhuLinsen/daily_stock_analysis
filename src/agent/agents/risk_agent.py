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

from src.agent.agents.base_agent import BaseAgent, coerce_confidence, coerce_finite_float, coerce_text
from src.report_language import normalize_report_language
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
        lang = normalize_report_language(ctx.meta.get("report_language", "zh"))
        lang_section = self._format_json_output_language_instruction(
            ctx,
            enum_fields="risk_level, signal_adjustment, flags[].category, flags[].severity, veto_buy",
        )
        if lang == "zh":
            checks = """\
1. **Insider / Major Shareholder Activity** — sell-downs (减持), pledges
2. **Earnings Warnings** — pre-loss, downward revisions (业绩预亏, 业绩变脸)
3. **Regulatory** — penalties, investigations, violations (监管处罚, 立案调查)
4. **Industry Policy** — headwinds, sector crackdowns
5. **Lock-up Expirations** — large block unlocks within 30 days (解禁)"""
        else:
            checks = """\
1. **Insider / Major Shareholder Activity** — sell-downs, share pledges
2. **Earnings Warnings** — pre-loss notices, downward earnings revisions
3. **Regulatory** — penalties, investigations, compliance violations
4. **Industry Policy** — headwinds, sector crackdowns
5. **Lock-up Expirations** — large block share unlocks within 30 days"""
        return f"""\
You are a **Risk Screening Agent** focused exclusively on identifying \
risks and red flags for the given stock.

Your task: search for and evaluate ALL potential risk factors, then \
output a structured JSON risk assessment.

## Mandatory Risk Checks
{checks}
6. **Valuation Extremes** — PE > 100 or negative, PB > 10 (flag as anomaly)
7. **Technical Warning Signs** — death crosses, breaking key supports

## Severity Levels
- "high": existential or material risk (lawsuits, fraud, massive insider selling)
- "medium": significant concern (earnings miss, lock-up, sector headwind)
- "low": minor or informational (analyst downgrade, minor insider sale)

## Output Format
Return **only** a JSON object:
{{
  "risk_level": "high|medium|low|none",
  "risk_score": 0-100,
  "flags": [
    {{
      "category": "insider|earnings|regulatory|industry|lockup|valuation|technical",
      "severity": "high|medium|low",
      "description": "Clear description of the risk",
      "source": "Where this information came from"
    }}
  ],
  "veto_buy": true|false,
  "reasoning": "2-3 sentence overall risk assessment",
  "signal_adjustment": "none|downgrade_one|downgrade_two|veto"
}}

Important: be thorough but factual. Only flag risks backed by evidence \
from your search results. Do NOT invent risks.
""" + lang_section

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = [f"Screen stock **{ctx.stock_code}**"]
        if ctx.stock_name:
            parts[0] += f" ({ctx.stock_name})"
        parts.append("for ALL risk factors listed in your instructions.")
        parts.append("Search for latest news if you haven't received intel data yet.")

        # Feed any existing intel data so the risk agent doesn't redo searches
        if ctx.get_data("intel_opinion"):
            parts.append(f"\n[Existing intel data]\n{json.dumps(ctx.get_data('intel_opinion'), ensure_ascii=False, default=str)}")

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

        confidence, conf_valid = coerce_confidence(
            parsed.get("risk_score"),
            default=0.5,
            scale=100.0,
            present=("risk_score" in parsed),
        )
        reasoning = coerce_text(parsed.get("reasoning"), default="")
        opinion = AgentOpinion(
            agent_name=self.agent_name,
            signal=_risk_to_signal(parsed.get("risk_level")),
            confidence=confidence,
            reasoning=reasoning,
            raw_data=parsed,
        )
        if not conf_valid:
            opinion._confidence_input_valid = False

        # Propagate structured risk flags to context
        flags = parsed.get("flags")
        if isinstance(flags, list):
            for flag in flags:
                if not isinstance(flag, dict):
                    continue
                category = coerce_text(flag.get("category"), default="unknown", fallback_on_empty=True).strip() or "unknown"
                description = coerce_text(flag.get("description"), default="")
                severity = coerce_text(flag.get("severity"), default="medium", fallback_on_empty=True).strip().lower() or "medium"
                source = flag.get("source")
                ctx.add_risk_flag(
                    category=category,
                    description=description,
                    severity=severity,
                    source=source.strip() if isinstance(source, str) and source.strip() else None,
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
        or type(score) not in (int, float)
        or coerce_finite_float(score) is None
        or not 0 <= score <= 100
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


def _risk_to_signal(risk_level: object) -> str:
    """Map risk level to a trading signal (inverted)."""
    if not isinstance(risk_level, str):
        return "hold"
    return _RISK_SIGNALS.get(risk_level.strip().lower(), "hold")

