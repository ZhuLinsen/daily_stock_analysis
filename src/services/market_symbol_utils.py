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


@dataclass(frozen=True)
class SuffixMarketSpec:
    """A suffix-only Yahoo Finance market rule.

    Most offshore markets have numeric bases (``digit_lengths``). Markets with
    alphabetic bases (e.g. Canada ``TD.TO`` / ``BAM-A.TO``) instead supply a
    ``base_pattern`` regex; exactly one of the two validators applies.
    """

    market: str
    suffixes: tuple[str, ...]
    digit_lengths: tuple[int, ...] = ()
    base_pattern: Optional[str] = None


_SUFFIX_MARKET_SPECS: tuple[SuffixMarketSpec, ...] = (
    SuffixMarketSpec("jp", ("T",), (4, 5)),
    SuffixMarketSpec("kr", ("KS", "KQ"), (6,)),
    # Taiwan support mirrors the same suffix-only pattern; keep it here so the
    # shared helpers stay complete for all yfinance-only offshore markets.
    SuffixMarketSpec("tw", ("TW", "TWO"), (4, 5, 6)),
    # Canada (TSX ``.TO`` / TSX-V ``.V``) uses an alphabetic base (optionally
    # hyphenated, e.g. ``BAM-A.TO``, ``REI-UN.TO``), so it validates via regex.
    SuffixMarketSpec("ca", ("TO", "V"), base_pattern=r"[A-Z0-9][A-Z0-9\-]{0,11}"),
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
    """Return jp/kr/tw for supported suffix-only Yahoo symbols, else None."""

    parts = split_suffix_symbol(stock_code)
    if parts is None:
        return None
    base, suffix = parts
    spec = _SUFFIX_TO_SPEC.get(suffix)
    if spec is None:
        return None
    if spec.base_pattern is not None:
        if not re.fullmatch(spec.base_pattern, base):
            return None
    elif not (base.isdigit() and len(base) in spec.digit_lengths):
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


def is_us_market_symbol(stock_code: str) -> bool:
    """Return True for a US stock symbol, EXCLUDING suffix-only offshore markets.

    Some offshore suffixes collide with the US single-letter-suffix rule — notably
    Canada `.V` (and hyphenated unit codes like `REI-UN.TO`). Use this — not bare
    ``is_us_stock_code`` —
    at any US-vs-offshore decision point so a Canadian/JP/KR/TW symbol is never
    treated as US (search locale/identity, social-sentiment routing, fetchers...).
    """
    if is_suffix_market_symbol(stock_code):
        return False
    # Lazy import keeps this module dependency-light / cycle-free.
    from data_provider.us_index_mapping import is_us_stock_code

    return is_us_stock_code(stock_code)
