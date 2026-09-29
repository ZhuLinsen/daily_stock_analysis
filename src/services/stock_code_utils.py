# -*- coding: utf-8 -*-
"""
Shared stock code utilities.
"""

from __future__ import annotations

import re
import unicodedata
from importlib import import_module
from dataclasses import dataclass
from typing import List, Optional

from data_provider.base import canonical_stock_code
from src.services.market_symbol_utils import (
    get_suffix_market,
    normalize_suffix_market_symbol,
    suffix_base_lookup_allowed,
)

def _load_optional_provider_attr(module_name: str, attr_name: str):
    """Load optional provider helpers without masking unrelated import failures."""
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name in {module_name, module_name.split(".", 1)[0]}:
            return None
        raise
    return getattr(module, attr_name, None)


_provider_is_bse_code = _load_optional_provider_attr("data_provider.base", "is_bse_code")
_provider_is_us_index_code = _load_optional_provider_attr(
    "data_provider.us_index_mapping",
    "is_us_index_code",
)


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
_US_INDEX_CODES = {
    "SPX",
    "^GSPC",
    "GSPC",
    "DJI",
    "^DJI",
    "DJIA",
    "IXIC",
    "^IXIC",
    "NASDAQ",
    "NDX",
    "^NDX",
    "VIX",
    "^VIX",
    "RUT",
    "^RUT",
}


@dataclass(frozen=True)
class DailyStockIdentity:
    """One parsed identity shared by daily-bar lookup, calendar, and refill."""

    normalized_code: str
    market: str
    refill_code: str
    code_candidates: tuple[str, ...]


def _filter_cross_market_numeric_aliases(
    *,
    raw_code: str,
    market: str,
    candidates: List[str],
) -> tuple[str, ...]:
    """Drop only derived numeric aliases known to collide across markets."""
    from src.core.trading_calendar import get_market_for_stock
    from src.data.stock_index_loader import resolve_index_stock_code_candidates

    filtered: List[str] = []
    for candidate in dict.fromkeys(value for value in candidates if value):
        if candidate == raw_code or not candidate.isdigit():
            filtered.append(candidate)
            continue

        indexed_markets = {
            indexed_market
            for indexed_code in resolve_index_stock_code_candidates(candidate)
            if (indexed_market := get_market_for_stock(indexed_code)) is not None
        }
        if indexed_markets and indexed_markets != {market}:
            continue
        filtered.append(candidate)
    return tuple(filtered)


def _infer_cn_exchange(base: str) -> str:
    """Infer CN exchange from a 6-digit A/B-share code."""
    if not (base.isdigit() and len(base) == 6):
        return ""

    if _is_bse_code(base):
        return "BJ"
    if base.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def _is_bse_code(code: str) -> bool:
    """Use provider logic when available; keep a local equivalent for lightweight tests."""
    if _provider_is_bse_code is not None:
        return _provider_is_bse_code(code)

    normalized = (code or "").strip().split(".")[0]
    if len(normalized) != 6 or not normalized.isdigit():
        return False
    if normalized.startswith("900"):
        return False
    return normalized.startswith(("92", "43", "81", "82", "83", "87", "88"))


def _is_us_index_code(code: str) -> bool:
    if _provider_is_us_index_code is not None:
        return _provider_is_us_index_code(code)
    return (code or "").strip().upper() in _US_INDEX_CODES


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
    if len(unpadded) <= 4 and unpadded != padded:
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
        elif explicit_exchange == "BJ" or _is_bse_code(normalized_upper):
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


def resolve_daily_stock_identity(
    code: Optional[str],
    *,
    market_hint: Optional[str] = None,
) -> Optional[DailyStockIdentity]:
    """Parse one stock identity for every local daily-bar consumer.

    Persisted market metadata and the stock index may disambiguate legacy bare
    JP/KR codes before numeric CN/HK defaults are applied.
    """
    raw_code = str(code or "").strip().upper()
    if not raw_code:
        return None

    identity_code = raw_code
    trusted_market = str(market_hint or "").strip().lower()
    if trusted_market == "hk" and raw_code.isdigit() and 1 <= len(raw_code) <= 3:
        identity_code = raw_code.zfill(5)
    elif raw_code.isdigit() and len(raw_code) in {4, 5, 6}:
        from src.data.stock_index_loader import resolve_index_stock_code_candidates

        indexed_candidates = resolve_index_stock_code_candidates(raw_code)
        indexed_identities = [
            (candidate, get_suffix_market(candidate))
            for candidate in indexed_candidates
        ]
        indexed_offshore = [
            (candidate, market)
            for candidate, market in indexed_identities
            if market in {"jp", "kr", "tw"}
        ]
        if trusted_market in {"jp", "kr", "tw"}:
            matching_candidates = [
                candidate
                for candidate, market in indexed_offshore
                if market == trusted_market
            ]
            if len(matching_candidates) == 1:
                identity_code = matching_candidates[0]
            elif trusted_market == "tw" and len(raw_code) in {4, 5, 6}:
                return DailyStockIdentity(
                    normalized_code=raw_code,
                    market="tw",
                    refill_code="",
                    code_candidates=(raw_code,),
                )
            elif indexed_candidates:
                return None
            elif trusted_market == "jp" and len(raw_code) in {4, 5}:
                identity_code = f"{raw_code}.T"
            elif trusted_market == "kr" and len(raw_code) == 6:
                return DailyStockIdentity(
                    normalized_code=raw_code,
                    market="kr",
                    refill_code="",
                    code_candidates=(raw_code,),
                )
            else:
                return None
        elif trusted_market == "cn":
            if len(raw_code) == 6:
                pass
            elif len(indexed_candidates) == 1 and len(indexed_offshore) == 1:
                identity_code = indexed_offshore[0][0]
            else:
                return None
        elif trusted_market == "hk":
            if len(raw_code) not in {4, 5}:
                return None
        elif trusted_market:
            return None
        elif len(indexed_candidates) > 1:
            return None
        elif len(indexed_offshore) == 1:
            identity_code = indexed_offshore[0][0]

    if _is_us_index_code(identity_code):
        normalized_code, explicit_exchange = identity_code, ""
    elif identity_code.isdigit() and len(identity_code) == 4:
        normalized_code, explicit_exchange = identity_code.zfill(5), "HK"
    else:
        normalized_code, explicit_exchange = _normalize_code_and_exchange(identity_code)
    if normalized_code is None:
        return None

    suffix_market = get_suffix_market(normalized_code)
    if explicit_exchange in {"SH", "SS", "SZ", "BJ"}:
        market = "cn"
    elif explicit_exchange == "HK":
        market = "hk"
    elif suffix_market:
        market = suffix_market
    elif _is_us_index_code(normalized_code):
        market = "us"
    elif re.fullmatch(r"[A-Z]{1,5}(?:\.(?:US|[A-Z]))?", normalized_code):
        market = "us"
    elif normalized_code.isdigit() and len(normalized_code) == 6:
        market = "cn"
    elif normalized_code.isdigit() and len(normalized_code) == 5:
        market = "hk"
    else:
        return None

    if market == "hk":
        normalized_code = normalized_code.zfill(5)
        refill_code = f"HK{normalized_code}"
    elif market == "us":
        normalized_code = normalized_code.removesuffix(".US")
        refill_code = normalized_code
    else:
        refill_code = normalized_code

    if market == "hk":
        candidates = [raw_code]
        candidates.extend(_build_hk_market_variants(normalized_code))
    else:
        candidates = [raw_code, normalized_code, refill_code]
        if suffix_base_lookup_allowed(normalized_code):
            candidates.append(normalized_code.rsplit(".", 1)[0])
    if market not in {"jp", "kr", "tw"}:
        for candidate in list(candidates):
            candidates.extend(
                _build_market_code_variants(
                    raw_code,
                    candidate,
                    explicit_exchange,
                )
            )
    unique_candidates = _filter_cross_market_numeric_aliases(
        raw_code=raw_code,
        market=market,
        candidates=candidates,
    )
    return DailyStockIdentity(
        normalized_code=normalized_code,
        market=market,
        refill_code=refill_code,
        code_candidates=unique_candidates,
    )


def build_daily_code_candidates(code: Optional[str]) -> List[str]:
    """Build ordered code variants used to locate locally stored daily bars."""
    identity = resolve_daily_stock_identity(code)
    return list(identity.code_candidates) if identity is not None else []


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

    # PR #2267 review remediation: converge registered CSI aliases
    # (``csi930955`` / ``930955.CSI`` / ``CSI930955``) to the parser canonical so
    # the resolver, task dedupe key and history candidates do not split the
    # same index into distinct keys. The parser canonical is returned verbatim
    # (lowercase ``csi{code}``) rather than re-uppercased by
    # ``canonical_stock_code`` below.
    normalized_csi = unicodedata.normalize("NFKC", text).strip().casefold()
    if re.fullmatch(r"csi\d{6}", normalized_csi) or re.fullmatch(r"\d{6}\.csi", normalized_csi):
        converged = _converge_registered_csi_identity(text)
        # Return the parser canonical verbatim (lowercase ``csi{code}``) for
        # every registered CSI form, including the already-canonical input.
        if converged is not None:
            return converged

    if is_code_like(text) or (text.isdigit() and len(text) == 4):
        from src.data.stock_index_loader import resolve_index_stock_code

        resolved = resolve_index_stock_code(text)
        if resolved:
            return canonical_stock_code(resolved)

    return canonical_stock_code(text)


def _converge_registered_csi_identity(raw: str) -> Optional[str]:
    """Converge a registered CSI explicit identity to its parser canonical.

    PR #2267 review remediation: the resolver, task dedupe key and history
    candidate builders must treat ``csi930955`` / ``930955.CSI`` /
    ``CSI930955`` as the same registered CSI
    index identity, so they do not split into distinct task keys or history
    candidates. Returns the parser canonical (lowercase ``csi{code}``) when the
    input is a registered CSI explicit identity, or ``None`` when it is not
    (so callers keep their existing degradation semantics for unregistered
    ``csi930956`` / ``930956.CSI``).
    """
    text = (raw or "").strip()
    if not text:
        return None

    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    is_csi_form = bool(
        re.fullmatch(r"csi\d{6}", normalized)
        or re.fullmatch(r"\d{6}\.csi", normalized)
    )
    if not is_csi_form:
        return None

    from src.services.stock_list_parser import parse_analysis_target

    target = parse_analysis_target(text)
    if target.asset_type == "index" and target.canonical_id:
        return target.canonical_id
    return None
