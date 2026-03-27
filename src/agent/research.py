# -*- coding: utf-8 -*-
"""
ResearchAgent — deep research specialist for in-depth analysis.

Responsible for:
- Decomposing a complex research query into sub-questions
- Iterative search and information gathering
- Cross-verification of findings
- Producing a structured research report

Triggered by ``/research`` command or API async task interface.
Designed for long-running analysis (up to ``AGENT_DEEP_RESEARCH_BUDGET``
tokens).
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.runner import RunLoopResult, run_agent_loop
from src.agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Default token budget for deep research
_DEFAULT_TOKEN_BUDGET = 30000


class ResearchAgent:
    """Multi-turn deep research agent.

    Unlike the standard agent loop which runs a fixed number of steps,
    the ResearchAgent:
    1. Decomposes the query into sub-questions (planning phase)
    2. Researches each sub-question with dedicated searches
    3. Synthesises findings into a comprehensive report
    4. Tracks total token usage against a configurable budget
    """

    agent_name = "research"
    tool_names = [
        "search_stock_news",
        "search_comprehensive_intel",
        "get_stock_info",
        "get_realtime_quote",
        "get_daily_history",
        "get_sector_rankings",
        "get_market_indices",
    ]

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMToolAdapter,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        max_sub_questions: int = 5,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.token_budget = token_budget
        self.max_sub_questions = max_sub_questions

    def research(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> ResearchResult:
        """Execute a deep research task.

        Args:
            query: The research question or topic.
            context: Optional context (stock_code, stock_name, etc.).
            progress_callback: Optional progress updates.
            timeout_seconds: Optional overall time budget for the whole
                research task.

        Returns:
            A :class:`ResearchResult` containing the report and metadata.
        """
        started_at = time.monotonic()
        tokens_used = 0
        all_findings: List[Dict[str, Any]] = []
        questions: List[str] = [query]

        # Phase 1: Decompose
        if self._is_timed_out(started_at, timeout_seconds):
            return self._build_timeout_result(
                query=query,
                questions=questions,
                findings_count=0,
                total_tokens=tokens_used,
                duration_s=round(time.monotonic() - started_at, 2),
                timeout_seconds=timeout_seconds,
            )
        if progress_callback:
            progress_callback({"type": "research_phase", "phase": "decompose", "message": "Decomposing research query..."})

        sub_questions = self._decompose_query(
            query,
            context,
            timeout_seconds=self._remaining_timeout_seconds(started_at, timeout_seconds),
        )
        tokens_used += sub_questions.get("tokens", 0)

        questions = sub_questions.get("questions", [query])[:self.max_sub_questions]
        if sub_questions.get("timed_out"):
            return self._build_timeout_result(
                query=query,
                questions=questions,
                findings_count=0,
                total_tokens=tokens_used,
                duration_s=round(time.monotonic() - started_at, 2),
                timeout_seconds=timeout_seconds,
            )
        logger.info("[ResearchAgent] decomposed into %d sub-questions", len(questions))

        # Phase 2: Research each sub-question
        for i, question in enumerate(questions):
            if self._is_timed_out(started_at, timeout_seconds):
                return self._build_timeout_result(
                    query=query,
                    questions=questions,
                    findings_count=len(all_findings),
                    total_tokens=tokens_used,
                    duration_s=round(time.monotonic() - started_at, 2),
                    timeout_seconds=timeout_seconds,
                )
            if tokens_used >= self.token_budget:
                logger.warning("[ResearchAgent] token budget exceeded (%d/%d), stopping", tokens_used, self.token_budget)
                break

            if progress_callback:
                progress_callback({
                    "type": "research_phase",
                    "phase": "search",
                    "message": f"Researching ({i + 1}/{len(questions)}): {question[:60]}...",
                    "progress": (i + 1) / len(questions),
                })

            finding = self._research_sub_question(
                question,
                context,
                tokens_used,
                timeout_seconds=self._remaining_timeout_seconds(started_at, timeout_seconds),
            )
            tokens_used += finding.get("tokens", 0)
            if finding.get("timed_out"):
                return self._build_timeout_result(
                    query=query,
                    questions=questions,
                    findings_count=len(all_findings),
                    total_tokens=tokens_used,
                    duration_s=round(time.monotonic() - started_at, 2),
                    timeout_seconds=timeout_seconds,
                )
            all_findings.append(finding)

        # Phase 3: Synthesise
        if self._is_timed_out(started_at, timeout_seconds):
            return self._build_timeout_result(
                query=query,
                questions=questions,
                findings_count=len(all_findings),
                total_tokens=tokens_used,
                duration_s=round(time.monotonic() - started_at, 2),
                timeout_seconds=timeout_seconds,
            )
        if progress_callback:
            progress_callback({"type": "research_phase", "phase": "synthesize", "message": "Synthesising research report..."})

        report = (
            self._synthesise_report(
                query,
                all_findings,
                context,
                timeout_seconds=self._remaining_timeout_seconds(started_at, timeout_seconds),
            )
            if all_findings
            else {"content": "No findings gathered.", "tokens": 0}
        )
        tokens_used += report.get("tokens", 0)
        if report.get("timed_out"):
            return self._build_timeout_result(
                query=query,
                questions=questions,
                findings_count=len(all_findings),
                total_tokens=tokens_used,
                duration_s=round(time.monotonic() - started_at, 2),
                timeout_seconds=timeout_seconds,
            )

        duration = round(time.monotonic() - started_at, 2)

        return ResearchResult(
            success=not report.get("error"),
            report=report.get("content", ""),
            sub_questions=questions,
            findings_count=len(all_findings),
            total_tokens=tokens_used,
            duration_s=duration,
            error=report.get("error"),
        )

    @staticmethod
    def _remaining_timeout_seconds(started_at: float, timeout_seconds: Optional[float]) -> Optional[float]:
        """Return remaining overall time budget for the research task."""
        if timeout_seconds is None:
            return None
        return max(0.0, float(timeout_seconds) - (time.monotonic() - started_at))

    @staticmethod
    def _is_timed_out(started_at: float, timeout_seconds: Optional[float]) -> bool:
        """Return whether the overall research deadline has been exceeded."""
        remaining = ResearchAgent._remaining_timeout_seconds(started_at, timeout_seconds)
        return remaining is not None and remaining <= 0

    @staticmethod
    def _resolve_step_timeout(default_timeout: int, timeout_seconds: Optional[float]) -> Optional[int]:
        """Clamp one stage timeout to the remaining overall research budget."""
        if timeout_seconds is None:
            return default_timeout
        if timeout_seconds <= 0:
            return None
        return max(1, math.ceil(min(float(default_timeout), float(timeout_seconds))))

    @staticmethod
    def _looks_like_timeout_error(error: Any) -> bool:
        """Best-effort detection for timeout-like failures from lower layers."""
        message = str(error or "").lower()
        return "timed out" in message or "timeout" in message

    @staticmethod
    def _build_timeout_result(
        *,
        query: str,
        questions: List[str],
        findings_count: int,
        total_tokens: int,
        duration_s: float,
        timeout_seconds: Optional[float],
    ) -> ResearchResult:
        """Build a structured timeout result without leaving detached work behind."""
        timeout_label = f"{timeout_seconds}s" if timeout_seconds is not None else "the configured limit"
        logger.warning("[ResearchAgent] timed out after %s for query: %s", timeout_label, query[:120])
        return ResearchResult(
            success=False,
            report="",
            sub_questions=questions,
            findings_count=findings_count,
            total_tokens=total_tokens,
            duration_s=duration_s,
            error=f"Deep research timed out after {timeout_label}",
            timed_out=True,
        )

    def _call_text_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        timeout: int,
    ) -> Dict[str, Any]:
        """Run a text-only LLM completion via the shared adapter."""
        response = self.llm_adapter.call_text(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        if response.provider == "error":
            raise RuntimeError(response.content or "LLM completion failed")
        return {
            "content": (response.content or "").strip(),
            "tokens": response.usage.get("total_tokens", 0),
        }

    def _decompose_query(
        self,
        query: str,
        context: Optional[Dict[str, Any]],
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Use LLM to decompose a research query into sub-questions."""
        stock_hint = ""
        if context and context.get("stock_code"):
            stock_hint = f"\nStock context: {context['stock_code']} ({context.get('stock_name', '')})"

        system = """\
You are a research planning assistant. Given a research query, decompose it \
into 3-5 specific, searchable sub-questions.

Return a JSON object:
{"questions": ["question 1", "question 2", ...]}
"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Research query: {query}{stock_hint}"},
        ]

        try:
            step_timeout = self._resolve_step_timeout(15, timeout_seconds)
            if step_timeout is None:
                return {"questions": [query], "tokens": 0, "timed_out": True}
            completion = self._call_text_completion(
                messages,
                temperature=0.3,
                max_tokens=400,
                timeout=step_timeout,
            )
            raw = completion["content"]
            tokens = completion["tokens"]

            # Parse JSON
            if raw.startswith("```"):
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
            parsed = json.loads(raw)
            return {"questions": parsed.get("questions", [query]), "tokens": tokens}
        except Exception as exc:
            logger.warning("[ResearchAgent] decompose failed: %s", exc)
            if timeout_seconds is not None and self._looks_like_timeout_error(exc):
                return {"questions": [query], "tokens": 0, "timed_out": True, "error": str(exc)}
            return {"questions": [query], "tokens": 0}

    def _research_sub_question(
        self,
        question: str,
        context: Optional[Dict[str, Any]],
        current_tokens: int,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Research a single sub-question using the agent loop."""
        if timeout_seconds is not None and timeout_seconds <= 0:
            return {
                "question": question,
                "content": "",
                "tokens": 0,
                "success": False,
                "timed_out": True,
                "error": "Deep research timed out before sub-question execution",
            }
        remaining_budget = self.token_budget - current_tokens

        system = f"""\
You are a research agent investigating a specific question.
Use your tools to search for relevant information, then summarise \
your findings in 2-4 paragraphs.  Be factual and cite sources.
Token budget remaining: ~{remaining_budget}
"""
        stock_context = ""
        if context and context.get("stock_code"):
            stock_context = f" (related to stock {context['stock_code']})"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Research question: {question}{stock_context}"},
        ]

        try:
            registry = self._filtered_registry()
            result: RunLoopResult = run_agent_loop(
                messages=messages,
                tool_registry=registry,
                llm_adapter=self.llm_adapter,
                max_steps=4,
                max_wall_clock_seconds=timeout_seconds,
                tool_call_timeout_seconds=timeout_seconds,
            )
            if not result.success and self._looks_like_timeout_error(result.error):
                return {
                    "question": question,
                    "content": "",
                    "tokens": result.total_tokens,
                    "success": False,
                    "timed_out": True,
                    "error": result.error,
                }
            return {
                "question": question,
                "content": result.content,
                "tokens": result.total_tokens,
                "success": result.success,
            }
        except Exception as exc:
            logger.warning("[ResearchAgent] sub-question failed: %s", exc)
            if timeout_seconds is not None and self._looks_like_timeout_error(exc):
                return {
                    "question": question,
                    "content": "",
                    "tokens": 0,
                    "success": False,
                    "timed_out": True,
                    "error": str(exc),
                }
            return {"question": question, "content": "", "tokens": 0, "success": False, "error": str(exc)}

    def _synthesise_report(
        self,
        original_query: str,
        findings: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Synthesise all findings into a coherent research report."""
        findings_text = "\n\n".join(
            f"### Sub-question: {f['question']}\n{f.get('content', 'No data')}"
            for f in findings if f.get("content")
        )

        system = """\
You are a senior research analyst. Synthesise the following research \
findings into a comprehensive, well-structured report.

## Report Structure
1. **Executive Summary** (2-3 sentences)
2. **Key Findings** (bullet points)
3. **Detailed Analysis** (sections per topic)
4. **Risk Factors** (if applicable)
5. **Conclusion & Recommendations**

Use Markdown formatting.  Be concise but thorough.
"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Original query: {original_query}\n\n## Research Findings\n\n{findings_text}"},
        ]

        try:
            step_timeout = self._resolve_step_timeout(30, timeout_seconds)
            if step_timeout is None:
                return {"content": "", "tokens": 0, "timed_out": True}
            completion = self._call_text_completion(
                messages,
                temperature=0.3,
                max_tokens=2000,
                timeout=step_timeout,
            )
            content = completion["content"]
            tokens = completion["tokens"]
            return {"content": content, "tokens": tokens}
        except Exception as exc:
            logger.warning("[ResearchAgent] synthesis failed: %s", exc)
            if timeout_seconds is not None and self._looks_like_timeout_error(exc):
                return {"content": "", "tokens": 0, "timed_out": True, "error": str(exc)}
            return {"content": findings_text, "tokens": 0, "error": str(exc)}

    def _filtered_registry(self) -> ToolRegistry:
        """Return a registry restricted to research-related tools.

        Reuses the same filtering logic as :meth:`BaseAgent._filtered_registry`.
        """
        from src.agent.agents.base_agent import BaseAgent
        # Borrow the shared implementation; it respects self.tool_names / self.tool_registry.
        return BaseAgent._filtered_registry(self)


@dataclass
class ResearchResult:
    """Output from a deep research task."""

    success: bool = False
    report: str = ""
    sub_questions: List[str] = field(default_factory=list)
    findings_count: int = 0
    total_tokens: int = 0
    duration_s: float = 0.0
    error: Optional[str] = None
    timed_out: bool = False
