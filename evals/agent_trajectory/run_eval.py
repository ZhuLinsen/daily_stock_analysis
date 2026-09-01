#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run one agent-trajectory eval sample against the real agent executor (Issue #1956).

Consumes a real ``tool_calls_log + AgentResult`` produced by
``src.agent.factory.build_agent_executor`` (the same capture hook the
analysis pipeline uses in ``src/core/pipeline.py``), scores it with the
pure metrics layer and emits a short human-readable text summary plus an
optional structured JSON report.

The eval is a *reporter*, not a gate: metric violations lower the report,
they never fail the process.  Exit codes: 0 = ran (violations included),
1 = load (golden / tool registry) / build / run failure, 2 = usage error.

The entry supports the single-agent runner only.  When ``AGENT_ARCH=multi``
the factory returns the orchestrator whose trajectories use per-stage local
step numbers, which breaks the single-runner metric contract, so the entry
rejects that arch up front with exit code 1.  Golden samples are validated
against the real tool registry before running, so misspelled or stale
``expected_tools`` fail as invalid samples instead of scoring as low hit
rate.

Usage:
    python evals/agent_trajectory/run_eval.py --sample 600519_technical
    python evals/agent_trajectory/run_eval.py --all --json-out eval_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the project root to sys.path so the script also works as
# `python evals/agent_trajectory/run_eval.py` from anywhere.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from evals.agent_trajectory.metrics import (
    GoldenSample,
    TrajectoryMetrics,
    compute_trajectory_metrics,
    format_text_report,
    load_golden_samples,
)


def _build_report(sample: GoldenSample, metrics: TrajectoryMetrics) -> Dict[str, Any]:
    """Structured JSON report for one sample (schema in docs/agent-trajectory-eval.md)."""
    return {
        "sample_id": sample.id,
        "task_description": sample.task_description,
        "stock_code": sample.stock_code,
        "metrics": asdict(metrics),
        "violations": metrics.violations,
    }


def _write_json(path: Optional[Path], payload: Any) -> None:
    """Write ``payload`` as indented UTF-8 JSON (trailing newline)."""
    if path is None:
        return
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_KNOWN_TOOL_NAMES: Optional[set] = None


def _check_agent_arch() -> None:
    """Reject multi-agent arch up front (mirrors the factory's own decision).

    ``src.agent.factory.build_agent_executor`` returns the orchestrator when
    ``config.agent_arch == "multi"``; its trajectories concatenate per-stage
    logs with local step numbering and set ``total_steps`` to the stage count,
    which the single-runner metric contract cannot interpret.  Fail fast
    instead of scoring a distorted trajectory.
    """
    from src.config import get_config

    arch = getattr(get_config(), "agent_arch", "single")
    if arch == "multi":
        raise RuntimeError(
            "AGENT_ARCH=multi is not supported by this minimal eval: "
            "orchestrator trajectories use per-stage local step numbers, "
            "which break the single-runner metric contract"
        )


def _known_tool_names():
    """Authoritative tool names from the real registry modules (lazy, cached).

    The metrics layer deliberately does not import ``src/``; the entry point
    supplies these names so ``load_golden_samples`` rejects misspelled or
    stale ``expected_tools`` instead of scoring them as low hit rate.
    """
    global _KNOWN_TOOL_NAMES
    if _KNOWN_TOOL_NAMES is None:
        from src.agent.tools.analysis_tools import ALL_ANALYSIS_TOOLS
        from src.agent.tools.backtest_tools import ALL_BACKTEST_TOOLS
        from src.agent.tools.data_tools import ALL_DATA_TOOLS
        from src.agent.tools.market_tools import ALL_MARKET_TOOLS
        from src.agent.tools.search_tools import ALL_SEARCH_TOOLS

        all_tools = ALL_DATA_TOOLS + ALL_ANALYSIS_TOOLS + ALL_SEARCH_TOOLS + ALL_MARKET_TOOLS + ALL_BACKTEST_TOOLS
        _KNOWN_TOOL_NAMES = {tool_def.name for tool_def in all_tools}
    return _KNOWN_TOOL_NAMES


def _build_executor():
    """Build the real agent executor (lazy import so tests can monkeypatch this)."""
    _check_agent_arch()
    from src.agent.factory import build_agent_executor

    return build_agent_executor()


def run_sample(executor, sample: GoldenSample, *, json_out: Optional[Path] = None) -> TrajectoryMetrics:
    """Run one golden sample against a duck-typed agent executor and score it.

    ``executor`` only needs ``run(task, context=None) -> result`` where
    ``result`` carries ``tool_calls_log`` (and optionally ``total_steps``) —
    the same shape as ``src.agent.executor.AgentResult``.  The production
    executor is built lazily by :func:`_build_executor`; tests may pass a
    stub.  A result carrying an explicit ``success=False`` is a run failure
    (the executor reported a provider / timeout / budget error) and raises
    ``RuntimeError`` before any scoring; duck-typed results without a
    ``success`` attribute are treated as successful.  The text summary is
    always printed to stdout; ``json_out`` additionally writes the
    structured report for this sample.
    """
    context: Optional[Dict[str, Any]] = None
    if sample.stock_code:
        context = {"stock_code": sample.stock_code}
    result = executor.run(sample.task_description, context=context)
    if getattr(result, "success", None) is False:
        error = getattr(result, "error", None)
        raise RuntimeError(f"agent run failed (success=false): {error or 'no error detail'}")
    log = getattr(result, "tool_calls_log", None) or []
    total_steps = getattr(result, "total_steps", None)
    metrics = compute_trajectory_metrics(log, sample, total_steps=total_steps)
    print(format_text_report(metrics))
    _write_json(json_out, _build_report(sample, metrics))
    return metrics


def main(argv=None) -> int:
    """Run one golden sample (--sample ID) or every sample (--all)."""
    parser = argparse.ArgumentParser(
        description="Run one agent-trajectory eval sample against the real agent executor (Issue #1956).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample", metavar="ID", help="run the golden sample with this id")
    group.add_argument("--all", action="store_true", help="run every golden sample")
    parser.add_argument(
        "--golden-path",
        default=None,
        help="path to golden_samples.json (default: the checked-in file next to this module)",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="write a structured JSON report to this path (--all writes a keyed object)",
    )
    args = parser.parse_args(argv)

    try:
        known = _known_tool_names()
    except Exception as exc:
        print(f"error: failed to load tool registry for golden validation: {exc}", file=sys.stderr)
        return 1

    try:
        samples = load_golden_samples(path=args.golden_path, known_tool_names=known)
    except (OSError, ValueError) as exc:
        print(f"error: failed to load golden samples: {exc}", file=sys.stderr)
        return 1

    if args.sample:
        selected = next((s for s in samples if s.id == args.sample), None)
        if selected is None:
            available = ", ".join(s.id for s in samples) if samples else "(none)"
            print(f"error: unknown sample id '{args.sample}'; available: {available}", file=sys.stderr)
            return 1
        samples = [selected]

    try:
        executor = _build_executor()
    except Exception as exc:  # pragma: no cover - exercised via monkeypatched failure
        print(f"error: failed to build agent executor: {exc}", file=sys.stderr)
        return 1

    reports: Dict[str, Dict[str, Any]] = {}
    for sample in samples:
        print(f"[eval] sample: {sample.id} | task: {sample.task_description}")
        try:
            metrics = run_sample(executor, sample)
        except Exception as exc:
            print(f"error: sample '{sample.id}' failed: {exc}", file=sys.stderr)
            return 1
        reports[sample.id] = _build_report(sample, metrics)

    if args.json_out:
        _write_json(Path(args.json_out), reports if args.all else reports[args.sample])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
