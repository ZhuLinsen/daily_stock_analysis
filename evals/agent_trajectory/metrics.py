# -*- coding: utf-8 -*-
"""Pure-function trajectory metrics for agent evaluation (Issue #1956).

This module computes quality metrics for an agent execution trajectory from its
``tool_calls_log`` (see ``src/agent/runner.py`` for the producer contract):

* each entry carries ``step / tool / arguments / success / duration /
  result_length / cached`` and optionally ``timeout`` or ``guarded`` fields;
* entries with missing optional fields are tolerated with defaults (e.g. the
  Codex App Server backend emits ``arguments_summary`` instead of
  ``arguments``).

The scoring functions in this module are pure: ``compute_trajectory_metrics``,
``format_text_report`` and ``validate_golden_sample`` consume plain data (a log
list and a ``GoldenSample``) and never touch the filesystem, network, or LLM.
The one exception is the loader ``load_golden_samples``, which reads the golden
JSON file from disk.  This keeps the metrics layer deterministic, unit-testable
without an API key, and free of ``src/`` imports — it can score trajectories
from any source.

Idempotency key contract
------------------------
Two log entries are considered "the same call" when their ``tool`` names are
equal and their serialized ``arguments`` are equal.  Arguments may contain
unhashable values (dict / list), so the key is built with
``json.dumps(arguments, sort_keys=True, default=str)`` — a *stable string*,
not a hash.  Do not replace this with ``tuple(arguments)`` or ``repr()``:
insertion order or collection type would then change call identity and corrupt
redundancy / retry counts.

Codex App Server entries carry only ``arguments_summary`` — the redacted and
truncated preview produced by ``redact_diagnostic_value`` — so their identity
is best-effort: distinct calls whose summaries collide after redaction or
truncation may be over-counted as redundant.  A stable argument fingerprint
requires a producer-side change in ``src/agent/codex_agent_backend.py``, which
is out of scope for this metrics layer.

Codex App Server entries also record ``step=1`` for every tool call in a turn
and ``total_steps=1`` on success — the real budget there is the tool-call
count (``max_tool_calls=request.max_steps``).  Step-derived metrics
(``distinct_steps`` / ``max_steps_touched``) are therefore suppressed with an
explicit violation for Codex-shaped logs instead of reporting a misleading
one-step result.  A comparable step budget requires a producer-side field in
``src/agent/codex_agent_backend.py``, which is out of scope for this metrics
layer.

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
* ``expected_outcomes``: machine-readable trajectory features a golden sample
  may require, from the fixed vocabulary ``guarded`` / ``cached`` / ``retry`` /
  ``guarded_retry``.  ``guarded`` is observed when any entry carries
  ``guarded=True`` (the stock-scope guard interception), ``cached`` when any
  entry carries ``cached=True``, ``retry`` when at least one retry is counted
  per the contract above, and ``guarded_retry`` when a (tool, args-key) pair
  with a guarded occurrence is *followed by* a later occurrence of the same
  pair — the guarded call itself was retried, so a guard from one call plus a
  retry of an unrelated call does not satisfy it.  When the sample sets
  ``expected_guarded_stock``, the guarded occurrence of ``guarded_retry``
  must additionally target that stock (the task's required out-of-scope
  call), so two guarded retries of any other stock do not satisfy it.  A
  required outcome that is not observed is reported as a violation, so a
  golden sample that declares guard / cache / retry expectations cannot be
  passed by a trajectory that skips the behaviour it describes.
* ``expected_hit_rate`` is stock-scoped: an expected tool counts as hit only
  when at least one of its calls references ``golden.stock_code`` — matched
  exactly against the dedicated ``stock_code`` argument field of runner
  entries (normalized string comparison, never a substring scan, so e.g.
  ``"1600519"`` cannot satisfy ``600519``), the guard metadata
  ``requested_stock_code``, or the Codex ``arguments_summary`` preview
  (substring match, best-effort).  Entries with no stock evidence at all keep
  the name-only tolerance, and *every* call of an expected tool whose stock
  resolves to a different code is reported in a violation — one matching call
  does not legitimize cross-stock calls of the same tool.
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

#: Machine-readable trajectory features a golden sample may require of a log
#: (``guarded`` = a guarded call, ``cached`` = a cached call, ``retry`` = at
#: least one retry, ``guarded_retry`` = a guarded call followed by a later
#: occurrence of the same (tool, args-key) pair).  See the "Metric semantics"
#: section of the module docstring.
EXPECTED_OUTCOME_TAGS = ("guarded", "cached", "retry", "guarded_retry")


@dataclass
class GoldenSample:
    """Expected trajectory for one evaluation task.

    ``expected_tools`` are the tool names the agent should call; tools outside
    this set are tolerated only when ``allow_optional_tools`` is true.
    ``expected_outcomes`` are required trajectory features from the vocabulary
    ``guarded`` / ``cached`` / ``retry`` / ``guarded_retry`` (see the module
    docstring); every declared outcome must be observable in the log.
    ``expected_guarded_stock`` optionally pins the stock the guard must
    intercept (the task's out-of-scope call): when set, ``guarded_retry`` is
    only observed for guarded calls targeting that stock.
    """

    id: str
    task_description: str
    stock_code: str
    expected_tools: List[str]
    skills: List[str] = field(default_factory=list)
    allowed_max_steps: int = 10
    allow_optional_tools: bool = True
    expected_outcomes: List[str] = field(default_factory=list)
    expected_guarded_stock: Optional[str] = None


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


def _normalized_stock(value: Any) -> str:
    """Normalize a resolvable stock value (str / int) for exact comparison."""
    return str(value).strip()


def _entry_matches_stock(entry: Dict[str, Any], stock_code: str) -> bool:
    """Best-effort check that a log entry's call targeted ``stock_code``.

    Guard metadata (``requested_stock_code``) is authoritative; runner
    entries are matched exactly against their dedicated ``stock_code``
    argument field (every stock tool in the repository takes it) — the value
    is normalized and compared for equality, never scanned as a substring, so
    ``"1600519"`` cannot satisfy a ``600519`` golden.  Codex App Server
    entries carry only the redacted ``arguments_summary`` preview, which has
    no structured field and is matched by substring.  Entries with no stock
    evidence at all (or unresolvable values) keep the name-only tolerance so
    malformed or minimal entries still count as before.
    """
    requested = entry.get("requested_stock_code")
    if requested:
        if not isinstance(requested, (str, int)) or isinstance(requested, bool):
            return True
        return _normalized_stock(requested) == stock_code
    args = entry.get("arguments")
    if isinstance(args, dict):
        value = args.get("stock_code")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return True
        return _normalized_stock(value) == stock_code
    summary = entry.get("arguments_summary")
    if isinstance(summary, str) and summary:
        return stock_code in summary
    return True


def _entry_mismatches_stock(entry: Dict[str, Any], stock_code: str) -> bool:
    """True when the entry's stock resolves to a *different* code.

    Only evidence that resolves to a concrete code can mismatch: guard
    metadata, or the ``stock_code`` argument field of runner entries.
    Unresolvable evidence (Codex summary previews, malformed values) is
    treated as "no evidence" — it can neither match nor mismatch, so it never
    produces a wrong-stock violation on its own.
    """
    requested = entry.get("requested_stock_code")
    if requested:
        if not isinstance(requested, (str, int)) or isinstance(requested, bool):
            return False
        return _normalized_stock(requested) != stock_code
    args = entry.get("arguments")
    if isinstance(args, dict):
        value = args.get("stock_code")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return False
        return _normalized_stock(value) != stock_code
    return False


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
    key_guarded_at: Dict[tuple, int] = {}
    stock_hit: Dict[str, bool] = {}
    wrong_stock_calls: List[str] = []
    codex_shaped = False
    stock_code = golden.stock_code if isinstance(golden.stock_code, str) and golden.stock_code.strip() else ""
    guarded_stock = golden.expected_guarded_stock
    guarded_stock_valid = isinstance(guarded_stock, str) and bool(guarded_stock.strip())
    # Extract the expected tool list before scanning entries so per-entry
    # wrong-stock reporting can consult it during the loop.
    if isinstance(golden.expected_tools, list):
        expected = [t for t in golden.expected_tools if isinstance(t, str) and t]
    else:
        # Defend against hand-edited samples passing a bare string:
        # validation rejects it at load time, but scoring must not misparse
        # it into per-character tool names either.
        expected = []
    # A hand-edited sample may repeat a tool name; normalize to first
    # occurrences before scoring so the hit rate cannot be inflated
    # (["quote", "quote"] with one quote call must read 1/2, not 2/3).
    expected_dupes = len(set(expected)) != len(expected)
    if expected_dupes:
        expected = list(dict.fromkeys(expected))
    expected_set = set(expected)
    failed_calls = 0
    cached_calls = 0
    guarded_calls = 0
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
        if stock_code and tool and tool not in stock_hit and _entry_matches_stock(entry, stock_code):
            stock_hit[tool] = True
        # Every call of an expected tool whose stock resolves to a different
        # code is reported — a matching call elsewhere must not legitimize
        # cross-stock usage of the same tool (stock_hit only tracks whether
        # the tool ever matched, not whether every call did).
        if stock_code and tool in expected_set and _entry_mismatches_stock(entry, stock_code):
            wrong_stock_calls.append(tool)
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
        if entry.get("guarded"):
            guarded_calls += 1
        if not isinstance(entry.get("arguments"), dict) and entry.get("arguments_summary"):
            codex_shaped = True

        key = (tool, _args_key(_entry_arguments(entry)))
        if key_counts.get(key, 0):
            redundant_calls += 1
        key_counts[key] = key_counts.get(key, 0) + 1
        # Record the occurrence index of the (first) guarded call so the
        # "guarded_retry" outcome can require a *later* occurrence of the
        # same key instead of matching any guard and any retry anywhere.
        # When the sample pins the guarded stock, only guarded calls
        # targeting that stock can seed the outcome.
        if entry.get("guarded") and key not in key_guarded_at:
            if not guarded_stock_valid or _entry_matches_stock(entry, guarded_stock):
                key_guarded_at[key] = key_counts[key]
        # An occurrence is a retry only when the same call already failed
        # before it (see module docstring for the precise contract).
        if key_failed_seen.get(key):
            key_retries[key] = key_retries.get(key, 0) + 1
        # A success clears the failure state: repeats after a recovery count
        # as redundant only, not as further retries.
        key_failed_seen[key] = not success

    retries = sum(key_retries.values())
    violations: List[str] = []

    if codex_shaped:
        # Codex App Server backend records step=1 for every tool call in a
        # turn and total_steps=1 on success, so step-derived metrics would
        # silently read as a normal one-step run; suppress them instead.
        violations.append(
            "step metrics are unsupported for Codex App Server logs (backend "
            "records step=1 per turn and total_steps=1 on success): "
            "distinct_steps / max_steps_touched suppressed"
        )
        distinct_steps = 0
        max_step = 0
    else:
        # The final answer round consumes a step but produces no tool call,
        # so when the caller supplies the run's real total it may exceed the
        # log.
        total = 0
        if total_steps is not None:
            try:
                total = int(total_steps)
            except (TypeError, ValueError):
                total = 0
            total = total if total > 0 else 0
        distinct_steps = max(distinct_steps, total)
        max_step = max(max_step, total)

    if expected_dupes:
        violations.append("expected_tools contains duplicate names")
    if not stock_code:
        violations.append("golden.stock_code is not a non-empty string")
    # Stock-scoped hit semantics: an expected tool only counts when one of
    # its calls actually referenced the golden stock (see module docstring);
    # without a valid golden stock the scoring falls back to name-only.
    missing_expected = (
        [t for t in expected if t not in stock_hit] if stock_code else [t for t in expected if t not in used_tools]
    )
    if stock_code and wrong_stock_calls:
        violations.append(
            f"expected tools called for a different stock than " f"{golden.stock_code}: {', '.join(wrong_stock_calls)}"
        )
    expected_hit_rate = (len(expected) - len(missing_expected)) / len(expected) if expected else 0.0
    optional_tools_used = [t for t in used_tools if t not in expected]

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

    # Machine-readable outcome expectations: each declared tag must be
    # observable in the log, otherwise the sample's guard / cache / retry
    # contract is violated (see the module docstring).
    if not isinstance(golden.expected_outcomes, list):
        violations.append("expected_outcomes must be a list of outcome tags")
        outcomes: List[str] = []
    else:
        outcomes = [t for t in golden.expected_outcomes if isinstance(t, str) and t]
        if len(set(outcomes)) != len(outcomes):
            violations.append("expected_outcomes contains duplicate tags")
            outcomes = list(dict.fromkeys(outcomes))
        unknown = [t for t in outcomes if t not in EXPECTED_OUTCOME_TAGS]
        if unknown:
            violations.append(f"unknown expected outcome tags: {', '.join(unknown)}")
    # A pinned but malformed guarded stock must not silently disable the
    # stock binding for guarded_retry.
    if golden.expected_guarded_stock is not None and not guarded_stock_valid:
        violations.append("expected_guarded_stock must be a non-empty string")
    observed = []
    if guarded_calls:
        observed.append("guarded")
    if cached_calls:
        observed.append("cached")
    if retries:
        observed.append("retry")
    if any(idx < key_counts.get(k, 0) for k, idx in key_guarded_at.items()):
        observed.append("guarded_retry")
    missing_outcomes = [t for t in outcomes if t in EXPECTED_OUTCOME_TAGS and t not in observed]
    if missing_outcomes:
        violations.append(f"expected outcomes not observed: {', '.join(missing_outcomes)}")

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
        retries=retries,
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

    # Materialize once before the loop: a one-shot generator must survive the
    # validation of every sample, not just the first.
    known = set(known_tool_names) if known_tool_names is not None else None
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
        # Structural validation runs before duplicate detection so that a
        # mistyped (possibly unhashable) id is rejected as a ValueError here
        # instead of crashing the membership check below.
        issues = validate_golden_sample(sample, known)
        if issues:
            raise ValueError(f"sample '{sample.id}': " + "; ".join(issues))
        if sample.id in seen_ids:
            raise ValueError(f"duplicate sample id: {sample.id}")
        seen_ids.add(sample.id)
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
    passing: text fields must be strings, ``expected_tools``/``skills`` and
    ``expected_outcomes`` must be lists, ``allowed_max_steps`` an integer and
    ``allow_optional_tools`` a boolean.  ``expected_tools`` and
    ``expected_outcomes`` must be duplicate-free, and outcome tags must come
    from the fixed vocabulary ``guarded`` / ``cached`` / ``retry`` /
    ``guarded_retry``.  ``expected_guarded_stock``, when set, must be a
    non-empty string that differs from ``stock_code`` (it names the
    out-of-scope call) and pairs with a declared ``guarded_retry`` outcome.
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
    elif len(set(sample.expected_tools)) != len(sample.expected_tools):
        issues.append("expected_tools must not contain duplicate names")
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
    if not isinstance(sample.expected_outcomes, list):
        issues.append("expected_outcomes must be a list of outcome tags")
    elif any(not isinstance(t, str) or not t.strip() for t in sample.expected_outcomes):
        issues.append("expected_outcomes must contain only non-empty strings")
    elif len(set(sample.expected_outcomes)) != len(sample.expected_outcomes):
        issues.append("expected_outcomes must not contain duplicate tags")
    else:
        unknown = [t for t in sample.expected_outcomes if t not in EXPECTED_OUTCOME_TAGS]
        if unknown:
            issues.append(f"unknown expected_outcomes: {', '.join(unknown)}")
    if sample.expected_guarded_stock is not None:
        if not isinstance(sample.expected_guarded_stock, str) or not sample.expected_guarded_stock.strip():
            issues.append("expected_guarded_stock must be a non-empty string")
        elif sample.expected_guarded_stock.strip() == sample.stock_code:
            issues.append("expected_guarded_stock must differ from stock_code (it names the out-of-scope call)")
        elif not isinstance(sample.expected_outcomes, list) or "guarded_retry" not in sample.expected_outcomes:
            issues.append("expected_guarded_stock requires guarded_retry in expected_outcomes")
    return issues
