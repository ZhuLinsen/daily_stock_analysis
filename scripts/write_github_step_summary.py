# -*- coding: utf-8 -*-
"""Publish generated Markdown reports to GitHub Actions $GITHUB_STEP_SUMMARY."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from typing import List, Optional, Sequence


_SHANGHAI_TZ = timezone(timedelta(hours=8))
_DEFAULT_MAX_BYTES = 200_000


def _redact_text(text: str) -> str:
    """Best-effort redaction reusing diagnostic secret scrubber."""
    try:
        from src.llm.local_cli_backend import redact_diagnostic_text

        return redact_diagnostic_text(text)
    except Exception:
        return text


def _truncate_utf8_bytes(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="ignore")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    return truncated, True


def _select_report_files(reports_dir: Path, target_date: Optional[str] = None) -> List[Path]:
    if not reports_dir.is_dir():
        return []

    date_token = (target_date or datetime.now(_SHANGHAI_TZ).strftime("%Y%m%d")).strip()
    candidates = [
        p for p in reports_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".md"
        and (p.name.startswith("report_") or p.name.startswith("market_review_"))
    ]
    if not candidates:
        return []

    matching = [p for p in candidates if date_token and date_token in p.name]
    chosen = matching if matching else [max(candidates, key=lambda p: (p.stat().st_mtime, p.name))]

    def _sort_key(path: Path) -> tuple[int, float, str]:
        # Put stock dashboard reports first, then market review, newest first.
        group = 0 if path.name.startswith("report_") else 1
        return (group, -path.stat().st_mtime, path.name)

    return sorted(chosen, key=_sort_key)


def _build_ledger_summary_block(ledger_dir: Optional[Path]) -> str:
    if ledger_dir is None or not ledger_dir.is_dir():
        return ""
    try:
        from src.services.ledger_arena_service import verify_commitments

        status = verify_commitments(ledger_dir=ledger_dir)
    except Exception:
        return ""

    total = int(status.get("total") or 0)
    if total <= 0:
        return ""

    verified = int(status.get("verified") or 0)
    all_valid = bool(status.get("all_valid", False))
    shield = "✅ Verified" if all_valid else "⚠️ Tamper / Mismatch Detected"
    items = status.get("items") or []
    latest_line = ""
    if items:
        top = items[0]
        latest_line = (
            f"| Latest Signed Ledger | `{top.get('date')}` ({top.get('group')}) — "
            f"`{str(top.get('sha256') or '')[:16]}...` ({top.get('record_count', 0)} calls) |"
        )
    lines = [
        "\n\n---\n",
        "### 🏆 Verifiable SHA-256 Track Record",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Commitment Integrity | {shield} ({verified}/{total} files) |",
    ]
    if latest_line:
        lines.append(latest_line)
    return "\n".join(lines)


def build_step_summary_markdown(
    reports_dir: Path,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    target_date: Optional[str] = None,
    ledger_dir: Optional[Path] = None,
) -> str:
    """Build redacted Markdown payload for GitHub Actions Job Summary."""
    files = _select_report_files(reports_dir, target_date=target_date)
    if not files:
        return ""

    sections: List[str] = ["<!-- dsa-step-summary -->"]
    for idx, path in enumerate(files):
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            continue
        if idx > 0:
            sections.append("\n---\n")
        sections.append(_redact_text(raw))

    if len(sections) == 1:
        return ""

    ledger_block = _build_ledger_summary_block(ledger_dir)
    footer = (
        f"{ledger_block}\n\n---\n\n"
        "> Full reports and logs are saved in the workflow artifact (`analysis-reports-*`)."
    )
    body = "\n".join(sections)
    budget = max(1024, int(max_bytes) - len(footer.encode("utf-8")) - 128)
    clipped, was_truncated = _truncate_utf8_bytes(body, budget)
    if was_truncated:
        notice = "\n\n> _(Summary preview truncated to fit Job Summary limit; download `analysis-reports-*` artifact for the complete report.)_"
        return f"{clipped}{notice}{footer}\n"
    return f"{clipped}{footer}\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write DSA report preview to GITHUB_STEP_SUMMARY")
    parser.add_argument("--reports-dir", default="reports", help="Directory containing generated Markdown reports")
    parser.add_argument("--max-bytes", type=int, default=_DEFAULT_MAX_BYTES, help="Maximum UTF-8 bytes to append")
    parser.add_argument("--date", default=None, help="Optional YYYYMMDD date filter")
    parser.add_argument("--ledger-dir", default=None, help="Optional SHA-256 ledger directory for summary badge")
    args = parser.parse_args(argv)

    summary_path_raw = (os.getenv("GITHUB_STEP_SUMMARY") or "").strip()
    if not summary_path_raw:
        return 0

    try:
        markdown = build_step_summary_markdown(
            Path(args.reports_dir),
            max_bytes=args.max_bytes,
            target_date=args.date,
            ledger_dir=Path(args.ledger_dir) if args.ledger_dir else None,
        )
        if not markdown:
            return 0
        summary_path = Path(summary_path_raw)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("a", encoding="utf-8") as fh:
            fh.write(markdown)
    except Exception as exc:  # pragma: no cover - never fail Actions workflow on summary formatting
        print(f"WARN: failed to write GITHUB_STEP_SUMMARY: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
