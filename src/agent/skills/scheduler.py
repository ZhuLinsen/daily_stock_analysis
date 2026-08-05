# -*- coding: utf-8 -*-
"""
Concurrent scheduler for specialist strategy-skill agents.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
logger = logging.getLogger(__name__)

RunStageCallable = Callable[[Any, AgentContext, Optional[Callable], Optional[float]], StageResult]


@dataclass
class SkillBatchResult:
    stage_results: List[StageResult] = field(default_factory=list)
    opinions: List[AgentOpinion] = field(default_factory=list)
    invalid_records: List[Dict[str, Any]] = field(default_factory=list)
    max_concurrency: int = 1
    timeout_per_skill: float = 0.0


class AgentSkillScheduler:
    """Run selected skill agents concurrently without sharing mutable context writes."""

    def __init__(self, *, max_concurrency: int = 3, timeout_per_skill: float = 0.0) -> None:
        self.max_concurrency = _clamp_int(max_concurrency, minimum=1, maximum=4)
        self.timeout_per_skill = max(0.0, float(timeout_per_skill or 0.0))

    def run(
        self,
        agents: List[Any],
        ctx: AgentContext,
        run_stage: RunStageCallable,
        *,
        progress_callback: Optional[Callable] = None,
    ) -> SkillBatchResult:
        selected_agents = list(agents)
        if not selected_agents:
            return SkillBatchResult(
                max_concurrency=self.max_concurrency,
                timeout_per_skill=self.timeout_per_skill,
            )

        stage_results_by_index: Dict[int, StageResult] = {}
        opinions_by_index: Dict[int, List[AgentOpinion]] = {}
        invalid_by_index: Dict[int, Dict[str, Any]] = {}
        worker_count = min(self.max_concurrency, len(selected_agents))
        executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="agent-skill")
        futures = {
            executor.submit(
                copy_context().run,
                self._run_one,
                agent,
                ctx,
                run_stage,
                progress_callback,
            ): (index, agent)
            for index, agent in enumerate(selected_agents)
        }

        try:
            for future in as_completed(futures):
                index, agent = futures[future]
                try:
                    result, opinions = future.result()
                except Exception as exc:
                    logger.warning("[AgentSkillScheduler] skill '%s' failed: %s", agent.agent_name, exc)
                    result = StageResult(
                        stage_name=getattr(agent, "agent_name", ""),
                        status=StageStatus.FAILED,
                        error=str(exc),
                    )
                    opinions = []

                stage_results_by_index[index] = result
                if opinions:
                    opinions_by_index[index] = opinions
                invalid = self._invalid_record_for(agent, result, opinions)
                if invalid is not None:
                    invalid_by_index[index] = invalid
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        ordered_results = [
            stage_results_by_index[index]
            for index in range(len(selected_agents))
            if index in stage_results_by_index
        ]
        ordered_opinions = [
            opinion
            for index in range(len(selected_agents))
            for opinion in opinions_by_index.get(index, [])
        ]
        ordered_invalid = [
            invalid_by_index[index]
            for index in range(len(selected_agents))
            if index in invalid_by_index
        ]
        return SkillBatchResult(
            stage_results=ordered_results,
            opinions=ordered_opinions,
            invalid_records=ordered_invalid,
            max_concurrency=self.max_concurrency,
            timeout_per_skill=self.timeout_per_skill,
        )

    def _run_one(
        self,
        agent: Any,
        ctx: AgentContext,
        run_stage: RunStageCallable,
        progress_callback: Optional[Callable],
    ) -> tuple[StageResult, List[AgentOpinion]]:
        isolated_ctx = _clone_context_for_skill(ctx)
        opinion_count_before = len(isolated_ctx.opinions)
        timeout = self.timeout_per_skill if self.timeout_per_skill > 0 else None
        result = run_stage(agent, isolated_ctx, progress_callback, timeout)

        opinions: List[AgentOpinion] = []
        if result.opinion is not None:
            opinions.append(result.opinion)
        else:
            opinions.extend(isolated_ctx.opinions[opinion_count_before:])
        return result, opinions

    @staticmethod
    def _invalid_record_for(
        agent: Any,
        result: StageResult,
        opinions: List[AgentOpinion],
    ) -> Optional[Dict[str, Any]]:
        if result.success and opinions:
            return None

        error = result.error or ""
        reason = "skill_timeout" if "timeout" in error.lower() or "timed out" in error.lower() else "skill_error"
        if result.success and not opinions:
            reason = "skill_error"
            error = error or "skill completed without a structured opinion"

        return {
            "agent_name": getattr(agent, "agent_name", result.stage_name),
            "raw_signal": None,
            "confidence": 0.0,
            "reason": reason,
            "error": error,
        }


def _clone_context_for_skill(ctx: AgentContext) -> AgentContext:
    return AgentContext(
        query=ctx.query,
        stock_code=ctx.stock_code,
        stock_name=ctx.stock_name,
        session_id=ctx.session_id,
        data=dict(ctx.data or {}),
        opinions=list(ctx.opinions or []),
        risk_flags=[dict(flag) for flag in (ctx.risk_flags or []) if isinstance(flag, dict)],
        meta=dict(ctx.meta or {}),
        created_at=ctx.created_at,
    )


def _clamp_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))
