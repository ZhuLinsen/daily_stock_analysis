# -*- coding: utf-8 -*-
"""Phone-friendly number formatting and two-column "card" tables for reports.

Wide 8-10 column Markdown tables are unreadable on phones and in push apps.
Cards render each section as a narrow ``label | value`` table, skip empty
values, and format numbers with the instrument's currency symbol, thousands
separators and compact K/M/B units (Chinese reports keep 万/亿 units).
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, List, Optional, Tuple

EMPTY = None  # marker for "no value"; such rows are dropped from cards

_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "HKD": "HK$",
    "CNY": "¥",
    "RMB": "¥",
    "CNH": "¥",
    "JPY": "¥",
    "KRW": "₩",
    "TWD": "NT$",
    "CHF": "CHF ",
}

_EMPTY_STRINGS = {"", "n/a", "na", "none", "null", "-", "--", "nan", "未知"}


def to_number(value: Any) -> Optional[float]:
    """Parse ints/floats/numeric strings (``"1,234.5"``, ``"2.5%"``); None when not numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "").rstrip("%")
        if text.lower() in _EMPTY_STRINGS:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def currency_symbol(currency: Optional[str]) -> str:
    code = (currency or "").strip().upper()
    if not code:
        return ""
    return _CURRENCY_SYMBOLS.get(code, f"{code} ")


def _compact(number: float, lang: str) -> str:
    """1234567 -> '1.23M' (or '123.46万' for Chinese)."""
    magnitude = abs(number)
    if lang == "zh":
        if magnitude >= 1e8:
            return f"{number / 1e8:,.2f}亿"
        if magnitude >= 1e4:
            return f"{number / 1e4:,.2f}万"
        return f"{number:,.0f}"
    for divisor, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if magnitude >= divisor:
            return f"{number / divisor:,.2f}{unit}"
    return f"{number:,.0f}"


def fmt_price(value: Any, currency: Optional[str] = None) -> Optional[str]:
    number = to_number(value)
    if number is None:
        return EMPTY
    decimals = 4 if 0 < abs(number) < 0.1 else 2
    sign = "-" if number < 0 else ""
    return f"{sign}{currency_symbol(currency)}{abs(number):,.{decimals}f}"


def fmt_money(value: Any, currency: Optional[str] = None, lang: str = "en") -> Optional[str]:
    """Large amounts (revenue, turnover): '$92.28B' / '€16.10B' / '922.79亿 USD'."""
    number = to_number(value)
    if number is None:
        return EMPTY
    if lang == "zh":
        code = (currency or "").upper()
        return f"{_compact(number, 'zh')}{' ' + code if code and code not in ('CNY', 'RMB') else '元'}"
    sign = "-" if number < 0 else ""
    return f"{sign}{currency_symbol(currency)}{_compact(abs(number), lang)}"


def fmt_shares(value: Any, lang: str = "en", unit_label: str = "shares") -> Optional[str]:
    number = to_number(value)
    if number is None or number <= 0:
        return EMPTY
    if lang == "zh":
        return f"{_compact(number, 'zh')}股"
    return f"{_compact(number, lang)} {unit_label}".strip()


def fmt_pct(value: Any, *, signed: bool = False) -> Optional[str]:
    number = to_number(value)
    if number is None:
        return EMPTY
    return f"{number:+.2f}%" if signed else f"{number:.2f}%"


def fmt_change(value: Any) -> Optional[str]:
    """Daily change with an arrow: '▲ +2.55%' / '▼ -1.20%' / '0.00%'."""
    number = to_number(value)
    if number is None:
        return EMPTY
    if number > 0:
        return f"▲ +{number:.2f}%"
    if number < 0:
        return f"▼ {number:.2f}%"
    return "0.00%"


def join_values(*parts: Optional[str], sep: str = " ") -> Optional[str]:
    kept = [p for p in parts if p]
    return sep.join(kept) if kept else EMPTY


def card(title: str, rows: Iterable[Tuple[str, Optional[str]]]) -> List[str]:
    """Render a two-column card; returns [] when every value is empty."""
    kept = [(label, value) for label, value in rows if value not in (None, "") and str(value).strip().upper() != "N/A"]
    if not kept:
        return []
    lines = [title, "", "| | |", "|:--|--:|"]
    for label, value in kept:
        safe_value = str(value).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {label} | {safe_value} |")
    lines.append("")
    return lines


def shorten(text: Any, limit: int) -> str:
    """Trim to ``limit`` chars on a word boundary with an ellipsis (no mid-word cuts)."""
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    cut = value[:limit]
    space = cut.rfind(" ")
    if space >= limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-—") + "…"


_LEVEL_PREFIX_RE = re.compile(r"^\s*[^\d:：]{1,30}[:：]\s*")
_LEVEL_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def split_level(value: Any) -> Tuple[Optional[float], str]:
    """Split an LLM price level like 'Ideal buy point: 542.54 (near MA5 support)'.

    Returns ``(542.54, 'near MA5 support')``; ``(None, original)`` when no number.
    """
    text = str(value or "").strip()
    if not text or text.upper() == "N/A":
        return None, ""
    text = _LEVEL_PREFIX_RE.sub("", text, count=1)
    match = _LEVEL_NUMBER_RE.search(text)
    if not match:
        return None, text
    number = to_number(match.group(0))
    note = (text[: match.start()] + text[match.end():]).strip()
    note = note.strip(" ()（）-—,;:").strip()
    return number, note


def fmt_level(value: Any, currency: Optional[str] = None, reference: Optional[float] = None) -> Optional[str]:
    """'**€11.05** · near MA5 support (+8.0%)' from a raw LLM level string."""
    number, note = split_level(value)
    if number is None:
        return shorten(note, 70) or EMPTY
    parts: List[str] = [f"**{fmt_price(number, currency)}**"]
    if reference:
        parts.append(f"({(number / reference - 1) * 100:+.1f}%)")
    if note:
        parts.append(f"· {shorten(note, 50)}")
    return " ".join(parts)
