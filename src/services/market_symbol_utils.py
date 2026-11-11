# -*- coding: utf-8 -*-
"""Shared market-symbol helpers for suffix-only offshore markets.

Keep this module dependency-light so it can be used by data providers, market
context, trading calendars, stock-index loading, and API input normalization
without introducing import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SuffixMarketSpec:
    """A suffix-only Yahoo Finance market rule."""

    market: str
    suffixes: tuple[str, ...]
    digit_lengths: tuple[int, ...]


_SUFFIX_MARKET_SPECS: tuple[SuffixMarketSpec, ...] = (
    SuffixMarketSpec("jp", ("T",), (4, 5)),
    SuffixMarketSpec("kr", ("KS", "KQ"), (6,)),
    # Taiwan support mirrors the same suffix-only pattern; keep it here so the
    # shared helpers stay complete for all yfinance-only offshore markets.
    SuffixMarketSpec("tw", ("TW", "TWO"), (4, 5, 6)),
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
    if not (base.isdigit() and len(base) in spec.digit_lengths):
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


# Canada (Issue #2420) is a suffix-only market whose ticker base is ALPHABETIC,
# unlike the digit-based JP/KR/TW specs above, so it cannot live in
# ``SuffixMarketSpec``/``_SUFFIX_MARKET_SPECS``:
# - TSX  ``.TO`` (e.g. ``SHOP.TO``): suffix match is case-insensitive, mirroring
#   the ``.T``/``.KS`` precedent (``7203.T``/``7203.t`` both route to jp).
# - TSXV ``.V``  (e.g. ``SHOP.V``): ONLY the uppercase ``.V`` form is treated as
#   TSXV. A lowercase ``.v`` collides with the US single-letter class-share
#   suffix family (``BRK.B`` / ``SHOP.U``), so it must keep the legacy US
#   semantics. ``split_suffix_symbol`` upper-cases its input, which would
#   destroy that distinction — hence the raw-text check below.
_CA_BASE_MAX_LEN = 6


def get_ca_suffix_market(stock_code: str) -> Optional[str]:
    """Return ``"ca"`` for TSX ``.TO`` and uppercase-only TSXV ``.V`` symbols.

    The suffix check is case-sensitive for ``.V`` by design: the raw token must
    literally end with ``.V``. Bases must be purely alphabetic 1-6 letter TSX
    tickers (``SHOP``/``BANK``/``RY``); digit bases (``7203.TO``) are rejected.
    """

    raw = (stock_code or "").strip()
    if "." not in raw:
        return None
    upper = raw.upper()
    base, suffix = upper.rsplit(".", 1)
    if not base or len(base) > _CA_BASE_MAX_LEN or not base.isalpha():
        return None
    if suffix == "TO":
        return "ca"
    if suffix == "V" and raw.endswith(".V"):
        return "ca"
    return None


def is_ca_market_symbol(stock_code: str) -> bool:
    """Return whether a stock code is a supported Canada (TSX/TSXV) symbol."""

    return get_ca_suffix_market(stock_code) == "ca"


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
