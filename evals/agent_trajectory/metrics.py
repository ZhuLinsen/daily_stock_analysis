# -*- coding: utf-8 -*-
"""Pure-function trajectory metrics for agent evaluation (Issue #1956).

This module computes quality metrics for an agent execution trajectory from its
``tool_calls_log`` (see ``src/agent/runner.py`` for the producer contract):

* each entry carries ``step / tool / arguments / success / duration /
  result_length / cached`` and optionally ``timeout`` or ``guarded`` fields;
* entries with missing optional fields are tolerated with defaults (e.g. the
  Codex App Server backend emits ``arguments_summary`` instead of
  ``arguments``).

All functions in this module are pure: they consume plain data (a log list and
a ``GoldenSample``) and never touch the filesystem, network, or LLM.  This keeps
the metrics layer deterministic, unit-testable without an API key, and free of
``src/`` imports — it can score trajectories from any source.

Idempotency key contract
------------------------
Two log entries are considered "the same call" when their ``tool`` names are
equal and their serialized ``arguments`` are equal.  Arguments may contain
unhashable values (dict / list), so the key is built with
``json.dumps(arguments, sort_keys=True, default=str)`` — a *stable string*,
not a hash.  Do not replace this with ``tuple(arguments)`` or ``repr()``:
insertion order or collection type would then change call identity and corrupt
redundancy / retry counts.

Metric semantics
----------------
* ``redundant_calls``: every occurrence of a (tool, args-key) pair beyond its
  first — regardless of success.
* ``retries``: occurrences that follow a *failed* occurrence of the same pair
  (i.e. "tried again after a failure").  ``retries`` is a subset of
  ``redundant_calls``; repeats after success count as redundant but not retry,
  and a success clears the pair's failure state — so ``fail -> success ->
  success`` counts exactly one retry, not two.
* ``cached_calls``: entries with ``cached=True`` (runner semantics: reuse of a
  non-retriable failure result).
* ``max_steps_touched``: the log does not carry ``max_steps`` itself, so this
  is the conservative heuristic ``max(step) >= golden.allowed_max_steps`` —
  a proxy for "the run reached the step budget", not proof of the loop
  exhausting it.  When ``total_steps`` is supplied (see
  :func:`compute_trajectory_metrics`), the larger of ``total_steps`` and the
  log-derived step is compared instead — the final answer round consumes a
  step but produces no tool call, so the log alone understates consumption.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class GoldenSample:
    """Expected trajectory for one evaluation task.

    ``expected_tools`` are the tool names the agent should call; tools outside
    this set are tolerated only when ``allow_optional_tools`` is true.
    """

    id: str
    task_description: str
    stock_code: str
    expected_tools: List[str]
    skills: List[str] = field(default_factory=list)
    allowed_max_steps: int = 10
    allow_optional_tools: bool = True


@dataclass
class TrajectoryMetrics:
    """All metrics computed for one trajectory against one golden sample."""

    expected_hit_rate: float
    expected_total: int
    missing_expected: List[str]
    optional_tools_used: List[str]
    redundant_calls: int
    cached_calls: int
    failed_calls: int
    retries: int
    distinct_steps: int
    max_steps_touched: bool
    violations: List[str]


def _args_key(arguments: Any) -> str:
    """Return a stable idempotency key for tool-call arguments (see module docstring)."""
    if arguments is None:
        arguments = {}
    return json.dumps(arguments, sort_keys=True, default=str)


def _entry_arguments(entry: Dict[str, Any]) -> Any:
    """Extract the idempotent argument payload from a log entry.

    Runner entries carry ``arguments`` (a dict); Codex App Server entries carry
    ``arguments_summary`` (a string) instead.  Falling back to ``{}`` for
    non-dict ``arguments`` would merge every summary-only entry into one key,
    so the summary is wrapped to keep call identity distinct.
    """
    arguments = entry.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    summary = entry.get("arguments_summary")
    if summary:
        return {"arguments_summary": summary}
    return arguments


def _coerce_step(value: Any) -> int:
    """Coerce a log entry's ``step`` to a non-negative int (missing/odd -> 0)."""
    try:
        step = int(value)
    except (TypeError, ValueError):
        return 0
    return step if step > 0 else 0


def compute_trajectory_metrics(
    log: List[Dict[str, Any]],
    golden: GoldenSample,
    total_steps: Optional[int] = None,
) -> TrajectoryMetrics:
    """Compute all trajectory metrics from a ``tool_calls_log`` and a golden sample.

    ``total_steps`` optionally carries the number of loop rounds the run
    actually consumed (``RunLoopResult.total_steps``), which includes the
    final plain-answer round that produces no tool call.  When it is larger
    than the log-derived step count it is used for ``distinct_steps`` and the
    ``max_steps_touched`` heuristic; otherwise the log alone decides, and the
    default ``None`` keeps the log-only behaviour.
    """
    used_tools: List[str] = []
    key_counts: Dict[tuple, int] = {}
    key_failed_seen: Dict[tuple, bool] = {}
    key_retries: Dict[tuple, int] = {}
    failed_calls = 0
    cached_calls = 0
    redundant_calls = 0
    distinct_steps = 0
    max_step = 0
    seen_steps: set = set()

    for entry in log:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool") or ""
        if tool and tool not in used_tools:
            used_tools.append(tool)
        step = _coerce_step(entry.get("step"))
        if step and step not in seen_steps:
            seen_steps.add(step)
            distinct_steps += 1
            max_step = max(max_step, step)
        success = bool(entry.get("success", True))
        if not success:
            failed_calls += 1
        if entry.get("cached"):
            cached_calls += 1

        key = (tool, _args_key(_entry_arguments(entry)))
        if key_counts.get(key, 0):
            redundant_calls += 1
        key_counts[key] = key_counts.get(key, 0) + 1
        # An occurrence is a retry only when the same call already failed
        # before it (see module docstring for the precise contract).
        if key_failed_seen.get(key):
            key_retries[key] = key_retries.get(key, 0) + 1
        # A success clears the failure state: repeats after a recovery count
        # as redundant only, not as further retries.
        key_failed_seen[key] = not success

    # The final answer round consumes a step but produces no tool call, so
    # when the caller supplies the run's real total it may exceed the log.
    total = 0
    if total_steps is not None:
        try:
            total = int(total_steps)
        except (TypeError, ValueError):
            total = 0
        total = total if total > 0 else 0
    distinct_steps = max(distinct_steps, total)
    max_step = max(max_step, total)

    if isinstance(golden.expected_tools, list):
        expected = [t for t in golden.expected_tools if isinstance(t, str) and t]
    else:
        # Defend against hand-edited samples passing a bare string:
        # validation rejects it at load time, but scoring must not misparse
        # it into per-character tool names either.
        expected = []
    missing_expected = [t for t in expected if t not in used_tools]
    expected_hit_rate = (len(expected) - len(missing_expected)) / len(expected) if expected else 0.0
    optional_tools_used = [t for t in used_tools if t not in expected]

    violations: List[str] = []
    if not expected:
        violations.append("golden sample has no expected_tools")

    # Malformed golden samples must not crash scoring nor flip semantics:
    # a truthy string like "false" must not silently turn a strict sample
    # permissive, and a non-integer step limit must not crash the comparison.
    optional_allowed = golden.allow_optional_tools
    if not isinstance(optional_allowed, bool):
        violations.append("allow_optional_tools is not a boolean")
        optional_allowed = False
    if optional_tools_used and not optional_allowed:
        violations.append(f"optional tools used but not allowed: {', '.join(optional_tools_used)}")

    limit = golden.allowed_max_steps
    if isinstance(limit, bool) or not isinstance(limit, int):
        violations.append("allowed_max_steps is not an integer")
        limit = 0
    max_steps_touched = bool(max_step and limit > 0 and max_step >= limit)
    if max_steps_touched:
        violations.append(f"trajectory reached allowed_max_steps ({golden.allowed_max_steps})")

    return TrajectoryMetrics(
        expected_hit_rate=expected_hit_rate,
        expected_total=len(expected),
        missing_expected=missing_expected,
        optional_tools_used=optional_tools_used,
        redundant_calls=redundant_calls,
        cached_calls=cached_calls,
        failed_calls=failed_calls,
        retries=sum(key_retries.values()),
        distinct_steps=distinct_steps,
        max_steps_touched=max_steps_touched,
        violations=violations,
    )


def format_text_report(m: TrajectoryMetrics) -> str:
    """Render metrics as a deterministic, human-readable text report."""
    hit_count = max(0, m.expected_total - len(m.missing_expected))
    hit_percent = f"{m.expected_hit_rate * 100:.1f}%"
    missing = ", ".join(m.missing_expected) if m.missing_expected else "无"
    optional = ", ".join(m.optional_tools_used) if m.optional_tools_used else "无"
    violations = "; ".join(m.violations) if m.violations else "无"
    max_steps_label = "是" if m.max_steps_touched else "否"
    return (
        "============================================\n"
        "Agent Trajectory 评估报告\n"
        "============================================\n"
        f"- 期望工具命中: {hit_count}/{m.expected_total} ({hit_percent})\n"
        f"- 缺失期望工具: {missing}\n"
        f"- 期望外工具: {optional}\n"
        f"- 冗余调用: {m.redundant_calls} | 缓存调用: {m.cached_calls} | "
        f"失败调用: {m.failed_calls} | 重试: {m.retries}\n"
        f"- 消耗步数: {m.distinct_steps} (触碰 max_steps: {max_steps_label})\n"
        f"- 违规项: {violations}\n"
    )


def load_golden_samples(
    path: Optional[str] = None,
    known_tool_names: Optional[Iterable[str]] = None,
) -> List[GoldenSample]:
    """Load golden samples from ``path`` (default: ``golden_samples.json`` next to this module).

    Raises ``FileNotFoundError`` when the file is missing and ``ValueError`` on
    malformed JSON or structural issues (see :func:`validate_golden_sample`).
    Unknown extra JSON keys are ignored so the file can carry forward-looking
    metadata without breaking the loader.
    """
    if path is None:
        path = str(Path(__file__).with_name("golden_samples.json"))
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"golden samples file must contain a JSON list, got {type(data).__name__}")

    golden_fields = {f.name for f in fields(GoldenSample)}
    samples: List[GoldenSample] = []
    seen_ids: set = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"sample #{index} must be a JSON object, got {type(item).__name__}")
        try:
            sample = GoldenSample(**{k: v for k, v in item.items() if k in golden_fields})
        except TypeError as exc:
            raise ValueError(f"sample #{index} has invalid fields: {exc}") from exc
        if sample.id in seen_ids:
            raise ValueError(f"duplicate sample id: {sample.id}")
        seen_ids.add(sample.id)
        issues = validate_golden_sample(sample, known_tool_names)
        if issues:
            raise ValueError(f"sample '{sample.id}': " + "; ".join(issues))
        samples.append(sample)
    return samples


def validate_golden_sample(
    sample: GoldenSample,
    known_tool_names: Optional[Iterable[str]] = None,
) -> List[str]:
    """Return a list of structural issues for ``sample``; empty list means valid.

    When ``known_tool_names`` is provided, ``expected_tools`` must be a subset
    of it; the caller supplies the authoritative registry names (this module
    deliberately does not import ``src/``).  Any ``Iterable[str]`` is accepted
    — including one-shot generators — and materialized once internally, so
    membership checks never consume the caller's iterable.

    Field *types* are part of the structural contract — hand-edited golden
    JSON must fail with a clear message instead of crashing or silently
    passing: text fields must be strings, ``expected_tools``/``skills`` must
    be lists, ``allowed_max_steps`` an integer and ``allow_optional_tools`` a
    boolean.
    """
    issues: List[str] = []
    known = set(known_tool_names) if known_tool_names is not None else None
    if not isinstance(sample.id, str) or not sample.id.strip():
        issues.append("id must be a non-empty string")
    if not isinstance(sample.task_description, str) or not sample.task_description.strip():
        issues.append("task_description must be a non-empty string")
    if not isinstance(sample.stock_code, str) or not sample.stock_code.strip():
        issues.append("stock_code must be a non-empty string")
    if not isinstance(sample.expected_tools, list):
        issues.append("expected_tools must be a list of tool names")
    elif not sample.expected_tools:
        issues.append("expected_tools must be a non-empty list")
    elif any(not isinstance(t, str) or not t.strip() for t in sample.expected_tools):
        issues.append("expected_tools must contain only non-empty strings")
    elif known is not None:
        # Only reachable when expected_tools is a non-empty list of non-empty
        # strings, so malformed values can never crash the membership check.
        unknown = [t for t in sample.expected_tools if t not in known]
        if unknown:
            issues.append(f"unknown expected_tools: {', '.join(unknown)}")
    if not isinstance(sample.skills, list):
        issues.append("skills must be a list of strings")
    elif any(not isinstance(s, str) or not s.strip() for s in sample.skills):
        issues.append("skills must contain only non-empty strings")
    if isinstance(sample.allowed_max_steps, bool) or not isinstance(sample.allowed_max_steps, int):
        issues.append("allowed_max_steps must be an integer")
    elif sample.allowed_max_steps < 1:
        issues.append("allowed_max_steps must be >= 1")
    if not isinstance(sample.allow_optional_tools, bool):
        issues.append("allow_optional_tools must be a boolean")
    return issues
