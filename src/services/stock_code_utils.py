# -*- coding: utf-8 -*-
"""
Shared stock code utilities.
"""

from __future__ import annotations

import re
from typing import List, Optional

from data_provider.base import canonical_stock_code, is_bse_code, normalize_stock_code
from src.services.market_symbol_utils import normalize_suffix_market_symbol


# Known exchange prefixes (case-insensitive) and the digit lengths they accept.
# e.g. SH600519 -> 600519, HK00700 -> 00700
_PREFIX_DIGIT_LENS: dict = {
    "SH": (6,),
    "SZ": (6,),
    "SS": (6,),
    "BJ": (6,),
    "HK": (1, 2, 3, 4, 5),
}

_SUFFIX_DIGIT_LENS: dict = {
    ".SH": (6,),
    ".SZ": (6,),
    ".SS": (6,),
    ".BJ": (6,),
    ".HK": (1, 2, 3, 4, 5),
    ".T": (4, 5),
    ".KS": (6,),
    ".KQ": (6,),
    # Taiwan: TWSE `.TW` and TPEx `.TWO`; base is 4-6 digits (ETFs up to 6).
    # `.TWO` listed before `.TW` as a defensive ordering convention.
    ".TWO": (4, 5, 6),
    ".TW": (4, 5, 6),
}

_PRESERVE_SUFFIXES = {".T", ".KS", ".KQ", ".TW", ".TWO"}


def _infer_cn_exchange(base: str) -> str:
    """Infer CN exchange from a 6-digit A/B-share code."""
    if not (base.isdigit() and len(base) == 6):
        return ""

    if is_bse_code(base):
        return "BJ"
    if base.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def _valid_exchange_code(exchange: str, base: str, digit_lens: tuple[int, ...]) -> bool:
    if not (base.isdigit() and len(base) in digit_lens):
        return False
    if exchange in {"SH", "SS"}:
        return _infer_cn_exchange(base) == "SH"
    if exchange == "SZ":
        return _infer_cn_exchange(base) == "SZ"
    if exchange == "BJ":
        return _infer_cn_exchange(base) == "BJ"
    return True


def _split_explicit_exchange(
    text: str,
) -> Optional[tuple[str, str, tuple[int, ...]]]:
    """Return one recognized explicit exchange and its unvalidated base."""
    for suffix, digit_lens in _SUFFIX_DIGIT_LENS.items():
        if text.endswith(suffix):
            base = text[: -len(suffix)].strip()
            return suffix.lstrip("."), base, digit_lens

    for prefix, digit_lens in _PREFIX_DIGIT_LENS.items():
        dotted_prefix = f"{prefix}."
        if text.startswith(dotted_prefix):
            base = text[len(dotted_prefix):]
            return prefix, base, digit_lens
        if text.startswith(prefix):
            base = text[len(prefix):]
            # Do not mistake US tickers such as SHOP/HKEX for exchange prefixes.
            if base.isdigit():
                return prefix, base, digit_lens
    return None


def _normalize_explicit_exchange_parts(
    parts: Optional[tuple[str, str, tuple[int, ...]]],
) -> Optional[str]:
    """Return the normalized base from one previously parsed exchange."""
    if parts is None:
        return None
    exchange, base, digit_lens = parts
    if not _valid_exchange_code(exchange, base, digit_lens):
        return None
    return base.zfill(5) if exchange == "HK" else base


def is_code_like(value: str) -> bool:
    """Check if string looks like a stock code (5-6 digits, 1-5 letters, or prefixed code)."""
    text = value.strip().upper()
    if not text:
        return False
    if text.isdigit() and len(text) in (5, 6):
        return True
    explicit_parts = _split_explicit_exchange(text)
    if explicit_parts is not None:
        return _normalize_explicit_exchange_parts(explicit_parts) is not None
    if re.match(r"^[A-Z]{1,5}(?:\.(?:US|[A-Z]))?$", text):
        return True
    return False


def normalize_code(raw: str) -> Optional[str]:
    """Normalize and validate a single stock code.

    Supports:
    - Plain digit codes: 600519, 00700
    - Suffix format: 600519.SH, 600519.SZ, 920493.BJ, 00700.HK
    - Prefix format: SH600519, SH.600519, SZ000001, BJ920493, HK00700 (case-insensitive)
    - US ticker symbols: AAPL, TSLA
    """
    normalized, _ = _normalize_code_and_exchange(raw)
    return normalized


def _normalize_code_and_exchange(raw: str) -> tuple[Optional[str], str]:
    """Normalize once and retain an explicit exchange for candidate expansion."""
    text = raw.strip().upper()
    if not text:
        return None, ""
    if text.isdigit() and len(text) in (5, 6):
        return text, ""
    explicit_parts = _split_explicit_exchange(text)
    explicit_exchange = explicit_parts[0] if explicit_parts is not None else ""
    explicit_code = _normalize_explicit_exchange_parts(explicit_parts)
    if explicit_parts is not None and explicit_code is None:
        return None, explicit_exchange
    suffix_symbol = normalize_suffix_market_symbol(text)
    if suffix_symbol is not None:
        return suffix_symbol, explicit_exchange
    if any(text.endswith(suffix) for suffix in _PRESERVE_SUFFIXES):
        return None, explicit_exchange
    if re.match(r"^[A-Z]{1,5}(?:\.(?:US|[A-Z]))?$", text):
        return text, explicit_exchange
    if explicit_code is not None:
        return explicit_code, explicit_exchange
    return None, explicit_exchange


def _build_hk_market_variants(hk_digits: str) -> List[str]:
    """Build normalized HK variants for padded and legacy code shapes."""
    if not hk_digits.isdigit() or not hk_digits:
        return []

    padded = hk_digits.zfill(5)
    unpadded = padded.lstrip("0") or "0"
    variants = [
        f"HK{padded}",
        f"{padded}.HK",
        padded,
        f"HK{unpadded}",
        f"{unpadded}.HK",
        f"HK.{padded}",
    ]
    if unpadded == padded:
        variants.pop(3)
        variants.pop(3)
    if len(unpadded) <= 3 and unpadded != padded:
        variants.extend([unpadded, f"HK.{unpadded}"])
    return variants


def _build_market_code_variants(
    raw_code: str,
    normalized_code: str,
    explicit_exchange: str,
) -> List[str]:
    """Return additional market-formatted variants for stored-code matching."""
    variants: List[str] = []
    if not raw_code:
        return variants

    raw_code_upper = raw_code.upper()
    normalized_upper = normalized_code.upper() if normalized_code else ""

    def _add_us_variants(code: str) -> None:
        if not code:
            return
        if code.endswith(".US"):
            bare = code[:-3]
            if bare.isalpha() and 1 <= len(bare) <= 5:
                variants.append(bare)
            return
        if "." not in code and code.isalpha() and 1 <= len(code) <= 5:
            variants.append(f"{code}.US")

    _add_us_variants(raw_code_upper)
    if normalized_upper != raw_code_upper:
        _add_us_variants(normalized_upper)

    if normalized_upper.isdigit() and len(normalized_upper) == 6:
        if explicit_exchange in {"SH", "SS"}:
            exchange = "SH"
        elif explicit_exchange == "SZ":
            exchange = "SZ"
        elif explicit_exchange == "BJ" or is_bse_code(normalized_upper):
            exchange = "BJ"
        elif normalized_upper.startswith(("5", "6", "9")):
            exchange = "SH"
        else:
            exchange = "SZ"

        variants.extend(
            [
                f"{exchange}{normalized_upper}",
                f"{normalized_upper}.{exchange}",
                f"{exchange}.{normalized_upper}",
            ]
        )
        if exchange == "SH":
            variants.extend(
                [
                    f"SS{normalized_upper}",
                    f"{normalized_upper}.SS",
                    f"SS.{normalized_upper}",
                ]
            )

    if explicit_exchange == "HK" and normalized_upper.isdigit():
        variants.extend(_build_hk_market_variants(normalized_upper))
    elif normalized_upper.startswith("HK") and normalized_upper[2:].isdigit() and len(normalized_upper[2:]) <= 5:
        variants.extend(_build_hk_market_variants(normalized_upper[2:]))
    if raw_code_upper.isdigit() and len(raw_code_upper) in (4, 5):
        variants.extend(_build_hk_market_variants(raw_code_upper))

    return variants


def build_daily_code_candidates(code: Optional[str]) -> List[str]:
    """Build ordered code variants used to locate locally stored daily bars."""
    raw_code = str(code or "").strip().upper()
    if not raw_code:
        return []
    normalized_code, explicit_exchange = _normalize_code_and_exchange(raw_code)
    if normalized_code is None:
        return []

    candidates = [raw_code]
    for candidate in (normalize_stock_code(raw_code), normalized_code):
        if candidate and candidate != raw_code:
            candidates.append(candidate)
    for candidate in list(candidates):
        candidates.extend(
            _build_market_code_variants(
                raw_code,
                candidate,
                explicit_exchange,
            )
        )
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def resolve_index_stock_code_for_analysis(raw: str) -> str:
    """Resolve bare JP/KR candidates via stock index and keep suffix forms.

    For code-like inputs and indexed 4-digit JP bare bases:
    - Existing index-backed entries (e.g. ``005930`` -> ``005930.KS``) are
      preferred.
    - Non-matching code-like inputs keep the canonicalized input.

    Non-code-like values are still canonicalized only, letting callers keep
    their own validation policy (e.g. API name resolution path).
    """
    text = (raw or "").strip()
    if not text:
        return ""

    if is_code_like(text) or (text.isdigit() and len(text) == 4):
        from src.data.stock_index_loader import resolve_index_stock_code

        resolved = resolve_index_stock_code(text)
        if resolved:
            return canonical_stock_code(resolved)

    return canonical_stock_code(text)
