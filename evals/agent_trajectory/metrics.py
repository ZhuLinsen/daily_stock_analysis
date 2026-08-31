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

Both entry paths enforce the same golden-sample structure contract:
``validate_golden_sample`` (the loader path) rejects malformed samples
outright, while ``compute_trajectory_metrics`` (the direct-construction path)
reports malformed fields as violations and excludes the invalid parts from
scoring — a caller who builds a ``GoldenSample`` by hand must never get a
silently relaxed result (see the compute docstring for the exact mapping).

Idempotency key contract
------------------------
Two log entries are considered "the same call" when their ``tool`` names are
equal and their serialized ``arguments`` are equal.  Arguments may contain
unhashable values (dict / list), so the key is built with
``json.dumps(arguments, sort_keys=True, default=str)`` — a *stable string*,
not a hash.  Do not replace this with ``tuple(arguments)`` or ``repr()``:
insertion order or collection type would then change call identity and corrupt
redundancy / retry counts.  Mirroring the production
``_build_tool_cache_key``, a *string* ``stock_code`` field is canonicalized
before serialization so runtime-equivalent alias forms share one identity,
while non-string values (JSON numbers) stay raw; all other arguments stay
raw.

Codex App Server entries carry only ``arguments_summary`` — the preview
produced by ``redact_diagnostic_value`` (the JSON serialization of the
arguments dict, possibly redacted / truncated).  A well-formed preview is
parsed back to the original arguments dict *before* keying, so the recovered
payload goes through the same ``_args_key`` canonicalization as a runner
payload: alias spellings of ``stock_code`` and argument insertion order do
not split call identity.  Previews that no longer parse to an object
(truncated / redacted) fall back to keying by the raw preview string, which
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
  call) with *actual stock evidence* — the name-only tolerance does not
  apply to the pinned check, so a blocked call that never identifies a
  stock (empty or missing arguments payload) cannot prove the pinned probe.
  Every occurrence of the pair must remain blocked
  (``cached`` / ``guarded`` / failed): a clean success at *any* point — before
  or after the first guarded occurrence — is an escape (the scope guard was
  bypassed, or the call provably gets through it) and does not satisfy it.  A
  required outcome that is not observed is reported as a violation, so a
  golden sample that declares guard / cache / retry expectations cannot be
  passed by a trajectory that skips the behaviour it describes.  Codex-shaped
  logs cannot observe guard-dependent tags (``guarded`` / ``cached`` /
  ``guarded_retry``) because the producer drops that metadata; declaring them
  for such a log is reported as an explicit unsupported violation instead of
  a false "not observed" regression.  ``retry`` stays scoreable for Codex
  logs — it derives from (tool, args-key) repeats, which their entries do
  carry.
* ``expected_hit_rate`` is stock-scoped: an expected tool counts as hit only
  when at least one of its calls references ``golden.stock_code`` — matched
  exactly against the dedicated ``stock_code`` argument field of runner
  entries (never a substring scan, so e.g. ``"1600519"`` cannot satisfy
  ``600519``), the guard metadata ``requested_stock_code``, or the Codex
  ``arguments_summary`` preview (structured ``stock_code`` recovered from a
  well-formed preview is compared exactly; otherwise a substring scan,
  best-effort).  Both sides
  of each comparison are canonicalized first with the runtime-equivalent
  stock-code normalization (see below), so production-accepted forms such as
  ``SH600519`` / ``600519.SH`` / ``SZ.000001`` / ``hk700`` resolve to the
  same identity as their clean code instead of being mis-scored as
  wrong-stock.  Entries with no stock evidence at all keep the name-only
  tolerance — reserved for entries with no stock evidence at all; an
  explicitly present but invalid value (null / boolean / non-scalar, empty
  guard metadata) is a non-match and earns no hit credit.  *Every* call of
  an expected tool whose stock resolves to a different code is reported in a
  violation — one matching call does not legitimize cross-stock calls of the
  same tool.  The one exception is the
  sample's own pinned out-of-scope stock (``expected_guarded_stock``): a call
  that targets it (with actual stock evidence, the same strict match as the
  outcome seeding) and stays blocked (``guarded`` / ``cached`` / failed) is
  the deliberate probe the task itself requires, so it is exempt from
  wrong-stock reporting; a clean success on the pinned stock is still
  reported (and escapes ``guarded_retry``).
* Stock-code canonicalization: :func:`_canonicalize_stock_code` mirrors the
  runtime normalization chain
  (``src/agent/tools/execution._normalize_tool_stock_code`` delegating to
  ``data_provider.base.normalize_stock_code`` /
  ``canonical_stock_code``): whitespace / case folding, exchange
  prefix/suffix stripping (SH / SZ / SS / BJ), HK variants folded to
  ``HK00xxx``, Yahoo JP / KR / TW suffix forms preserved.  The metrics layer
  stays free of runtime imports; the test suite keeps a parity test against
  the production function so the mirror cannot silently drift, and live-run
  callers can inject the production normalizer via
  ``stock_code_normalizer``.
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
from typing import Any, Callable, Dict, Iterable, List, Optional

#: Machine-readable trajectory features a golden sample may require of a log
#: (``guarded`` = a guarded call, ``cached`` = a cached call, ``retry`` = at
#: least one retry, ``guarded_retry`` = a guarded call followed by later
#: occurrences of the same (tool, args-key) pair that all remain blocked —
#: cached / guarded / failed).  See the "Metric semantics" section of the
#: module docstring.
EXPECTED_OUTCOME_TAGS = ("guarded", "cached", "retry", "guarded_retry")

#: Outcome tags that depend on per-entry guard / cache metadata.  The Codex
#: App Server backend drops that metadata (it records only step / tool /
#: arguments_summary / success / duration), so Codex-shaped logs can never
#: observe these tags and such declarations are marked unsupported instead of
#: failing as "not observed" (see the module docstring).
GUARD_DEPENDENT_OUTCOME_TAGS = ("guarded", "cached", "guarded_retry")


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
    only observed for guarded calls targeting that stock, and blocked calls
    (guarded / cached / failed) targeting it are exempt from wrong-stock
    reporting — the sample itself requires the probe.
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


def _args_key(arguments: Any, normalizer: Optional[Callable[[Any], str]] = None) -> str:
    """Return a stable idempotency key for tool-call arguments (see module docstring).

    Mirrors ``src/agent/tools/execution._build_tool_cache_key``: when the
    payload is a dict, a *string* ``stock_code`` field is canonicalized
    before serialization so runtime-equivalent alias forms (``SH600519`` /
    ``600519.SH`` / ``600519``) share one call identity; every other
    argument stays raw, exactly like the production cache key.  Non-string
    ``stock_code`` values (JSON numbers from ``json.loads``) are preserved
    as-is because the production normalizer returns them unchanged, so
    ``600519`` and ``"600519"`` remain distinct identities.  Non-dict
    payloads (Codex ``arguments_summary`` wrappers, bare fallbacks) are
    serialized as-is.
    """
    if arguments is None:
        arguments = {}
    if isinstance(arguments, dict) and "stock_code" in arguments:
        value = arguments["stock_code"]
        # Only strings pass through the canonicalizer, mirroring the
        # type-preserving production ``_normalize_tool_stock_code``; the
        # runtime cache key keeps ``600519`` and ``"600519"`` apart.
        if isinstance(value, str):
            if normalizer is None:
                normalizer = _canonicalize_stock_code
            normalized = dict(arguments)
            normalized["stock_code"] = _apply_stock_normalizer(normalizer, value)
            arguments = normalized
    return json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)


def _entry_arguments(entry: Dict[str, Any]) -> Any:
    """Extract the idempotent argument payload from a log entry.

    Runner entries carry ``arguments`` (a dict).  Codex App Server entries
    carry ``arguments_summary`` — the JSON serialization of the arguments
    dict (possibly redacted / truncated) — so a well-formed preview is parsed
    back to the original dict and keyed through ``_args_key`` exactly like a
    runner payload (``stock_code`` canonicalization, sorted keys, argument
    insertion order must not split call identity).  Previews that do not
    parse back to a dict fall back to a raw-preview wrapper so distinct
    calls whose summaries collide after truncation keep distinct identities
    (documented best-effort; falling back to ``{}`` would merge every
    summary-only entry into one key).
    """
    arguments = entry.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    summary = entry.get("arguments_summary")
    if isinstance(summary, str) and summary:
        recovered = _summary_dict(summary)
        if recovered is not None:
            return recovered
        return {"arguments_summary": summary}
    return arguments


def _coerce_step(value: Any) -> int:
    """Coerce a log entry's ``step`` to a non-negative int (missing/odd -> 0)."""
    try:
        step = int(value)
    except (TypeError, ValueError):
        return 0
    return step if step > 0 else 0


def _canonicalize_stock_code(value: Any) -> str:
    """Canonicalize a stock code the way the runtime does before comparing.

    Mirrors ``src/agent/tools/execution._normalize_tool_stock_code`` (the
    guard path) and its delegate
    ``data_provider.base.normalize_stock_code``: trims whitespace, folds
    case, strips exchange prefixes/suffixes (``SH600519`` / ``600519.SH`` /
    ``SZ.000001`` / ``BJ920748`` ...), folds HK variants to ``HK00xxx``, and
    preserves Yahoo JP/KR/TW suffix forms (``7203.T`` / ``005930.KS`` /
    ``2330.TW``).  The mirror keeps this module free of runtime imports;
    ``tests/test_agent_trajectory_metrics.py`` asserts parity with the
    production function, and live-run callers can inject the production
    normalizer instead (see :func:`compute_trajectory_metrics`).
    """
    if not isinstance(value, str):
        return str(value)
    text = value.strip().upper()
    if not text:
        return text
    if text.endswith(".HK"):
        base = text[:-3]
        if base.isdigit() and 1 <= len(base) <= 5:
            return "HK" + base.zfill(5)
    if text.startswith("HK"):
        base = text[2:]
        if base.isdigit() and 1 <= len(base) <= 5:
            return "HK" + base.zfill(5)
    if text.isdigit() and len(text) == 5:
        return "HK" + text
    code = value.strip()
    upper = code.upper()
    if upper.startswith(("SH", "SZ", "SS")) and not upper.startswith(("SH.", "SZ.", "SS.")):
        candidate = code[2:]
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate
    if upper.startswith(("SH.", "SZ.", "SS.")):
        candidate = code[3:]
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate
    if upper.startswith("BJ") and not upper.startswith("BJ."):
        candidate = code[2:]
        if candidate.isdigit() and len(candidate) == 6:
            return candidate
    if upper.startswith("BJ."):
        candidate = code[3:]
        if candidate.isdigit() and len(candidate) == 6:
            return candidate
    if "." in code:
        base, suffix = code.rsplit(".", 1)
        if suffix.upper() == "T" and base.isdigit() and len(base) in (4, 5):
            return base + ".T"
        if suffix.upper() in ("KS", "KQ") and base.isdigit() and len(base) == 6:
            return base + "." + suffix.upper()
        if suffix.upper() in ("TW", "TWO") and base.isdigit() and 4 <= len(base) <= 6:
            return base + "." + suffix.upper()
        if suffix.upper() == "HK" and base.isdigit() and 1 <= len(base) <= 5:
            return "HK" + base.zfill(5)
        if base.upper() in ("SH", "SS", "SZ", "BJ") and suffix.isdigit():
            return suffix
        if suffix.upper() in ("SH", "SZ", "SS", "BJ") and base.isdigit():
            return base
    return text


def _apply_stock_normalizer(normalizer: Callable[[Any], str], value: Any) -> str:
    """Apply a stock normalizer defensively (non-str results fall back to the mirror)."""
    result = normalizer(value)
    return result if isinstance(result, str) else _canonicalize_stock_code(value)


def _entry_matches_stock(
    entry: Dict[str, Any],
    stock_code: str,
    normalizer: Callable[[Any], str],
    require_evidence: bool = False,
) -> bool:
    """Best-effort check that a log entry's call targeted ``stock_code``.

    Guard metadata (``requested_stock_code``) is authoritative; runner
    entries are matched exactly against their dedicated ``stock_code``
    argument field (every stock tool in the repository takes it) — the value
    is canonicalized and compared for equality, never scanned as a substring,
    so ``"1600519"`` cannot satisfy a ``600519`` golden while
    ``"SH600519"`` can.  Codex App Server entries carry only the redacted
    ``arguments_summary`` preview: when that preview parses back to a JSON
    object with a ``stock_code`` field, the recovered value is canonicalized
    and compared exactly like a runner argument (so ``hk700`` matches an
    ``HK00700`` golden); otherwise the preview is scanned by substring as a
    best-effort fallback.  Entries with no stock evidence at all keep the
    name-only tolerance so minimal entries still count as before; an
    explicitly present but invalid value (null / boolean / non-scalar) is a
    non-match — it provably does not target the golden stock and must not
    earn hit credit (see the module docstring).

    ``require_evidence`` tightens the check for stock-pinned assertions
    (``expected_guarded_stock``): entries with no stock evidence at all are
    non-matches instead of name-only hits — a blocked call that never
    identifies a stock cannot prove the pinned out-of-scope probe.
    """
    if "requested_stock_code" in entry:
        requested = entry["requested_stock_code"]
        # An explicitly present but invalid guard record is a non-match:
        # it carries no usable target and must not fall through to the
        # name-only tolerance (an empty string compares non-equal below).
        if not isinstance(requested, (str, int)) or isinstance(requested, bool):
            return False
        return _apply_stock_normalizer(normalizer, requested) == stock_code
    args = entry.get("arguments")
    if isinstance(args, dict):
        if "stock_code" not in args:
            # No stock evidence in the payload: documented name-only
            # tolerance for ordinary hit scoring (the entry still counts,
            # like a minimal entry) — but never for stock-pinned assertions.
            return not require_evidence
        value = args["stock_code"]
        # Explicitly present but invalid (null / boolean / non-scalar):
        # not evidence for the golden stock, so not a hit either.
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return False
        return _apply_stock_normalizer(normalizer, value) == stock_code
    summary = entry.get("arguments_summary")
    if isinstance(summary, str) and summary:
        value = _summary_stock_code(summary)
        if value is _SUMMARY_NO_EVIDENCE:
            return stock_code in summary
        # Recovered but invalid (JSON null / false / array): a non-match,
        # never name-only tolerance.
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return False
        return _apply_stock_normalizer(normalizer, value) == stock_code
    return not require_evidence


# Sentinel distinguishing "the summary holds no structured stock_code" from a
# legitimate ``None`` value.
_SUMMARY_NO_EVIDENCE = object()


def _summary_dict(summary: str) -> Optional[Dict[str, Any]]:
    """Parse a Codex ``arguments_summary`` back to the arguments dict.

    ``src/agent/codex_agent_backend`` stores
    ``redact_diagnostic_value(record.arguments)`` — the JSON serialization of
    the arguments dict — so a well-formed (untruncated, unredacted) preview
    recovers the original payload.  Returns ``None`` when the preview is not
    intact JSON of an object (truncated / redacted / non-object previews);
    callers then fall back to their documented best-effort handling.
    """
    try:
        parsed = json.loads(summary)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _summary_stock_code(summary: str) -> Any:
    """Recover the structured ``stock_code`` value from a Codex ``arguments_summary``.

    Returns ``_SUMMARY_NO_EVIDENCE`` when the preview does not parse back to
    a JSON object with a ``stock_code`` key (truncated / redacted /
    non-object previews), leaving callers to their documented no-evidence
    tolerance or substring fallback.
    """
    parsed = _summary_dict(summary)
    if parsed is not None and "stock_code" in parsed:
        return parsed["stock_code"]
    return _SUMMARY_NO_EVIDENCE


def _entry_mismatches_stock(
    entry: Dict[str, Any],
    stock_code: str,
    normalizer: Callable[[Any], str],
) -> bool:
    """True when the entry's stock resolves to a *different* code.

    Only evidence that resolves to a concrete code can mismatch: guard
    metadata, the ``stock_code`` argument field of runner entries, or a
    ``stock_code`` value recovered from a well-formed Codex
    ``arguments_summary``.  Unresolvable evidence (truncated / redacted
    previews, malformed values) is treated as "no evidence" — it can neither
    match nor mismatch, so it never produces a wrong-stock violation on its
    own.
    """
    requested = entry.get("requested_stock_code")
    if requested:
        if not isinstance(requested, (str, int)) or isinstance(requested, bool):
            return False
        return _apply_stock_normalizer(normalizer, requested) != stock_code
    args = entry.get("arguments")
    if isinstance(args, dict):
        value = args.get("stock_code")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return False
        return _apply_stock_normalizer(normalizer, value) != stock_code
    summary = entry.get("arguments_summary")
    if isinstance(summary, str) and summary:
        value = _summary_stock_code(summary)
        if value is _SUMMARY_NO_EVIDENCE:
            return False
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return False
        return _apply_stock_normalizer(normalizer, value) != stock_code
    return False


def _entry_stayed_blocked(entry: Dict[str, Any], success: bool) -> bool:
    """True when the call did not execute cleanly (guarded / cached / failed).

    A blocked call proves nothing about whether the scope guard can be
    bypassed, while a clean success of an out-of-scope call does — the same
    predicate drives the ``guarded_retry`` escape tracking and the
    wrong-stock exemption for pinned out-of-scope probes.
    """
    return bool(entry.get("cached") or entry.get("guarded") or not success)


def compute_trajectory_metrics(
    log: List[Dict[str, Any]],
    golden: GoldenSample,
    total_steps: Optional[int] = None,
    stock_code_normalizer: Optional[Callable[[Any], str]] = None,
) -> TrajectoryMetrics:
    """Compute all trajectory metrics from a ``tool_calls_log`` and a golden sample.

    ``total_steps`` optionally carries the number of loop rounds the run
    actually consumed (``RunLoopResult.total_steps``), which includes the
    final plain-answer round that produces no tool call.  When it is larger
    than the log-derived step count it is used for ``distinct_steps`` and the
    ``max_steps_touched`` heuristic; otherwise the log alone decides, and the
    default ``None`` keeps the log-only behaviour.

    ``stock_code_normalizer`` optionally injects the runtime stock-code
    canonicalization for live runs (e.g.
    ``src.agent.tools.execution._normalize_tool_stock_code``); the default is
    the module's runtime-equivalent mirror :func:`_canonicalize_stock_code`,
    which keeps the metrics layer free of runtime imports.

    Direct construction of a hand-edited ``GoldenSample`` is held to the same
    structure contract as :func:`validate_golden_sample` on the loader path:
    malformed parts are reported as violations and excluded from scoring
    instead of silently reshaping the result.  Malformed ``expected_tools`` /
    ``expected_outcomes`` elements are dropped with an explicit violation,
    and a pinned ``expected_guarded_stock`` is only honoured for the coherent
    pairing the validator requires (``guarded_retry`` declared, and a stock
    different from ``golden.stock_code`` after canonicalization) — an
    unpaired pin is reported and disabled rather than silently erasing
    wrong-stock reporting.
    """
    used_tools: List[str] = []
    key_counts: Dict[tuple, int] = {}
    key_failed_seen: Dict[tuple, bool] = {}
    key_retries: Dict[tuple, int] = {}
    key_guarded_at: Dict[tuple, int] = {}
    key_guarded_escaped: set = set()
    stock_hit: Dict[str, bool] = {}
    wrong_stock_calls: List[str] = []
    codex_shaped = False
    if stock_code_normalizer is None:
        normalizer = _canonicalize_stock_code
        normalizer_invalid = False
    elif callable(stock_code_normalizer):
        normalizer = stock_code_normalizer
        normalizer_invalid = False
    else:
        normalizer = _canonicalize_stock_code
        normalizer_invalid = True
    golden_stock_valid = isinstance(golden.stock_code, str) and bool(golden.stock_code.strip())
    stock_code = _apply_stock_normalizer(normalizer, golden.stock_code) if golden_stock_valid else ""
    guarded_stock = golden.expected_guarded_stock
    guarded_stock_nonempty = isinstance(guarded_stock, str) and bool(guarded_stock.strip())
    # A pinned stock only takes effect for the coherent pairing
    # validate_golden_sample() enforces: expected_guarded_stock must be
    # declared together with guarded_retry in expected_outcomes.  An
    # unpaired pin is malformed — it is reported below and must not reshape
    # scoring (no wrong-stock exemption, no pinned seeding).
    guarded_stock_valid = guarded_stock_nonempty and (
        isinstance(golden.expected_outcomes, list) and "guarded_retry" in golden.expected_outcomes
    )
    guarded_stock = _apply_stock_normalizer(normalizer, guarded_stock) if guarded_stock_nonempty else guarded_stock
    # Extract the expected tool list before scanning entries so per-entry
    # wrong-stock reporting can consult it during the loop.  Malformed
    # elements are not silently dropped: they are reported as a violation
    # below (mirroring validate_golden_sample, which rejects them at load
    # time) and only the valid names take part in scoring.
    if isinstance(golden.expected_tools, list):
        expected_tools_malformed = [t for t in golden.expected_tools if not isinstance(t, str) or not t]
        expected = [t for t in golden.expected_tools if isinstance(t, str) and t]
    else:
        # Defend against hand-edited samples passing a bare string:
        # validation rejects it at load time, but scoring must not misparse
        # it into per-character tool names either.
        expected_tools_malformed = []
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
        success = bool(entry.get("success", True))
        if tool and tool not in used_tools:
            used_tools.append(tool)
        if stock_code and tool and tool not in stock_hit and _entry_matches_stock(entry, stock_code, normalizer):
            stock_hit[tool] = True
        # Every call of an expected tool whose stock resolves to a different
        # code is reported — a matching call elsewhere must not legitimize
        # cross-stock usage of the same tool (stock_hit only tracks whether
        # the tool ever matched, not whether every call did).  The one
        # exception is the sample's pinned out-of-scope stock: a blocked
        # probe of it (guarded / cached / failed) is exactly what the golden
        # requires, so it is not a wrong-stock violation — but a clean
        # success on the pinned stock is still reported (and escapes
        # guarded_retry).
        pinned_probe_blocked = (
            guarded_stock_valid
            and _entry_matches_stock(entry, guarded_stock, normalizer, require_evidence=True)
            and _entry_stayed_blocked(entry, success)
        )
        if (
            stock_code
            and tool in expected_set
            and not pinned_probe_blocked
            and _entry_mismatches_stock(entry, stock_code, normalizer)
        ):
            wrong_stock_calls.append(tool)
        step = _coerce_step(entry.get("step"))
        if step and step not in seen_steps:
            seen_steps.add(step)
            distinct_steps += 1
            max_step = max(max_step, step)
        if not success:
            failed_calls += 1
        if entry.get("cached"):
            cached_calls += 1
        if entry.get("guarded"):
            guarded_calls += 1
        if not isinstance(entry.get("arguments"), dict) and entry.get("arguments_summary"):
            codex_shaped = True

        key = (tool, _args_key(_entry_arguments(entry), normalizer))
        if key_counts.get(key, 0):
            redundant_calls += 1
        key_counts[key] = key_counts.get(key, 0) + 1
        # A clean success bypasses the stock-scope guard: the call escaped.
        # The key is disqualified from the "guarded_retry" outcome whether
        # the success happened before or after the first guarded occurrence —
        # the golden contract requires every out-of-scope call to stay
        # blocked at all times, and a pre-guard success proves the call can
        # get through the guard.
        if not _entry_stayed_blocked(entry, success):
            key_guarded_escaped.add(key)
        # Record the occurrence index of the (first) guarded call so the
        # "guarded_retry" outcome can require a *later* occurrence of the
        # same key instead of matching any guard and any retry anywhere.
        # When the sample pins the guarded stock, only guarded calls
        # carrying actual stock evidence for that stock can seed the
        # outcome — a blocked call that never identifies a stock cannot
        # prove the pinned out-of-scope probe (no name-only tolerance here).
        if entry.get("guarded") and key not in key_guarded_at:
            if not guarded_stock_valid or _entry_matches_stock(entry, guarded_stock, normalizer, require_evidence=True):
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
    if expected_tools_malformed:
        violations.append("expected_tools must contain only non-empty strings")
    if normalizer_invalid:
        violations.append("stock_code_normalizer is not callable")
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
        malformed_outcomes = [t for t in golden.expected_outcomes if not isinstance(t, str) or not t]
        # Malformed outcome elements are reported (same wording as
        # validate_golden_sample) instead of silently dropping the
        # requirement they tried to declare.
        if malformed_outcomes:
            violations.append("expected_outcomes must contain only non-empty strings")
        outcomes = [t for t in golden.expected_outcomes if isinstance(t, str) and t]
        if len(set(outcomes)) != len(outcomes):
            violations.append("expected_outcomes contains duplicate tags")
            outcomes = list(dict.fromkeys(outcomes))
        unknown = [t for t in outcomes if t not in EXPECTED_OUTCOME_TAGS]
        if unknown:
            violations.append(f"unknown expected outcome tags: {', '.join(unknown)}")
    # A pinned but malformed guarded stock must not silently disable the
    # stock binding for guarded_retry — nor silently keep it: mirror the
    # structure contract validate_golden_sample() enforces at load time, so
    # the direct-construction path reports the same violations instead of
    # drifting from the loader semantics.
    if golden.expected_guarded_stock is not None and not guarded_stock_nonempty:
        violations.append("expected_guarded_stock must be a non-empty string")
    elif guarded_stock_nonempty and guarded_stock == stock_code:
        violations.append(
            "expected_guarded_stock must name a different stock than stock_code "
            "after canonicalization (it names the out-of-scope call)"
        )
    elif guarded_stock_nonempty and not guarded_stock_valid:
        violations.append("expected_guarded_stock requires guarded_retry in expected_outcomes")
    # Codex App Server entries carry no guarded / cached metadata (the
    # backend records only step / tool / arguments_summary / success /
    # duration), so guard-dependent outcome tags can never be observed from a
    # Codex-shaped log; mark them unsupported instead of emitting a false
    # "expected outcomes not observed" regression.  ``retry`` stays
    # scoreable: it derives from (tool, args-key) repeats, which Codex
    # entries do carry.
    unsupported_outcomes = [t for t in outcomes if t in GUARD_DEPENDENT_OUTCOME_TAGS] if codex_shaped else []
    if unsupported_outcomes:
        violations.append(
            "expected outcomes unsupported for Codex App Server logs "
            "(backend drops guarded/cached metadata): " + ", ".join(unsupported_outcomes)
        )
    observed = []
    if guarded_calls:
        observed.append("guarded")
    if cached_calls:
        observed.append("cached")
    if retries:
        observed.append("retry")
    if any(idx < key_counts.get(k, 0) and k not in key_guarded_escaped for k, idx in key_guarded_at.items()):
        observed.append("guarded_retry")
    missing_outcomes = [
        t for t in outcomes if t in EXPECTED_OUTCOME_TAGS and t not in observed and t not in unsupported_outcomes
    ]
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
        elif _canonicalize_stock_code(sample.expected_guarded_stock) == _canonicalize_stock_code(sample.stock_code):
            issues.append(
                "expected_guarded_stock must name a different stock than stock_code "
                "after canonicalization (it names the out-of-scope call)"
            )
        elif not isinstance(sample.expected_outcomes, list) or "guarded_retry" not in sample.expected_outcomes:
            issues.append("expected_guarded_stock requires guarded_retry in expected_outcomes")
    return issues
