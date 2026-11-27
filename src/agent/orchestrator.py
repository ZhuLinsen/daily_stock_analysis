# -*- coding: utf-8 -*-
"""
AgentOrchestrator — multi-agent pipeline coordinator.

Manages the lifecycle of specialised agents (Technical → Intel → Risk →
Specialist → Decision) for a single stock analysis run.

Modes:
- ``quick``   : Technical only → Decision (fastest, ~2 LLM calls)
- ``standard``: Technical → Intel → Decision (default)
- ``full``    : Technical → Intel → Risk → Decision
- ``specialist``: Technical → Intel → Risk → specialist evaluation → Decision

The orchestrator:
1. Seeds an :class:`AgentContext` with the user query and stock code
2. Runs agents sequentially, passing the shared context
3. Collects :class:`StageResult` from each agent
4. Produces a unified :class:`OrchestratorResult` with the final dashboard

Importantly, this class exposes the same ``run(task, context)`` and
``chat(message, session_id, ...)`` interface as ``AgentExecutor`` so it
can be a drop-in replacement via the factory.
"""

from __future__ import annotations

import json
import inspect
import logging
import math
import re
import time
from contextvars import copy_context
from dataclasses import dataclass, field
from math import ceil
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from src.agent.agents.base_agent import coerce_finite_float, coerce_str_list, coerce_text
from src.agent.chat_context import build_visible_chat_history
from src.agent.dashboard_payload import sanitize_agent_dashboard_payload
from src.agent.disagreement import (
    build_agent_disagreement_summary,
    build_evidence_debate_brief,
    should_trigger_evidence_debate,
)
from src.agent.llm_adapter import LLMToolAdapter
from src.core.stock_execution_context import raise_if_stock_cancelled, stock_child_thread_pool
from src.agent.protocols import (
    AgentContext,
    AgentRunStats,
    StageFailureReason,
    StageResult,
    StageStatus,
    is_valid_strategy_signal,
    normalize_decision_signal,
    normalize_stage_failure_reason,
)
from src.agent.skills.base import resolve_skill_instructions_for_language
from src.agent.skills.defaults import is_skill_agent_name
from src.agent.skills.engine import EvidencePartition, StrategyEngine, StrategyResult, StrategyResultStatus
from src.agent.skills.scheduler import AgentSkillScheduler, SkillBatchResult
from src.agent.risk_override import (
    RiskOverrideApplication,
    build_risk_override_application,
    build_risk_override_plan,
)
from src.agent.runtime_facts import (
    AgentRuntimeFacts,
    DegradationBoundary,
    DegradedEvent,
    PipelineTerminationFact,
    build_agent_runtime_facts,
)
from src.agent.runner import parse_dashboard_json, sanitize_non_finite_floats
from src.agent.stock_scope import StockScopeResolution
from src.agent.stream_events import stream_event
from src.agent.tools.registry import ToolRegistry
from src.config import AGENT_MAX_STEPS_DEFAULT, get_config
from src.report_language import (
    format_chat_failure_message,
    get_placeholder_text,
    get_report_labels,
    localize_bias_status,
    localize_chip_health,
    localize_confidence_level,
    localize_volume_status,
    normalize_report_language,
)
from src.schemas.decision_action import localize_action_label, normalize_decision_action

if TYPE_CHECKING:
    from src.agent.executor import AgentResult
    from src.services.agent_chat_session_service import AgentChatSessionService, ResolvedChatTurn
    from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

# Valid orchestrator modes (ordered by cost/depth)
VALID_MODES = ("quick", "standard", "full", "specialist")
NON_CRITICAL_BASE_STAGES = frozenset({"intel", "risk"})
_INCOMPLETE_RISK_REVIEW_NOTE = {
    "zh": "风控必审尚未完成，暂缓买入。",
    "en": "The mandatory risk review is incomplete. Defer buying.",
    "ko": "필수 위험 검토가 완료되지 않았습니다. 매수를 보류하세요.",
}
_APPLIED_RISK_REVIEW_NOTE = {
    "zh": "风控审查已下调操作建议。",
    "en": "Risk review downgraded the recommendation.",
    "ko": "위험 검토 결과에 따라 투자 의견을 하향했습니다.",
}
_BUY_BLOCKED_BY_RISK_REVIEW_NOTE = {
    "zh": "风控审查要求暂缓买入。",
    "en": "Defer buying per the risk review.",
    "ko": "위험 검토 결과에 따라 매수를 보류하세요.",
}
_TIMEOUT_PARTIAL_NOTE = {
    "zh": "多 Agent 超时，以下结论基于已完成阶段自动降级生成。",
    "en": "Multi-agent pipeline timed out; this conclusion was downgraded from completed stages.",
    "ko": "멀티 에이전트 시간 초과로 완료된 단계만을 기반으로 축소 생성된 결론입니다.",
}
_BUDGET_SKIP_PARTIAL_NOTE = {
    "zh": "多 Agent 预算不足，以下结论基于已完成阶段自动降级生成。",
    "en": "Multi-agent budget was insufficient; this conclusion was downgraded from completed stages.",
    "ko": "멀티 에이전트 예산 부족으로 완료된 단계만을 기반으로 축소 생성된 결론입니다.",
}
_DEGRADED_RESULT_PREFIX = {
    "zh": "[降级结果] ",
    "en": "[Degraded Result] ",
    "ko": "[축소 결과] ",
}
_EMPTY_RISK_WARNING = {
    "zh": "暂无额外风险提示",
    "en": "No additional risk warnings.",
    "ko": "추가 위험 경고 없음",
}


def _risk_review_status(stage: Optional[StageResult]) -> StageStatus:
    if stage is None:
        return StageStatus.PENDING
    if stage.success:
        from src.agent.agents.risk_agent import is_complete_risk_review

        raw_data = stage.opinion.raw_data if stage.opinion else None
        if not is_complete_risk_review(raw_data):
            return StageStatus.FAILED
    return stage.status


def _risk_review_incomplete(ctx: AgentContext) -> bool:
    return bool(ctx.meta.get("risk_review_required")) and ctx.meta.get("risk_review_status") != StageStatus.COMPLETED


def _dashboard_recommends_buy(payload: Dict[str, Any]) -> bool:
    phase = payload.get("phase_decision")
    phase = phase if isinstance(phase, dict) else {}
    watch_conditions = phase.get("watch_conditions")
    core = payload.get("core_conclusion")
    position = core.get("position_advice") if isinstance(core, dict) else None
    advice = payload.get("operation_advice")
    return any(normalize_decision_action(value) in {"buy", "add"} for value in (
        payload.get("decision_type"),
        payload.get("action"),
        payload.get("action_label"),
        *(advice.values() if isinstance(advice, dict) else (advice,)),
        *(position.values() if isinstance(position, dict) else ()),
        phase.get("immediate_action"),
        *(watch_conditions if isinstance(watch_conditions, list) else ()),
    ))


def _stage_trajectory_snapshot(result: StageResult) -> Dict[str, Any]:
    """Return the small JSON-safe stage trace exposed to the eval boundary.

    ``StageResult.meta`` also contains runtime-only values such as raw model
    text.  Keep this boundary deliberately whitelisted so the evaluator sees
    execution facts without receiving prompts, messages, or arbitrary metadata.
    """
    status = getattr(result.status, "value", result.status)
    failure_reason = result.failure_reason
    if failure_reason is None and result.status == StageStatus.FAILED:
        failure_reason = StageFailureReason.STAGE_FAILURE
    failure_reason = getattr(failure_reason, "value", failure_reason)
    raw_steps = result.total_steps
    try:
        total_steps = max(0, int(raw_steps or 0))
    except (TypeError, ValueError):
        total_steps = 0
    raw_log = result.meta.get("tool_calls_log") or []
    tool_calls_log = [dict(entry) if isinstance(entry, dict) else entry for entry in raw_log]
    return {
        "stage_name": str(result.stage_name or ""),
        "status": str(status),
        "total_steps": total_steps,
        "tool_calls_log": tool_calls_log,
        "failure_reason": str(failure_reason) if failure_reason is not None else None,
        "duration_s": result.duration_s,
        "tokens_used": result.tokens_used,
        "tool_calls_count": result.tool_calls_count,
    }


def _skipped_stage_trajectory(stage_name: str, reason: StageFailureReason) -> Dict[str, Any]:
    """Represent a stage that was not started at a pipeline boundary."""
    return {
        "stage_name": str(stage_name or ""),
        "status": StageStatus.SKIPPED.value,
        "total_steps": 0,
        "tool_calls_log": [],
        "failure_reason": reason.value,
        "duration_s": 0.0,
        "tokens_used": 0,
        "tool_calls_count": 0,
    }


@dataclass
class OrchestratorResult:
    """Unified result from a multi-agent pipeline run."""

    success: bool = False
    content: str = ""
    dashboard: Optional[Dict[str, Any]] = None
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    provider: str = ""
    model: str = ""
    error: Optional[str] = None
    stats: Optional[AgentRunStats] = None
    runtime_facts: Optional[AgentRuntimeFacts] = None
    stage_trajectories: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedOrchestratorChatTurn:
    """A persisted multi-agent Chat turn ready for pipeline execution."""

    session_id: str
    context: AgentContext
    accepted_snapshot: Optional[Dict[str, Any]] = None
    db_manager: Optional[DatabaseManager] = None


class AgentOrchestrator:
    """Multi-agent pipeline coordinator.

    Drop-in replacement for ``AgentExecutor`` — exposes the same ``run()``
    and ``chat()`` interface.  The factory switches between them via
    ``AGENT_ARCH``.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_adapter: LLMToolAdapter,
        skill_instructions: str = "",
        technical_skill_policy: str = "",
        max_steps: int = AGENT_MAX_STEPS_DEFAULT,
        mode: str = "standard",
        skill_manager=None,
        config=None,
    ):
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter
        self.skill_instructions = skill_instructions
        self.technical_skill_policy = technical_skill_policy
        self.max_steps = max_steps
        normalized_mode = "specialist" if mode in {"strategy", "skill"} else mode
        self.mode = normalized_mode if normalized_mode in VALID_MODES else "standard"
        self.skill_manager = skill_manager
        self.config = config
        self.strategy_engine = StrategyEngine()

    def _get_timeout_seconds(self) -> int:
        """Return the pipeline timeout in seconds.

        ``0`` means disabled. The timeout is a cooperative budget for the
        whole pipeline rather than a hard interruption of an in-flight stage.
        """
        raw_value = getattr(self.config, "agent_orchestrator_timeout_s", 0)
        try:
            return max(0, int(raw_value or 0))
        except (TypeError, ValueError):
            return 0

    def _get_sub_agent_timeout_map(self) -> Dict[str, float]:
        """Return per-agent timeout clamps from config, skipping disabled (0) entries."""
        config = self.config
        if config is None:
            return {}
        entries = [
            ("technical", "agent_technical_agent_timeout_s"),
            ("intel", "agent_intel_agent_timeout_s"),
            ("risk", "agent_risk_agent_timeout_s"),
            ("decision", "agent_decision_agent_timeout_s"),
            ("portfolio", "agent_portfolio_agent_timeout_s"),
            ("skill", "agent_skill_agent_timeout_s"),
        ]
        return {
            key: float(val)
            for key, attr in entries
            if (val := getattr(config, attr, None)) is not None and val > 0
        }

    def _get_skill_concurrency(self) -> int:
        raw_value = getattr(self.config, "agent_skill_concurrency", 3)
        try:
            parsed = int(raw_value or 3)
        except (TypeError, ValueError):
            parsed = 3
        return max(1, min(4, parsed))

    def _build_timeout_result(
        self,
        stats: AgentRunStats,
        all_tool_calls: List[Dict[str, Any]],
        models_used: List[str],
        elapsed_s: float,
        timeout_s: int,
        ctx: Optional[AgentContext] = None,
        parse_dashboard: bool = True,
        stage_trajectories: Optional[List[Dict[str, Any]]] = None,
    ) -> OrchestratorResult:
        """Build a standard timeout result payload."""
        stats.total_duration_s = round(elapsed_s, 2)
        stats.models_used = list(dict.fromkeys(models_used))
        error = f"Pipeline timed out after {elapsed_s:.2f}s (limit: {timeout_s}s)"
        provider = stats.models_used[0] if stats.models_used else ""
        model = ", ".join(stats.models_used)

        dashboard = None
        content = ""
        if ctx is not None:
            report_language = normalize_report_language(ctx.meta.get("report_language"))
            self._prepare_partial_debate_result(ctx, stats)
            dashboard, content = self._resolve_final_output(ctx, parse_dashboard=parse_dashboard)
            if parse_dashboard and dashboard is not None:
                dashboard = self._mark_partial_dashboard(
                    dashboard,
                    note=_TIMEOUT_PARTIAL_NOTE[report_language],
                    report_language=report_language,
                )
                ctx.set_data("final_dashboard", dashboard)
                content = json.dumps(dashboard, ensure_ascii=False, indent=2)

        return OrchestratorResult(
            success=bool(content) if (not parse_dashboard or dashboard is not None) else False,
            content=content,
            dashboard=dashboard,
            error=error,
            stats=stats,
            total_steps=stats.total_stages,
            total_tokens=stats.total_tokens,
            tool_calls_log=all_tool_calls,
            stage_trajectories=list(stage_trajectories or []),
            provider=provider,
            model=model,
            runtime_facts=build_agent_runtime_facts(ctx) if ctx is not None else None,
        )

    def _build_budget_skip_result(
        self,
        stats: AgentRunStats,
        all_tool_calls: List[Dict[str, Any]],
        models_used: List[str],
        elapsed_s: float,
        timeout_s: int,
        stage_name: str,
        remaining_budget: float,
        min_stage_budget_s: int,
        ctx: Optional[AgentContext] = None,
        parse_dashboard: bool = True,
        stage_trajectories: Optional[List[Dict[str, Any]]] = None,
    ) -> OrchestratorResult:
        """Build a result for budget-insufficient stage skip (non-timeout semantics)."""
        stats.total_duration_s = round(elapsed_s, 2)
        stats.models_used = list(dict.fromkeys(models_used))
        dashboard = None
        content = ""
        if ctx is not None:
            report_language = normalize_report_language(ctx.meta.get("report_language"))
            self._prepare_partial_debate_result(ctx, stats)
            dashboard, content = self._resolve_final_output(ctx, parse_dashboard=parse_dashboard)
            if parse_dashboard and dashboard is not None:
                dashboard = self._mark_partial_dashboard(
                    dashboard,
                    note=_BUDGET_SKIP_PARTIAL_NOTE[report_language],
                    report_language=report_language,
                )
                ctx.set_data("final_dashboard", dashboard)
                content = json.dumps(dashboard, ensure_ascii=False, indent=2)

        return OrchestratorResult(
            success=bool(content) if (not parse_dashboard or dashboard is not None) else False,
            content=content,
            dashboard=dashboard,
            error=(
                f"Pipeline skipped before stage '{stage_name}' due to insufficient budget "
                f"({remaining_budget:.1f}s remaining, minimum {min_stage_budget_s}s required)"
            ),
            stats=stats,
            total_steps=stats.total_stages,
            total_tokens=stats.total_tokens,
            tool_calls_log=all_tool_calls,
            stage_trajectories=list(stage_trajectories or []),
            provider=stats.models_used[0] if stats.models_used else "",
            model=", ".join(stats.models_used),
            runtime_facts=build_agent_runtime_facts(ctx) if ctx is not None else None,
        )


    def _prepare_agent(self, agent: Any) -> Any:
        """Apply orchestrator-level runtime settings to a child agent.

        When the orchestrator-level ``max_steps`` equals the default
        (``AGENT_MAX_STEPS_DEFAULT``),
        each agent keeps its own per-agent limit — this prevents inflating
        a decision agent (designed for 3 steps) to 10 steps.

        When the user **explicitly** raises the global limit above the
        default, all agents adopt the global value so the user's intent to
        allow more steps is respected.

        When the user **lowers** the global limit below an agent's default,
        the agent is capped at the global value.
        """
        if hasattr(agent, "max_steps"):
            if self.max_steps > AGENT_MAX_STEPS_DEFAULT:
                # User explicitly raised the limit — apply to all agents.
                agent.max_steps = self.max_steps
            else:
                # Default or lowered — keep per-agent limit as ceiling.
                agent.max_steps = min(agent.max_steps, self.max_steps)
        return agent

    def _callable_accepts_timeout_kwarg(self, func: Any) -> Optional[bool]:
        """Return whether a callable accepts ``timeout_seconds`` when inspectable."""
        if not callable(func):
            return None
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return None

        if "timeout_seconds" in signature.parameters:
            return True
        return any(
            param.kind is inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )

    def _agent_run_accepts_timeout(self, run_callable: Any) -> bool:
        """Best-effort compatibility check for legacy test doubles / custom agents."""
        side_effect = getattr(run_callable, "side_effect", None)
        accepts_timeout = self._callable_accepts_timeout_kwarg(side_effect)
        if accepts_timeout is not None:
            return accepts_timeout

        accepts_timeout = self._callable_accepts_timeout_kwarg(run_callable)
        if accepts_timeout is not None:
            return accepts_timeout

        return True

    def _run_stage_agent(
        self,
        agent: Any,
        ctx: AgentContext,
        progress_callback: Optional[Callable] = None,
        timeout_seconds: Optional[float] = None,
    ) -> StageResult:
        """Run a stage agent while preserving compatibility with older call signatures."""
        raise_if_stock_cancelled()
        # Clamp by per-agent limit when configured.
        # When pipeline budget is disabled (timeout_seconds is None),
        # the sub-agent's own limit still applies as a standalone cap.
        sub_agent_timeout_map = self._get_sub_agent_timeout_map()
        if sub_agent_timeout_map:
            agent_limit = sub_agent_timeout_map.get(agent.agent_name)
            if agent_limit is None and agent.agent_name in getattr(self, "_skill_agent_names", set()):
                agent_limit = sub_agent_timeout_map.get("skill")
            if agent_limit is not None:
                if timeout_seconds is not None:
                    timeout_seconds = min(timeout_seconds, agent_limit)
                else:
                    timeout_seconds = agent_limit
        run_kwargs = {"progress_callback": progress_callback}
        if (
            timeout_seconds is not None
            and timeout_seconds > 0
            and self._agent_run_accepts_timeout(agent.run)
        ):
            run_kwargs["timeout_seconds"] = timeout_seconds
        return agent.run(ctx, **run_kwargs)

    # -----------------------------------------------------------------
    # Public interface (mirrors AgentExecutor)
    # -----------------------------------------------------------------

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> "AgentResult":
        """Run the multi-agent pipeline for a dashboard analysis.

        Returns an ``AgentResult`` (same type as ``AgentExecutor.run``).
        """
        from src.agent.executor import AgentResult

        ctx = self._build_context(task, context)
        ctx.meta["response_mode"] = "dashboard"
        orch_result = self._execute_pipeline(ctx, parse_dashboard=True)

        return AgentResult(
            success=orch_result.success,
            content=orch_result.content,
            dashboard=orch_result.dashboard,
            tool_calls_log=orch_result.tool_calls_log,
            total_steps=orch_result.total_steps,
            total_tokens=orch_result.total_tokens,
            provider=orch_result.provider,
            model=orch_result.model,
            error=orch_result.error,
            stage_trajectories=orch_result.stage_trajectories,
            runtime_facts=orch_result.runtime_facts,
        )

    def chat(
        self,
        message: str,
        session_id: str,
        progress_callback: Optional[Callable] = None,
        context: Optional[Dict[str, Any]] = None,
        selected_skill_ids: Optional[List[str]] = None,
        resolved_turn: Optional[ResolvedChatTurn] = None,
        session_service: Optional[AgentChatSessionService] = None,
    ) -> "AgentResult":
        """Run the pipeline in chat mode (free-form answer, no dashboard parse).

        Conversation history is managed externally by the caller (via
        ``conversation_manager``); the orchestrator focuses on multi-agent
        coordination.
        """
        turn = self.prepare_turn(
            message=message,
            session_id=session_id,
            context=context,
            selected_skill_ids=selected_skill_ids,
            resolved_turn=resolved_turn,
            session_service=session_service,
        )
        return self.execute_turn(
            turn,
            progress_callback=progress_callback,
        )

    def prepare_turn(
        self,
        *,
        message: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        selected_skill_ids: Optional[List[str]] = None,
        resolved_turn: Optional[ResolvedChatTurn] = None,
        session_service: Optional[AgentChatSessionService] = None,
    ) -> PreparedOrchestratorChatTurn:
        """Prepare context and persist the user turn before SSE acceptance."""
        from src.agent.conversation import conversation_manager

        config = self.config or getattr(self.llm_adapter, "_config", None) or get_config()
        if resolved_turn is not None:
            if (session_service is None or resolved_turn.snapshot["session_id"] != session_id
                    or resolved_turn.message != message or resolved_turn.clarification is not None):
                raise ValueError("Resolved Chat preparation requires its session owner and a non-clarification turn")
            scope_resolution = StockScopeResolution(resolved_turn.effective_context, resolved_turn.stock_scope)
        else:
            from src.services.agent_chat_session_service import AgentChatSessionService

            db, snapshot = conversation_manager.prepare_turn(session_id)
            scope_resolution, disposition = AgentChatSessionService(db).prepare_compatibility_turn(
                config, snapshot, message, context=context,
            )
        ctx = self._build_context(
            message, scope_resolution.effective_context,
            scope_resolution=scope_resolution if scope_resolution.stock_scope is not None else None,
        )
        ctx.session_id = session_id
        ctx.meta["response_mode"] = "chat"
        if scope_resolution.stock_scope is not None:
            ctx.meta["stock_scope"] = scope_resolution.stock_scope

        history_kwargs = {"db_manager": db, "source_snapshot": snapshot} if resolved_turn is None else {
            "db_manager": session_service.db, "source_snapshot": resolved_turn.snapshot,
        }
        history = build_visible_chat_history(session_id, self.llm_adapter, config, **history_kwargs)
        if history:
            ctx.meta["conversation_history"] = history

        # Persist user turn
        accepted = None
        if resolved_turn is not None:
            accepted = session_service.commit_user_turn(resolved_turn)
        else:
            accepted = conversation_manager.commit_user_turn(
                db, snapshot, message, selected_skill_ids, state_disposition=disposition,
            )

        return PreparedOrchestratorChatTurn(
            session_id=session_id,
            context=ctx,
            accepted_snapshot=accepted,
            db_manager=session_service.db if resolved_turn is not None else db,
        )

    def execute_turn(
        self,
        turn: PreparedOrchestratorChatTurn,
        *,
        progress_callback: Optional[Callable] = None,
    ) -> "AgentResult":
        """Execute an accepted multi-agent Chat turn and persist its result."""
        from src.agent.executor import AgentResult
        from src.agent.conversation import conversation_manager

        orch_result = self._execute_pipeline(
            turn.context,
            parse_dashboard=False,
            progress_callback=progress_callback,
        )

        # Persist assistant response
        report_language = normalize_report_language(turn.context.meta.get("report_language"))
        if turn.accepted_snapshot is not None:
            content = (
                orch_result.content
                if orch_result.success
                else format_chat_failure_message(orch_result.error, report_language)
            )
            conversation_manager.add_message(
                turn.session_id, "assistant", content, accepted_turn=turn.accepted_snapshot,
                db_manager=turn.db_manager,
            )
        elif orch_result.success:
            conversation_manager.add_message(turn.session_id, "assistant", orch_result.content)
        else:
            conversation_manager.add_message(
                turn.session_id,
                "assistant",
                format_chat_failure_message(orch_result.error, report_language),
            )

        return AgentResult(
            success=orch_result.success,
            content=orch_result.content,
            dashboard=orch_result.dashboard,
            tool_calls_log=orch_result.tool_calls_log,
            total_steps=orch_result.total_steps,
            total_tokens=orch_result.total_tokens,
            provider=orch_result.provider,
            model=orch_result.model,
            error=orch_result.error,
            stage_trajectories=orch_result.stage_trajectories,
            runtime_facts=orch_result.runtime_facts,
        )

    # -----------------------------------------------------------------
    # Pipeline execution
    # -----------------------------------------------------------------

    def _execute_pipeline(
        self,
        ctx: AgentContext,
        parse_dashboard: bool = True,
        progress_callback: Optional[Callable] = None,
    ) -> OrchestratorResult:
        """Run the agent pipeline according to ``self.mode``."""
        stats = AgentRunStats()
        all_tool_calls: List[Dict[str, Any]] = []
        stage_trajectories: List[Dict[str, Any]] = []
        models_used: List[str] = []
        t0 = time.time()
        timeout_s = self._get_timeout_seconds()

        agents = self._build_agent_chain(ctx)
        debate_enabled = bool(getattr(self.config, "agent_debate_enabled", False))
        specialist_agents_inserted = False
        strategy_engine_ran = False
        risk_stage = None
        index = 0

        # Minimum seconds required for a stage to do useful work.  Starting
        # a stage with less budget virtually guarantees a timeout that wastes
        # an LLM billing cycle.  Only enforced after at least one stage has
        # completed so that the first stage always gets a chance to run
        # even when the total budget is small.
        _MIN_STAGE_BUDGET_S = 15

        while index < len(agents):
            agent = agents[index]
            elapsed_s = time.time() - t0
            remaining_budget = timeout_s - elapsed_s if timeout_s else None

            if (
                index == 0
                and len(agents) >= 2
                and self._can_parallelize_discovery_pair(agents[0], agents[1])
                and not (timeout_s and remaining_budget is not None and remaining_budget <= 0)
            ):
                tech_agent, intel_agent = agents[0], agents[1]
                tech_result, intel_result = self._run_discovery_wave_parallel(
                    tech_agent,
                    intel_agent,
                    ctx,
                    progress_callback=progress_callback,
                    timeout_seconds=remaining_budget,
                )
                for stage_agent, stage_result in ((tech_agent, tech_result), (intel_agent, intel_result)):
                    stats.record_stage(stage_result)
                    stage_trajectories.append(_stage_trajectory_snapshot(stage_result))
                    all_tool_calls.extend(
                        tc for tc in (stage_result.meta.get("tool_calls_log") or [])
                    )
                    models_used.extend(stage_result.meta.get("models_used", []))

                elapsed_s = time.time() - t0
                if tech_result.status == StageStatus.FAILED:
                    logger.error("[Orchestrator] critical stage '%s' failed: %s", tech_agent.agent_name, tech_result.error)
                    return OrchestratorResult(
                        success=False,
                        error=f"Stage '{tech_agent.agent_name}' failed: {tech_result.error}",
                        stats=stats,
                        total_steps=stats.total_stages,
                        total_tokens=stats.total_tokens,
                        tool_calls_log=all_tool_calls,
                        stage_trajectories=stage_trajectories,
                        runtime_facts=build_agent_runtime_facts(ctx),
                    )
                if intel_result.status == StageStatus.FAILED:
                    self._record_degraded_stage(ctx, intel_agent.agent_name, intel_result)
                    logger.warning(
                        "[Orchestrator] stage '%s' failed (non-critical, degrading): %s",
                        intel_agent.agent_name,
                        intel_result.error,
                    )

                if timeout_s and elapsed_s >= timeout_s:
                    logger.error("[Orchestrator] pipeline timed out after discovery wave")
                    self._record_pipeline_termination(
                        ctx,
                        last_completed_stage=intel_agent.agent_name
                        if intel_result.status == StageStatus.COMPLETED
                        else tech_agent.agent_name,
                    )
                    if progress_callback:
                        progress_callback(stream_event(
                            "pipeline_timeout",
                            stage=intel_agent.agent_name,
                            elapsed=round(elapsed_s, 2),
                            timeout=timeout_s,
                        ))
                    self._apply_partition_fallback(ctx)
                    return self._build_timeout_result(
                        stats,
                        all_tool_calls,
                        models_used,
                        elapsed_s,
                        timeout_s,
                        ctx=ctx,
                        parse_dashboard=parse_dashboard,
                        stage_trajectories=stage_trajectories,
                    )

                index = 2
                continue

            stage_min_budget_s = (
                _MIN_STAGE_BUDGET_S
            )
            timeout_exhausted = (
                timeout_s
                and remaining_budget is not None
                and remaining_budget <= 0
            )
            budget_guard_triggered = (
                timeout_s
                and remaining_budget is not None
                and index > 0
                and remaining_budget < stage_min_budget_s
            )
            if timeout_exhausted:
                logger.error("[Orchestrator] pipeline timed out before stage '%s'", agent.agent_name)
                self._record_degraded_event(
                    ctx,
                    stage=agent.agent_name,
                    reason=StageFailureReason.TIMEOUT,
                    boundary=DegradationBoundary.BEFORE_STAGE,
                )
                if progress_callback:
                    progress_callback(stream_event(
                        "pipeline_timeout",
                        stage=agent.agent_name,
                        elapsed=round(elapsed_s, 2),
                        timeout=timeout_s,
                    ))
                if ctx is not None:
                    self._apply_partition_fallback(ctx)
                stage_trajectories.append(
                    _skipped_stage_trajectory(agent.agent_name, StageFailureReason.TIMEOUT)
                )
                return self._build_timeout_result(
                    stats,
                    all_tool_calls,
                    models_used,
                    elapsed_s,
                    timeout_s,
                    ctx=ctx,
                    parse_dashboard=parse_dashboard,
                    stage_trajectories=stage_trajectories,
                )

            if budget_guard_triggered:
                logger.warning(
                    "[Orchestrator] pipeline insufficient budget before stage '%s' (%.1fs remaining, min %ds)",
                    agent.agent_name,
                    remaining_budget,
                    stage_min_budget_s,
                )
                self._record_degraded_event(
                    ctx,
                    stage=agent.agent_name,
                    reason=StageFailureReason.BUDGET_SKIP,
                    boundary=DegradationBoundary.BEFORE_STAGE,
                )
                if progress_callback:
                    progress_callback(stream_event(
                        "pipeline_budget_skipped",
                        stage=agent.agent_name,
                        elapsed=round(elapsed_s, 2),
                        timeout=timeout_s,
                        remaining=round(remaining_budget, 2),
                        minimum=stage_min_budget_s,
                        reason="insufficient_budget",
                        message=(
                            f"Skipped {agent.agent_name} analysis due to insufficient "
                            "remaining budget"
                        ),
                    ))
                if ctx is not None:
                    self._apply_partition_fallback(ctx)
                stage_trajectories.append(
                    _skipped_stage_trajectory(agent.agent_name, StageFailureReason.BUDGET_SKIP)
                )
                return self._build_budget_skip_result(
                    stats,
                    all_tool_calls,
                    models_used,
                    elapsed_s,
                    timeout_s,
                    agent.agent_name,
                    remaining_budget,
                    stage_min_budget_s,
                    ctx=ctx,
                    parse_dashboard=parse_dashboard,
                    stage_trajectories=stage_trajectories,
                )

            if (
                self.mode == "specialist"
                and (agent.agent_name == "decision" or (debate_enabled and agent.agent_name == "risk"))
                and not specialist_agents_inserted
            ):
                specialist_agents = self._build_specialist_agents(ctx)
                self._skill_agent_names = {a.agent_name for a in specialist_agents}
                specialist_agents_inserted = True
                if specialist_agents:
                    batch = self._run_specialist_agent_batch(
                        specialist_agents,
                        ctx,
                        progress_callback=progress_callback,
                        timeout_seconds=remaining_budget,
                    )
                    for stage_result in batch.stage_results:
                        stats.record_stage(stage_result)
                        stage_trajectories.append(_stage_trajectory_snapshot(stage_result))
                        all_tool_calls.extend(
                            tc for tc in (stage_result.meta.get("tool_calls_log") or [])
                        )
                        models_used.extend(stage_result.meta.get("models_used", []))
                        if stage_result.status == StageStatus.FAILED:
                            self._record_degraded_stage(ctx, stage_result.stage_name, stage_result)
                    ctx.opinions.extend(batch.opinions)
                    invalid_bucket = ctx.meta.get("invalid_opinions")
                    if not isinstance(invalid_bucket, list):
                        invalid_bucket = []
                    invalid_bucket.extend(batch.invalid_records)
                    ctx.meta["invalid_opinions"] = invalid_bucket
                    ctx.meta["skill_scheduler"] = {
                        "mode": "thread_pool",
                        "max_concurrency": batch.max_concurrency,
                        "timeout_per_skill": batch.timeout_per_skill,
                        "scheduled_skill_count": len(specialist_agents),
                        "completed_skill_count": sum(1 for item in batch.stage_results if item.success),
                        "invalid_skill_count": len(batch.invalid_records),
                    }
                    continue

            if agent.agent_name == "decision":
                if not strategy_engine_ran:
                    self._run_strategy_engine(ctx)
                    strategy_engine_ran = True
                self._prepare_decision_context(ctx, risk_stage)
                if ctx.meta["risk_review_required"] and risk_stage is None:
                    from src.agent.agents.risk_agent import RiskAgent

                    agents.insert(index, self._build_base_agent(RiskAgent))
                    continue
            elif agent.agent_name == "risk" and debate_enabled and not ctx.meta.get("risk_review_required"):
                if self.mode == "specialist":
                    self._run_strategy_engine(ctx)
                    strategy_engine_ran = True
                self._prepare_decision_context(ctx)

            if progress_callback:
                progress_callback(stream_event(
                    "stage_start",
                    stage=agent.agent_name,
                    message=f"Starting {agent.agent_name} analysis...",
                ))

            remaining_timeout_s = (
                max(0.0, timeout_s - elapsed_s)
                if timeout_s
                else None
            )
            result: StageResult = self._run_stage_agent(
                agent,
                ctx,
                progress_callback=progress_callback,
                timeout_seconds=remaining_timeout_s,
            )
            if agent.agent_name == "risk":
                risk_stage = result
                if ctx.meta.get("risk_review_required"):
                    review_status = _risk_review_status(result)
                    ctx.meta["risk_review_status"] = review_status
                    if result.success and review_status == StageStatus.FAILED:
                        result.status = StageStatus.FAILED
                        result.failure_reason = StageFailureReason.STAGE_FAILURE
                        result.error = "Risk review did not return a complete risk assessment"
            stats.record_stage(result)
            stage_trajectories.append(_stage_trajectory_snapshot(result))
            all_tool_calls.extend(
                tc for tc in (result.meta.get("tool_calls_log") or [])
            )
            models_used.extend(result.meta.get("models_used", []))
            elapsed_s = time.time() - t0
            if progress_callback:
                progress_callback(stream_event(
                    "stage_done",
                    stage=agent.agent_name,
                    status=result.status.value,
                    duration=result.duration_s,
                ))

            if ctx.meta.get("response_mode") == "chat" and agent.agent_name == "decision":
                final_text = result.meta.get("raw_text")
                if isinstance(final_text, str) and final_text.strip():
                    ctx.set_data("final_response_text", final_text.strip())

            # Abort pipeline on critical failure.
            # Non-critical stages that degrade gracefully:
            #   - intel / risk (standard support stages)
            #   - skill agents (specialist evaluation, optional)
            if result.status == StageStatus.FAILED:
                if not self._is_non_critical_stage(agent.agent_name):
                    logger.error("[Orchestrator] critical stage '%s' failed: %s", agent.agent_name, result.error)
                    return OrchestratorResult(
                        success=False,
                        error=f"Stage '{agent.agent_name}' failed: {result.error}",
                        stats=stats,
                        total_steps=stats.total_stages,
                        total_tokens=stats.total_tokens,
                        tool_calls_log=all_tool_calls,
                        stage_trajectories=stage_trajectories,
                        runtime_facts=build_agent_runtime_facts(ctx),
                    )
                else:
                    self._record_degraded_stage(ctx, agent.agent_name, result)
                    logger.warning(
                        "[Orchestrator] stage '%s' failed (non-critical, degrading): %s",
                        agent.agent_name,
                        result.error,
                    )

            if timeout_s and elapsed_s >= timeout_s:
                logger.error("[Orchestrator] pipeline timed out after stage '%s'", agent.agent_name)
                last_completed_stage = next(
                    (
                        stage.stage_name
                        for stage in reversed(stats.stage_results)
                        if stage.status == StageStatus.COMPLETED
                    ),
                    None,
                )
                self._record_pipeline_termination(
                    ctx,
                    last_completed_stage=last_completed_stage,
                )
                if progress_callback:
                    progress_callback(stream_event(
                        "pipeline_timeout",
                        stage=agent.agent_name,
                        elapsed=round(elapsed_s, 2),
                        timeout=timeout_s,
                    ))
                self._apply_partition_fallback(ctx)
                return self._build_timeout_result(
                    stats,
                    all_tool_calls,
                    models_used,
                    elapsed_s,
                    timeout_s,
                    ctx=ctx,
                    parse_dashboard=parse_dashboard,
                    stage_trajectories=stage_trajectories,
                )

            index += 1

        # Assemble final output
        total_duration = round(time.time() - t0, 2)
        stats.total_duration_s = total_duration
        stats.models_used = list(dict.fromkeys(models_used))

        dashboard, content = self._resolve_final_output(ctx, parse_dashboard=parse_dashboard)

        model_str = ", ".join(dict.fromkeys(m for m in models_used if m))
        provider = stats.models_used[0] if stats.models_used else ""

        if parse_dashboard and dashboard is None:
            return OrchestratorResult(
                success=False,
                content=content,
                dashboard=None,
                tool_calls_log=all_tool_calls,
                total_steps=stats.total_stages,
                total_tokens=stats.total_tokens,
                provider=provider,
                model=model_str,
                error="Failed to parse dashboard JSON from agent response",
                stats=stats,
                stage_trajectories=stage_trajectories,
                runtime_facts=build_agent_runtime_facts(ctx),
            )

        return OrchestratorResult(
            success=bool(content),
            content=content,
            dashboard=dashboard,
            tool_calls_log=all_tool_calls,
            total_steps=stats.total_stages,
            total_tokens=stats.total_tokens,
            provider=provider,
            model=model_str,
            stats=stats,
            stage_trajectories=stage_trajectories,
            runtime_facts=build_agent_runtime_facts(ctx),
        )

    # -----------------------------------------------------------------
    # Agent chain construction
    # -----------------------------------------------------------------

    def _resolve_skill_instructions(self, ctx: Optional[AgentContext]) -> str:
        report_language = (
            ctx.meta.get("report_language", "zh") if ctx is not None else "zh"
        )
        return resolve_skill_instructions_for_language(
            self.skill_instructions,
            self.skill_manager,
            report_language,
        )

    def _build_base_agent(self, agent_type, *, skill_instructions: Optional[str] = None):
        return self._prepare_agent(agent_type(
            tool_registry=self.tool_registry,
            llm_adapter=self.llm_adapter,
            skill_instructions=self.skill_instructions if skill_instructions is None else skill_instructions,
            technical_skill_policy=self.technical_skill_policy,
        ))

    def _build_agent_chain(self, ctx: AgentContext) -> list:
        """Instantiate the ordered agent list based on ``self.mode``."""
        from src.agent.agents.technical_agent import TechnicalAgent
        from src.agent.agents.intel_agent import IntelAgent
        from src.agent.agents.decision_agent import DecisionAgent
        from src.agent.agents.risk_agent import RiskAgent

        self._skill_agent_names = set()
        resolved_skills = self._resolve_skill_instructions(ctx)

        technical = self._build_base_agent(TechnicalAgent, skill_instructions=resolved_skills)
        intel = self._build_base_agent(IntelAgent, skill_instructions=resolved_skills)
        risk = self._build_base_agent(RiskAgent, skill_instructions=resolved_skills)
        decision = self._build_base_agent(DecisionAgent, skill_instructions=resolved_skills)

        if self.mode == "quick":
            return [technical, decision]
        elif self.mode == "standard":
            return [technical, intel, decision]
        elif self.mode == "full":
            return [technical, intel, risk, decision]
        elif self.mode == "specialist":
            # The router needs discovery opinions before it can select specialists.
            return [technical, intel, risk, decision]
        else:
            return [technical, intel, decision]

    def _can_parallelize_discovery_pair(self, first_agent: Any, second_agent: Any) -> bool:
        """Enable parallel Wave-1 discovery only for real TechnicalAgent + IntelAgent pairs."""
        from src.agent.agents.intel_agent import IntelAgent
        from src.agent.agents.technical_agent import TechnicalAgent

        parallel_enabled = getattr(self.config, "agent_parallel_discovery", True)
        return (
            bool(parallel_enabled)
            and type(first_agent) is TechnicalAgent
            and type(second_agent) is IntelAgent
        )

    @staticmethod
    def _clone_context_for_discovery(ctx: AgentContext) -> AgentContext:
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

    def _run_discovery_wave_parallel(
        self,
        tech_agent: Any,
        intel_agent: Any,
        ctx: AgentContext,
        *,
        progress_callback: Optional[Callable] = None,
        timeout_seconds: Optional[float] = None,
    ) -> tuple[StageResult, StageResult]:
        """Run TechnicalAgent and IntelAgent concurrently on isolated context clones."""
        tech_ctx = self._clone_context_for_discovery(ctx)
        intel_ctx = self._clone_context_for_discovery(ctx)
        base_opinion_len = len(ctx.opinions or [])
        base_risk_len = len(ctx.risk_flags or [])
        base_data = dict(ctx.data or {})
        base_meta = dict(ctx.meta or {})
        def forward_progress_event(event: Dict[str, Any]) -> None:
            if progress_callback is None:
                return
            # Worker progress must reach streaming callers while the wave is
            # still running.  The callback is responsible for its own
            # thread-safe delivery (the Chat SSE callback enqueues events).
            progress_callback(event)

        if progress_callback:
            for agent in (tech_agent, intel_agent):
                progress_callback(stream_event(
                    "stage_start",
                    stage=agent.agent_name,
                    message=f"Starting {agent.agent_name} analysis...",
                ))

        with stock_child_thread_pool(2, "dsa-wave1") as pool:
            tech_future = pool.submit(
                copy_context().run,
                self._run_stage_agent,
                tech_agent,
                tech_ctx,
                progress_callback=forward_progress_event if progress_callback else None,
                timeout_seconds=timeout_seconds,
            )
            intel_future = pool.submit(
                copy_context().run,
                self._run_stage_agent,
                intel_agent,
                intel_ctx,
                progress_callback=forward_progress_event if progress_callback else None,
                timeout_seconds=timeout_seconds,
            )
            tech_result = tech_future.result()
            intel_result = intel_future.result()

        # Deterministic main-thread merge in [technical, intel] order.
        for sub_ctx in (tech_ctx, intel_ctx):
            ctx.opinions.extend(sub_ctx.opinions[base_opinion_len:])
            ctx.risk_flags.extend(sub_ctx.risk_flags[base_risk_len:])
            for k, v in (sub_ctx.data or {}).items():
                if k not in base_data or base_data[k] != v:
                    ctx.data[k] = v
            for k, v in (sub_ctx.meta or {}).items():
                if k not in base_meta or base_meta[k] != v:
                    ctx.meta[k] = v

        if progress_callback:
            for res in (tech_result, intel_result):
                progress_callback(stream_event(
                    "stage_done",
                    stage=res.stage_name,
                    status=res.status.value,
                    duration=res.duration_s,
                ))

        return tech_result, intel_result

    def _build_specialist_agents(self, ctx: AgentContext) -> list:
        """Build specialist sub-agents based on requested skills.

        Uses the skill router to select applicable skills, then creates
        lightweight agent wrappers for each.
        """
        try:
            from src.agent.skills.router import SkillRouter
            common_kwargs = dict(
                tool_registry=self.tool_registry,
                llm_adapter=self.llm_adapter,
                skill_instructions=self._resolve_skill_instructions(ctx),
                technical_skill_policy=self.technical_skill_policy,
            )
            router = SkillRouter()
            selected = router.select_skills(ctx, max_count=4)
            if not selected:
                return []

            from src.agent.skills.skill_agent import SkillAgent
            agents = []
            for skill_id in selected:
                agent = self._prepare_agent(SkillAgent(
                    skill_id=skill_id,
                    **common_kwargs,
                ))
                agents.append(agent)
            return agents
        except Exception as exc:
            logger.warning("[Orchestrator] failed to build skill agents: %s", exc)
            return []

    def _build_skill_agents(self, ctx: AgentContext) -> list:
        """Compatibility wrapper for legacy imports."""
        return self._build_specialist_agents(ctx)

    def _build_strategy_agents(self, ctx: AgentContext) -> list:
        """Compatibility wrapper for legacy tests/imports."""
        return self._build_specialist_agents(ctx)

    def _run_specialist_agent_batch(
        self,
        agents: list,
        ctx: AgentContext,
        *,
        progress_callback: Optional[Callable] = None,
        timeout_seconds: Optional[float] = None,
    ) -> SkillBatchResult:
        sub_agent_timeout_map = self._get_sub_agent_timeout_map()
        configured_skill_timeout = sub_agent_timeout_map.get("skill", 0.0)
        budget_per_skill = self._skill_batch_timeout_slice(
            len(agents),
            timeout_seconds=timeout_seconds,
        )
        if configured_skill_timeout and budget_per_skill is not None:
            timeout_per_skill = min(configured_skill_timeout, budget_per_skill)
        elif configured_skill_timeout:
            timeout_per_skill = configured_skill_timeout
        elif budget_per_skill is not None:
            timeout_per_skill = budget_per_skill
        else:
            timeout_per_skill = 0.0
        scheduler = AgentSkillScheduler(
            max_concurrency=self._get_skill_concurrency(),
            timeout_per_skill=timeout_per_skill,
        )
        if progress_callback:
            for agent in agents:
                progress_callback(stream_event(
                    "stage_start",
                    stage=agent.agent_name,
                    message=f"Starting {agent.agent_name} analysis...",
                ))

        batch = scheduler.run(
            agents,
            ctx,
            self._run_stage_agent,
            progress_callback=progress_callback,
        )
        if progress_callback:
            for result in batch.stage_results:
                progress_callback(stream_event(
                    "stage_done",
                    stage=result.stage_name,
                    status=result.status.value,
                    duration=result.duration_s,
                ))
        return batch

    def _skill_batch_timeout_slice(
        self,
        agent_count: int,
        *,
        timeout_seconds: Optional[float],
    ) -> Optional[float]:
        """Split remaining specialist budget across queued concurrency waves."""
        if timeout_seconds is None:
            return None
        try:
            remaining = float(timeout_seconds)
        except (TypeError, ValueError):
            return None
        if remaining <= 0:
            return 0.0

        count = max(1, int(agent_count or 1))
        worker_count = min(self._get_skill_concurrency(), count)
        wave_count = max(1, ceil(count / worker_count))
        return remaining / wave_count

    # -----------------------------------------------------------------
    # Skill aggregation
    # -----------------------------------------------------------------

    def _partition_skill_opinions(self, ctx: AgentContext) -> None:
        """Split skill opinions into Evidence Chain (valid) and Diagnostics (invalid).

        Per docs/multi-strategy-contract.md §"Evidence Chain 与 Diagnostics 分离":
        this is the ONLY partition point. After this method, ctx.opinions
        contains only valid skill opinions; invalid ones are moved to
        ctx.meta["invalid_opinions"] and never re-enter downstream evidence.
        """
        kept: List = []
        invalid_bucket: List[Dict[str, Any]] = ctx.meta.setdefault("invalid_opinions", [])
        if not isinstance(invalid_bucket, list):
            invalid_bucket = []
            ctx.meta["invalid_opinions"] = invalid_bucket

        for op in ctx.opinions:
            if not is_skill_agent_name(op.agent_name):
                kept.append(op)
                continue

            raw_signal = op.signal if op.signal else (
                op.raw_data.get("signal") if isinstance(op.raw_data, dict) else None
            )

            if raw_signal is None or (isinstance(raw_signal, str) and not raw_signal.strip()):
                reason = "missing_signal"
                raw_display = raw_signal if isinstance(raw_signal, str) else None
                is_valid = False
            elif is_valid_strategy_signal(raw_signal):
                if not op.confidence_input_valid:
                    is_valid = False
                    reason = "invalid_confidence"
                    raw_display = str(raw_signal)
                else:
                    is_valid = True
                    reason = ""
                    raw_display = str(raw_signal)
            else:
                is_valid = False
                reason = "unrecognized_signal"
                raw_display = str(raw_signal)

            if is_valid:
                kept.append(op)
            else:
                invalid_bucket.append({
                    "agent_name": op.agent_name,
                    "raw_signal": raw_display,
                    "confidence": op.confidence,
                    "reason": reason,
                })
                logger.info(
                    "[Orchestrator] invalid skill opinion moved to diagnostics: agent=%s raw_signal=%r reason=%s",
                    op.agent_name, raw_display, reason,
                )

        ctx.opinions = kept

    def _aggregate_skill_opinions(self, ctx: AgentContext) -> None:
        """Run SkillAggregator to produce a consensus opinion.

        Merges individual skill-agent opinions into a single weighted
        consensus and stores it in context so the decision agent can use it.
        """
        try:
            from src.agent.skills.aggregator import SkillAggregator
            aggregator = SkillAggregator()
            consensus = aggregator.aggregate(ctx)
            if consensus:
                ctx.opinions.append(consensus)
                ctx.set_data("skill_consensus", {
                    "signal": consensus.signal,
                    "confidence": consensus.confidence,
                    "reasoning": consensus.reasoning,
                    "raw_data": consensus.raw_data,
                    "strategy_synthesis": consensus.raw_data.get("strategy_synthesis"),
                    "conflicts": consensus.raw_data.get("conflicts", []),
                })
                logger.info(
                    "[Orchestrator] skill consensus: signal=%s confidence=%.2f",
                    consensus.signal, consensus.confidence,
                )
            else:
                logger.info("[Orchestrator] no skill opinions to aggregate")
        except Exception as exc:
            logger.warning("[Orchestrator] skill aggregation failed: %s", exc)

    def _aggregate_strategy_opinions(self, ctx: AgentContext) -> None:
        """Compatibility wrapper for legacy tests/imports."""
        self._aggregate_skill_opinions(ctx)

    def _run_strategy_engine(self, ctx: AgentContext) -> None:
        """Run the full skill pipeline via StrategyEngine and update ctx.

        Replaces the old two-step _partition_skill_opinions + _aggregate_skill_opinions
        calls. The engine is the single authoritative owner of strategy_synthesis.
        """
        existing_invalid = ctx.meta.get("invalid_opinions")
        if not isinstance(existing_invalid, list):
            existing_invalid = []
        result = self.strategy_engine.process(
            ctx.opinions,
            diagnostic_records=existing_invalid,
        )

        ctx.meta["invalid_opinions"] = list(result.invalid_records)
        ctx.opinions = list(result.non_skill_opinions) + list(result.valid_skill_opinions)
        if result.consensus_opinion is not None:
            ctx.opinions.append(result.consensus_opinion)

        if result.skill_consensus_data is not None:
            ctx.set_data("skill_consensus", result.skill_consensus_data)

        if result.status == StrategyResultStatus.CONSENSUS:
            logger.info(
                "[Orchestrator] strategy engine: signal=%s confidence=%.2f",
                result.consensus_opinion.signal,
                result.consensus_opinion.confidence,
            )
        elif result.status == StrategyResultStatus.NO_CONSENSUS:
            logger.info(
                "[Orchestrator] strategy engine: NO_CONSENSUS invalid_count=%d",
                result.invalid_count,
            )
        else:
            logger.info("[Orchestrator] strategy engine: NO_SKILLS")

    def _apply_partition_fallback(self, ctx: AgentContext) -> None:
        """Partition skill opinions for timeout/budget-skip early-exit paths.

        Does not aggregate — only ensures invalid diagnostics are preserved
        in ctx.meta["invalid_opinions"] before the pipeline bails out.
        Idempotent: skips if the engine already ran fully (skill_consensus present).
        """
        if ctx.get_data("skill_consensus") is not None:
            return

        partition = self.strategy_engine.partition_only(ctx.opinions)
        kept_skills = []
        extra_invalid: List[Dict[str, Any]] = []
        for op in partition.valid_skill_opinions:
            if not op.confidence_input_valid:
                raw_data = op.raw_data if isinstance(op.raw_data, dict) else {}
                extra_invalid.append({
                    "agent_name": op.agent_name,
                    "raw_signal": raw_data.get("original_signal") or op.signal,
                    "confidence": op.confidence,
                    "reason": "invalid_confidence",
                })
                continue
            kept_skills.append(op)
        ctx.opinions = list(partition.non_skill_opinions) + kept_skills
        invalid_bucket = ctx.meta.get("invalid_opinions")
        if not isinstance(invalid_bucket, list):
            invalid_bucket = []
        invalid_bucket.extend(partition.invalid_records)
        invalid_bucket.extend(extra_invalid)
        ctx.meta["invalid_opinions"] = invalid_bucket

    def _prepare_decision_context(self, ctx: AgentContext, risk_stage: Optional[StageResult] = None) -> None:
        """Populate low-sensitivity summaries consumed by DecisionAgent."""
        summary = build_agent_disagreement_summary(
            ctx,
            risk_override_enabled=getattr(self.config, "agent_risk_override", True),
        )
        ctx.meta["agent_disagreement_summary"] = summary
        debate_enabled = bool(getattr(self.config, "agent_debate_enabled", False))
        triggered, reason = should_trigger_evidence_debate(
            ctx,
            enabled=debate_enabled,
        )
        if triggered:
            previous_brief = ctx.meta.get("evidence_debate_brief")
            if not previous_brief:
                logger.info("[Orchestrator] evidence debate triggered (reason=%s)", reason)
            brief = build_evidence_debate_brief(ctx, summary, trigger_reason=reason)
            ctx.meta["evidence_debate_brief"] = brief
            ctx.meta["risk_review_required"] = True
            ctx.meta["risk_review_status"] = _risk_review_status(risk_stage)
        else:
            ctx.meta.pop("evidence_debate_brief", None)
            ctx.meta["risk_review_required"] = False
            ctx.meta.pop("risk_review_status", None)

    def _prepare_partial_debate_result(self, ctx: AgentContext, stats: AgentRunStats) -> None:
        if not getattr(self.config, "agent_debate_enabled", False):
            return
        risk_stage = next((stage for stage in stats.stage_results if stage.stage_name == "risk"), None)
        self._prepare_decision_context(ctx, risk_stage)
        if ctx.meta["risk_review_required"] and risk_stage is None:
            ctx.meta["risk_review_status"] = StageStatus.SKIPPED

    def _record_degraded_stage(
        self,
        ctx: AgentContext,
        agent_name: str,
        result: StageResult,
    ) -> None:
        """Record a low-sensitivity degraded stage marker for downstream synthesis."""
        if result.status != StageStatus.FAILED:
            raise ValueError("degraded stage markers are only produced for failed stages")

        degraded_stages = ctx.meta.setdefault("degraded_stages", [])
        if not isinstance(degraded_stages, list):
            degraded_stages = []
            ctx.meta["degraded_stages"] = degraded_stages
        degraded_stages.append({
            "stage_name": agent_name,
            "status": result.status.value,
            "non_critical": self._is_non_critical_stage(agent_name),
        })
        self._record_degraded_event(
            ctx,
            stage=agent_name,
            reason=normalize_stage_failure_reason(result.failure_reason),
            boundary=DegradationBoundary.DURING_STAGE,
        )

    @staticmethod
    def _record_degraded_event(
        ctx: AgentContext,
        *,
        stage: str,
        reason: Any,
        boundary: DegradationBoundary,
    ) -> None:
        """Record one deduplicated fact for an incomplete stage."""
        normalized = DegradedEvent(
            stage=stage,
            reason=reason,
            boundary=boundary,
        )
        event = {
            "stage": normalized.stage,
            "reason": normalized.reason.value,
            "boundary": normalized.boundary.value,
        }
        events = ctx.meta.setdefault("degraded_events", [])
        if not isinstance(events, list):
            events = []
            ctx.meta["degraded_events"] = events
        if event not in events:
            events.append(event)

    @staticmethod
    def _record_pipeline_termination(
        ctx: AgentContext,
        *,
        last_completed_stage: Optional[str],
    ) -> None:
        """Record a pipeline timeout without attributing it to a stage."""
        termination = PipelineTerminationFact(
            reason=StageFailureReason.TIMEOUT,
            last_completed_stage=last_completed_stage,
        )
        ctx.meta["pipeline_termination"] = {
            "reason": termination.reason.value,
            "last_completed_stage": termination.last_completed_stage,
        }

    def _is_non_critical_stage(self, agent_name: str) -> bool:
        """Return whether a failed stage should degrade instead of aborting."""
        normalized_name = str(agent_name or "").strip()
        return (
            normalized_name in NON_CRITICAL_BASE_STAGES
            or normalized_name in getattr(self, "_skill_agent_names", set())
        )

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _build_context(
        self, task: str, context: Optional[Dict[str, Any]] = None, *,
        scope_resolution: Optional[StockScopeResolution] = None,
    ) -> AgentContext:
        """Seed an ``AgentContext`` from the user request."""
        ctx = AgentContext(query=task)

        if context:
            ctx.stock_code = context.get("stock_code", "")
            ctx.stock_name = context.get("stock_name", "")
            requested_skills = context.get("skills")
            if requested_skills is None:
                requested_skills = context.get("strategies", [])
            ctx.meta["skills_requested"] = requested_skills or []
            ctx.meta["strategies_requested"] = requested_skills or []
            ctx.meta["report_language"] = normalize_report_language(context.get("report_language", "zh"))
            if context.get("market_phase_context"):
                ctx.meta["market_phase_context"] = context["market_phase_context"]
            daily_market_context = context.get("daily_market_context")
            if isinstance(daily_market_context, dict) and daily_market_context:
                ctx.meta["daily_market_context"] = dict(daily_market_context)
            market_structure_context = context.get("market_structure_context")
            if isinstance(market_structure_context, dict) and market_structure_context:
                ctx.meta["market_structure_context"] = dict(market_structure_context)
            analysis_context_pack_summary = context.get("analysis_context_pack_summary")
            if isinstance(analysis_context_pack_summary, str) and analysis_context_pack_summary:
                ctx.meta["analysis_context_pack_summary"] = analysis_context_pack_summary

            # Pre-populate data fields that the caller already has
            for data_key in ("realtime_quote", "daily_history", "chip_distribution",
                             "trend_result", "news_context"):
                if context.get(data_key):
                    ctx.set_data(data_key, context[data_key])

        # Try to extract stock code from the query text
        if scope_resolution is not None:
            ctx.stock_code = scope_resolution.stock_scope.expected_stock_code
            ctx.meta["stock_scope"] = scope_resolution.stock_scope
            ctx.meta["stock_canonical_id"] = (context or {}).get("canonical_id")
            ctx.meta["stock_asset_type"] = (context or {}).get("asset_type")
        elif not ctx.stock_code:
            ctx.stock_code = _extract_stock_code(task)

        if "report_language" not in ctx.meta:
            ctx.meta["report_language"] = "zh"

        return ctx

    @staticmethod
    def _fallback_summary(ctx: AgentContext) -> str:
        """Build a plaintext summary when dashboard JSON is unavailable."""
        report_language = normalize_report_language(ctx.meta.get("report_language"))
        if report_language == "ko":
            heading = f"# 분석 요약: {ctx.stock_code} ({ctx.stock_name})"
            signal_fmt = "신호: {signal} (신뢰도: {conf:.0%})"
            risk_heading = "## 리스크 플래그"
        else:
            heading = f"# Analysis Summary: {ctx.stock_code} ({ctx.stock_name})"
            signal_fmt = "Signal: {signal} (confidence: {conf:.0%})"
            risk_heading = "## Risk Flags"

        lines = [heading, ""]
        for op in ctx.opinions:
            lines.append(f"## {op.agent_name}")
            conf = coerce_finite_float(op.confidence)
            lines.append(signal_fmt.format(signal=op.signal, conf=conf if conf is not None else 0.0))
            lines.append(str(op.reasoning or ""))
            lines.append("")
        valid_flags = [rf for rf in ctx.risk_flags if isinstance(rf, dict)]
        if valid_flags:
            lines.append(risk_heading)
            for rf in valid_flags:
                severity = str(rf.get("severity") or "medium")
                description = str(rf.get("description") or "")
                lines.append(f"- [{severity}] {description}")
        return "\n".join(lines)

    def _resolve_final_output(
        self,
        ctx: AgentContext,
        *,
        parse_dashboard: bool,
    ) -> tuple[Optional[Dict[str, Any]], str]:
        """Resolve the best available final output from context.

        For dashboard mode, prefer:
        1. Parsed/normalized decision dashboard
        2. Parsed raw dashboard text
        3. Synthesised dashboard from completed opinions
        4. Plaintext fallback summary
        """
        final_dashboard = ctx.get_data("final_dashboard")
        final_raw = ctx.get_data("final_dashboard_raw")
        final_text = ctx.get_data("final_response_text")
        chat_mode = ctx.meta.get("response_mode") == "chat"

        if parse_dashboard:
            dashboard = self._resolve_dashboard_payload(ctx, final_dashboard, final_raw)
            if dashboard is not None:
                return dashboard, json.dumps(dashboard, ensure_ascii=False, indent=2)
            if ctx.opinions:
                return None, self._fallback_summary(ctx)
            return None, ""

        if _risk_review_incomplete(ctx):
            language = normalize_report_language(ctx.meta.get("report_language"))
            return None, _INCOMPLETE_RISK_REVIEW_NOTE[language]
        if ctx.meta.get("risk_review_required") and self._risk_blocks_buy(ctx):
            # Free-form Chat replies can mix signals. Use the authoritative
            # review result before the reply is returned or saved to history.
            language = normalize_report_language(ctx.meta.get("report_language"))
            return None, _BUY_BLOCKED_BY_RISK_REVIEW_NOTE[language]
        if chat_mode and isinstance(final_text, str) and final_text.strip():
            return None, final_text.strip()
        if isinstance(final_raw, str) and final_raw.strip():
            return None, final_raw
        if isinstance(final_dashboard, dict):
            dashboard = self._finalize_dashboard_payload(final_dashboard, ctx)
            if dashboard is not None:
                return dashboard, json.dumps(dashboard, ensure_ascii=False, indent=2)
        if ctx.opinions:
            return None, self._fallback_summary(ctx)
        return None, ""

    def _resolve_dashboard_payload(
        self,
        ctx: AgentContext,
        final_dashboard: Any,
        final_raw: Any,
    ) -> Optional[Dict[str, Any]]:
        """Resolve one dashboard, apply risk once, then derive signal fields."""
        candidate: Optional[Dict[str, Any]] = None

        if isinstance(final_dashboard, dict):
            candidate = final_dashboard
        elif isinstance(final_raw, str) and final_raw.strip():
            parsed = parse_dashboard_json(final_raw)
            if isinstance(parsed, dict):
                candidate = parsed

        prepared = self._prepare_dashboard_payload(candidate or {}, ctx)
        if prepared is None:
            return None

        if ctx.meta.get("risk_review_required"):
            self._apply_mandatory_review_to_signal(ctx, prepared)
        ctx.set_data("final_dashboard", prepared)
        self._apply_risk_override(ctx)
        post_risk = ctx.get_data("final_dashboard")
        if not isinstance(post_risk, dict):
            return None

        dashboard = self._finalize_dashboard_payload(post_risk, ctx)
        if dashboard is None:
            return None
        ctx.set_data("final_dashboard", dashboard)
        return dashboard

    def _apply_mandatory_review_to_signal(self, ctx: AgentContext, payload: Dict[str, Any]) -> None:
        signal = payload["decision_type"]
        nested = payload.get("dashboard")
        has_buy_advice = _dashboard_recommends_buy(payload) or (
            isinstance(nested, dict) and _dashboard_recommends_buy(nested)
        )
        if _risk_review_incomplete(ctx):
            if signal == "buy" or has_buy_advice:
                payload["decision_type"] = "hold"
        elif signal != "buy" and has_buy_advice and self._risk_blocks_buy(ctx):
            # The veto must see the buy recommendation even when the model's
            # three-state statistics field disagrees with the actionable advice.
            payload["decision_type"] = "buy"

    def _risk_blocks_buy(self, ctx: AgentContext) -> bool:
        return bool(build_risk_override_plan(
            ctx, current_signal="buy", override_enabled=getattr(self.config, "agent_risk_override", True),
        ).will_apply)

    def _prepare_dashboard_payload(
        self,
        payload: Optional[Dict[str, Any]],
        ctx: AgentContext,
    ) -> Optional[Dict[str, Any]]:
        """Select a safe payload and canonical signal without deriving advice."""
        prepared = sanitize_agent_dashboard_payload(dict(payload or {}))
        meaningful_data_keys = (
            "realtime_quote",
            "daily_history",
            "chip_distribution",
            "trend_result",
            "news_context",
            "intel_opinion",
            "fundamental_context",
        )
        has_meaningful_context = any(
            ctx.get_data(key) is not None for key in meaningful_data_keys
        )
        if not prepared and not ctx.opinions and not has_meaningful_context:
            return None

        base_opinion = self._select_base_opinion(ctx)
        prepared["decision_type"] = normalize_decision_signal(
            prepared.get("decision_type")
            or (base_opinion.signal if base_opinion else "hold")
        )
        return prepared

    def _finalize_dashboard_payload(
        self,
        payload: Optional[Dict[str, Any]],
        ctx: AgentContext,
    ) -> Optional[Dict[str, Any]]:
        """Derive the downstream dashboard shape from the post-risk signal."""
        payload = sanitize_agent_dashboard_payload(dict(payload or {}))
        meaningful_data_keys = (
            "realtime_quote",
            "daily_history",
            "chip_distribution",
            "trend_result",
            "news_context",
            "intel_opinion",
            "fundamental_context",
        )
        has_meaningful_context = any(ctx.get_data(key) is not None for key in meaningful_data_keys)
        if not payload and not ctx.opinions and not has_meaningful_context:
            return None

        base_opinion = self._select_base_opinion(ctx)
        application = ctx.meta.get("risk_override_application")
        risk_applied = isinstance(application, RiskOverrideApplication) and application.applied
        decision_type = (
            application.post_risk_signal.value
            if risk_applied
            else normalize_decision_signal(
                payload.get("decision_type")
                or (base_opinion.signal if base_opinion else "hold")
            )
        )
        review_incomplete = _risk_review_incomplete(ctx)
        review_blocks_buy = review_incomplete or (
            ctx.meta.get("risk_review_required") and (risk_applied or self._risk_blocks_buy(ctx))
        )
        risk_adjusted = risk_applied or review_blocks_buy
        raw_confidence = coerce_finite_float(getattr(base_opinion, "confidence", None))
        confidence = max(0.0, min(1.0, raw_confidence)) if raw_confidence is not None else 0.5
        parsed_score = coerce_finite_float(payload.get("sentiment_score"))
        if parsed_score is not None:
            sentiment_score = max(0, min(100, int(parsed_score)))
        else:
            sentiment_score = _estimate_sentiment_score(decision_type, confidence)
        if risk_adjusted:
            sentiment_score = _adjust_sentiment_score(sentiment_score, decision_type)

        dashboard_block = payload.get("dashboard")
        if not isinstance(dashboard_block, dict):
            dashboard_block = {}
        else:
            dashboard_block = dict(dashboard_block)
            # Strip any LLM-written strategy_synthesis — StrategyEngine is the sole writer.
            dashboard_block.pop("strategy_synthesis", None)

        core = dashboard_block.get("core_conclusion")
        if not isinstance(core, dict):
            core = {}
        else:
            core = dict(core)

        intelligence = dashboard_block.get("intelligence")
        if not isinstance(intelligence, dict):
            intelligence = {}
        else:
            intelligence = dict(intelligence)

        battle = dashboard_block.get("battle_plan")
        if not isinstance(battle, dict):
            battle = {}
        else:
            battle = dict(battle)

        report_language = normalize_report_language(ctx.meta.get("report_language"))
        review_note = _INCOMPLETE_RISK_REVIEW_NOTE[report_language]
        if review_incomplete:
            analysis_summary = review_note
        elif review_blocks_buy:
            notes = _APPLIED_RISK_REVIEW_NOTE if risk_applied else _BUY_BLOCKED_BY_RISK_REVIEW_NOTE
            analysis_summary = notes[report_language]
        else:
            analysis_summary = _first_non_empty_text(
                payload.get("analysis_summary"),
                core.get("one_sentence"),
                getattr(base_opinion, "reasoning", ""),
            )
        if not analysis_summary:
            op_label = _signal_to_operation(decision_type, report_language)
            if report_language == "en":
                analysis_summary = (
                    f"Multi-agent pipeline did not produce a full dashboard; handling as {op_label}."
                )
            elif report_language == "ko":
                analysis_summary = (
                    f"멀티 에이전트가 전체 대시보드를 생성하지 못해 {op_label} 기준으로 처리했습니다."
                )
            else:
                analysis_summary = f"多 Agent 未生成完整仪表盘，当前按{op_label}处理。"
        if risk_applied:
            if report_language == "en":
                transition_prefix = (
                    f"[Risk Downgrade: {application.from_signal.value} -> "
                    f"{application.post_risk_signal.value}]"
                )
            elif report_language == "ko":
                transition_prefix = (
                    f"[리스크 하향: {application.from_signal.value} -> "
                    f"{application.post_risk_signal.value}]"
                )
            else:
                transition_prefix = (
                    f"[风控下调: {application.from_signal.value} -> "
                    f"{application.post_risk_signal.value}]"
                )
            if not analysis_summary.startswith(transition_prefix):
                analysis_summary = f"{transition_prefix} {analysis_summary}"
        analysis_summary = _truncate_text(analysis_summary, 220)

        trend_prediction = _first_non_empty_text(
            payload.get("trend_prediction"),
            (getattr(base_opinion, "raw_data", {}) or {}).get("trend_summary")
            if base_opinion is not None else "",
        )
        if not trend_prediction:
            technical = self._latest_opinion(ctx, {"technical"})
            tech_raw = technical.raw_data if technical and isinstance(technical.raw_data, dict) else {}
            ma_alignment = coerce_text(tech_raw.get("ma_alignment"), default="", fallback_on_empty=True).strip()
            trend_score_num = coerce_finite_float(tech_raw.get("trend_score"))
            if ma_alignment or trend_score_num is not None:
                if trend_score_num is not None:
                    score_display: Any = (
                        int(trend_score_num)
                        if trend_score_num.is_integer()
                        else round(trend_score_num, 2)
                    )
                else:
                    score_display = "N/A"
                if report_language == "en":
                    trend_prediction = (
                        f"Technicals {ma_alignment or 'neutral'}, trend score {score_display}"
                    )
                elif report_language == "ko":
                    trend_prediction = (
                        f"기술적 추세 {ma_alignment or 'neutral'}, 추세 점수 {score_display}"
                    )
                else:
                    trend_prediction = f"技术面{ma_alignment or 'neutral'}，趋势评分 {score_display}"
            else:
                if report_language == "en":
                    trend_prediction = "Pending further stage confirmation"
                elif report_language == "ko":
                    trend_prediction = "추가 단계 결과 확인 필요"
                else:
                    trend_prediction = "待结合更多阶段结果确认"

        operation_advice_raw = payload.get("operation_advice")
        if review_blocks_buy:
            action = "watch"
            if decision_type == "sell":
                model_action = normalize_decision_action(payload.get("action") or operation_advice_raw)
                action = "reduce" if model_action == "reduce" else "sell"
            operation_advice = localize_action_label(action, report_language)
        elif risk_applied:
            pre_risk_advice = _normalize_operation_advice_value(
                operation_advice_raw,
                application.from_signal.value,
                report_language,
            )
            operation_advice = _adjust_operation_advice(
                pre_risk_advice,
                decision_type,
                report_language,
            )
        else:
            operation_advice = _normalize_operation_advice_value(
                operation_advice_raw,
                decision_type,
                report_language,
            )

        existing_position = core.get("position_advice")
        if risk_adjusted:
            position_advice = _post_risk_position_advice(decision_type, report_language)
        else:
            position_advice = (
                dict(existing_position)
                if isinstance(existing_position, dict)
                else {}
            )
            if isinstance(operation_advice_raw, dict):
                no_position = _first_non_empty_text(
                    operation_advice_raw.get("no_position"),
                    operation_advice_raw.get("empty_position"),
                )
                has_position = _first_non_empty_text(
                    operation_advice_raw.get("has_position"),
                    operation_advice_raw.get("holding_position"),
                )
                if no_position and "no_position" not in position_advice:
                    position_advice["no_position"] = no_position
                if has_position and "has_position" not in position_advice:
                    position_advice["has_position"] = has_position
            defaults = _default_position_advice(decision_type, report_language)
            position_advice.setdefault("no_position", defaults["no_position"])
            position_advice.setdefault("has_position", defaults["has_position"])

        key_levels = self._collect_key_levels(ctx, payload, dashboard_block)
        sniper = battle.get("sniper_points")
        if not isinstance(sniper, dict):
            sniper = {}
        else:
            sniper = dict(sniper)

        ideal_buy = _pick_first_level(
            sniper.get("ideal_buy"),
            key_levels.get("ideal_buy_if_valuation_improves"),
            key_levels.get("ideal_buy"),
            key_levels.get("support"),
            key_levels.get("immediate_support"),
        )
        sniper["ideal_buy"] = ideal_buy if ideal_buy is not None else "N/A"

        secondary_buy = _coerce_level_value(sniper.get("secondary_buy"))
        if secondary_buy is None:
            secondary_buy = _pick_first_level(
                key_levels.get("secondary_buy"),
                key_levels.get("support"),
                key_levels.get("immediate_support"),
            )
        if _level_values_equal(secondary_buy, sniper.get("ideal_buy")):
            secondary_buy = None
        sniper["secondary_buy"] = secondary_buy if secondary_buy is not None else "N/A"
        placeholder_text = get_placeholder_text(report_language)
        stop_loss = _pick_first_level(
            sniper.get("stop_loss"),
            key_levels.get("stop_loss"),
            key_levels.get("strong_support_stop_loss"),
        )
        sniper["stop_loss"] = stop_loss if stop_loss is not None else placeholder_text
        take_profit = _pick_first_level(
            sniper.get("take_profit"),
            key_levels.get("take_profit"),
            key_levels.get("next_breakout_target"),
            key_levels.get("current_resistance"),
            key_levels.get("resistance"),
        )
        sniper["take_profit"] = take_profit if take_profit is not None else "N/A"

        risk_alerts = self._collect_risk_alerts(ctx, intelligence)
        positive_catalysts = self._collect_positive_catalysts(ctx, intelligence)
        latest_news = _extract_latest_news_title(intelligence)

        if not isinstance(intelligence.get("risk_alerts"), list):
            intelligence["risk_alerts"] = coerce_str_list(intelligence.get("risk_alerts")) or risk_alerts
        elif not intelligence.get("risk_alerts"):
            intelligence["risk_alerts"] = risk_alerts
        if not isinstance(intelligence.get("positive_catalysts"), list):
            coerced_catalysts = coerce_str_list(intelligence.get("positive_catalysts"))
            if coerced_catalysts:
                intelligence["positive_catalysts"] = coerced_catalysts
            elif positive_catalysts:
                intelligence["positive_catalysts"] = positive_catalysts
            else:
                intelligence.pop("positive_catalysts", None)
        elif positive_catalysts and not intelligence.get("positive_catalysts"):
            intelligence["positive_catalysts"] = positive_catalysts
        if latest_news and not intelligence.get("latest_news"):
            intelligence["latest_news"] = latest_news

        one_sentence = analysis_summary if review_blocks_buy else _first_non_empty_text(
            core.get("one_sentence"),
            analysis_summary,
        )
        if risk_applied and not one_sentence.startswith(transition_prefix):
            one_sentence = f"{transition_prefix} {one_sentence}"
        core["one_sentence"] = _truncate_text(one_sentence, 60)
        if not core.get("time_sensitivity"):
            core["time_sensitivity"] = get_report_labels(report_language)["default_time_sensitivity"]
        if risk_adjusted or not core.get("signal_type"):
            core["signal_type"] = _signal_to_signal_type(decision_type, report_language)
        core["position_advice"] = position_advice

        battle["sniper_points"] = sniper
        if review_blocks_buy:
            for block in (payload, dashboard_block):
                block.update(action=action, action_label=operation_advice)
                phase_decision = block.get("phase_decision")
                if isinstance(phase_decision, dict):
                    block["phase_decision"] = {
                        **phase_decision,
                        "action_window": None,
                        "immediate_action": operation_advice,
                        "watch_conditions": [analysis_summary],
                    }
            if "decision_type" in dashboard_block:
                dashboard_block["decision_type"] = decision_type
            if "operation_advice" in dashboard_block:
                dashboard_block["operation_advice"] = operation_advice
            battle["action_checklist"] = [analysis_summary]
        elif "action_checklist" not in battle:
            battle["action_checklist"] = []
        elif not isinstance(battle.get("action_checklist"), list):
            battle["action_checklist"] = coerce_str_list(battle.get("action_checklist"))
        position_strategy = battle.get("position_strategy")
        stop_loss_value = sniper.get("stop_loss", placeholder_text)
        if report_language == "en":
            risk_ctrl_adjusted = f"Stop-loss reference: {stop_loss_value}"
            risk_ctrl_default = f"Stop-loss reference {stop_loss_value}"
        elif report_language == "ko":
            risk_ctrl_adjusted = f"손절 참고: {stop_loss_value}"
            risk_ctrl_default = f"손절 참고 {stop_loss_value}"
        else:
            risk_ctrl_adjusted = f"止损参考：{stop_loss_value}"
            risk_ctrl_default = f"止损参考 {stop_loss_value}"
        if risk_adjusted:
            position_strategy = (
                dict(position_strategy)
                if isinstance(position_strategy, dict)
                else {}
            )
            position_strategy["suggested_position"] = _default_position_size(decision_type, report_language)
            position_strategy["entry_plan"] = position_advice["no_position"]
            if review_blocks_buy or "risk_control" not in position_strategy:
                position_strategy["risk_control"] = risk_ctrl_adjusted
            battle["position_strategy"] = position_strategy
        elif not isinstance(position_strategy, dict) or not position_strategy:
            battle["position_strategy"] = {
                "suggested_position": _default_position_size(decision_type, report_language),
                "entry_plan": position_advice["no_position"],
                "risk_control": risk_ctrl_default,
            }

        raw_dp = dashboard_block.get("data_perspective")
        data_perspective = (
            _sanitize_data_perspective(raw_dp, report_language)
            if isinstance(raw_dp, dict)
            else {}
        )
        built_data_perspective = self._build_data_perspective(ctx, key_levels)
        if built_data_perspective:
            built_sanitized = _sanitize_data_perspective(built_data_perspective, report_language)
            for section_key in ("trend_status", "price_position", "volume_analysis", "chip_structure"):
                if section_key not in data_perspective and section_key in built_sanitized:
                    data_perspective[section_key] = built_sanitized[section_key]
        if data_perspective:
            dashboard_block["data_perspective"] = data_perspective
        else:
            dashboard_block.pop("data_perspective", None)

        strategy_synthesis = self._collect_strategy_synthesis(ctx, dashboard_block)
        if strategy_synthesis:
            dashboard_block["strategy_synthesis"] = strategy_synthesis

        dashboard_block["core_conclusion"] = core
        dashboard_block["intelligence"] = intelligence
        dashboard_block["battle_plan"] = battle

        key_points = None if review_blocks_buy else payload.get("key_points")
        if not isinstance(key_points, list) or not key_points:
            key_points = [
                _truncate_text(op.reasoning, 120)
                for op in ctx.opinions
                if isinstance(op.reasoning, str) and op.reasoning.strip()
                and not (review_blocks_buy and op.agent_name == "decision")
            ][:5]

        risk_sep = "；" if report_language == "zh" else "; "
        risk_warning = _first_non_empty_text(
            payload.get("risk_warning"),
            risk_sep.join(risk_alerts[:3]),
            getattr(self._latest_opinion(ctx, {"risk"}), "reasoning", ""),
        )
        if not risk_warning:
            risk_warning = _EMPTY_RISK_WARNING[report_language]
        if risk_applied:
            risk_opinion = self._latest_opinion(ctx, {"risk"})
            risk_raw = (
                risk_opinion.raw_data
                if risk_opinion and isinstance(risk_opinion.raw_data, dict)
                else {}
            )
            risk_warning = self._merge_risk_warning(
                risk_warning,
                risk_raw,
                ctx.risk_flags,
                decision_type,
                report_language=report_language,
            )
        if review_incomplete and not risk_warning.startswith(review_note):
            risk_warning = f"{review_note} {risk_warning}"

        payload["stock_name"] = _first_non_empty_text(payload.get("stock_name"), ctx.stock_name, ctx.stock_code)
        payload["sentiment_score"] = sentiment_score
        payload["trend_prediction"] = trend_prediction
        payload["operation_advice"] = operation_advice
        payload["decision_type"] = decision_type
        payload["confidence_level"] = _confidence_label(confidence, report_language)
        payload["analysis_summary"] = analysis_summary
        payload["key_points"] = key_points
        payload["risk_warning"] = risk_warning
        payload["dashboard"] = dashboard_block
        payload = sanitize_non_finite_floats(payload)
        if risk_adjusted:
            for opinion in reversed(ctx.opinions):
                if opinion.agent_name == "decision":
                    opinion.signal = decision_type
                    opinion.reasoning = analysis_summary
                    opinion.raw_data = payload
                    break
        return payload

    def _collect_strategy_synthesis(
        self,
        ctx: AgentContext,
        dashboard_block: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        # Deterministic synthesis from skill_consensus is the authoritative source
        consensus_data = ctx.get_data("skill_consensus")
        if isinstance(consensus_data, dict):
            synthesis = consensus_data.get("strategy_synthesis")
            if isinstance(synthesis, dict) and synthesis:
                return synthesis
            raw_data = consensus_data.get("raw_data")
            if isinstance(raw_data, dict):
                synthesis = raw_data.get("strategy_synthesis")
                if isinstance(synthesis, dict) and synthesis:
                    return synthesis

        # Fallback: scan opinions
        for opinion in reversed(ctx.opinions):
            if getattr(opinion, "agent_name", "") != "skill_consensus":
                continue
            raw_data = opinion.raw_data if isinstance(opinion.raw_data, dict) else {}
            synthesis = raw_data.get("strategy_synthesis")
            if isinstance(synthesis, dict) and synthesis:
                return synthesis
        return None

    def _collect_key_levels(
        self,
        ctx: AgentContext,
        payload: Dict[str, Any],
        dashboard_block: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Collect key price levels from dashboard payloads and agent opinions."""
        levels: Dict[str, Any] = {}

        def absorb(source: Any) -> None:
            if not isinstance(source, dict):
                return
            for key, value in source.items():
                normalized = _coerce_level_value(value)
                if normalized is not None and key not in levels:
                    levels[key] = normalized

        absorb(payload.get("key_levels"))
        absorb(dashboard_block.get("key_levels"))
        for opinion in reversed(ctx.opinions):
            absorb(getattr(opinion, "key_levels", {}))
            raw = opinion.raw_data if isinstance(opinion.raw_data, dict) else {}
            absorb(raw.get("key_levels"))
        return levels

    def _build_data_perspective(
        self,
        ctx: AgentContext,
        key_levels: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a lightweight data_perspective block from cached market data."""
        report_language = normalize_report_language(ctx.meta.get("report_language"))
        realtime = ctx.get_data("realtime_quote")
        realtime_dict = realtime if isinstance(realtime, dict) else {}
        chip = ctx.get_data("chip_distribution")
        trend = ctx.get_data("trend_result")
        technical = self._latest_opinion(ctx, {"technical"})
        tech_raw = technical.raw_data if technical and isinstance(technical.raw_data, dict) else {}
        trend_dict = trend if isinstance(trend, dict) else {}

        data_perspective: Dict[str, Any] = {}
        ma_alignment = coerce_text(tech_raw.get("ma_alignment"), default="", fallback_on_empty=True).strip()
        trend_score_num = coerce_finite_float(tech_raw.get("trend_score"))
        trend_score_display: Any = (
            (int(trend_score_num) if trend_score_num.is_integer() else round(trend_score_num, 2))
            if trend_score_num is not None
            else None
        )
        if ma_alignment or trend_score_display is not None:
            data_perspective["trend_status"] = {
                "ma_alignment": ma_alignment or "N/A",
                "trend_score": trend_score_display if trend_score_display is not None else "N/A",
                "is_bullish": ma_alignment.lower() == "bullish",
            }

        def _bias_label(bias):
            val = coerce_finite_float(bias)
            if val is None:
                return ""
            if report_language == "en":
                if val > 5:
                    return "Overbought"
                if val > 2:
                    return "Elevated"
                if val < -5:
                    return "Oversold"
                if val < -2:
                    return "Depressed"
                return "Neutral"
            if report_language == "ko":
                if val > 5:
                    return "과매수"
                if val > 2:
                    return "과열 주의"
                if val < -5:
                    return "과매도"
                if val < -2:
                    return "저평가 권역"
                return "중립"
            if val > 5:
                return "超买"
            elif val > 2:
                return "偏高"
            elif val < -5:
                return "超卖"
            elif val < -2:
                return "偏低"
            return "中性"

        def _r(val, n=2):
            """Round finite numeric values for display."""
            return _sanitize_display_number(val, round_digits=n, default="N/A")

        def _clean_metric(val):
            """Sanitize scalar numeric/string metrics and reject bool/containers/non-finite."""
            return _sanitize_display_number(val, default="N/A")

        def _pick(primary_dict, primary_key, fallback_dict, fallback_key, default="N/A"):
            """Pick first non-None value, avoiding falsy-zero trap."""
            v = primary_dict.get(primary_key)
            if v is not None:
                return v
            v2 = fallback_dict.get(fallback_key, default)
            return v2 if v2 is not None else default

        if realtime_dict or trend_dict:
            support_val = _pick_first_level(
                key_levels.get("support"),
                key_levels.get("immediate_support"),
            )
            resistance_val = _pick_first_level(
                key_levels.get("resistance"),
                key_levels.get("current_resistance"),
            )
            fallback_bias_status = coerce_text(tech_raw.get("bias_status"), default="", fallback_on_empty=True).strip()
            bias_status = _bias_label(trend_dict.get("bias_ma5")) or (
                localize_bias_status(fallback_bias_status, report_language)
                if fallback_bias_status
                else "N/A"
            )
            raw_volume_status = trend_dict.get("volume_status") or tech_raw.get("volume_status")
            volume_status_text = coerce_text(raw_volume_status, default="", fallback_on_empty=True).strip()
            localized_volume_status = (
                localize_volume_status(volume_status_text, report_language)
                if volume_status_text
                else "N/A"
            )
            data_perspective["price_position"] = {
                "current_price": _r(_pick(trend_dict, "current_price", realtime_dict, "price")),
                "ma5": _r(_pick(trend_dict, "ma5", tech_raw, "ma5")),
                "ma10": _r(_pick(trend_dict, "ma10", tech_raw, "ma10")),
                "ma20": _r(_pick(trend_dict, "ma20", tech_raw, "ma20")),
                "bias_ma5": _r(_pick(trend_dict, "bias_ma5", tech_raw, "bias_ma5")),
                "bias_status": bias_status,
                "support_level": support_val if support_val is not None else "N/A",
                "resistance_level": resistance_val if resistance_val is not None else "N/A",
            }
            data_perspective["volume_analysis"] = {
                "volume_ratio": _clean_metric(realtime_dict.get("volume_ratio", "N/A")),
                "turnover_rate": _clean_metric(realtime_dict.get("turnover_rate", "N/A")),
                "volume_status": localized_volume_status,
                "volume_meaning": coerce_text(tech_raw.get("reasoning"), default="") if tech_raw else "",
            }

        if isinstance(chip, dict):
            concentration = chip.get("concentration_90")
            if concentration is None:
                concentration = chip.get("concentration")
            raw_chip_health = coerce_text(chip.get("chip_health"), default="", fallback_on_empty=True).strip()
            chip_health = (
                localize_chip_health(raw_chip_health, report_language)
                if raw_chip_health
                else localize_chip_health("average", report_language)
            )
            data_perspective["chip_structure"] = {
                "profit_ratio": _clean_metric(chip.get("profit_ratio", "N/A")),
                "avg_cost": _clean_metric(chip.get("avg_cost", "N/A")),
                "concentration": _clean_metric(concentration) if concentration is not None else "N/A",
                "chip_health": chip_health,
            }

        return data_perspective

    def _collect_risk_alerts(
        self,
        ctx: AgentContext,
        intelligence: Dict[str, Any],
    ) -> List[str]:
        alerts: List[str] = []

        def absorb(values: Any) -> None:
            if not isinstance(values, list):
                return
            for item in values:
                text = ""
                if isinstance(item, str):
                    text = item.strip()
                elif isinstance(item, dict):
                    text = str(item.get("description") or item.get("title") or "").strip()
                if text and text not in alerts:
                    alerts.append(text)

        absorb(intelligence.get("risk_alerts"))
        intel = self._latest_opinion(ctx, {"intel"})
        intel_raw = intel.raw_data if intel and isinstance(intel.raw_data, dict) else {}
        absorb(intel_raw.get("risk_alerts"))
        risk = self._latest_opinion(ctx, {"risk"})
        risk_raw = risk.raw_data if risk and isinstance(risk.raw_data, dict) else {}
        absorb(risk_raw.get("flags"))
        for flag in ctx.risk_flags:
            description = str(flag.get("description", "")).strip()
            if description and description not in alerts:
                alerts.append(description)
        return alerts[:8]

    def _collect_positive_catalysts(
        self,
        ctx: AgentContext,
        intelligence: Dict[str, Any],
    ) -> List[str]:
        catalysts: List[str] = []

        def absorb(values: Any) -> None:
            if not isinstance(values, list):
                return
            for item in values:
                text = str(item).strip()
                if text and text not in catalysts:
                    catalysts.append(text)

        absorb(intelligence.get("positive_catalysts"))
        intel = self._latest_opinion(ctx, {"intel"})
        intel_raw = intel.raw_data if intel and isinstance(intel.raw_data, dict) else {}
        absorb(intel_raw.get("positive_catalysts"))
        return catalysts[:8]

    @staticmethod
    def _latest_opinion(ctx: AgentContext, names: set[str]) -> Optional[Any]:
        for opinion in reversed(ctx.opinions):
            if opinion.agent_name in names:
                return opinion
        return None

    def _select_base_opinion(self, ctx: AgentContext) -> Optional[Any]:
        preferred_groups = (
            {"decision"},
            {"skill_consensus", "strategy_consensus"},
            {"technical"},
            {"intel"},
            {"risk"},
        )
        for names in preferred_groups:
            opinion = self._latest_opinion(ctx, names)
            if opinion is not None:
                return opinion
        if ctx.opinions:
            return ctx.opinions[-1]
        return None

    @staticmethod
    def _mark_partial_dashboard(
        dashboard: Dict[str, Any],
        *,
        note: str,
        report_language: str = "zh",
    ) -> Dict[str, Any]:
        tagged = dict(dashboard)
        summary = _first_non_empty_text(tagged.get("analysis_summary"))
        prefix = _DEGRADED_RESULT_PREFIX[normalize_report_language(report_language)]
        if summary and not summary.startswith(prefix):
            tagged["analysis_summary"] = prefix + summary
        elif not summary:
            tagged["analysis_summary"] = prefix + note

        warning = _first_non_empty_text(tagged.get("risk_warning"))
        tagged["risk_warning"] = f"{note} {warning}".strip() if warning else note

        nested = tagged.get("dashboard")
        if isinstance(nested, dict):
            nested = dict(nested)
            core = nested.get("core_conclusion")
            if isinstance(core, dict):
                core = dict(core)
                one_sentence = _first_non_empty_text(core.get("one_sentence"), tagged.get("analysis_summary"))
                if one_sentence and not str(one_sentence).startswith(prefix):
                    core["one_sentence"] = prefix + str(one_sentence)
                nested["core_conclusion"] = core
            tagged["dashboard"] = nested
        return tagged

    def _apply_risk_override(self, ctx: AgentContext) -> Optional[RiskOverrideApplication]:
        """Apply risk rules and retain their validated actual outcome."""
        dashboard = ctx.get_data("final_dashboard")
        if not isinstance(dashboard, dict):
            return None

        current_signal = normalize_decision_signal(dashboard.get("decision_type", "hold"))
        existing = ctx.meta.get("risk_override_application")
        if (
            isinstance(existing, RiskOverrideApplication)
            and existing.post_risk_signal.value == current_signal
        ):
            return existing

        plan = build_risk_override_plan(
            ctx,
            current_signal=current_signal,
            override_enabled=getattr(self.config, "agent_risk_override", True),
        )
        application = build_risk_override_application(plan)
        ctx.meta["risk_override_application"] = application
        if not application.applied:
            return application

        current_signal = application.from_signal.value
        new_signal = application.to_signal.value
        dashboard["decision_type"] = new_signal

        ctx.set_data("final_dashboard", dashboard)
        ctx.set_data("risk_override_applied", {
            "from": current_signal,
            "to": new_signal,
            "adjustment": plan.adjustment or ("veto" if plan.veto_buy else "none"),
            "reason": plan.reason,
        })

        logger.info(
            "[Orchestrator] risk override applied: %s -> %s (adjustment=%s, high_flag=%s)",
            current_signal,
            new_signal,
            plan.adjustment or ("veto" if plan.veto_buy else "none"),
            plan.has_high_flag,
        )
        return application

    @staticmethod
    def _merge_risk_warning(
        existing_warning: Any,
        risk_raw: Dict[str, Any],
        risk_flags: List[Dict[str, Any]],
        signal: str,
        *,
        report_language: str = "zh",
    ) -> str:
        """Build a concise risk warning after a forced downgrade."""
        warnings: List[str] = []
        if isinstance(existing_warning, str) and existing_warning.strip():
            warnings.append(existing_warning.strip())
        if isinstance(risk_raw.get("reasoning"), str) and risk_raw["reasoning"].strip():
            warnings.append(risk_raw["reasoning"].strip())
        for flag in risk_flags[:3]:
            if not isinstance(flag, dict):
                continue
            description = str(flag.get("description", "")).strip()
            severity = str(flag.get("severity", "")).lower()
            if description:
                warnings.append(f"[{severity or 'risk'}] {description}")
        lang = normalize_report_language(report_language)
        if lang == "en":
            prefix = f"Risk override active: final signal downgraded to {signal}."
        elif lang == "ko":
            prefix = f"리스크 통제 발동: 최종 신호가 {signal}(으)로 하향 조정되었습니다."
        else:
            prefix = f"风控接管：最终信号已下调为 {signal}。"
        merged = " ".join(dict.fromkeys([prefix] + warnings))
        return merged[:500]


# Common English words (2-5 uppercase letters) that should NOT be treated as
# US stock tickers.  This set is checked by _extract_stock_code() and should
# be kept at module level to avoid re-creating it on every call.
_COMMON_WORDS: set[str] = {
    # Pronouns / articles / prepositions / conjunctions
    "AM", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO",
    "UP", "US", "WE",
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL",
    "CAN", "HAD", "HER", "WAS", "ONE", "OUR", "OUT", "HAS",
    "HIS", "HOW", "ITS", "LET", "MAY", "NEW", "NOW", "OLD",
    "SEE", "WAY", "WHO", "DID", "GET", "HIM", "USE", "SAY",
    "SHE", "TOO", "ANY", "WITH", "FROM", "THAT", "THAN",
    "THIS", "WHAT", "WHEN", "WILL", "JUST", "ALSO",
    "BEEN", "EACH", "HAVE", "MUCH", "ONLY", "OVER",
    "SOME", "SUCH", "THEM", "THEN", "THEY", "VERY",
    "WERE", "YOUR", "ABOUT", "AFTER", "COULD", "EVERY",
    "OTHER", "THEIR", "THERE", "THESE", "THOSE", "WHICH",
    "WOULD", "BEING", "STILL", "WHERE",
    # Finance/analysis jargon that looks like tickers
    "BUY", "SELL", "HOLD", "LONG", "PUT", "CALL",
    "ETF", "IPO", "RSI", "EPS", "PEG", "ROE", "ROA",
    "USA", "USD", "CNY", "HKD", "EUR", "GBP",
    "STOCK", "TRADE", "PRICE", "INDEX", "FUND",
    "HIGH", "LOW", "OPEN", "CLOSE", "STOP", "LOSS",
    "TREND", "BULL", "BEAR", "RISK", "CASH", "BOND",
    "MACD", "VWAP", "BOLL", "KDJ",
    "TTM", "LTM", "NTM", "FWD", "YOY", "QOQ", "YTD",
    "EBIT", "EBITDA", "DCF", "CAGR", "FCF", "NAV", "AUM",
    "PE", "PB",
    # Greetings / filler words that often appear in chat messages
    "HELLO", "PLEASE", "THANKS", "CHECK", "LOOK", "THINK",
    "MAYBE", "GUESS", "TELL", "SHOW", "WHAT", "WHATS",
    "WHY", "WHEN", "HOWDY", "HEY", "HI",
}

_LOWERCASE_TICKER_HINTS = re.compile(
    r"分析|看看|查一?下|研究|诊断|走势|趋势|股价|股票|个股",
)


def _is_denied_ticker_candidate(candidate: str) -> bool:
    """Return whether a text token should not be auto-treated as a ticker."""
    return (candidate or "").strip().upper() in _COMMON_WORDS


def _extract_stock_code(text: str) -> str:
    """Best-effort stock code extraction from free text."""
    # A-share 6-digit — use lookarounds instead of \b because Python's \b
    # does not fire at Chinese-character / digit boundaries.
    m = re.search(r'(?<!\d)((?:[03648]\d{5}|92\d{4}))(?!\d)', text)
    if m:
        return m.group(1)
    # HK — same lookaround approach
    m = re.search(r'(?<![a-zA-Z])(hk\d{5})(?!\d)', text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # US ticker — require 2+ uppercase letters bounded by non-alpha chars.
    for match in re.finditer(r'(?<![a-zA-Z])([A-Z]{2,5}(?:\.[A-Z]{1,2})?)(?![a-zA-Z])', text):
        candidate = match.group(1)
        if not _is_denied_ticker_candidate(candidate):
            return candidate

    stripped = (text or "").strip()
    bare_match = re.fullmatch(r'([A-Za-z]{2,5}(?:\.[A-Za-z]{1,2})?)', stripped)
    if bare_match:
        candidate = bare_match.group(1).upper()
        if not _is_denied_ticker_candidate(candidate):
            return candidate

    if not _LOWERCASE_TICKER_HINTS.search(stripped):
        return ""

    for match in re.finditer(r'(?<![a-zA-Z])([A-Za-z]{2,5}(?:\.[A-Za-z]{1,2})?)(?![a-zA-Z])', text):
        raw_candidate = match.group(1)
        candidate = raw_candidate.upper()
        if _is_denied_ticker_candidate(candidate):
            continue
        return candidate
    return ""


def _adjust_sentiment_score(score: int, signal: str) -> int:
    """Clamp sentiment score into the target band for the overridden signal."""
    bands = {
        "buy": (60, 79),
        "hold": (40, 59),
        "sell": (0, 39),
    }
    low, high = bands.get(signal, (0, 100))
    return max(low, min(high, score))


_SIGNAL_TO_OPERATION_MAP = {
    "zh": {"buy": "买入", "hold": "观望", "sell": "减仓/卖出"},
    "en": {"buy": "Buy", "hold": "Watch", "sell": "Reduce / Sell"},
    "ko": {"buy": "매수", "hold": "관망", "sell": "비중축소/매도"},
}

_SIGNAL_TO_SIGNAL_TYPE_MAP = {
    "zh": {
        "buy": "🟢买入信号",
        "hold": "🟡持有观望",
        "sell": "🔴卖出信号",
        "_default": "⚠️风险警告",
    },
    "en": {
        "buy": "🟢 Buy Signal",
        "hold": "🟡 Hold / Watch",
        "sell": "🔴 Sell Signal",
        "_default": "⚠️ Risk Warning",
    },
    "ko": {
        "buy": "🟢 매수 신호",
        "hold": "🟡 보유 / 관망",
        "sell": "🔴 매도 신호",
        "_default": "⚠️ 리스크 경고",
    },
}

_DEFAULT_POSITION_ADVICE_MAP = {
    "zh": {
        "buy": {
            "no_position": "可结合支撑位分批试仓，避免一次性追高。",
            "has_position": "可继续持有，回踩关键位不破再考虑加仓。",
        },
        "hold": {
            "no_position": "暂不追高，等待更清晰的入场条件。",
            "has_position": "以观察为主，跌破止损位再执行风控。",
        },
        "sell": {
            "no_position": "暂不参与，等待风险充分释放。",
            "has_position": "优先控制回撤，按计划减仓或离场。",
        },
    },
    "en": {
        "buy": {
            "no_position": "Build a starter position in tranches near support and avoid chasing rallies.",
            "has_position": "Hold core shares and add only if pullbacks hold key support.",
        },
        "hold": {
            "no_position": "Avoid chasing; wait for a clearer entry signal.",
            "has_position": "Hold and observe; enforce risk stops if key support breaks.",
        },
        "sell": {
            "no_position": "Stay on the sidelines until downside risks clear.",
            "has_position": "Prioritize drawdown control by trimming or exiting as planned.",
        },
    },
    "ko": {
        "buy": {
            "no_position": "지지선 부근에서 분할 진입하고 추격 매수는 피하세요.",
            "has_position": "보유를 유지하고 핵심 지지선 방어 시 추가 매수를 검토하세요.",
        },
        "hold": {
            "no_position": "추격 매수를 자제하고 명확한 진입 조건을 기다리세요.",
            "has_position": "관망을 우선하며 손절가 이탈 시 리스크 관리를 실행하세요.",
        },
        "sell": {
            "no_position": "리스크가 충분히 해소될 때까지 신규 진입을 보류하세요.",
            "has_position": "낙폭 방어를 우선하며 계획에 따라 비중 축소 또는 청산하세요.",
        },
    },
}

_POST_RISK_POSITION_ADVICE_MAP = {
    "zh": {
        "hold": {
            "no_position": "风险未解除前先观望，等待更清晰的入场条件。",
            "has_position": "谨慎持有并收紧止损，待风险缓解后再考虑加仓。",
        },
        "sell": {
            "no_position": "风险明显偏高，暂不新开仓。",
            "has_position": "优先控制回撤，建议减仓或退出高风险仓位。",
        },
    },
    "en": {
        "hold": {
            "no_position": "Stay on the sidelines until risks ease and a clearer setup emerges.",
            "has_position": "Hold cautiously with tighter stops; wait for risks to subside before adding.",
        },
        "sell": {
            "no_position": "Elevated risk; do not open new positions.",
            "has_position": "Prioritize drawdown control; trim or exit high-risk exposure.",
        },
    },
    "ko": {
        "hold": {
            "no_position": "리스크가 해소되기 전까지 관망하며 명확한 진입 조건을 기다리세요.",
            "has_position": "손절선을 강화해 신중히 보유하고 위험 완화 후 추가 매수를 검토하세요.",
        },
        "sell": {
            "no_position": "리스크가 높아 신규 매수를 보류하세요.",
            "has_position": "낙폭 방어를 우선하여 고위험 비중을 축소하거나 청산하세요.",
        },
    },
}

_DEFAULT_POSITION_SIZE_MAP = {
    "zh": {"buy": "轻仓试仓", "hold": "控制仓位", "sell": "降仓防守"},
    "en": {"buy": "Light probe position", "hold": "Controlled exposure", "sell": "Reduce / Defensive"},
    "ko": {"buy": "소규모 탐색 진입", "hold": "비중 관리", "sell": "비중 축소·방어"},
}


def _adjust_operation_advice(advice: str, signal: str, report_language: str = "zh") -> str:
    """Normalize action wording to the overridden decision signal."""
    lang = normalize_report_language(report_language)
    mapping = _SIGNAL_TO_OPERATION_MAP[lang]
    if signal not in mapping:
        return advice
    if advice == mapping[signal]:
        return advice
    if lang == "en":
        return f"{mapping[signal]} (downgraded by risk control)"
    if lang == "ko":
        return f"{mapping[signal]} (리스크 통제로 하향)"
    return f"{mapping[signal]}（原建议已被风控下调）"


def _signal_to_operation(signal: str, report_language: str = "zh") -> str:
    lang = normalize_report_language(report_language)
    mapping = _SIGNAL_TO_OPERATION_MAP[lang]
    return mapping.get(signal, mapping["hold"])


def _signal_to_signal_type(signal: str, report_language: str = "zh") -> str:
    lang = normalize_report_language(report_language)
    mapping = _SIGNAL_TO_SIGNAL_TYPE_MAP[lang]
    return mapping.get(signal, mapping["_default"])


def _default_position_advice(signal: str, report_language: str = "zh") -> Dict[str, str]:
    lang = normalize_report_language(report_language)
    mapping = _DEFAULT_POSITION_ADVICE_MAP[lang]
    return mapping.get(signal, mapping["hold"])


def _post_risk_position_advice(signal: str, report_language: str = "zh") -> Dict[str, str]:
    """Return authoritative position advice after an applied risk transition."""
    lang = normalize_report_language(report_language)
    mapping = _POST_RISK_POSITION_ADVICE_MAP[lang]
    return dict(mapping.get(signal, _default_position_advice(signal, lang)))


def _default_position_size(signal: str, report_language: str = "zh") -> str:
    lang = normalize_report_language(report_language)
    mapping = _DEFAULT_POSITION_SIZE_MAP[lang]
    return mapping.get(signal, mapping["hold"])


def _normalize_operation_advice_value(
    value: Any,
    signal: str,
    report_language: str = "zh",
) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _signal_to_operation(signal, report_language)


def _confidence_label(confidence: float, report_language: str = "zh") -> str:
    val = coerce_finite_float(confidence)
    if val is None:
        level = "low"
    elif val >= 0.75:
        level = "high"
    elif val >= 0.45:
        level = "medium"
    else:
        level = "low"
    return localize_confidence_level(level, report_language)


def _estimate_sentiment_score(signal: str, confidence: float) -> int:
    parsed = coerce_finite_float(confidence)
    clamped = max(0.0, min(1.0, parsed if parsed is not None else 0.5))
    bands = {
        "buy": (65, 79),
        "hold": (45, 59),
        "sell": (20, 39),
    }
    low, high = bands.get(signal, (45, 59))
    return int(round(low + (high - low) * clamped))


def _is_non_finite_numeric_str(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    try:
        return not math.isfinite(float(stripped))
    except OverflowError:
        return True
    except ValueError:
        return False


def _sanitize_display_number(
    val: Any,
    *,
    round_digits: Optional[int] = None,
    default: Any = "N/A",
) -> Any:
    """Return a finite display scalar, rejecting bool, containers, and non-finite inputs."""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        num = coerce_finite_float(val)
        if num is None:
            return default
        return round(num, round_digits) if round_digits is not None else num
    if isinstance(val, str):
        if _is_non_finite_numeric_str(val):
            return default
        return val
    return default


def _sanitize_data_perspective(
    dp: Dict[str, Any],
    report_language: str,
) -> Dict[str, Any]:
    """Normalize and sanitize both model-authored and synthesized data_perspective blocks."""
    cleaned = dict(dp)

    trend_status = cleaned.get("trend_status")
    if "trend_status" in cleaned and (not isinstance(trend_status, dict) or not trend_status):
        cleaned.pop("trend_status", None)
    elif isinstance(trend_status, dict):
        ts = dict(trend_status)
        ma = coerce_text(ts.get("ma_alignment"), default="", fallback_on_empty=True).strip()
        ts["ma_alignment"] = ma or "N/A"
        if "trend_score" in ts:
            t_score = coerce_finite_float(ts.get("trend_score"))
            if t_score is not None:
                ts["trend_score"] = int(t_score) if t_score.is_integer() else round(t_score, 2)
            else:
                ts["trend_score"] = "N/A"
        if "is_bullish" in ts and not isinstance(ts.get("is_bullish"), bool):
            ts["is_bullish"] = ma.lower() == "bullish"
        cleaned["trend_status"] = ts

    price_position = cleaned.get("price_position")
    if "price_position" in cleaned and (not isinstance(price_position, dict) or not price_position):
        cleaned.pop("price_position", None)
    elif isinstance(price_position, dict):
        pp = dict(price_position)
        for key in ("current_price", "ma5", "ma10", "ma20", "bias_ma5"):
            if key in pp:
                pp[key] = _sanitize_display_number(pp.get(key), round_digits=2, default="N/A")
        for key in ("support_level", "resistance_level"):
            if key in pp:
                level_val = _coerce_level_value(pp.get(key))
                pp[key] = level_val if level_val is not None else "N/A"
        if "bias_status" in pp:
            b_text = coerce_text(pp.get("bias_status"), default="", fallback_on_empty=True).strip()
            pp["bias_status"] = localize_bias_status(b_text, report_language) if b_text else "N/A"
        cleaned["price_position"] = pp

    volume_analysis = cleaned.get("volume_analysis")
    if "volume_analysis" in cleaned and (not isinstance(volume_analysis, dict) or not volume_analysis):
        cleaned.pop("volume_analysis", None)
    elif isinstance(volume_analysis, dict):
        va = dict(volume_analysis)
        for key in ("volume_ratio", "turnover_rate"):
            if key in va:
                va[key] = _sanitize_display_number(va.get(key), default="N/A")
        if "volume_status" in va:
            v_text = coerce_text(va.get("volume_status"), default="", fallback_on_empty=True).strip()
            va["volume_status"] = localize_volume_status(v_text, report_language) if v_text else "N/A"
        if "volume_meaning" in va:
            va["volume_meaning"] = coerce_text(va.get("volume_meaning"), default="")
        cleaned["volume_analysis"] = va

    chip_structure = cleaned.get("chip_structure")
    if "chip_structure" in cleaned and (not isinstance(chip_structure, dict) or not chip_structure):
        cleaned.pop("chip_structure", None)
    elif isinstance(chip_structure, dict):
        cs = dict(chip_structure)
        for key in ("profit_ratio", "avg_cost", "concentration"):
            if key in cs:
                cs[key] = _sanitize_display_number(cs.get(key), default="N/A")
        if "chip_health" in cs:
            c_text = coerce_text(cs.get("chip_health"), default="", fallback_on_empty=True).strip()
            cs["chip_health"] = (
                localize_chip_health(c_text, report_language)
                if c_text
                else localize_chip_health("average", report_language)
            )
        cleaned["chip_structure"] = cs

    return cleaned


def _coerce_level_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = coerce_finite_float(value)
        return round(numeric, 2) if numeric is not None else None
    if not isinstance(value, str):
        return None
    text = value.replace(",", "").replace("，", "").strip()
    if not text or text.upper() == "N/A" or text in {"-", "—"}:
        return None
    try:
        numeric = float(text)
    except (OverflowError, ValueError):
        return text
    return round(numeric, 2) if math.isfinite(numeric) else None


def _pick_first_level(*values: Any) -> Any:
    for value in values:
        normalized = _coerce_level_value(value)
        if normalized is not None:
            return normalized
    return None


def _level_values_equal(left: Any, right: Any) -> bool:
    left_normalized = _coerce_level_value(left)
    right_normalized = _coerce_level_value(right)
    return (
        left_normalized is not None
        and right_normalized is not None
        and left_normalized == right_normalized
    )


def _first_non_empty_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _truncate_text(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _extract_latest_news_title(intelligence: Dict[str, Any]) -> str:
    key_news = intelligence.get("key_news")
    if isinstance(key_news, list):
        for item in key_news:
            if isinstance(item, dict):
                title = str(item.get("title", "")).strip()
                if title:
                    return title
    latest_news = intelligence.get("latest_news")
    if isinstance(latest_news, str) and latest_news.strip():
        return latest_news.strip()
    return ""
