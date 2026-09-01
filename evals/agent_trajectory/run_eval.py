#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run one agent-trajectory eval sample against the real agent executor (Issue #1956).

Consumes a real ``tool_calls_log + AgentResult`` produced by
``src.agent.factory.build_agent_executor`` (the same capture hook the
analysis pipeline uses in ``src/agent/pipeline.py``), scores it with the
pure metrics layer and emits a short human-readable text summary plus an
optional structured JSON report.

The eval is a *reporter*, not a gate: metric violations lower the report,
they never fail the process.  Exit codes: 0 = ran (violations included),
1 = load / build / run failure, 2 = usage error.

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


def _build_executor():
    """Build the real agent executor (lazy import so tests can monkeypatch this)."""
    from src.agent.factory import build_agent_executor

    return build_agent_executor()


def run_sample(executor, sample: GoldenSample, *, json_out: Optional[Path] = None) -> TrajectoryMetrics:
    """Run one golden sample against a duck-typed agent executor and score it.

    ``executor`` only needs ``run(task, context=None) -> result`` where
    ``result`` carries ``tool_calls_log`` (and optionally ``total_steps``) —
    the same shape as ``src.agent.executor.AgentResult``.  The production
    executor is built lazily by :func:`_build_executor`; tests may pass a
    stub.  The text summary is always printed to stdout; ``json_out``
    additionally writes the structured report for this sample.
    """
    context: Optional[Dict[str, Any]] = None
    if sample.stock_code:
        context = {"stock_code": sample.stock_code}
    result = executor.run(sample.task_description, context=context)
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
        samples = load_golden_samples(path=args.golden_path)
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
