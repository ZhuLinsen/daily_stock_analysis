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
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.tools.registry import ToolRegistry
from src.storage import persist_llm_usage as _persist_usage

logger = logging.getLogger(__name__)

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
    # Raw messages list at the end of the loop (callers may want to persist)
    messages: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def model(self) -> str:
        """Comma-separated de-duplicated model names used during the run."""
        return ", ".join(dict.fromkeys(m for m in self.models_used if m))


# ============================================================
# Helpers
# ============================================================

def serialize_tool_result(result: Any) -> str:
    """Serialize a tool result to a JSON string consumable by an LLM."""
    if result is None:
        return json.dumps({"result": None})
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)
    if hasattr(result, "__dict__"):
        try:
            d = {k: v for k, v in result.__dict__.items() if not k.startswith("_")}
            return json.dumps(d, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)
    return str(result)


def _normalize_tool_stock_code(value: Any) -> Any:
    """Canonicalize stock code arguments so equivalent HK variants share one cache key."""
    if not isinstance(value, str):
        return value

    text = value.strip().upper()
    if not text:
        return text

    if text.endswith(".HK"):
        base = text[:-3]
        if base.isdigit() and 1 <= len(base) <= 5:
            return f"HK{base.zfill(5)}"

    if text.startswith("HK"):
        base = text[2:]
        if base.isdigit() and 1 <= len(base) <= 5:
            return f"HK{base.zfill(5)}"

    if text.isdigit() and len(text) == 5:
        return f"HK{text}"

    try:
        from data_provider.base import canonical_stock_code, normalize_stock_code

        return canonical_stock_code(normalize_stock_code(text))
    except Exception:
        return text


def _build_tool_cache_key(tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Build a stable cache key for tool calls with normalized stock-code arguments."""
    if not isinstance(arguments, dict):
        return None

    normalized_args: Dict[str, Any] = {}
    for key, value in arguments.items():
        if key == "stock_code":
            normalized_args[key] = _normalize_tool_stock_code(value)
        else:
            normalized_args[key] = value

    try:
        payload = json.dumps(normalized_args, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return None
    return f"{tool_name}:{payload}"


def _is_non_retriable_tool_result(result: Any) -> bool:
    """Return True when a tool result explicitly tells the agent not to retry."""
    return (
        isinstance(result, dict)
        and bool(result.get("error"))
        and result.get("retriable") is False
    )


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
                return parsed
            parsed = _try_repair_json(block, repair_json)
            if parsed is not None:
                return parsed

    # Strategy 2: raw parse
    parsed = _try_parse_json(content)
    if parsed is not None:
        return parsed

    # Strategy 3: json_repair on full content
    parsed = _try_repair_json(content, repair_json)
    if parsed is not None:
        return parsed

    # Strategy 4: brace-delimited
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        candidate = content[brace_start : brace_end + 1]
        parsed = _try_parse_json(candidate)
        if parsed is not None:
            return parsed
        parsed = _try_repair_json(candidate, repair_json)
        if parsed is not None:
            return parsed

    logger.warning("Failed to parse dashboard JSON from agent response")
    return None


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
        tool_call_timeout_seconds: Optional timeout for one parallel tool batch.

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

    for step in range(max_steps):
        remaining_timeout = _remaining_timeout_seconds(start_time, max_wall_clock_seconds)
        if remaining_timeout is not None and remaining_timeout <= 0:
            logger.warning("Agent timed out before step %d", step + 1)
            return _build_timeout_result(
                start_time=start_time,
                max_wall_clock_seconds=float(max_wall_clock_seconds),
                step=step,
                tool_calls_log=tool_calls_log,
                total_tokens=total_tokens,
                provider_used=provider_used,
                models_used=models_used,
                messages=messages,
            )

        logger.info("Agent step %d/%d", step + 1, max_steps)

        # --- progress: thinking ---
        if progress_callback:
            if not tool_calls_log:
                thinking_msg = "正在制定分析路径..."
            else:
                last_tool = tool_calls_log[-1].get("tool", "")
                label = labels.get(last_tool, last_tool)
                thinking_msg = f"「{label}」已完成，继续深入分析..."
            progress_callback({"type": "thinking", "step": step + 1, "message": thinking_msg})

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
        if model_for_usage and model_for_usage != "error" and response.usage:
            _persist_usage(response.usage, model_for_usage, call_type="agent")

        remaining_timeout = _remaining_timeout_seconds(start_time, max_wall_clock_seconds)
        if remaining_timeout is not None and remaining_timeout <= 0:
            logger.warning("Agent timed out after LLM call at step %d", step + 1)
            return _build_timeout_result(
                start_time=start_time,
                max_wall_clock_seconds=float(max_wall_clock_seconds),
                step=step + 1,
                tool_calls_log=tool_calls_log,
                total_tokens=total_tokens,
                provider_used=provider_used,
                models_used=models_used,
                messages=messages,
            )

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
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        **({"thought_signature": tc.thought_signature} if tc.thought_signature is not None else {}),
                    }
                    for tc in response.tool_calls
                ],
            }
            if response.reasoning_content is not None:
                assistant_msg["reasoning_content"] = response.reasoning_content
            messages.append(assistant_msg)

            # Execute tools (parallel when > 1)
            effective_tool_timeout = tool_call_timeout_seconds
            if remaining_timeout is not None:
                effective_tool_timeout = min(
                    remaining_timeout,
                    tool_call_timeout_seconds if tool_call_timeout_seconds and tool_call_timeout_seconds > 0 else remaining_timeout,
                )
            tool_results = _execute_tools(
                response.tool_calls,
                tool_registry,
                step + 1,
                progress_callback,
                tool_calls_log,
                non_retriable_tool_results,
                tool_wait_timeout_seconds=effective_tool_timeout,
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
                return _build_timeout_result(
                    start_time=start_time,
                    max_wall_clock_seconds=float(max_wall_clock_seconds),
                    step=step + 1,
                    tool_calls_log=tool_calls_log,
                    total_tokens=total_tokens,
                    provider_used=provider_used,
                    models_used=models_used,
                    messages=messages,
                )

        else:
            # ---- final answer branch ----
            logger.info(
                "Agent completed in %d steps (%.1fs, %d tokens)",
                step + 1,
                time.time() - start_time,
                total_tokens,
            )
            if progress_callback:
                progress_callback({"type": "generating", "step": step + 1, "message": "正在生成最终分析..."})

            final_content = response.content or ""
            is_error = response.provider == "error"

            return RunLoopResult(
                success=not is_error and bool(final_content),
                content=final_content if not is_error else "",
                tool_calls_log=tool_calls_log,
                total_steps=step + 1,
                total_tokens=total_tokens,
                provider=provider_used,
                models_used=models_used,
                error=final_content if is_error else None,
                messages=messages,
            )

    # Max steps exceeded
    logger.warning("Agent hit max steps (%d)", max_steps)
    return RunLoopResult(
        success=False,
        content="",
        tool_calls_log=tool_calls_log,
        total_steps=max_steps,
        total_tokens=total_tokens,
        provider=provider_used,
        models_used=models_used,
        error=f"Agent exceeded max steps ({max_steps})",
        messages=messages,
    )


# ============================================================
# Internal tool execution
# ============================================================

def _execute_tools(
    tool_calls,
    tool_registry: ToolRegistry,
    step: int,
    progress_callback: Optional[Callable],
    tool_calls_log: List[Dict[str, Any]],
    non_retriable_tool_results: Optional[Dict[str, str]] = None,
    tool_wait_timeout_seconds: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Execute one or more tool calls, returning ordered result dicts.

    Single tools run inline; multiple tools run in parallel threads.
    """

    def _exec_single(tc_item):
        t0 = time.time()
        cache_key = _build_tool_cache_key(tc_item.name, tc_item.arguments)

        if cache_key and non_retriable_tool_results is not None and cache_key in non_retriable_tool_results:
            dur = round(time.time() - t0, 2)
            logger.info(
                "Tool '%s' skipped via non-retriable cache for arguments=%s",
                tc_item.name,
                tc_item.arguments,
            )
            return tc_item, non_retriable_tool_results[cache_key], False, dur, True

        try:
            res = tool_registry.execute(tc_item.name, **tc_item.arguments)
            res_str = serialize_tool_result(res)
            ok = True
            if cache_key and non_retriable_tool_results is not None and _is_non_retriable_tool_result(res):
                non_retriable_tool_results[cache_key] = res_str
        except Exception as e:
            res_str = json.dumps({"error": str(e)})
            ok = False
            logger.warning("Tool '%s' failed: %s", tc_item.name, e)
        dur = round(time.time() - t0, 2)
        return tc_item, res_str, ok, dur, False

    results: List[Dict[str, Any]] = []

    if len(tool_calls) == 1:
        tc = tool_calls[0]
        if progress_callback:
            progress_callback({"type": "tool_start", "step": step, "tool": tc.name})
        timeout_triggered = False
        if tool_wait_timeout_seconds and tool_wait_timeout_seconds > 0:
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                future = pool.submit(_exec_single, tc)
                try:
                    _, result_str, success, dur, cached = future.result(timeout=tool_wait_timeout_seconds)
                except FuturesTimeoutError:
                    timeout_triggered = True
                    future.cancel()
                    timeout_label = f"{tool_wait_timeout_seconds:.2f}s"
                    logger.warning("Tool '%s' timed out after %s at step %d", tc.name, timeout_label, step)
                    result_str = json.dumps({
                        "error": f"Tool execution timed out after {timeout_label}",
                        "timeout": True,
                    })
                    success = False
                    dur = round(tool_wait_timeout_seconds, 2)
                    cached = False
            finally:
                pool.shutdown(wait=not timeout_triggered, cancel_futures=timeout_triggered)
        else:
            _, result_str, success, dur, cached = _exec_single(tc)
        if progress_callback:
            progress_callback({"type": "tool_done", "step": step, "tool": tc.name, "success": success, "duration": dur})
        log_entry = {
            "step": step, "tool": tc.name, "arguments": tc.arguments,
            "success": success, "duration": dur, "result_length": len(result_str),
            "cached": cached,
        }
        if tool_wait_timeout_seconds and tool_wait_timeout_seconds > 0 and not success:
            try:
                if json.loads(result_str).get("timeout") is True:
                    log_entry["timeout"] = True
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        tool_calls_log.append(log_entry)
        results.append({"tc": tc, "result_str": result_str})
    else:
        for tc in tool_calls:
            if progress_callback:
                progress_callback({"type": "tool_start", "step": step, "tool": tc.name})

        pool = ThreadPoolExecutor(max_workers=min(len(tool_calls), 5))
        timeout_triggered = False
        try:
            futures = {pool.submit(_exec_single, tc): tc for tc in tool_calls}
            pending = set(futures)
            for future in as_completed(
                futures,
                timeout=tool_wait_timeout_seconds if tool_wait_timeout_seconds and tool_wait_timeout_seconds > 0 else None,
            ):
                pending.discard(future)
                tc_item, result_str, success, dur, cached = future.result()
                if progress_callback:
                    progress_callback({"type": "tool_done", "step": step, "tool": tc_item.name, "success": success, "duration": dur})
                tool_calls_log.append({
                    "step": step, "tool": tc_item.name, "arguments": tc_item.arguments,
                    "success": success, "duration": dur, "result_length": len(result_str),
                    "cached": cached,
                })
                results.append({"tc": tc_item, "result_str": result_str})
        except FuturesTimeoutError:
            timeout_triggered = True
            timeout_label = (
                f"{tool_wait_timeout_seconds:.2f}s"
                if tool_wait_timeout_seconds is not None
                else "the configured limit"
            )
            logger.warning("Tool batch timed out after %s at step %d", timeout_label, step)
            for future, tc_item in futures.items():
                if future in pending:
                    future.cancel()
                    result_str = json.dumps({
                        "error": f"Tool execution timed out after {timeout_label}",
                        "timeout": True,
                    })
                    if progress_callback:
                        progress_callback({
                            "type": "tool_done",
                            "step": step,
                            "tool": tc_item.name,
                            "success": False,
                            "duration": round(tool_wait_timeout_seconds or 0.0, 2),
                        })
                    tool_calls_log.append({
                        "step": step,
                        "tool": tc_item.name,
                        "arguments": tc_item.arguments,
                        "success": False,
                        "duration": round(tool_wait_timeout_seconds or 0.0, 2),
                        "result_length": len(result_str),
                        "cached": False,
                        "timeout": True,
                    })
                    results.append({"tc": tc_item, "result_str": result_str})
        finally:
            pool.shutdown(wait=not timeout_triggered, cancel_futures=timeout_triggered)

    return results
