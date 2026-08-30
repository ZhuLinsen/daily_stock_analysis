# -*- coding: utf-8 -*-
"""Shared market-symbol helpers for suffix-only offshore markets.

Keep this module dependency-light so it can be used by data providers, market
context, trading calendars, stock-index loading, and API input normalization
without introducing import cycles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# NSE/BSE tickers are alphanumeric (e.g. RELIANCE, M&M, L&TFH), unlike the
# fixed-digit JP/KR/TW codes, so they get a base pattern instead of digit
# lengths.
_INDIA_BASE_PATTERN = re.compile(r"^[A-Z0-9&\-]{1,20}$")


@dataclass(frozen=True)
class SuffixMarketSpec:
    """A suffix-only Yahoo Finance market rule."""

    market: str
    suffixes: tuple[str, ...]
    digit_lengths: tuple[int, ...] = ()
    base_pattern: Optional[re.Pattern[str]] = None

    def base_is_valid(self, base: str) -> bool:
        if self.base_pattern is not None:
            return bool(self.base_pattern.match(base))
        return base.isdigit() and len(base) in self.digit_lengths


_SUFFIX_MARKET_SPECS: tuple[SuffixMarketSpec, ...] = (
    SuffixMarketSpec("jp", ("T",), digit_lengths=(4, 5)),
    SuffixMarketSpec("kr", ("KS", "KQ"), digit_lengths=(6,)),
    # Taiwan support mirrors the same suffix-only pattern; keep it here so the
    # shared helpers stay complete for all yfinance-only offshore markets.
    SuffixMarketSpec("tw", ("TW", "TWO"), digit_lengths=(4, 5, 6)),
    # India: NSE (.NS) / BSE (.BO) via Yahoo Finance, alphanumeric tickers.
    SuffixMarketSpec("in", ("NS", "BO"), base_pattern=_INDIA_BASE_PATTERN),
)

_MARKET_TO_SPEC = {spec.market: spec for spec in _SUFFIX_MARKET_SPECS}
_SUFFIX_TO_SPEC = {
    suffix: spec
    for spec in _SUFFIX_MARKET_SPECS
    for suffix in spec.suffixes
}


def split_suffix_symbol(stock_code: str) -> tuple[str, str] | None:
    """Return ``(base, suffix)`` for dotted symbols, upper-cased and stripped."""

    code = (stock_code or "").strip().upper()
    if "." not in code:
        return None
    base, suffix = code.rsplit(".", 1)
    if not base or not suffix:
        return None
    return base, suffix


def get_suffix_market(stock_code: str) -> Optional[str]:
    """Return jp/kr/tw/in for supported suffix-only Yahoo symbols, else None."""

    parts = split_suffix_symbol(stock_code)
    if parts is None:
        return None
    base, suffix = parts
    spec = _SUFFIX_TO_SPEC.get(suffix)
    if spec is None:
        return None
    if not spec.base_is_valid(base):
        return None
    return spec.market


def is_suffix_market_symbol(stock_code: str, market: Optional[str] = None) -> bool:
    """Return whether a stock code is a supported suffix-only Yahoo symbol."""

    detected = get_suffix_market(stock_code)
    if market is None:
        return detected is not None
    return detected == (market or "").strip().lower()


def is_jp_suffix_symbol(stock_code: str) -> bool:
    return is_suffix_market_symbol(stock_code, "jp")


def is_kr_suffix_symbol(stock_code: str) -> bool:
    return is_suffix_market_symbol(stock_code, "kr")


def is_tw_suffix_symbol(stock_code: str) -> bool:
    return is_suffix_market_symbol(stock_code, "tw")


def is_in_suffix_symbol(stock_code: str) -> bool:
    return is_suffix_market_symbol(stock_code, "in")


def normalize_suffix_market_symbol(stock_code: str) -> Optional[str]:
    """Normalize supported suffix-only symbols to upper-case Yahoo form."""

    parts = split_suffix_symbol(stock_code)
    if parts is None:
        return None
    base, suffix = parts
    if get_suffix_market(f"{base}.{suffix}") is None:
        return None
    return f"{base}.{suffix}"


def suffix_base_lookup_allowed(canonical_code: str) -> bool:
    """Return True when a suffix-market code may be resolved from its bare base.

    JP/KR intentionally allow stock-index-backed bare-code lookup to support the
    existing MVP behavior. TW remains strict suffix-only for now because its
    follow-up index work is not part of this issue.
    """

    return get_suffix_market(canonical_code) in {"jp", "kr"}


def market_suffixes(market: str) -> tuple[str, ...]:
    spec = _MARKET_TO_SPEC.get((market or "").strip().lower())
    return spec.suffixes if spec else ()
