#!/usr/bin/env python3
"""Run one deterministic, duration-balanced shard of the offline test suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DURATIONS_PATH = REPO_ROOT / ".github" / "ci-test-durations.json"


def discover_test_files(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return every pytest file covered by the repository's setup.cfg contract."""
    return sorted(
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "tests").rglob("test_*.py")
        if path.is_file()
    )


def load_durations(path: Path = DEFAULT_DURATIONS_PATH) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("durations"), dict):
        raise ValueError(f"Invalid CI duration data: {path}")

    durations: dict[str, float] = {}
    for test_file, duration in payload["durations"].items():
        if not isinstance(test_file, str) or not test_file.startswith("tests/"):
            raise ValueError(f"Invalid test path in CI duration data: {test_file!r}")
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError(f"Invalid duration for {test_file}: {duration!r}")
        durations[test_file] = float(duration)
    return durations


def partition_test_files(
    test_files: Sequence[str],
    durations: Mapping[str, float],
    splits: int,
    initial_totals: Sequence[float] | None = None,
) -> tuple[list[list[str]], list[float]]:
    """Greedily balance whole test modules while preserving order within a shard."""
    if splits < 1:
        raise ValueError("splits must be positive")
    if len(set(test_files)) != len(test_files):
        raise ValueError("test_files must not contain duplicates")
    if initial_totals is None:
        initial_totals = [0.0] * splits
    if len(initial_totals) != splits or any(total < 0 for total in initial_totals):
        raise ValueError("initial_totals must contain one non-negative value per split")

    known = [float(value) for value in durations.values() if value > 0]
    fallback = statistics.median(known) if known else 1.0
    weights = {test_file: float(durations.get(test_file, fallback)) for test_file in test_files}
    groups: list[list[str]] = [[] for _ in range(splits)]
    totals = [float(total) for total in initial_totals]

    for test_file in sorted(test_files, key=lambda path: (-weights[path], path)):
        shard_index = min(
            range(splits),
            key=lambda index: (totals[index], len(groups[index]), index),
        )
        groups[shard_index].append(test_file)
        totals[shard_index] += weights[test_file]

    for group in groups:
        group.sort()
    return groups, totals


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", type=int, required=True)
    parser.add_argument("--group", type=int, required=True, help="1-based shard index")
    parser.add_argument(
        "--first-shard-overhead",
        type=float,
        default=0.0,
        help="Estimated seconds spent on checks that only shard 1 runs",
    )
    parser.add_argument("--durations-path", type=Path, default=DEFAULT_DURATIONS_PATH)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.splits < 1 or args.group < 1 or args.group > args.splits:
        raise SystemExit("--splits and --group must be positive with group <= splits")
    if args.first_shard_overhead < 0:
        raise SystemExit("--first-shard-overhead must be non-negative")

    test_files = discover_test_files()
    if not test_files:
        raise SystemExit("No tests/test_*.py files found")
    initial_totals = [args.first_shard_overhead, *([0.0] * (args.splits - 1))]
    groups, totals = partition_test_files(
        test_files,
        load_durations(args.durations_path),
        args.splits,
        initial_totals,
    )
    selected = groups[args.group - 1]
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]

    print(
        f"==> pytest shard {args.group}/{args.splits}: {len(selected)} files, "
        f"estimated critical-path load {totals[args.group - 1]:.1f}s",
        flush=True,
    )
    return subprocess.call(
        [sys.executable, "-m", "pytest", *selected, *pytest_args],
        cwd=REPO_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
