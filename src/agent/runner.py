# -*- coding: utf-8 -*-
"""
Shared runner — extracted LLM + tool execution loop.

Provides ``run_agent_loop``, the single authoritative implementation of the
ReAct execute-loop that was previously inlined inside ``AgentExecutor._run_loop``.
All current and future agents should delegate to this runner instead of
re-implementing the loop themselves.

Design goals:
- Keep the same observable behaviour as the original ``_run_loop``
- Accept pluggable callbacks for progress, message history, and result handling
- Remain stateless — all mutable state lives in the caller
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
import threading
import contextvars
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.dashboard_payload import sanitize_agent_dashboard_payload
from src.agent.protocols import StageFailureReason
from src.agent.stream_events import stream_event
from src.agent.tools.registry import ToolRegistry
from src.agent.tools.execution import (
    TOOL_CANCEL_EVENT,
    _build_tool_cache_key,
    _guard_tool_stock_scope,
    _is_non_retriable_tool_result,
    _is_stock_scoped_tool,
    _normalize_guard_stock_code,
    _normalize_tool_stock_code,
    execute_runner_tool_call,
    serialize_tool_result,
)
from src.agent.stock_scope import StockScope
from src.llm.usage import should_persist_usage_telemetry
from src.utils.data_processing import normalize_report_signal_attribution
from src.storage import persist_llm_usage as _persist_usage

logger = logging.getLogger(__name__)

__all__ = [
    "RunLoopResult",
    "parse_dashboard_json",
    "run_agent_loop",
    "serialize_tool_result",
    "try_parse_json",
    "_build_tool_cache_key",
    "_guard_tool_stock_scope",
    "_is_non_retriable_tool_result",
    "_is_stock_scoped_tool",
    "_normalize_guard_stock_code",
    "_normalize_tool_stock_code",
]

# Tool name → friendly label for progress messages
_THINKING_TOOL_LABELS: Dict[str, str] = {
    "get_realtime_quote": "行情获取",
    "get_daily_history": "K线数据获取",
    "analyze_trend": "技术指标分析",
    "get_chip_distribution": "筹码分布分析",
    "search_stock_news": "新闻搜索",
    "search_comprehensive_intel": "综合情报搜索",
    "get_market_indices": "市场概览获取",
    "get_sector_rankings": "行业板块分析",
    "get_analysis_context": "历史分析上下文",
    "get_stock_info": "基本信息获取",
    "analyze_pattern": "K线形态识别",
    "get_volume_analysis": "量能分析",
    "calculate_ma": "均线计算",
    "get_skill_backtest_summary": "技能回测概览",
    "get_strategy_backtest_summary": "策略回测概览",
    "get_stock_backtest_summary": "个股回测数据",
}


# ============================================================
# RunLoopResult — the output of one run_agent_loop invocation
# ============================================================

@dataclass
class RunLoopResult:
    """Output produced by :func:`run_agent_loop`."""

    success: bool = False
    content: str = ""
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    provider: str = ""
    models_used: List[str] = field(default_factory=list)
    error: Optional[str] = None
    failure_reason: Optional[StageFailureReason] = None
    # Raw messages list at the end of the loop (callers may want to persist)
    messages: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def model(self) -> str:
        """Comma-separated de-duplicated model names used during the run."""
        return ", ".join(dict.fromkeys(m for m in self.models_used if m))


# ============================================================
# Helpers
# ============================================================

def parse_dashboard_json(content: str) -> Optional[Dict[str, Any]]:
    """Extract and parse a Decision Dashboard JSON from agent text.

    Tries multiple strategies:
    1. Markdown code blocks (```json ... ```)
    2. Raw JSON parse
    3. ``json_repair`` library
    4. Brace-delimited substring
    """
    if not content:
        return None

    from json_repair import repair_json

    # Strategy 1: markdown code blocks
    json_blocks = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if json_blocks:
        for block in json_blocks:
            parsed = _try_parse_json(block)
            if parsed is not None:
                return _finalize_dashboard_payload(parsed)
            parsed = _try_repair_json(block, repair_json)
            if parsed is not None:
                return _finalize_dashboard_payload(parsed)

    # Strategy 2: raw parse
    parsed = _try_parse_json(content)
    if parsed is not None:
        return _finalize_dashboard_payload(parsed)

    # Strategy 3: json_repair on full content
    parsed = _try_repair_json(content, repair_json)
    if parsed is not None:
        return _finalize_dashboard_payload(parsed)

    # Strategy 4: brace-delimited
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        candidate = content[brace_start : brace_end + 1]
        parsed = _try_parse_json(candidate)
        if parsed is not None:
            return _finalize_dashboard_payload(parsed)
        parsed = _try_repair_json(candidate, repair_json)
        if parsed is not None:
            return _finalize_dashboard_payload(parsed)

    logger.warning("Failed to parse dashboard JSON from agent response")
    return None


def _finalize_dashboard_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize reserved fields before running normal dashboard normalization."""
    sanitized = sanitize_agent_dashboard_payload(payload)
    normalize_report_signal_attribution(sanitized)
    return sanitized


def try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON dict extraction from LLM text.

    Handles:
    1. Direct JSON parse
    2. Markdown code fences (```json ... ```)
    3. Brace-delimited substring
    4. ``json_repair`` fallback for slightly malformed JSON

    This is the shared utility that all agent ``post_process`` methods
    should use instead of duplicating the same logic.
    """
    if not text:
        return None

    candidates: List[str] = []
    cleaned = text.strip()
    if cleaned:
        candidates.append(cleaned)

    if cleaned.startswith("```"):
        unfenced = re.sub(r'^```(?:json)?\s*', '', cleaned)
        unfenced = re.sub(r'\s*```$', '', unfenced)
        if unfenced:
            candidates.append(unfenced.strip())

    fenced_blocks = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    for block in fenced_blocks:
        block = block.strip()
        if block:
            candidates.append(block)

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start:end + 1].strip()
        if snippet:
            candidates.append(snippet)

    seen: set[str] = set()
    unique_candidates: List[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)

    for candidate in unique_candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue

    try:
        from json_repair import repair_json
    except Exception:
        repair_json = None

    if repair_json is not None:
        for candidate in unique_candidates:
            repaired = _try_repair_json(candidate, repair_json)
            if repaired is not None:
                return repaired

    return None


# Keep private alias used internally by parse_dashboard_json
_try_parse_json = try_parse_json


def _try_repair_json(text: str, repair_fn: Callable) -> Optional[Dict[str, Any]]:
    try:
        repaired = repair_fn(text)
        obj = json.loads(repaired)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _remaining_timeout_seconds(
    start_time: float,
    max_wall_clock_seconds: Optional[float],
) -> Optional[float]:
    """Return remaining wall-clock budget in seconds, or None when disabled."""
    if max_wall_clock_seconds is None or max_wall_clock_seconds <= 0:
        return None
    return max(0.0, float(max_wall_clock_seconds) - (time.time() - start_time))


def _build_timeout_result(
    *,
    start_time: float,
    max_wall_clock_seconds: float,
    step: int,
    tool_calls_log: List[Dict[str, Any]],
    total_tokens: int,
    provider_used: str,
    models_used: List[str],
    messages: List[Dict[str, Any]],
) -> RunLoopResult:
    elapsed = time.time() - start_time
    return RunLoopResult(
        success=False,
        content="",
        tool_calls_log=tool_calls_log,
        total_steps=step,
        total_tokens=total_tokens,
        provider=provider_used,
        models_used=models_used,
        error=f"Agent timed out after {elapsed:.2f}s (limit: {max_wall_clock_seconds:.2f}s)",
        failure_reason=StageFailureReason.TIMEOUT,
        messages=messages,
    )


def _build_budget_guard_result(
    *,
    start_time: float,
    step: int,
    tool_calls_log: List[Dict[str, Any]],
    total_tokens: int,
    provider_used: str,
    models_used: List[str],
    messages: List[Dict[str, Any]],
    remaining_timeout_s: float,
    min_step_budget_s: float,
) -> RunLoopResult:
    elapsed = time.time() - start_time
    return RunLoopResult(
        success=False,
        content="",
        tool_calls_log=tool_calls_log,
        total_steps=step,
        total_tokens=total_tokens,
        provider=provider_used,
        models_used=models_used,
        error=(
            "Agent step skipped due to insufficient budget: "
            f"{remaining_timeout_s:.2f}s remaining, minimum {min_step_budget_s:.1f}s required"
        ),
        failure_reason=StageFailureReason.BUDGET_SKIP,
        messages=messages,
    )


# ============================================================
# Core loop
# ============================================================

def run_agent_loop(
    *,
    messages: List[Dict[str, Any]],
    tool_registry: ToolRegistry,
    llm_adapter: LLMToolAdapter,
    max_steps: int = 10,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    thinking_labels: Optional[Dict[str, str]] = None,
    max_wall_clock_seconds: Optional[float] = None,
    tool_call_timeout_seconds: Optional[float] = None,
    stock_scope: Optional[StockScope] = None,
    emit_stage_events: bool = True,
) -> RunLoopResult:
    """Execute the ReAct LLM ↔ tool loop.

    This is the *single shared implementation* of the agent execution loop.
    Both the legacy ``AgentExecutor`` and any future multi-agent runner
    should delegate here.

    Args:
        messages: The initial message list (system + user + optional history).
                  **Mutated in-place** — tool results are appended.
        tool_registry: Registry of callable tools.
        llm_adapter: LLM backend (handles multi-provider fallback).
        max_steps: Maximum number of LLM round-trips.
        progress_callback: Optional callback receiving progress dicts.
        thinking_labels: Override map of tool_name → friendly label.
        max_wall_clock_seconds: Optional overall timeout budget for the loop.
        tool_call_timeout_seconds: Optional explicit per-run tool-call timeout.
                  Highest-priority (first-wins) in the per-tool timeout chain —
                  overrides per-tool declarations and category defaults — but is
                  capped by ``max_wall_clock_seconds`` when both are set.
        emit_stage_events: Whether to emit the synthetic ``agent_loop``
            stage lifecycle. Orchestrated business stages disable this so
            ``stage_start`` / ``stage_done`` only describe real stages.

    Returns:
        A :class:`RunLoopResult` with the final content, stats, and the
        (mutated) messages list.
    """
    labels = thinking_labels or _THINKING_TOOL_LABELS
    tool_decls = tool_registry.to_openai_tools()

    start_time = time.time()
    tool_calls_log: List[Dict[str, Any]] = []
    non_retriable_tool_results: Dict[str, str] = {}
    total_tokens = 0
    provider_used = ""
    models_used: List[str] = []

    # Minimum seconds needed for a meaningful LLM round-trip.  If the
    # remaining budget is positive but below this threshold, the step will
    # almost certainly timeout mid-call, wasting a billed request.  Only
    # enforced from step 2 onwards so the first step always gets a chance
    # even when the total budget is small.
    _MIN_STEP_BUDGET_S = 8.0

    def _finish(result: RunLoopResult) -> RunLoopResult:
        if progress_callback and emit_stage_events:
            progress_callback(
                stream_event(
                    "stage_done",
                    stage="agent_loop",
                    status="completed" if result.success else "failed",
                    duration=round(time.time() - start_time, 2),
                )
            )
        return result

    if progress_callback and emit_stage_events:
        progress_callback(
            stream_event(
                "stage_start",
                stage="agent_loop",
                message="Starting agent analysis...",
            )
        )

    for step in range(max_steps):
        remaining_timeout = _remaining_timeout_seconds(start_time, max_wall_clock_seconds)
        timeout_exhausted = remaining_timeout is not None and remaining_timeout <= 0
        budget_guard_triggered = (
            not timeout_exhausted
            and remaining_timeout is not None
            and step > 0
            and remaining_timeout <= _MIN_STEP_BUDGET_S
        )
        if timeout_exhausted or budget_guard_triggered:
            if budget_guard_triggered:
                logger.warning(
                    "Agent budget too low for step %d (%.1fs remaining, min %.1fs)",
                    step + 1,
                    remaining_timeout,
                    _MIN_STEP_BUDGET_S,
                )
                return _finish(_build_budget_guard_result(
                    start_time=start_time,
                    step=step,
                    tool_calls_log=tool_calls_log,
                    total_tokens=total_tokens,
                    provider_used=provider_used,
                    models_used=models_used,
                    messages=messages,
                    remaining_timeout_s=remaining_timeout,
                    min_step_budget_s=_MIN_STEP_BUDGET_S,
                ))

            if remaining_timeout <= 0:
                logger.warning("Agent timed out before step %d", step + 1)
            return _finish(_build_timeout_result(
                start_time=start_time,
                max_wall_clock_seconds=float(max_wall_clock_seconds),
                step=step,
                tool_calls_log=tool_calls_log,
                total_tokens=total_tokens,
                provider_used=provider_used,
                models_used=models_used,
                messages=messages,
            ))

        logger.info("Agent step %d/%d", step + 1, max_steps)

        # --- progress: thinking ---
        if progress_callback:
            if not tool_calls_log:
                thinking_msg = "正在制定分析路径..."
            else:
                last_tool = tool_calls_log[-1].get("tool", "")
                label = labels.get(last_tool, last_tool)
                thinking_msg = f"「{label}」已完成，继续深入分析..."
            progress_callback(stream_event("thinking", step=step + 1, message=thinking_msg))

        # --- LLM call ---
        response = llm_adapter.call_with_tools(
            messages,
            tool_decls,
            timeout=remaining_timeout,
        )
        provider_used = response.provider
        total_tokens += (response.usage or {}).get("total_tokens", 0)
        m = getattr(response, "model", "") or response.provider
        if m and m != "error":
            models_used.append(m)
        model_for_usage = m or response.provider
        if model_for_usage and model_for_usage != "error" and should_persist_usage_telemetry(response.usage):
            _persist_usage(response.usage, model_for_usage, call_type="agent")

        remaining_timeout = _remaining_timeout_seconds(start_time, max_wall_clock_seconds)
        if remaining_timeout is not None and remaining_timeout <= 0:
            logger.warning("Agent timed out after LLM call at step %d", step + 1)
            return _finish(_build_timeout_result(
                start_time=start_time,
                max_wall_clock_seconds=float(max_wall_clock_seconds),
                step=step + 1,
                tool_calls_log=tool_calls_log,
                total_tokens=total_tokens,
                provider_used=provider_used,
                models_used=models_used,
                messages=messages,
            ))

        if response.tool_calls:
            # ---- tool execution branch ----
            logger.info(
                "Agent requesting %d tool call(s): %s",
                len(response.tool_calls),
                [tc.name for tc in response.tool_calls],
            )

            # Append assistant message (with tool_calls) to history
            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "_trace_provider": response.provider,
                "_trace_model": m,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        **({"provider_specific_fields": tc.provider_specific_fields} if tc.provider_specific_fields else {}),
                        **({"thought_signature": tc.thought_signature} if tc.thought_signature is not None else {}),
                    }
                    for tc in response.tool_calls
                ],
            }
            if response.reasoning_content is not None:
                assistant_msg["reasoning_content"] = response.reasoning_content
            if response.provider_blocks:
                assistant_msg["provider_blocks"] = response.provider_blocks
            messages.append(assistant_msg)

            # Execute tools (parallel when > 1).  ``tool_call_timeout_seconds`` is
            # the caller's explicit per-run override — highest priority in the
            # first-wins chain (Issue #1890 contract) — while ``remaining_timeout``
            # is the unbreakable outer wall-clock cap for this batch.
            tool_results = _execute_tools(
                response.tool_calls,
                tool_registry,
                step + 1,
                progress_callback,
                tool_calls_log,
                non_retriable_tool_results,
                tool_call_timeout_seconds=tool_call_timeout_seconds,
                tool_wait_timeout_seconds=remaining_timeout,
                stock_scope=stock_scope,
            )

            # Append tool results preserving original call order
            tc_order = {tc.id: i for i, tc in enumerate(response.tool_calls)}
            tool_results.sort(key=lambda x: tc_order.get(x["tc"].id, 0))
            for tr in tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "name": tr["tc"].name,
                        "tool_call_id": tr["tc"].id,
                        "content": tr["result_str"],
                    }
                )

            remaining_timeout = _remaining_timeout_seconds(start_time, max_wall_clock_seconds)
            if remaining_timeout is not None and remaining_timeout <= 0:
                logger.warning("Agent timed out after tool execution at step %d", step + 1)
                return _finish(_build_timeout_result(
                    start_time=start_time,
                    max_wall_clock_seconds=float(max_wall_clock_seconds),
                    step=step + 1,
                    tool_calls_log=tool_calls_log,
                    total_tokens=total_tokens,
                    provider_used=provider_used,
                    models_used=models_used,
                    messages=messages,
                ))

        else:
            # ---- final answer branch ----
            logger.info(
                "Agent completed in %d steps (%.1fs, %d tokens)",
                step + 1,
                time.time() - start_time,
                total_tokens,
            )
            if progress_callback:
                progress_callback(stream_event("generating", step=step + 1, message="正在生成最终分析..."))

            final_content = response.content or ""
            is_error = response.provider == "error"

            return _finish(RunLoopResult(
                success=not is_error and bool(final_content),
                content=final_content if not is_error else "",
                tool_calls_log=tool_calls_log,
                total_steps=step + 1,
                total_tokens=total_tokens,
                provider=provider_used,
                models_used=models_used,
                error=final_content if is_error else None,
                failure_reason=(StageFailureReason.STAGE_FAILURE if is_error else None),
                messages=messages,
            ))

    # Max steps exceeded
    logger.warning("Agent hit max steps (%d)", max_steps)
    return _finish(RunLoopResult(
        success=False,
        content="",
        tool_calls_log=tool_calls_log,
        total_steps=max_steps,
        total_tokens=total_tokens,
        provider=provider_used,
        models_used=models_used,
        error=f"Agent exceeded max steps ({max_steps}). Try increasing AGENT_MAX_STEPS if analysis tasks are complex.",
        failure_reason=StageFailureReason.STAGE_FAILURE,
        messages=messages,
    ))


# ============================================================
# Internal tool execution
# ============================================================

def _coerce_positive_timeout(value) -> Optional[float]:
    """Coerce a timeout candidate to a positive finite float, else ``None``.

    ``None`` / non-numeric / non-positive / ``inf`` / ``nan`` all map to
    ``None`` ("no limit at this level").  Rejecting non-finite values prevents
    an ``OverflowError`` from ``future.result(timeout=inf)`` and avoids the
    undefined ordering a ``nan`` would produce.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def _build_timeout_result_payload(
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_s: float,
    non_retriable_tool_results: Optional[Dict[str, str]],
) -> str:
    """Build the timeout-shaped result string and record it as non-retriable.

    A timed-out call is marked ``"retriable": False`` and inserted into
    ``non_retriable_tool_results`` so the LLM's retry of the *same* call reuses
    the cached failure instead of spinning up a second (possibly side-effecting)
    execution — a best-effort guard against duplicate work, since Python cannot
    forcibly cancel an already-started tool thread.
    """
    label = f"{timeout_s:.2f}s"
    result_str = json.dumps({
        "error": f"Tool execution timed out after {label}",
        "timeout": True,
        "retriable": False,
    })
    if non_retriable_tool_results is not None:
        cache_key = _build_tool_cache_key(tool_name, arguments)
        # Non-dict / missing ``arguments`` yields ``None`` here; skip the write so
        # unrelated no-arg tool calls cannot collide on a shared ``None`` key.
        if cache_key:
            non_retriable_tool_results[cache_key] = result_str
    return result_str


def _resolve_per_tool_timeout(
    tool_call,
    tool_registry: Optional[ToolRegistry],
    explicit_timeout: Optional[float] = None,
    wall_clock_budget: Optional[float] = None,
) -> Optional[float]:
    """Resolve the effective timeout for a single tool call (Issue #1890).

    Precedence is *first-wins*, exactly as confirmed in the issue contract:

        1. explicit per-run timeout (``tool_call_timeout_seconds``)
        2. per-tool declaration (``ToolDefinition.timeout_seconds``)
        3. category default (``AGENT_*_TOOL_TIMEOUT_S``)
        4. none (no per-tool limit)

    An earlier level is never lowered by a later one: an explicit
    ``tool_call_timeout_seconds`` can *relax* a stricter per-tool or category
    default (the previous ``min()`` across all levels made that impossible), and
    a per-tool declaration is never overridden by a smaller category default.

    ``wall_clock_budget`` (the remaining overall loop budget) is then applied as
    an *unbreakable outer cap*: the winner can never exceed it, so a long
    explicit timeout cannot blow past the caller's overall wall-clock budget.
    """
    explicit = _coerce_positive_timeout(explicit_timeout)
    budget = _coerce_positive_timeout(wall_clock_budget)

    if tool_registry is None:
        base = explicit
    else:
        tool_def = tool_registry.get(tool_call.name)
        if tool_def is None:
            base = explicit
        else:
            per_tool = _coerce_positive_timeout(getattr(tool_def, "timeout_seconds", None))
            category = _coerce_positive_timeout(
                tool_registry.category_default_timeout(tool_def.category)
            )
            # First-wins: explicit per-run > per-tool declaration > category default.
            base = (
                explicit
                if explicit is not None
                else (per_tool if per_tool is not None else category)
            )

    if base is None:
        # No explicit/per-tool/category limit; the wall-clock budget governs.
        return budget
    if budget is not None:
        return min(base, budget)
    return base


def _execute_tools(
    tool_calls,
    tool_registry: ToolRegistry,
    step: int,
    progress_callback: Optional[Callable],
    tool_calls_log: List[Dict[str, Any]],
    non_retriable_tool_results: Optional[Dict[str, str]] = None,
    tool_call_timeout_seconds: Optional[float] = None,
    tool_wait_timeout_seconds: Optional[float] = None,
    stock_scope: Optional[StockScope] = None,
) -> List[Dict[str, Any]]:
    """Execute one or more tool calls, returning ordered result dicts.

    A single tool with no resolved timeout runs inline (no thread); otherwise
    all tools share one executor whose per-tool timeouts are enforced by a
    deadline-driven wait loop — there are no per-tool nested pools, so a batch
    of N tools uses at most ``min(N, 5)`` threads (review: unify the single and
    parallel timeout wrapping).  ``tool_wait_timeout_seconds`` also caps the
    whole batch as an outer ceiling.

    ``tool_call_timeout_seconds`` is the caller's explicit per-run override
    (highest priority, first-wins) and ``tool_wait_timeout_seconds`` the
    remaining wall-clock budget (outer cap) — both feed
    :func:`_resolve_per_tool_timeout`.
    """

    def _exec_single(tc_item):
        return execute_runner_tool_call(
            tool_call=tc_item,
            tool_registry=tool_registry,
            stock_scope=stock_scope,
            non_retriable_tool_results=non_retriable_tool_results,
        )

    def _exec_with_deadline(tc_item, per_tool_timeout, deadline_holder):
        """Run one tool and record its per-tool deadline when the worker actually
        starts.  The batch pool is capped at ``min(N, 5)`` workers, so calls that
        queue behind a full pool must not burn their timeout before execution
        begins (review OR-COM-3d6b61f8) — otherwise a batch larger than five can
        falsely time out a tool that never got a worker.
        """
        if per_tool_timeout and per_tool_timeout > 0:
            deadline_holder[0] = time.monotonic() + per_tool_timeout
        return _exec_single(tc_item)

    def _record(tc_item, *, timed_out, timeout_s=None, out=None, guard_result=None):
        """Emit ``tool_done``, build the log entry, and append to ``results``."""
        if out is not None:
            _, result_str, success, dur, cached, guard_result = out
        else:
            result_str = _build_timeout_result_payload(
                tc_item.name, tc_item.arguments, timeout_s, non_retriable_tool_results,
            )
            success = False
            dur = round(timeout_s, 2)
            cached = False
        if progress_callback:
            progress_callback(stream_event(
                "tool_done", step=step, tool=tc_item.name, success=success, duration=dur,
            ))
        log_entry = {
            "step": step, "tool": tc_item.name, "arguments": tc_item.arguments,
            "success": success, "duration": dur, "result_length": len(result_str),
            "cached": cached,
        }
        if timed_out:
            log_entry["timeout"] = True
        if guard_result is not None:
            log_entry.update({
                "guarded": True,
                "expected_stock_code": guard_result.get("expected_stock_code"),
                "requested_stock_code": guard_result.get("requested_stock_code"),
                "allowed_stock_codes": guard_result.get("allowed_stock_codes", []),
            })
        tool_calls_log.append(log_entry)
        results.append({"tc": tc_item, "result_str": result_str})

    results: List[Dict[str, Any]] = []
    if not tool_calls:
        return results

    plan = []
    for tc in tool_calls:
        per_tool_timeout = _resolve_per_tool_timeout(
            tc, tool_registry, tool_call_timeout_seconds, tool_wait_timeout_seconds,
        )
        plan.append((tc, per_tool_timeout))
        if progress_callback:
            progress_callback(stream_event("tool_start", step=step, tool=tc.name))

    # Fast path: a single tool with no resolved timeout runs inline (no thread).
    if len(plan) == 1 and not (plan[0][1] and plan[0][1] > 0):
        _record(plan[0][0], timed_out=False, out=_exec_single(plan[0][0]))
        return results

    pool = ThreadPoolExecutor(max_workers=min(len(plan), 5))
    futures: Dict[Any, Any] = {}
    cancel_of: Dict[Any, threading.Event] = {}
    # ``deadline_of`` maps a Future to a single-element holder list; the worker
    # writes the deadline into it when it *starts* running (see
    # ``_exec_with_deadline``).  ``None`` until then means "still queued / no
    # per-tool timeout" and is never treated as expired.
    deadline_of: Dict[Any, List[Optional[float]]] = {}
    timeout_of: Dict[Any, float] = {}
    timeout_triggered = False
    try:
        # One executor for the whole batch.  Each future gets its own cancel
        # event (keyed by Future, not by tool name, so two parallel calls to the
        # same tool cannot shadow each other) and its own per-tool deadline.
        for tc, per_tool_timeout in plan:
            cancel_event = threading.Event()
            ctx = contextvars.copy_context()
            ctx.run(TOOL_CANCEL_EVENT.set, cancel_event)
            deadline_holder: List[Optional[float]] = [None]
            fut = pool.submit(
                ctx.run, _exec_with_deadline, tc, per_tool_timeout, deadline_holder,
            )
            futures[fut] = tc
            cancel_of[fut] = cancel_event
            timeout_of[fut] = per_tool_timeout or 0.0
            deadline_of[fut] = deadline_holder

        batch_deadline = (
            time.monotonic() + tool_wait_timeout_seconds
            if tool_wait_timeout_seconds and tool_wait_timeout_seconds > 0
            else None
        )
        pending = set(futures)

        while pending:
            now = time.monotonic()
            deadlines = []
            for f in pending:
                holder = deadline_of.get(f)
                if holder is not None and holder[0] is not None:
                    deadlines.append(holder[0])
            if batch_deadline is not None:
                deadlines.append(batch_deadline)
            next_deadline = min(deadlines) if deadlines else None
            if next_deadline is not None:
                wait_timeout = max(0.0, next_deadline - now)
            elif any(timeout_of.get(f, 0.0) > 0 for f in pending):
                # A pending call has a per-tool timeout but its worker has not
                # started yet (it is queued behind the capped pool).  Poll briefly
                # so a tool that starts and then hangs still gets its own timeout
                # (review OR-COM-3d6b61f8) instead of being forgotten.
                wait_timeout = 0.01
            else:
                # No deadline and no pending call has a timeout — nothing can time
                # out, so block until a call completes (efficient for the default
                # no-timeout path).
                wait_timeout = None
            done, _ = wait(pending, timeout=wait_timeout, return_when=FIRST_COMPLETED)
            for fut in done:
                pending.discard(fut)
                _record(futures[fut], timed_out=False, out=fut.result())

            now = time.monotonic()
            for fut in list(pending):
                holder = deadline_of.get(fut)
                deadline = holder[0] if holder is not None else None
                expired = (deadline is not None and now >= deadline) or (
                    batch_deadline is not None and now >= batch_deadline
                )
                if not expired:
                    continue
                pending.discard(fut)
                cancel_of[fut].set()
                timeout_triggered = True
                timeout_s = timeout_of.get(fut) or (tool_wait_timeout_seconds or 0.0)
                logger.warning(
                    "Tool '%s' timed out after %.2fs at step %d",
                    futures[fut].name, timeout_s, step,
                )
                _record(futures[fut], timed_out=True, timeout_s=timeout_s)
    finally:
        # Do not wait when a timeout fired — the timed-out handler may still be
        # running in a worker and would otherwise block this call indefinitely.
        pool.shutdown(wait=not timeout_triggered, cancel_futures=True)

    return results
