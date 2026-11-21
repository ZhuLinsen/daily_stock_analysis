# -*- coding: utf-8 -*-
"""Publish generated Markdown reports to GitHub Actions $GITHUB_STEP_SUMMARY."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import os
from pathlib import Path
import re
import sys
from typing import List, Optional, Sequence


_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_DEFAULT_MAX_BYTES = 200_000
_CROSS_MIDNIGHT_WINDOW_SECONDS = 2 * 60 * 60
_AGGREGATE_REPORT_RE = re.compile(r"^report_\d{8}\.md$")
_REPORT_DATE_RE = re.compile(r"(?:report|market_review)_(\d{8})(?=[_.])")
_MARKDOWN_FIELD_MARKER = r"[*_`]+"
_MARKDOWN_VALUE_MARKER = r"""[*_`"']+"""
_AUTHORIZATION_FIELD = r"(?:proxy[-_ \t]?)?authorization"
_AUTHORIZATION_SEPARATOR = r"[:=：]"
_HORIZONTAL_SPACE = r"[^\S\r\n]*"
_MARKDOWN_AUTHORIZATION_FIELD_PATTERN = re.compile(
    r"(?<![*_`])(?P<attached>(?<=[A-Za-z0-9_-]))?"
    rf"{_MARKDOWN_FIELD_MARKER}[ \t]*(?P<field>{_AUTHORIZATION_FIELD})"
    rf"(?:{_HORIZONTAL_SPACE}{_MARKDOWN_FIELD_MARKER}{_HORIZONTAL_SPACE}(?P<separator_before>{_AUTHORIZATION_SEPARATOR})"
    rf"|{_HORIZONTAL_SPACE}(?P<separator_inside>{_AUTHORIZATION_SEPARATOR}){_HORIZONTAL_SPACE}{_MARKDOWN_FIELD_MARKER})",
    re.IGNORECASE,
)
_FULLWIDTH_AUTHORIZATION_FIELD_PATTERN = re.compile(
    rf"""(?<![A-Za-z0-9_-])(?P<label>(?P<quote>["'])?{_AUTHORIZATION_FIELD}(?(quote)(?P=quote))){_HORIZONTAL_SPACE}：""",
    re.IGNORECASE,
)
_PADDED_AUTHORIZATION_CODE_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_-])(?P<prefix>{_AUTHORIZATION_FIELD}[ \t]*[:=][ \t]*(?:bearer|basic)[ \t]+)"
    r"[*_]*(?P<backticks>`+)[ \t]+(?P<token>[^`\s]+)[ \t]+(?P=backticks)(?!`)[*_]*",
    re.IGNORECASE,
)
_MARKDOWN_AUTHORIZATION_LABEL = (
    rf"(?:{_MARKDOWN_VALUE_MARKER}[ \t]*)?(?P<field>{_AUTHORIZATION_FIELD})"
    rf"(?:[ \t]*{_AUTHORIZATION_SEPARATOR})?(?:[ \t]*{_MARKDOWN_VALUE_MARKER})?"
    rf"(?:[ \t]*{_AUTHORIZATION_SEPARATOR})?"
)
_MARKDOWN_BREAK = r"<br[ \t]*/?>"
_MARKDOWN_AUTHORIZATION_SCHEME = (
    rf"(?:{_MARKDOWN_VALUE_MARKER}[ \t]*)?(?P<scheme>bearer|basic)(?:[ \t]*{_MARKDOWN_VALUE_MARKER})?"
)
_MARKDOWN_AUTHORIZATION_PREFIX = rf"{_MARKDOWN_AUTHORIZATION_SCHEME}(?=[^\S\r\n]|{_MARKDOWN_BREAK})"
_MARKDOWN_QUOTE_PREFIX = r"[ \t]*(?:>[ \t]*)*"
_MARKDOWN_LINE_BREAK = rf"[ \t]*(?:(?:\\[ \t]*)?\r?\n|{_MARKDOWN_BREAK}(?:[ \t]*\r?\n)?)"
_MARKDOWN_CONTINUATION = rf"{_MARKDOWN_LINE_BREAK}(?:{_MARKDOWN_QUOTE_PREFIX}\r?\n)*{_MARKDOWN_QUOTE_PREFIX}"
_MARKDOWN_SPLIT_AUTHORIZATION_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_*`-]){_MARKDOWN_AUTHORIZATION_LABEL}"
    rf"(?:(?<=[:=])[ \t]*|{_MARKDOWN_CONTINUATION})"
    rf"{_MARKDOWN_AUTHORIZATION_SCHEME}{_MARKDOWN_CONTINUATION}"
    rf"(?:(?P<token_markers>{_MARKDOWN_VALUE_MARKER})[ \t]*)?"
    # A new diagnostic field must retain its label for the shared scrubber.
    rf"(?![\w.-]+(?:[ \t]*{_MARKDOWN_VALUE_MARKER})?[ \t]*[:：]|[\w.-]+[ \t]+=)"
    rf"(?!{_AUTHORIZATION_FIELD}[ \t]*{_AUTHORIZATION_SEPARATOR})"
    r"""[^\s|`"'*<>#]+(?:[ \t]*(?P=token_markers)|[*`"']*)""",
    re.IGNORECASE,
)
_MARKDOWN_MULTILINE_AUTHORIZATION_PATTERN = re.compile(
    rf"(?<![A-Za-z0-9_*`-]){_MARKDOWN_AUTHORIZATION_LABEL}{_MARKDOWN_CONTINUATION}"
    rf"{_MARKDOWN_AUTHORIZATION_PREFIX}[^\r\n]+",
    re.IGNORECASE,
)
# An escaped pipe belongs to the value cell.
_MARKDOWN_TABLE_CELL = r"(?:\\[^\r\n]|[^|\\\r\n]|\\(?![^\r\n]))*"
_MARKDOWN_AUTHORIZATION_HEADER = (
    rf"(?P<link>(?:{_MARKDOWN_FIELD_MARKER})?\[)?(?P<label>{_MARKDOWN_AUTHORIZATION_LABEL})"
    rf"(?(link)(?P<link_tail>\](?:\({_MARKDOWN_TABLE_CELL}\)|\[[^\]|\r\n]*\])?(?:{_MARKDOWN_FIELD_MARKER})?)"
    rf"(?:{_HORIZONTAL_SPACE}{_AUTHORIZATION_SEPARATOR})?)"
)
_MARKDOWN_TABLE_CELL_PATTERN = re.compile(rf"(?:^|(?<=\|)){_MARKDOWN_TABLE_CELL}(?=\||$)")
_MARKDOWN_TABLE_DELIMITER_PATTERN = re.compile(r":?-+:?")
_MARKDOWN_TABLE_END_PATTERN = re.compile(
    r"(?:#{1,6}(?:[ \t]|$)|`{3,}|~{3,}|(?:[*+-]|\d+[.)])[ \t]+|(?:[-*_][ \t]*){3,}$)"
)
_MARKDOWN_QUOTE_PATTERN = re.compile(_MARKDOWN_QUOTE_PREFIX)
_MARKDOWN_AUTHORIZATION_HEADER_PATTERN = re.compile(_MARKDOWN_AUTHORIZATION_HEADER, re.IGNORECASE)
_EMPTY_AUTHORIZATION_VALUES = {"", "-", "—", "n/a", "none", "无"}


def _markdown_table_cells(line: str) -> list[re.Match[str]]:
    cells = list(_MARKDOWN_TABLE_CELL_PATTERN.finditer(line.rstrip("\r\n")))
    if len(cells) < 2:
        return cells
    # Ignore optional outer pipes and keep empty interior cells at their column index.
    start = 0 if cells[0].group().strip() else 1
    end = len(cells) if cells[-1].group().strip() else len(cells) - 1
    return cells[start:end]


def _replace_table_cell(line: str, cell: re.Match[str], replacement: str) -> str:
    value = cell.group()
    start = cell.end() - len(value.lstrip())
    end = cell.start() + len(value.rstrip())
    return f"{line[:start]}{replacement}{line[end:]}"


def _redact_markdown_authorization_tables(text: str) -> str:
    lines = text.splitlines(keepends=True)
    authorization_columns: list[int] = []
    table_quote_depth = 0
    table_delimiter_index = -1
    for index, line in enumerate(lines):
        if index == table_delimiter_index:
            continue
        prefix = _MARKDOWN_QUOTE_PATTERN.match(line).group()
        body = line[len(prefix):]
        quote_depth = prefix.count(">")
        if quote_depth != table_quote_depth or _MARKDOWN_TABLE_END_PATTERN.match(body):
            authorization_columns = []
        if not body.strip():
            authorization_columns = []
            continue

        if authorization_columns:
            # Body rows can omit trailing cells and all pipes in a one-cell row.
            cells = _markdown_table_cells(body)
            for column in authorization_columns:
                if column >= len(cells):
                    continue
                cell = cells[column]
                if cell.group().strip().casefold() not in _EMPTY_AUTHORIZATION_VALUES:
                    body = _replace_table_cell(body, cell, "`<redacted>`")
            lines[index] = prefix + body
            continue

        if "authorization" not in body.lower():
            continue
        delimiter_line = lines[index + 1] if index + 1 < len(lines) else ""
        delimiter_prefix = _MARKDOWN_QUOTE_PATTERN.match(delimiter_line).group()
        delimiter_body = delimiter_line[len(delimiter_prefix):]
        if "|" not in body and "|" not in delimiter_body:
            continue
        cells = _markdown_table_cells(body)
        delimiter_cells = _markdown_table_cells(delimiter_body)
        if quote_depth != delimiter_prefix.count(">") or len(delimiter_cells) != len(cells) or not all(
            _MARKDOWN_TABLE_DELIMITER_PATTERN.fullmatch(cell.group().strip()) for cell in delimiter_cells
        ):
            # Key/value tables store the credential in the cell after the field name.
            replacements: dict[int, str] = {}
            for column, (label_cell, value_cell) in enumerate(zip(cells, cells[1:])):
                header = _MARKDOWN_AUTHORIZATION_HEADER_PATTERN.fullmatch(label_cell.group().strip())
                if header is None:
                    continue
                replacements.setdefault(column, header.group("field"))
                if value_cell.group().strip().casefold() not in _EMPTY_AUTHORIZATION_VALUES:
                    replacements[column + 1] = "`<redacted>`"
            for column in sorted(replacements, reverse=True):
                body = _replace_table_cell(body, cells[column], replacements[column])
            lines[index] = prefix + body
            continue

        table_quote_depth = quote_depth
        table_delimiter_index = index + 1
        # Edit from right to left to keep cell offsets valid. Strip separators from
        # the label so the diagnostic scrubber leaves the rest of the header alone.
        for column in range(len(cells) - 1, -1, -1):
            cell = cells[column]
            header = _MARKDOWN_AUTHORIZATION_HEADER_PATTERN.fullmatch(cell.group().strip())
            if header is None:
                continue
            authorization_columns.append(column)
            label = re.sub(_AUTHORIZATION_SEPARATOR, "", header.group("label"))
            normalized_header = f"{header.group('link') or ''}{label}{header.group('link_tail') or ''}"
            body = _replace_table_cell(body, cell, normalized_header)
        lines[index] = prefix + body

    return "".join(lines)


def _prepare_markdown_authorization(text: str) -> str:
    """Handle Markdown authorization fields before line-based diagnostic redaction."""

    def normalize(match: re.Match[str]) -> str:
        separator = match.group("separator_before") or match.group("separator_inside")
        separator = separator.replace("：", ":")
        # Preserve the field boundary when emphasis immediately follows a word.
        boundary = " " if match.group("attached") is not None else ""
        return f"{boundary}{match.group('field')}{separator}"

    # Mask the value cell before normalizing labels that contain a colon.
    text = _redact_markdown_authorization_tables(text)
    normalized = _MARKDOWN_AUTHORIZATION_FIELD_PATTERN.sub(normalize, text)
    normalized = _FULLWIDTH_AUTHORIZATION_FIELD_PATTERN.sub(r"\g<label>:", normalized)
    # Keep the scheme so the diagnostic scrubber preserves prose after the masked token.
    normalized = _MARKDOWN_SPLIT_AUTHORIZATION_PATTERN.sub(r"\g<field>: \g<scheme> <redacted>", normalized)
    normalized = _MARKDOWN_MULTILINE_AUTHORIZATION_PATTERN.sub(r"\g<field>: <redacted>", normalized)
    return _PADDED_AUTHORIZATION_CODE_PATTERN.sub(r"\g<prefix>\g<token>", normalized)


def _redact_text(text: str) -> Optional[str]:
    """Redact the complete report, or fail closed if the scrubber is unavailable."""
    try:
        from src.llm.local_cli_backend import redact_diagnostic_text

        return redact_diagnostic_text(
            _prepare_markdown_authorization(text),
            limit=sys.maxsize,
        )
    except Exception:
        return None


def _truncate_utf8_bytes(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="ignore")
    if len(encoded) <= max_bytes:
        return text, False
    truncated = encoded[: max(0, max_bytes)].decode("utf-8", errors="ignore").rstrip()
    return truncated, True


def _select_report_files(reports_dir: Path, target_date: Optional[str] = None) -> List[Path]:
    if not reports_dir.is_dir():
        return []

    report_dates: dict[Path, date] = {}
    mtimes: dict[Path, float] = {}
    for path in reports_dir.iterdir():
        if path.suffix.lower() != ".md" or not path.name.startswith(("report_", "market_review_")) or not path.is_file():
            continue
        match = _REPORT_DATE_RE.match(path.name)
        mtime = path.stat().st_mtime
        try:
            report_dates[path] = datetime.strptime(match[1], "%Y%m%d").date() if match else datetime.fromtimestamp(mtime).date()
        except ValueError:
            continue
        mtimes[path] = mtime
    if not report_dates:
        return []

    try:
        report_date = datetime.strptime(target_date.strip(), "%Y%m%d").date() if target_date else datetime.now().date()
    except ValueError:
        return []

    def mtime_name_key(path: Path) -> tuple[float, str]:
        return mtimes[path], path.name

    if report_date not in report_dates.values():
        # Keep older artifacts usable even when no report matches today's local date.
        report_date = report_dates[max(report_dates, key=mtime_name_key)]

    same_day = [path for path, day in report_dates.items() if day == report_date]
    aggregate = [path for path in same_day if _AGGREGATE_REPORT_RE.fullmatch(path.name)]
    stock = aggregate or [path for path in same_day if path.name.startswith("report_")]
    market = [path for path in same_day if path.name.startswith("market_review_")]

    def latest_adjacent_report(candidates: Sequence[Path], anchors: Sequence[Path]) -> Optional[Path]:
        nearby = (
            path for path in candidates
            if any(abs(mtimes[path] - mtimes[anchor]) <= _CROSS_MIDNIGHT_WINDOW_SECONDS for anchor in anchors)
        )
        return max(nearby, key=mtime_name_key, default=None)

    if not aggregate or not market:
        adjacent = [path for path, day in report_dates.items() if abs((day - report_date).days) == 1]
        if market and not aggregate:
            paired = latest_adjacent_report(
                [path for path in adjacent if _AGGREGATE_REPORT_RE.fullmatch(path.name)], market
            )
            if paired is None and not stock:
                paired = latest_adjacent_report([path for path in adjacent if path.name.startswith("report_")], market)
            if paired is not None:
                stock = [paired]
        elif not market:
            paired = latest_adjacent_report([path for path in adjacent if path.name.startswith("market_review_")], stock)
            if paired is not None:
                market = [paired]

    return sorted(stock, key=mtime_name_key, reverse=True) + sorted(market, key=mtime_name_key, reverse=True)


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
    sep_bytes = len(sep.encode("utf-8"))
    if stock_body and market_body and body_budget > sep_bytes + 64:
        usable = body_budget - sep_bytes
        stock_bytes = len(stock_body.encode("utf-8"))
        market_bytes = len(market_body.encode("utf-8"))
        market_alloc = min(market_bytes, max(usable * 2 // 5, usable - stock_bytes))
        stock_alloc = usable - market_alloc
        clipped_stock, _ = _truncate_utf8_bytes(stock_body, stock_alloc)
        clipped_market, _ = _truncate_utf8_bytes(market_body, market_alloc)
        body_out = f"{clipped_stock}{sep}{clipped_market}" if clipped_stock and clipped_market else (clipped_stock or clipped_market)
    else:
        body_out, _ = _truncate_utf8_bytes(market_body or stock_body, body_budget)

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
        with summary_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(markdown)
    except Exception as exc:  # pragma: no cover - never fail Actions workflow on summary formatting
        print(f"WARN: failed to write GITHUB_STEP_SUMMARY: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
