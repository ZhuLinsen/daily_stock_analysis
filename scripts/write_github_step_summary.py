# -*- coding: utf-8 -*-
"""Publish generated Markdown reports to GitHub Actions $GITHUB_STEP_SUMMARY."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import sys
from typing import List, Optional, Sequence


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_DEFAULT_MAX_BYTES = 200_000
_AGGREGATE_REPORT_RE = re.compile(r"^report_\d{8}\.md$")


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
    truncated = encoded[: max(0, max_bytes)].decode("utf-8", errors="ignore").rstrip()
    return truncated, True


def _mtime_name_key(path: Path) -> tuple[float, str]:
    return (path.stat().st_mtime, path.name)


def _select_report_files(reports_dir: Path, target_date: Optional[str] = None) -> List[Path]:
    if not reports_dir.is_dir():
        return []

    date_token = (target_date or datetime.now().strftime("%Y%m%d")).strip()
    candidates = [
        p
        for p in reports_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() == ".md"
        and (p.name.startswith("report_") or p.name.startswith("market_review_"))
    ]
    if not candidates:
        return []

    agg_stock = [p for p in candidates if _AGGREGATE_REPORT_RE.match(p.name)]
    single_stock = [
        p for p in candidates if p.name.startswith("report_") and not _AGGREGATE_REPORT_RE.match(p.name)
    ]
    market_reviews = [p for p in candidates if p.name.startswith("market_review_")]

    agg_match = [p for p in agg_stock if date_token and date_token in p.name]
    single_match = [p for p in single_stock if date_token and date_token in p.name]
    market_match = [p for p in market_reviews if date_token and date_token in p.name]

    chosen_stock: List[Path] = []
    chosen_market: List[Path] = []

    if agg_match:
        chosen_stock = list(agg_match)
    elif single_match:
        chosen_stock = list(single_match)

    if market_match:
        chosen_market = list(market_match)

    # Cross-midnight run pairing: the workflow may deliberately wait longer than two
    # hours between the stock and market phases, so use the latest report from the
    # other category rather than imposing a shorter, unrelated clock window.
    if chosen_market and not chosen_stock:
        if agg_stock:
            latest_agg = max(agg_stock, key=_mtime_name_key)
            chosen_stock = [latest_agg]
        elif single_stock:
            chosen_stock = [max(single_stock, key=_mtime_name_key)]

    if chosen_stock and not chosen_market and market_reviews:
        chosen_market = [max(market_reviews, key=_mtime_name_key)]

    # When neither category matched date_token (e.g. manual run on older artifacts),
    # fall back cleanly to the latest aggregate stock report (or singles if absent) + latest market review.
    if not chosen_stock and not chosen_market:
        if agg_stock:
            chosen_stock = [max(agg_stock, key=_mtime_name_key)]
        elif single_stock:
            chosen_stock = [max(single_stock, key=_mtime_name_key)]
        if market_reviews:
            chosen_market = [max(market_reviews, key=_mtime_name_key)]

    chosen = chosen_stock + chosen_market

    def _sort_key(path: Path) -> tuple[int, float, str]:
        # Put aggregate/stock reports first, then market review, newest first.
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

    stock_sections: List[str] = []
    market_sections: List[str] = []
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            continue
        redacted = _redact_text(raw)
        if redacted is None:
            return ""
        if path.name.startswith("market_review_"):
            market_sections.append(redacted)
        else:
            stock_sections.append(redacted)

    if not stock_sections and not market_sections:
        return ""

    header = "<!-- dsa-step-summary -->\n"
    sep = "\n\n---\n\n"
    footer = "\n\n---\n\n> Full reports and logs are saved in the workflow artifact (`analysis-reports-*`).\n"
    notice = "\n\n> _(Summary preview truncated to fit Job Summary limit; download `analysis-reports-*` artifact for the complete report.)_"
    suffix = f"{notice}{footer}"

    stock_body = sep.join(stock_sections)
    market_body = sep.join(market_sections)
    if stock_body and market_body:
        full_body = f"{stock_body}{sep}{market_body}"
    else:
        full_body = stock_body or market_body

    max_bytes = max(0, int(max_bytes))
    complete = f"{header}{full_body}{footer}"
    if len(complete.encode("utf-8")) <= max_bytes:
        return complete

    overhead_bytes = len(f"{header}{suffix}".encode("utf-8"))
    if overhead_bytes >= max_bytes:
        clipped_all, _ = _truncate_utf8_bytes(f"{header}{suffix}", max_bytes)
        return clipped_all

    body_budget = max_bytes - overhead_bytes
    if stock_body and market_body and body_budget > len(sep.encode("utf-8")) + 64:
        sep_bytes = len(sep.encode("utf-8"))
        usable = body_budget - sep_bytes
        market_bytes = len(market_body.encode("utf-8"))
        reserve_cap = int(usable * 0.4)
        market_alloc = min(market_bytes, max(reserve_cap, 1)) if market_bytes <= reserve_cap else reserve_cap
        stock_alloc = usable - market_alloc
        clipped_stock, _ = _truncate_utf8_bytes(stock_body, stock_alloc)
        clipped_market, _ = _truncate_utf8_bytes(market_body, market_alloc)
        body_out = f"{clipped_stock}{sep}{clipped_market}" if clipped_stock and clipped_market else (clipped_stock or clipped_market)
    else:
        body_out, _ = _truncate_utf8_bytes(full_body, body_budget)

    result = f"{header}{body_out}{suffix}"
    if len(result.encode("utf-8")) > max_bytes:
        result, _ = _truncate_utf8_bytes(result, max_bytes)
    return result


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
