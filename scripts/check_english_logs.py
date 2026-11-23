#!/usr/bin/env python3
"""Check that runtime Python logger calls do not contain CJK characters."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable, Iterator, List, Sequence

DEFAULT_TARGETS: tuple[str, ...] = (
    "main.py",
    "server.py",
    "src",
    "data_provider",
    "api",
    "bot",
)

IGNORED_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
    }
)

LOG_METHODS: frozenset[str] = frozenset(
    {
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
        "critical",
        "fatal",
        "log",
    }
)

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3001-\u303f\uff00-\uffef]")


@dataclass(frozen=True)
class LogViolation:
    """Represents a runtime logger call containing CJK text."""

    path: Path
    line: int
    method: str
    snippet: str


def _is_logger_call(node: ast.Call) -> bool:
    """Return True when an AST Call invokes a logger/logging output method."""
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in LOG_METHODS:
        return False
    try:
        caller = ast.unparse(node.func.value).lower()
    except Exception:
        return False
    return "log" in caller


def _iter_log_string_constants(node: ast.AST) -> Iterator[ast.Constant]:
    """Yield string constants while skipping lookup keys in subscripts and ``get`` calls."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            yield node
        return

    if isinstance(node, ast.Subscript):
        yield from _iter_log_string_constants(node.value)
        return

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        yield from _iter_log_string_constants(node.func.value)
        for arg in node.args[1:]:
            yield from _iter_log_string_constants(arg)
        for kw in node.keywords:
            yield from _iter_log_string_constants(kw.value)
        return

    for child in ast.iter_child_nodes(node):
        yield from _iter_log_string_constants(child)


def _log_message_expressions(node: ast.Call) -> Iterator[ast.AST]:
    """Yield only the message expression from a logging call."""
    for keyword in node.keywords:
        if keyword.arg == "msg":
            yield keyword.value
            return

    message_index = 1 if node.func.attr == "log" else 0
    if len(node.args) > message_index:
        yield node.args[message_index]


def find_cjk_logs_in_source(source: str, path: Path) -> List[LogViolation]:
    """Inspect Python source text and return logger calls with CJK string literals."""
    tree = ast.parse(source, filename=str(path))
    violations: List[LogViolation] = []
    seen: set[tuple[int, str]] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_logger_call(node):
            continue

        matched_snippets: List[str] = []
        for expr in _log_message_expressions(node):
            for const in _iter_log_string_constants(expr):
                if isinstance(const.value, str) and CJK_RE.search(const.value):
                    matched_snippets.append(const.value.strip().replace("\n", "\\n"))

        if matched_snippets:
            key = (node.lineno, node.func.attr)
            if key in seen:
                continue
            seen.add(key)
            joined = " | ".join(matched_snippets)
            if len(joined) > 120:
                joined = joined[:117] + "..."
            violations.append(
                LogViolation(
                    path=path,
                    line=node.lineno,
                    method=node.func.attr,
                    snippet=joined,
                )
            )

    violations.sort(key=lambda item: (item.line, item.method))
    return violations


def iter_python_files(targets: Iterable[Path], repo_root: Path) -> List[Path]:
    """Expand files and directories into sorted unique .py paths."""
    files: set[Path] = set()
    for raw_target in targets:
        target = raw_target if raw_target.is_absolute() else (repo_root / raw_target)
        if not target.exists():
            continue
        if target.is_file():
            if target.suffix == ".py":
                files.add(target.resolve())
            continue
        for py_file in target.rglob("*.py"):
            if any(part in IGNORED_DIRS for part in py_file.parts):
                continue
            files.add(py_file.resolve())
    return sorted(files)


def check_paths(paths: Sequence[Path], repo_root: Path) -> List[LogViolation]:
    """Scan all Python files under the given paths for CJK log messages."""
    violations: List[LogViolation] = []
    for py_file in iter_python_files(paths, repo_root):
        source = py_file.read_text(encoding="utf-8")
        violations.extend(find_cjk_logs_in_source(source, py_file))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify runtime logger calls do not contain CJK text."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional files or directories to scan (defaults to backend runtime dirs).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    target_paths = [Path(p) for p in args.paths] if args.paths else [Path(p) for p in DEFAULT_TARGETS]
    violations = check_paths(target_paths, repo_root)

    if not violations:
        print("check_english_logs: OK (0 CJK runtime logger calls)")
        return 0

    for item in violations:
        try:
            rel_path = item.path.resolve().relative_to(repo_root)
        except ValueError:
            rel_path = item.path
        print(f"{rel_path}:{item.line}: logger.{item.method}: {item.snippet}", file=sys.stderr)
    print(
        f"check_english_logs: FAILED ({len(violations)} runtime logger call(s) contain CJK text)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
