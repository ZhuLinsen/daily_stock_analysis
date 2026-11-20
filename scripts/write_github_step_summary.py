# -*- coding: utf-8 -*-
"""Publish generated Markdown reports to GitHub Actions $GITHUB_STEP_SUMMARY."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
from typing import List, Optional, Sequence


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_DEFAULT_MAX_BYTES = 200_000


def _redact_text(text: str) -> Optional[str]:
    """Redact the complete report, or fail closed if the scrubber is unavailable."""
    try:
        from src.llm.local_cli_backend import redact_diagnostic_text

        return redact_diagnostic_text(text, limit=sys.maxsize)
    except Exception:
        return None


def _truncate_utf8_bytes(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="ignore")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()
    return truncated, True


def _select_report_files(reports_dir: Path, target_date: Optional[str] = None) -> List[Path]:
    if not reports_dir.is_dir():
        return []

    date_token = (target_date or datetime.now().strftime("%Y%m%d")).strip()
    candidates = [
        p for p in reports_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".md"
        and (p.name.startswith("report_") or p.name.startswith("market_review_"))
    ]
    if not candidates:
        return []

    matching = [p for p in candidates if date_token and date_token in p.name]
    if matching:
        chosen = matching
    else:
        chosen = []
        for prefix in ("report_", "market_review_"):
            prefix_candidates = [p for p in candidates if p.name.startswith(prefix)]
            if prefix_candidates:
                chosen.append(max(prefix_candidates, key=lambda p: (p.stat().st_mtime, p.name)))

    def _sort_key(path: Path) -> tuple[int, float, str]:
        # Put stock dashboard reports first, then market review, newest first.
        group = 0 if path.name.startswith("report_") else 1
        return (group, -path.stat().st_mtime, path.name)

    return sorted(chosen, key=_sort_key)


def build_step_summary_markdown(
    reports_dir: Path,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    target_date: Optional[str] = None,
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
        redacted = _redact_text(raw)
        if redacted is None:
            return ""
        sections.append(redacted)

    if len(sections) == 1:
        return ""

    footer = "\n\n---\n\n> Full reports and logs are saved in the workflow artifact (`analysis-reports-*`)."
    body = "\n".join(sections)
    max_bytes = max(0, int(max_bytes))
    complete = f"{body}{footer}\n"
    if len(complete.encode("utf-8")) <= max_bytes:
        return complete

    notice = "\n\n> _(Summary preview truncated to fit Job Summary limit; download `analysis-reports-*` artifact for the complete report.)_"
    suffix = f"{notice}{footer}\n"
    suffix_bytes = len(suffix.encode("utf-8"))
    if suffix_bytes >= max_bytes:
        return _truncate_utf8_bytes(suffix, max_bytes)[0]
    clipped, _ = _truncate_utf8_bytes(body, max_bytes - suffix_bytes)
    return f"{clipped}{suffix}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write DSA report preview to GITHUB_STEP_SUMMARY")
    parser.add_argument("--reports-dir", default="reports", help="Directory containing generated Markdown reports")
    parser.add_argument("--max-bytes", type=int, default=_DEFAULT_MAX_BYTES, help="Maximum UTF-8 bytes to append")
    parser.add_argument("--date", default=None, help="Optional YYYYMMDD date filter")
    args = parser.parse_args(argv)

    summary_path_raw = (os.getenv("GITHUB_STEP_SUMMARY") or "").strip()
    if not summary_path_raw:
        return 0

    try:
        markdown = build_step_summary_markdown(
            Path(args.reports_dir),
            max_bytes=args.max_bytes,
            target_date=args.date,
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
