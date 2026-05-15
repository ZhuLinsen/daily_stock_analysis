#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate and check the notification Actions env table in docs."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.notification_diagnostics import (  # noqa: E402
    KEY_SPECS,
    P0_ACTIONS_ENV_KEYS,
    P3_ROUTE_ENV_KEYS,
    P4_NOISE_ACTIONS_ENV_KEYS,
    P6_CHANNEL_ACTIONS_ENV_KEYS,
)

WORKFLOW_PATH = ROOT_DIR / ".github/workflows/daily_analysis.yml"
DOCS_PATH = ROOT_DIR / "docs/notifications.md"
TABLE_START = "<!-- notification-actions-env-table:start -->"
TABLE_END = "<!-- notification-actions-env-table:end -->"
ANALYZE_STEP_NAME = "执行股票分析"


@dataclass(frozen=True)
class EnvTableRow:
    key: str
    tier: str
    channels: tuple[str, ...]
    source: str
    default: str


def load_daily_analysis_env(workflow_path: Path = WORKFLOW_PATH) -> dict[str, str]:
    """Load the env block from the daily analysis workflow."""

    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    analyze_step = next((step for step in steps if step.get("name") == ANALYZE_STEP_NAME), None)
    available_step_names = [step.get("name", "<unnamed>") for step in steps]
    if analyze_step is None:
        raise ValueError(
            f"Expected daily_analysis.yml job analyze to include a step named "
            f"{ANALYZE_STEP_NAME!r}; available step names: {available_step_names}"
        )
    return analyze_step["env"]


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _key_metadata() -> dict[str, tuple[str, tuple[str, ...]]]:
    grouped: dict[str, dict[str, list[str]]] = {}
    for spec in KEY_SPECS:
        entry = grouped.setdefault(spec.key, {"tiers": [], "channels": []})
        entry["tiers"].append(spec.tier)
        entry["channels"].append(spec.channel)

    metadata: dict[str, tuple[str, tuple[str, ...]]] = {}
    for key, entry in grouped.items():
        tiers = _ordered_unique(entry["tiers"])
        tier = "/".join(tiers)
        channels = _ordered_unique(entry["channels"])
        metadata[key] = (tier, channels)
    return metadata


def _extract_default(expression: str) -> str:
    matches = re.findall(r"\|\|\s*'([^']*)'", expression)
    if not matches:
        return "-"
    return f"`{matches[-1]}`" if matches[-1] else "empty"


def classify_actions_source(expression: str, key: str) -> str:
    """Return a stable source summary without exposing raw expression details."""

    has_vars = f"vars.{key}" in expression
    has_secrets = f"secrets.{key}" in expression
    if has_vars and has_secrets:
        return "Variable or Secret"
    if has_secrets:
        return "Secret"
    if has_vars:
        return "Variable"
    return "Workflow"


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def build_notification_actions_env_rows(env: dict[str, str]) -> list[EnvTableRow]:
    """Build rows for notification keys that are explicitly mapped in Actions."""

    metadata = _key_metadata()
    rows: list[EnvTableRow] = []
    for key in env:
        if key not in metadata:
            continue
        expression = str(env[key])
        tier, channels = metadata[key]
        rows.append(
            EnvTableRow(
                key=key,
                tier=tier,
                channels=channels,
                source=classify_actions_source(expression, key),
                default=_extract_default(expression),
            )
        )
    return rows


def render_markdown_table(rows: Iterable[EnvTableRow]) -> str:
    """Render rows as a compact Markdown table."""

    lines = [
        "| Key | Tier | Channel / feature | Actions source | Default |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        channels = ", ".join(row.channels)
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{_markdown_cell(row.key)}`",
                    _markdown_cell(row.tier),
                    _markdown_cell(channels),
                    _markdown_cell(row.source),
                    _markdown_cell(row.default),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def normalize_markdown_block(content: str) -> str:
    return "\n".join(line.rstrip() for line in content.strip().splitlines())


def extract_managed_block(markdown: str) -> str:
    start = markdown.find(TABLE_START)
    end = markdown.find(TABLE_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"Could not find managed table markers {TABLE_START!r} and {TABLE_END!r}"
        )
    table_start = start + len(TABLE_START)
    return markdown[table_start:end].strip()


def replace_managed_block(markdown: str, table: str) -> str:
    start = markdown.find(TABLE_START)
    end = markdown.find(TABLE_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"Could not find managed table markers {TABLE_START!r} and {TABLE_END!r}"
        )
    before = markdown[: start + len(TABLE_START)]
    after = markdown[end:]
    return f"{before}\n\n{table}\n\n{after.lstrip()}"


def validate_required_mappings(env: dict[str, str]) -> None:
    required = (
        set(P0_ACTIONS_ENV_KEYS)
        | set(P3_ROUTE_ENV_KEYS)
        | set(P4_NOISE_ACTIONS_ENV_KEYS)
        | set(P6_CHANNEL_ACTIONS_ENV_KEYS)
    )
    missing = sorted(required - set(env))
    if missing:
        raise ValueError(
            "daily_analysis.yml is missing required notification env mappings: "
            + ", ".join(missing)
        )


def generate_table() -> str:
    env = load_daily_analysis_env()
    validate_required_mappings(env)
    return render_markdown_table(build_notification_actions_env_rows(env))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Update docs/notifications.md in place")
    parser.add_argument("--check", action="store_true", help="Fail if docs/notifications.md is stale")
    args = parser.parse_args(argv)

    table = generate_table()
    if args.write and args.check:
        parser.error("--write and --check cannot be used together")

    if args.write:
        markdown = DOCS_PATH.read_text(encoding="utf-8")
        DOCS_PATH.write_text(replace_managed_block(markdown, table), encoding="utf-8")
        return 0

    if args.check:
        markdown = DOCS_PATH.read_text(encoding="utf-8")
        current = extract_managed_block(markdown)
        if normalize_markdown_block(current) != normalize_markdown_block(table):
            print(
                "docs/notifications.md notification Actions env table is stale; "
                "run `python scripts/generate_notification_actions_env_table.py --write`.",
                file=sys.stderr,
            )
            return 1
        return 0

    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
