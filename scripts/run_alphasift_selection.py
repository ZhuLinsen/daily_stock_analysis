#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run AlphaSift multi-strategy screening and emit selected stock codes.

This script is intentionally small and CLI-oriented because GitHub Actions needs
to turn AlphaSift picks into ``STOCK_LIST`` before invoking ``main.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


DEFAULT_STRATEGIES = (
    "dual_low",
    "balanced_alpha",
    "momentum_quality",
    "quality_value",
    "oversold_reversal",
)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _build_command(base_command: str, strategy: str, market: str, max_output: int) -> list[str]:
    command = shlex.split(base_command, posix=os.name != "nt") if base_command.strip() else []
    if not command:
        executable = shutil.which("alphasift")
        command = [executable] if executable else [sys.executable, "-m", "alphasift"]

    return [
        *command,
        "screen",
        strategy,
        "--market",
        market,
        "--no-llm",
        "--no-post-analysis",
        "--max-output",
        str(max_output),
        "--json",
    ]


def _candidate_items(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        for key in ("picks", "candidates", "items", "results", "stocks"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []
    if isinstance(payload, list):
        return payload
    return []


def _extract_codes(payload: Any) -> list[str]:
    codes: list[str] = []
    for item in _candidate_items(payload):
        if isinstance(item, dict):
            code = item.get("code") or item.get("symbol") or item.get("stock_code")
        else:
            code = item
        text = str(code or "").strip()
        if text:
            codes.append(text)
    return codes


def _dedupe_limit(groups: Iterable[Iterable[str]], limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for code in group:
            normalized = code.strip()
            if normalized and normalized not in seen:
                selected.append(normalized)
                seen.add(normalized)
                if len(selected) >= limit:
                    return selected
    return selected


def _run_strategy(args: argparse.Namespace, strategy: str) -> list[str]:
    command = _build_command(args.command, strategy, args.market, args.per_strategy)
    print(f"   跑策略: {strategy} (Top {args.per_strategy})", flush=True)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"   ⚠️ {strategy}: 超时 {args.timeout}s，跳过", flush=True)
        return []
    except FileNotFoundError as exc:
        print(f"   ⚠️ {strategy}: AlphaSift 命令不可用：{exc}", flush=True)
        return []

    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = stderr.splitlines()[-1] if stderr else f"exit={completed.returncode}"
        print(f"   ⚠️ {strategy}: 运行失败：{detail}", flush=True)
        return []

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        preview = (completed.stdout or "").strip().replace("\n", " ")[:160]
        print(f"   ⚠️ {strategy}: JSON 解析失败：{exc}; stdout={preview!r}", flush=True)
        return []

    codes = _extract_codes(payload)[: args.per_strategy]
    if codes:
        print(f"   ✅ {strategy}: {','.join(codes)}", flush=True)
    else:
        warnings = payload.get("warnings") if isinstance(payload, dict) else None
        suffix = f"；warnings={warnings}" if warnings else ""
        print(f"   ⚠️ {strategy}: 无候选{suffix}", flush=True)
    return codes


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AlphaSift 多策略选股，输出去重后的股票代码。")
    parser.add_argument(
        "--strategies",
        default=os.getenv("ALPHASIFT_STRATEGIES", ",".join(DEFAULT_STRATEGIES)),
        help="逗号分隔的策略 ID 列表，默认读取 ALPHASIFT_STRATEGIES。",
    )
    parser.add_argument("--market", default=os.getenv("ALPHASIFT_MARKET", "cn"))
    parser.add_argument("--per-strategy", type=int, default=int(os.getenv("ALPHASIFT_PER_STRATEGY", "3")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("ALPHASIFT_SELECTION_LIMIT", "10")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("ALPHASIFT_STRATEGY_TIMEOUT_SECONDS", "120")))
    parser.add_argument("--command", default=os.getenv("ALPHASIFT_COMMAND", ""))
    parser.add_argument("--output-file", default=os.getenv("ALPHASIFT_OUTPUT_FILE", ""))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    strategies = _split_csv(args.strategies)
    print("🔍 开始 AlphaSift 多策略选股...", flush=True)
    if not strategies:
        print("⚠️ 未配置 AlphaSift 策略，跳过选股", flush=True)
        selected: list[str] = []
    else:
        selected = _dedupe_limit((_run_strategy(args, strategy) for strategy in strategies), args.limit)

    selected_text = ",".join(selected)
    if args.output_file:
        output_path = Path(args.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(selected_text, encoding="utf-8")

    if selected_text:
        print(f"✅ 多策略选股完成（去重后 Top {args.limit}）: {selected_text}", flush=True)
    else:
        print("⚠️ AlphaSift 未产生可用候选，将继续使用原 STOCK_LIST", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
