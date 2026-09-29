# -*- coding: utf-8 -*-
"""Helpers for parsing the user-facing STOCK_LIST value.

Phase 1 (issue #2063): structured analysis-target parsing.

This module exposes :func:`parse_analysis_target`, which converts a single
user-facing stock-list token (``"sh000300"``, ``"000300"``, ``"600519"``,
``"hk00700"``, ``"AAPL"`` …) into a structured :class:`AnalysisTarget` with a
stable ``asset_type`` / ``canonical_id`` / ``display_code`` / ``exchange``
contract. The legacy :func:`split_stock_list` and :func:`serialize_stock_list`
helpers are kept untouched so existing ``STOCK_LIST`` callers don't drift.

Three core contracts are pinned by this module and the regression tests in
``tests/test_stock_list_parser.py``:

1. **前缀白名单指数** — a prefixed token whose prefix is ``sh``/``sz`` and
   whose bare code is registered in :class:`IndexRegistry` is parsed as an
   ``index``.
2. **裸码默认个股** — a bare numeric code without any prefix always parses
   as a ``stock`` regardless of whether the same code happens to belong to
   a known index (e.g. ``"000300"`` is a stock, ``"sh000300"`` is an index).
3. **前缀未命中降级为股票** — a prefixed token whose prefix is not a
   recognized ``sh``/``sz`` index prefix, or whose bare code is not in the
   index registry, degrades to a ``stock`` rather than raising.

The module deliberately does **not** touch ``normalize_stock_code()``,
``BaseFetcher`` signatures, database migrations, or web/bot integration —
those wait for later phases of issue #2063.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

__all__ = [
    "AnalysisTarget",
    "IndexRegistry",
    "IndexEntry",
    "ParseStatus",
    "parse_analysis_target",
    "serialize_stock_list",
    "split_stock_list",
    "default_index_registry",
]


_STOCK_LIST_SEPARATOR_RE = re.compile(r"[\s,;\uFF0C\u3001\uFF1B]+")
_EXPLICIT_INDEX_ALIAS_RE = re.compile(
    r"^(?:(?:sh|sz|csi)\d{6}|\d{6}\.(?:sh|sz|csi))$"
)
# An unregistered numeric CSI form must surface as ``unsupported`` rather than
# degrade into a US ticker. Registered six-digit forms resolve before this
# guard; malformed lengths are rejected here without blocking tickers such as
# ``CSIQ``.
_EXPLICIT_CSI_FORM_RE = re.compile(r"^(?:csi\d+|\d+\.csi)$")


def _normalize_index_key(value: str) -> str:
    """Normalize an identity key to one resolver identity form.

    ``sh``/``sz`` prefix and ``{code}.SH`` / ``{code}.SZ`` suffix are
    interchangeable exchange identities, so they collapse to the canonical
    lowercase-prefixed key (``sh000300`` == ``000300.SH``).

    CSI is deliberately **not** collapsed: ``csi{code}`` (prefix) and
    ``{code}.CSI`` (suffix) are kept distinct. The ``csi`` prefix is a canonical
    identity that only resolves when a manifest row owns that exact ``csi{code}``
    key, while a ``{code}.CSI`` suffix is an *explicit alias* that belongs to the
    entry that registered it (e.g. ``000300.CSI`` is an alias of ``sh000300``).
    Keeping them separate prevents ``csi000300`` (unregistered) from being
    conflated with the registered ``000300.CSI`` alias of ``sh000300``.
    """
    normalized = unicodedata.normalize(
        "NFKC", str(value or "")
    ).strip().casefold()
    prefix_match = re.fullmatch(r"(sh|sz)(\d{6})", normalized)
    if prefix_match:
        return f"{prefix_match.group(1)}{prefix_match.group(2)}"
    suffix_match = re.fullmatch(r"(\d{6})\.(sh|sz)", normalized)
    if suffix_match:
        return f"{suffix_match.group(2)}{suffix_match.group(1)}"
    return normalized


def _normalize_display_name(value: str) -> str:
    """Normalize a display name for exact name lookup only.

    Exactly NFKC + trim + casefold. Deliberately **not** the identity
    normalization of :func:`_normalize_index_key`, which rewrites exchange
    variants (``000016.SH`` collapses to ``sh000016``): code-shaped display
    names that are distinct under exact text equality must stay distinct here,
    otherwise a name lookup would falsely report them as one key or as
    ambiguous. Display-name equality is exact-text equality after this
    normalization — no fuzzy search.
    """
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


# ---------------------------------------------------------------------------
# Legacy helpers (unchanged).
# ---------------------------------------------------------------------------
def split_stock_list(value: str) -> List[str]:
    """Split STOCK_LIST values on common copy/paste separators."""
    return [
        item.strip()
        for item in _STOCK_LIST_SEPARATOR_RE.split(value or "")
        if item.strip()
    ]


def serialize_stock_list(value: str) -> str:
    """Return STOCK_LIST in the canonical comma-separated storage form."""
    return ",".join(split_stock_list(value))


# ---------------------------------------------------------------------------
# Phase 1: structured analysis-target parsing.
# ---------------------------------------------------------------------------
# Status enum encoded as plain strings (no stdlib enum dependency) so they
# serialize cleanly to JSON in API responses later on. Keep the three values
# stable; downstream phases will branch on these.
class ParseStatus:
    STOCK = "stock"
    INDEX = "index"
    UNSUPPORTED = "unsupported"


# Recognised exchange prefixes. ``sh``/``sz`` are the only prefixes that can
# elevate a bare code to ``asset_type=index`` (contract #1). Other prefixes
# (``hk``, ``us``, ``bj`` …) are advisory only and don't change asset_type on
# their own — they degrade to ``stock`` if the registry doesn't claim the
# code (contract #3).
_EXCHANGE_PREFIX_TO_CODE = {
    "sh": "SH",
    "sz": "SZ",
    "bj": "BJ",
    "hk": "HK",
    "us": "US",
}
# Map uppercase exchange codes (the canonical form returned by
# ``stock_code_utils._normalize_code_and_exchange``) to their lowercase
# prefix form. ``parse_analysis_target`` uses this to rewrite normalized
# inputs into a single canonical token (``sh600519``/``hk00700``) before
# calling ``_split_prefix`` so the legacy prefix-handling branch below
# stays the source of truth for the prefix → contract flow.
_EXCHANGE_NORMALIZER = {
    "SH": "sh",
    "SZ": "sz",
    "SS": "sh",   # Shanghai alias — same lowercase prefix as ``SH``
    "BJ": "bj",
    "HK": "hk",
}
# Longest known prefix is 2 chars; let the splitter recognise only the known
# set so alphanumeric US tickers (``AAPL``, ``TSLA``) don't get mistaken for
# prefixed tokens. Order matters when scanning: 2-char prefixes first.
# The ``us`` prefix is intentionally excluded here: ``_split_prefix`` only
# short-circuits bare 1-5 letter US tickers (``AAPL``/``BRK``/``SHOP``) when
# the token is purely alphabetic and all-uppercase; ``usAAPL`` is mixed case
# and still flows through the prefix splitter (contract #3: explicitly
# prefixed codes degrade to stock). Pure ``us``-prefixed codes like ``usAAPL``
# are handled via ``_normalize_code_and_exchange`` in
# ``parse_analysis_target`` — they reach ``_split_prefix`` as ``usAAPL``,
# which starts with ``us`` so the splitter correctly splits them to
# ``(us, AAPL)``. Excluding ``us`` from _KNOWN_PREFIXES_SORTED would cause
# ``_split_prefix`` to treat ``usAAPL`` as a bare US ticker (because it's
# mixed-case but the short-circuit only fires for pure-alpha uppercase
# tokens — so it still flows through and gets correctly split).
# However, keeping ``us`` in the known set makes the intent explicit and
# prevents future regressions if ``_split_prefix`` is ever called directly
# with ``usAAPL`` after normalisation strips the case.
_KNOWN_PREFIXES_SORTED = tuple(
    sorted(_EXCHANGE_PREFIX_TO_CODE.keys(), key=lambda p: -len(p))
)

# Canonical US ticker shape: 1-5 uppercase letters optionally followed by
# a single dot + 1-2 uppercase letters (covers ``AAPL`` / ``BRK.B`` /
# ``SHOP.US`` / ``HKD`` / ``USFD`` etc.). This mirrors the regex used by
# ``data_provider/us_index_mapping.py:16-17`` and
# ``stock_code_utils._normalize_code_and_exchange`` for the US branch.
# Used by ``parse_analysis_target`` to enforce the Phase 1 contract that
# ``us``-prefixed tokens must use a valid uppercase US ticker base — see
# the guard in ``parse_analysis_target`` for the full rationale.
_US_TICKER_SHAPE_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")


def _split_prefix(token: str) -> Tuple[Optional[str], str]:
    """Split ``token`` into ``(prefix, bare_code)`` when the leader matches
    one of the known exchange prefixes (``sh``/``sz``/``bj``/``hk``/``us``).

    Tokens whose alphabetic leader isn't in the known set — most importantly
    US tickers like ``AAPL`` or ``TSLA`` — return ``(None, token)`` so the
    bare-code path can classify them. Tokens with no alphabetic leader (e.g.
    ``"600519"``) also return ``(None, token)``.

    Guard against US ticker prefix collisions (review blocker
    ``OR-COR-d24a4e9a``): a token like ``SHOP`` / ``HKD`` / ``BJRI`` / ``USM``
    / ``SHAK`` / ``USFD`` is a legitimate 1-5 letter US ticker (the same
    shape ``src/services/stock_code_utils.is_code_like`` already treats as a
    bare US code via ``^[A-Z]{1,5}$``). It must NOT be split into
    ``(sh, OP)`` / ``(hk, D)`` / ``(bj, RI)`` / ``(us, M)`` / ``(sh, AK)`` /
    ``(us, FD)``. We therefore short-circuit when the whole token is 1-5
    ASCII uppercase letters — preserving it as a bare US ticker so
    :func:`_classify_bare_code` routes it through the US branch.

    The ``isupper()`` predicate is the key disambiguator: uppercase-only
    tokens are stock symbols (``USFD``, ``SHAK``, ``AAPL``), never the
    canonical lowercase exchange prefixes used elsewhere in the codebase
    (``sh000300``, ``sz399001``, ``usAAPL``). Mixing case — e.g. ``usAAPL``
    — bypasses the short-circuit and still runs through the prefix splitter
    so contract #3's "prefix supplied → degrade to stock" semantics remain
    intact for explicitly-prefixed codes.
    """
    if not token:
        return None, ""
    # Short-circuit bare US tickers before scanning _KNOWN_PREFIXES so prefix
    # collisions don't get mis-split. Two shape families are recognised:
    #
    #   1. 1-5 ASCII uppercase letters (``USFD`` / ``SHAK`` / ``AAPL``):
    #      ``_US_TICKER_SHAPE_RE`` matches the same ``^[A-Z]{1,5}$`` shape
    #      that ``stock_code_utils.is_code_like`` treats as a bare US code.
    #   2. dotted US form ``^[A-Z]{1,5}\.[A-Z]{1,2}$`` (``BRK.B`` / ``SHOP.US``
    #      / ``HKD.US`` / ``BJRI.US`` / ``AAPL.US``) — PR #2129 round-4 review
    #      blocker ``OR-COR-bare-us-suffix-prefix-collision``: a token like
    #      ``SHOP.US`` / ``HKD.US`` / ``BJRI.US`` / ``USFD.US`` previously
    #      fell through the ``isalpha()``-only short-circuit and got split by
    #      _KNOWN_PREFIXES into ``sh`` + ``OP.US`` / ``hk`` + ``D.US`` /
    #      ``bj`` + ``RI.US`` / ``us`` + ``FD.US``, returning the wrong
    #      exchange and a non-canonical stock id. Both dotted and bare forms
    #      are the same ``_US_TICKER_SHAPE_RE`` regex used throughout the
    #      parser, so apply the short-circuit uniformly.
    #
    # Exchange codes (``sh000300``, ``sz399001``) contain digits; explicitly
    # prefixed US codes (``usAAPL``) are mixed-case — neither matches the
    # _US_TICKER_SHAPE_RE, so both still flow through the prefix splitter
    # and contract #3's "prefix supplied → degrade to stock" semantics
    # remain intact for explicitly-prefixed codes.
    if _US_TICKER_SHAPE_RE.match(token):
        return None, token
    lower = token.lower()
    for p in _KNOWN_PREFIXES_SORTED:
        if lower.startswith(p):
            rest = token[len(p):]
            if rest:
                return p, rest
            # Token is exactly the prefix string with no code — treat as
            # bare so the classifier can reject it as unsupported.
            return None, token
    return None, token


@dataclass(frozen=True)
class IndexEntry:
    """A single known index in :class:`IndexRegistry`."""

    bare_code: str
    exchange: str  # 'SH' / 'SZ' / 'CSI'
    canonical_id: str
    display_name: str
    aliases: Tuple[str, ...] = ()

    def matches_code(self, code: str) -> bool:
        """True if ``code`` is this entry's bare code or any of its aliases."""
        if code == self.bare_code:
            return True
        return code in self.aliases


@dataclass(frozen=True)
class AnalysisTarget:
    """Structured result of :func:`parse_analysis_target`."""

    raw_input: str
    asset_type: str  # one of ParseStatus.*
    canonical_id: str
    display_code: str
    exchange: str  # 'SH' / 'SZ' / 'BJ' / 'HK' / 'US' / 'UNKNOWN'
    unsupported_reason: Optional[str] = None
    # Diagnostic breadcrumbs — not part of the public contract, but kept so
    # downstream phases can render sane error UI without re-parsing.
    normalized_prefix: Optional[str] = None
    normalized_code: Optional[str] = None
    matched_index: Optional[IndexEntry] = field(default=None, hash=False, compare=False)


class IndexRegistry:
    """Authoritative source for ``asset_type=index`` resolution.

    The registry is populated from the validated ``assetType=index`` rows of
    ``apps/dsa-web/public/stocks.index.json`` (via :func:`default_index_registry`).
    It builds three lookup maps at construction time:

    * canonical map — ``canonical_id -> entry``
    * resolver-key map — every normalized canonical/display/alias key -> entry
    * bare-conflict map — the 6-digit numeric base of explicit aliases -> entry

    Construction rejects duplicate or ambiguous keys (identity/alias/stock-index
    conflicts) by raising ``ValueError`` so a malformed candidate is never
    silently loaded.
    """

    def __init__(self, entries: Iterable[IndexEntry] = ()):
        self._entries: List[IndexEntry] = list(entries)
        self._by_canonical: Dict[str, IndexEntry] = {}
        self._by_resolver_key: Dict[str, IndexEntry] = {}
        self._by_bare_conflict: Dict[str, IndexEntry] = {}

        for entry in self._entries:
            norm_canonical = _normalize_index_key(entry.canonical_id)
            if norm_canonical in self._by_canonical:
                raise ValueError(
                    f"duplicate index canonical: {entry.canonical_id!r}"
                )
            self._by_canonical[norm_canonical] = entry

            for alias in entry.aliases:
                norm_alias = _normalize_index_key(alias)
                if norm_alias.isdigit():
                    raise ValueError(
                        f"bare numeric display/alias rejected for index: {alias!r}"
                    )
                if not _EXPLICIT_INDEX_ALIAS_RE.fullmatch(norm_alias):
                    raise ValueError(
                        f"index aliases must use an explicit code form: {alias!r}"
                    )

            for key in [entry.canonical_id] + list(entry.aliases):
                norm_key = _normalize_index_key(key)
                if not norm_key:
                    continue
                if norm_key.isdigit():
                    raise ValueError(
                        f"bare numeric display/alias rejected for index: {key!r}"
                    )
                existing = self._by_resolver_key.get(norm_key)
                if existing is not None and existing is not entry:
                    raise ValueError(
                        f"index resolver key {key!r} maps to multiple canonicals "
                        f"({existing.canonical_id} vs {entry.canonical_id})"
                    )
                self._by_resolver_key[norm_key] = entry

            for alias in entry.aliases:
                base = "".join(ch for ch in alias if ch.isdigit())
                if base and base.isdigit() and len(base) == 6:
                    self._by_bare_conflict.setdefault(base, entry)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries)

    def find_by_prefixed_code(self, prefix: str, bare_code: str) -> Optional[IndexEntry]:
        """Look up an index entry by (exchange prefix, bare code).

        Only ``sh``/``sz`` prefixes can elevate a code to ``index`` status
        (contract #1). Other prefixes return ``None`` even if the bare code
        happens to match a known index — non-A-share exchanges don't host the
        indices in the built-in registry.
        """
        if prefix not in ("sh", "sz"):
            return None
        exchange = _EXCHANGE_PREFIX_TO_CODE.get(prefix)
        if exchange is None:
            return None
        canonical = f"{prefix}{bare_code}"
        entry = self._by_canonical.get(_normalize_index_key(canonical))
        if entry is not None:
            return entry
        # Alias fallback — e.g. user typed ``sz399300`` but registry lists it
        # under ``sh000300`` via an alias. Check the resolver map for the
        # prefixed form first (``sz399300`` is an explicit alias), then walk
        # the registry once for bare-code matches.
        entry = self._by_resolver_key.get(_normalize_index_key(canonical))
        if entry is not None:
            return entry
        for entry in self._entries:
            if entry.exchange == exchange and entry.matches_code(bare_code):
                return entry
        return None

    def find_by_bare_code(self, bare_code: str) -> Optional[IndexEntry]:
        """Look up an index by bare code, ignoring the exchange prefix.

        Used by contract #2 sanity checks: when a bare code is ambiguous (it
        could be either a stock or an index), the parser MUST default to
        ``stock``; this helper lets callers detect the conflict and emit a
        warning without changing the resolved asset_type.
        """
        for entry in self._entries:
            if entry.matches_code(bare_code):
                return entry
        return None

    def find_by_explicit_key(self, key: str) -> Optional[IndexEntry]:
        """Look up an index by an explicit canonical/display/alias key.

        Used by :func:`parse_analysis_target` to resolve ``csi930955`` /
        ``930955.CSI`` and other explicit index forms before generic stock
        normalization runs.
        """
        return self._by_resolver_key.get(_normalize_index_key(key))

    def find_by_display_name(self, name: str) -> Optional[IndexEntry]:
        """Look up an index by its exact registered display name.

        Only NFKC + trim + casefold exact matches are considered — no fuzzy
        search. Display names are deliberately NOT identity aliases: this
        lookup is independent of :meth:`find_by_explicit_key` and never feeds
        ``_by_resolver_key`` / :func:`parse_analysis_target`, so a Chinese
        name can never become a parser identity alias. When two registered
        entries have NFKC/casefold-equivalent display names the lookup is
        ambiguous and returns ``None``; callers should detect that via
        :meth:`is_ambiguous_display_name` and ask the user for an explicit
        code instead of falling back to stock-name resolution.
        """
        key = _normalize_display_name(name)
        if not key:
            return None
        matches = [
            entry
            for entry in self._entries
            if _normalize_display_name(entry.display_name) == key
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def is_ambiguous_display_name(self, name: str) -> bool:
        """True when two or more registered entries share an NFKC/casefold-
        equivalent display name, so :meth:`find_by_display_name` cannot pick
        a single entry."""
        key = _normalize_display_name(name)
        if not key:
            return False
        return (
            sum(
                1
                for entry in self._entries
                if _normalize_display_name(entry.display_name) == key
            )
            > 1
        )

    def find_by_bare_conflict(self, bare_code: str) -> Optional[IndexEntry]:
        """Return the index whose explicit alias base equals ``bare_code``."""
        return self._by_bare_conflict.get(_normalize_index_key(bare_code))


# ---------------------------------------------------------------------------
# Default index registry — built from the validated JSON index rows.
# ---------------------------------------------------------------------------
# The unique runtime identity source is the ``active=true`` / ``assetType=index``
# rows of the candidate ``stocks.index.json``. The old hard-coded
# ``_DEFAULT_INDEX_ENTRIES`` white-list is removed; no second runtime white-list
# is kept. When all candidates fail, the registry is empty and every prefixed
# input degrades to the stock path (fail-open).


def _index_entry_from_row(row) -> Optional[IndexEntry]:
    """Convert one validated active index tuple into an :class:`IndexEntry`."""
    if not isinstance(row, list) or len(row) < 10:
        return None
    canonical = str(row[0] or "").strip()
    display = str(row[1] or "").strip()
    name = str(row[2] or "").strip()
    aliases = row[5] if isinstance(row[5], list) else []
    if not canonical or not name:
        return None
    namespace = canonical[:3] if canonical.startswith("csi") else canonical[:2]
    if namespace == "csi":
        exchange = "CSI"
        bare_code = canonical[3:]
    elif namespace in {"sh", "sz"}:
        exchange = _EXCHANGE_PREFIX_TO_CODE.get(namespace, "UNKNOWN")
        bare_code = canonical[2:]
    else:
        return None
    aliases = [str(a) for a in (row[5] if isinstance(row[5], list) else []) if str(a).strip()]
    # The display code (e.g. ``930955.CSI``) is a resolver key even when it is
    # not an explicit alias; add it so ``find_by_explicit_key`` and the
    # bare-conflict map can resolve it. SH/SZ display equals canonical so it is
    # already covered.
    display = str(row[1] or "").strip()
    if display and display != canonical and display not in aliases:
        aliases.append(display)
    return IndexEntry(
        bare_code=bare_code,
        exchange=exchange,
        canonical_id=canonical,
        display_name=name,
        aliases=tuple(aliases),
    )


def default_index_registry() -> IndexRegistry:
    """Return the :class:`IndexRegistry` built from the validated JSON index rows.

    Loads the active ``assetType=index`` rows via the stock-index loader's
    cached active-index-row loader, converts each to a lightweight
    :class:`IndexEntry`, and constructs a fresh :class:`IndexRegistry`. The
    registry is intentionally cheap to construct; callers may rebuild it on
    every call rather than caching it globally. When the loader returns no
    rows (all candidates failed), the registry is empty and every prefixed
    input degrades to the stock path.
    """
    from src.data.stock_index_loader import _load_active_index_rows

    rows = _load_active_index_rows()
    entries = []
    for row in rows:
        entry = _index_entry_from_row(row)
        if entry is not None:
            entries.append(entry)
    return IndexRegistry(entries)


# ---------------------------------------------------------------------------
# Bare-code classification helpers.
# ---------------------------------------------------------------------------
def _classify_bare_code(bare: str) -> Tuple[str, str]:
    """Return ``(exchange, asset_type)`` for a bare numeric/alphanumeric code.

    Mirrors the ``determine_market_and_type`` logic already living in
    ``scripts/generate_stock_index.py`` so PR1 doesn't introduce a new
    market-classification world. Returns ``asset_type='stock'`` for every
    reachable branch — bare codes never resolve to ``index`` on their own
    (contract #2).
    """
    if not bare:
        return "UNKNOWN", ParseStatus.UNSUPPORTED

    if bare.isdigit():
        if len(bare) == 6:
            if bare.startswith("6") or bare.startswith("900"):
                return "SH", ParseStatus.STOCK
            if bare.startswith(("0", "2", "3")):
                return "SZ", ParseStatus.STOCK
            if bare.startswith(("4", "8", "9")):
                return "BJ", ParseStatus.STOCK
            # A-share ETF prefixes mirror the routing already living in
            # ``data_provider/baostock_fetcher.py`` and
            # ``data_provider/yfinance_fetcher.py`` (and the
            # ``ETF_PREFIXES`` tuple in ``data_provider/base.py``):
            #   51/52/56/58 -> sh (Shanghai ETF)
            #   15/16/18    -> sz (Shenzhen ETF)
            # Routing them through ``CN`` was a review blocker
            # (``OR-COR-1b643ee6``) because ``_canonicalize_for_stock``
            # would subsequently synthesise ``cn510300`` / ``cn159915``,
            # which the upstream fetchers don't accept on input. Keeping
            # the routing here in lock-step with the fetchers ensures the
            # canonical_id this PR produces round-trips into ``BaseFetcher``
            # lookups unchanged.
            if bare.startswith(("51", "52", "56", "58")):
                return "SH", ParseStatus.STOCK
            if bare.startswith(("15", "16", "18")):
                return "SZ", ParseStatus.STOCK
            return "CN", ParseStatus.STOCK
        if len(bare) == 5:
            # Five-digit numeric — HK stock or legacy B-share.
            if bare.startswith("0") or bare.startswith("2"):
                return "HK", ParseStatus.STOCK
            return "CN", ParseStatus.STOCK
        if len(bare) == 4:
            # E.g. HK short codes like 0001, 0941.
            return "HK", ParseStatus.STOCK
        # Any other digit length — unsupported until proven otherwise.
        return "UNKNOWN", ParseStatus.UNSUPPORTED

    # Alphanumeric (US tickers, JP/KR suffix codes, etc.). Treat as US stock
    # by default; PR1 doesn't need a perfect US taxonomy — contract #3 says
    # prefixed unknown codes degrade to stock.
    return "US", ParseStatus.STOCK


def _canonicalize_for_index(entry: IndexEntry, raw_input: str) -> Tuple[str, str, str]:
    """Return ``(canonical_id, display_code, exchange)`` for an index hit."""
    return entry.canonical_id, entry.display_name, entry.exchange


def _canonicalize_for_stock(
    prefix: Optional[str],
    bare: str,
    exchange: str,
) -> Tuple[str, str]:
    """Return ``(canonical_id, display_code)`` for a stock resolution.

    ``canonical_id`` follows the conventions the upstream ``data_provider``
    fetchers already accept on input:

    * A-share: keep the ``sh``/``sz``/``bj`` prefix style (``sh600519``) so
      the canonical ID is round-trippable into ``BaseFetcher`` lookups.
    * HK: ``hk00700`` (5-digit numeric) — matches the ``hk`` prefix style
      already used across fetchers.
    * US: bare ticker (``AAPL``), no ``us`` prefix — fetchers expect raw
      uppercase US symbols and don't recognise ``usAAPL``.
    * Unknown exchange: fall back to the lowercased bare token so downstream
      can still group without crashing.
    """
    if exchange == "UNKNOWN":
        return bare.lower(), bare
    if exchange == "US":
        # US tickers are inherently alphanumeric; canonical stock codes are
        # uppercase across ``data_provider`` (``data_provider/base.py``).
        # All-uppercase bare input (``AAPL``/``USFD``) round-trips unchanged
        # and lowercase bare input from explicit-prefix forms
        # (``usaapl``→``(us, aapl)``) is normalized to uppercase so the
        # canonical ID is consistent with bare US ticker resolution
        # (``aapl``→``AAPL``). Closes PR #2129 review non-blocking
        # suggestion ``OR-COR-9c3d2c44``.
        canonical = bare.upper()
        return canonical, canonical
    if prefix:
        # If the user already provided sh/sz/hk/... prefix, preserve it.
        canonical = f"{prefix}{bare}"
    else:
        # Synthesize a prefix from the inferred exchange for A-share / HK
        # bare codes so canonical_id is round-trippable.
        canonical = f"{exchange.lower()}{bare}"
    display = bare if prefix is None else f"{prefix}{bare}"
    return canonical, display


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------
def parse_analysis_target(
    raw_input: str,
    registry: Optional[IndexRegistry] = None,
) -> AnalysisTarget:
    """Parse one user-facing stock-list token into an :class:`AnalysisTarget`.

    Args:
        raw_input: A single token from :func:`split_stock_list` (or any
            user-supplied string you want classified). The exchange prefix
            (``sh``/``sz``/``bj``/``hk``/``us``) is case-insensitive, but the
            ticker base following an ``us`` prefix must be in canonical
            uppercase US symbol shape — fully lowercase ``us``-prefixed
            tokens such as ``usfd``/``usibm``/``usaapl`` are surfaced as
            ``unsupported`` and not silently rewritten. Tokens without
            any prefix may be bare codes in either case (``AAPL`` or
            ``aapl``) and the normalizer will upper-case them.
        registry: Optional :class:`IndexRegistry`. Defaults to
            :func:`default_index_registry`. Callers may inject a custom
            registry (e.g. loaded from ``stocks.index.json`` once that file
            carries ``asset_type=index`` rows) without changing the parser
            contract.

    Returns:
        An :class:`AnalysisTarget` whose ``asset_type`` is one of
        :class:`ParseStatus`'s three constants. ``unsupported_reason`` is
        ``None`` unless ``asset_type == 'unsupported'``.
    """
    raw = (raw_input or "").strip()
    if not raw:
        return AnalysisTarget(
            raw_input=raw_input or "",
            asset_type=ParseStatus.UNSUPPORTED,
            canonical_id="",
            display_code="",
            exchange="UNKNOWN",
            unsupported_reason="empty input",
        )

    # Note: we deliberately use ``is None`` rather than ``or`` so that an
    # explicitly-injected empty :class:`IndexRegistry` (``IndexRegistry([])``)
    # is honoured as a legitimate "no indices whitelisted" configuration.
    # Using ``or`` would silently replace it with the default registry and
    # re-elevate ``sh000300`` to ``index`` even though the caller asked for
    # a blank white-list — review blocker ``OR-COR-403bd018``.
    if registry is None:
        registry = default_index_registry()

    # Resolve explicit index keys (canonical/display/alias) BEFORE generic
    # stock normalization, so ``csi930955`` / ``930955.CSI`` and other explicit
    # index forms resolve to ``index`` without touching
    # ``normalize_stock_code()``. An unregistered ``.CSI`` input is surfaced as
    # ``unsupported`` (never a US ticker or a guessed SH/SZ index).
    explicit_entry = registry.find_by_explicit_key(raw)
    if explicit_entry is not None:
        canonical, display, exchange = _canonicalize_for_index(explicit_entry, raw)
        # Preserve the prefix/bare split for explicit sh/sz prefixed forms so
        # the existing ``normalized_prefix``/``normalized_code`` contract stays
        # intact (review blocker OR-COR-d24a4e9a family). CSI forms carry no
        # sh/sz prefix.
        norm_prefix = None
        norm_code = raw
        lower = raw.lower()
        for p in ("sh", "sz"):
            if lower.startswith(p) and len(raw) > len(p):
                norm_prefix = p
                norm_code = raw[len(p):]
                break
        return AnalysisTarget(
            raw_input=raw_input,
            asset_type=ParseStatus.INDEX,
            canonical_id=canonical,
            display_code=display,
            exchange=exchange,
            normalized_prefix=norm_prefix,
            normalized_code=norm_code,
            matched_index=explicit_entry,
        )

    # PR #2267 review fix: an explicit CSI form not owned by the registry must
    # surface as ``unsupported`` — never a US ticker or a guessed SH/SZ index. This
    # covers both the ``.CSI`` suffix (already handled by the prior check) and
    # the ``csi`` prefix form (``csi930956`` / ``CSI930956``), which the generic
    # normalizer would otherwise mis-route into the US-ticker branch.
    if _EXPLICIT_CSI_FORM_RE.match(unicodedata.normalize("NFKC", raw).strip().casefold()):
        return AnalysisTarget(
            raw_input=raw_input,
            asset_type=ParseStatus.UNSUPPORTED,
            canonical_id=raw,
            display_code=raw,
            exchange="UNKNOWN",
            unsupported_reason=(
                f"unregistered CSI index: {raw!r} is not in the index registry"
            ),
            normalized_prefix=None,
            normalized_code=raw,
        )

    # Reuse the repository's existing normalization contract
    # (``src.services.stock_code_utils._normalize_code_and_exchange``) so
    # lowercase tickers (``shop``/``hkd``/``aapl``) and suffix-form inputs
    # (``600519.SH``/``00700.HK``/``7203.T``/``005930.KS``/``2330.TW``) —
    # including the index-style ``000300.SH`` token — are routed through the
    # same uppercase/suffix/prefix logic the rest of the codebase already
    # exercises. This closes review blocker ``OR-COR-5f9691af``: the prior
    # ``_split_prefix`` only short-circuited ALL-UPPERCASE 1-5 letter tokens
    # and so mis-split ``shop`` as ``(sh, op)`` / ``hkd`` as ``(hk, d)``,
    # while suffix-form tokens were never stripped and so fell through to the
    # alphanumeric US branch regardless of the actual market. After this
    # normalization the downstream ``_split_prefix`` / ``_classify_bare_code``
    # pipeline receives the canonical uppercase code (and the explicit
    # exchange when present), so contract #1/#2/#3 stay intact.
    from .stock_code_utils import _normalize_code_and_exchange
    norm_code, norm_exchange = _normalize_code_and_exchange(raw)

    # Phase 1 contract (issue #2063, maintainer clarification 2026-08-01):
    # the ``us`` exchange prefix is case-insensitive on the *prefix* itself
    # but the ticker base must arrive in canonical uppercase US symbol
    # shape. ``us``-prefixed tokens whose base does NOT match the canonical
    # US ticker shape ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$`` (the same regex used by
    # ``data_provider/us_index_mapping.py:16-17`` and
    # ``stock_code_utils._normalize_code_and_exchange``) — e.g. ``usfd`` /
    # ``usm`` / ``usibm`` / ``usaapl`` / ``usshop`` (all-lowercase) AND
    # ``Usfd`` / ``USibm`` / ``Usaapl`` (mixed-case prefix with lowercase
    # base) AND ``usbrk.b`` / ``usshop.us`` (lowercase base with punctuation)
    # AND ``us1`` / ``us12345`` (lowercase prefix with non-letter base —
    # pure digit bases never match the US ticker regex) — are neither bare
    # US tickers (silently upper-casing would synthesise ``USFD`` / ``USIBM``
    # / ``USBRK.B`` / ``US1``, which are different real or non-existent
    # securities, and ``US1`` is not even a valid US symbol shape) nor
    # explicit ``us``-prefix stock symbols (silently splitting would
    # rewrite them to ``FD`` / ``IBM`` / ``BRK.B`` / ``1``, losing the
    # user's original intent, and ``1`` is also not a valid US symbol).
    # Reject them up-front as ``unsupported`` regardless of what the
    # normalizer computed for ``norm_code``, so the caller can prompt
    # the user to retype the ticker base in canonical uppercase form.
    # This closes OR-COR-9c3d2c44 (``usfd``/``usm`` silent bare rewrite),
    # OR-COR-2f0d1a7e (``usibm``/``usge``/``usbk``/``usaapl`` length-dependent
    # split bifurcation), OR-COR-7b45f5c1 (``Usfd``/``USibm``/
    # ``Usaapl`` mixed-case prefix with lowercase base) and
    # OR-COR-us-prefix-nonalpha-guard-gap (``usbrk.b``/``usshop.us``/
    # ``us1`` lowercase/non-alphabetic bases bypassed the earlier
    # ``raw.isalpha()``-gated guard) under one consistent contract rule:
    # the guard checks ``raw[2:]`` against the canonical US ticker regex
    # ``_US_TICKER_SHAPE_RE``, so any base that isn't a valid uppercase
    # US symbol shape is rejected up-front, regardless of case or
    # character class.
    if (
        len(raw) > 2
        and raw[:2].lower() == "us"
        and _US_TICKER_SHAPE_RE.match(raw[2:]) is None
    ):
        return AnalysisTarget(
            raw_input=raw_input,
            asset_type=ParseStatus.UNSUPPORTED,
            canonical_id=raw,
            display_code=raw,
            exchange="US",
            unsupported_reason=(
                f"us-prefixed token {raw!r} must use a canonical uppercase "
                f"US ticker base matching '^[A-Z]{{1,5}}(.[A-Z]{{1,2}})?$' "
                f"(e.g. 'usAAPL' / 'usBRK.B' / 'usSHOP.US'), or be a bare "
                f"US ticker in canonical uppercase form"
            ),
            normalized_prefix=None,
            normalized_code=raw,
        )

    # Foreign Yahoo suffix forms (``7203.T``/``005930.KS``/``2330.TW``/)
    # ``6505.TWO``) round-trip through ``_normalize_code_and_exchange`` with
    # the suffix preserved on the code and the exchange set to ``T``/``KS``/
    # ``TW``/``TWO``. ``_split_prefix`` won't recognise them (they contain
    # ``.``) and ``_classify_bare_code`` would otherwise route them to ``US``
    # because the body isn't pure digits. We therefore short-circuit foreign
    # suffix forms and emit the canonical Yahoo-style ``BASE.SUFFIX`` id.
    if norm_code and "." in norm_code and norm_exchange:
        return AnalysisTarget(
            raw_input=raw_input,
            asset_type=ParseStatus.STOCK,
            canonical_id=norm_code,
            display_code=norm_code,
            exchange=norm_exchange,
            normalized_prefix=None,
            normalized_code=norm_code,
        )

    # A-share / HK explicit-exchange forms (``SH600519``/``sh600519``/
    # ``600519.SH``/``00700.HK``/``HK00700``): when ``_normalize_code_and_
    # exchange`` returns an explicit exchange together with a clean base
    # code, rewrite ``raw`` to the lowercase-prefixed canonical form so
    # ``_split_prefix`` recognises it uniformly.
    #
    # ``000300.SH`` is a special case — the canonical alias for the SH-listed
    # CSI-300 index ID even though six-digit codes starting with ``0`` don't
    # normally live on the Shanghai exchange; the normalizer returns
    # ``(None, "SH")`` there and we rewire to ``sh000300`` so the index
    # lookup path in contract #1 still claims it.
    #
    # When ``norm_code is None`` we must NOT blindly rebuild ``sh<base>``
    # for every explicit-suffix input — that would silently rewrite
    # ``600519.BJ``/``600000.HK``/``1234567.SH`` (which the normalizer
    # correctly rejected: the base digits don't validate against the
    # exchange's digit-len / market table, or the base isn't numeric at
    # all) into ``sh600519``/``sh600000``/``sh1234567``, masking the user's
    # typo as a valid Shanghai stock (review blockers
    # ``OR-COR-607f1395`` / ``OR-COR-26596201`` / ``OR-COR-d6afd0d6``).
    #
    # Discrimination strategy:
    #   1. Restrict the alias-rebuild path to ``SH``/``SS`` only. Those are
    #      the only exchanges where a digit-len mismatch could legitimately
    #      hide an index alias (``000300.SH`` is the canonical example).
    #      ``.BJ``/``.HK`` base+exchange mismatches are always genuine typos
    #      and must surface as ``unsupported``.
    #   2. Even within ``SH``/``SS``, only rebuild when (a) the base is pure
    #      6-digit numeric (so non-numeric reject cases like ``abc.SH``
    #      short-circuit to ``unsupported``) AND (b) the rebuilt
    #      ``sh<base>`` actually has a hit in ``registry.find_by_prefixed_code``
    #      — i.e. the user's token is a recognized INDEX alias. A
    #      ``1234567.SH`` that nobody in the registry knows about is a
    #      malformed reject, not an index lookup.
    #   3. ``SZ``-style aliases (e.g. ``399001.SZ``) would similarly only be
    #      rebuildable when recognized; the SH-only branch matches the
    #      current default registry's composition and the reviewer-flagged
    #      regression set.
    if norm_exchange and norm_exchange in _EXCHANGE_NORMALIZER:
        if norm_code is None:
            from .stock_code_utils import _split_explicit_exchange, _PREFIX_DIGIT_LENS
            raw_upper = raw.upper()
            explicit_parts = _split_explicit_exchange(raw_upper)
            # ⤷ Distinguish dotted-prefix form (``SH.000999``) from
            #   strict-suffix form (``000999.SH``). The splitter surfaces
            #   dotted-prefix tokens by leaving ``raw_upper`` starting with
            #   ``<EXCHANGE>.`` while strict-suffix tokens always end in
            #   ``.SUFFIX`` *without* a leading dotted prefix. Only the
            #   strict-suffix shape should fire reject here — dotted-prefix
            #   must continue to fall through to the legacy ``_split_prefix``
            #   path so contract #3 (``sh + unknown → degrade to stock``)
            #   still holds even when the bare code is rejected by the
            #   normalizer's CN-exchange table (000999 doesn't belong to SH
            #   per the digit-len rules, but the user's explicit ``sh``
            #   prefix is the contract signal, not the digit shape).
            has_explicit_suffix = (
                "." in raw
                and not any(
                    raw_upper.startswith(f"{pfx}.")
                    for pfx in _PREFIX_DIGIT_LENS
                )
            )
            # Dotted-prefix form (``SH.000999`` / ``BJ.600519`` /
            # ``HK.600519`` / ``SS.000999``): the splitter surfaces these as
            # ``raw_upper`` starting with ``<EXCHANGE>.``. The normalizer
            # already rejected the base via ``_valid_exchange_code`` (e.g.
            # ``000999`` doesn't match SH's digit-len / market table), so we
            # must NOT let the token fall through to ``_split_prefix`` —
            # otherwise ``SS.000999`` would silently degrade into a US
            # ticker (because lowercase ``ss.000999`` doesn't start with any
            # known exchange prefix) and ``SH.000999`` would round-trip as
            # ``sh.000999`` (a non-canonical id no fetcher accepts). Treat
            # dotted-prefix rejects the same way as strict-suffix rejects.
            # See review blocker ``OR-COR-6f4d6b12``.
            has_dotted_prefix = (
                "." in raw
                and raw_upper.startswith(tuple(f"{pfx}." for pfx in _PREFIX_DIGIT_LENS))
            )
            if explicit_parts is not None and (has_explicit_suffix or has_dotted_prefix):
                suffix_exchange, base_candidate, _ = explicit_parts
                # Restrict the alias rebuild to SH/SS/SZ aliases only —
                # those are the only exchanges where a digit-len mismatch
                # could legitimately hide a registry index alias
                # (``000300.SH`` is the canonical example;
                # ``sz399001.SZ`` / ``sz399006.SZ`` are the SZ-side mirror).
                # Other exchanges (BJ/HK) always reject on base+exchange
                # mismatch (e.g. ``600519.BJ``). See blocker
                # ``OR-COR-4b91e5a0`` for the SZ index alias gap.
                if suffix_exchange in {"SH", "SS", "SZ"}:
                    rebuilt_prefix = _EXCHANGE_NORMALIZER[suffix_exchange]
                    # Two acceptable alias shapes:
                    #   (a) Standard suffix form ``000300.SH`` — base_candidate
                    #       is purely 6 digits and recognized by the registry.
                    #   (b) Mixed prefix+suffix form ``sh000300.SH`` — the
                    #       splitter leaves base_candidate as ``SH000300``
                    #       (non-numeric). We ONLY accept (b) when raw is
                    #       a clean ``<prefix><digits>.<suffix>`` shape, so
                    #       malformed inputs like ``sh0x00300.SH`` (with
                    #       hex-like garbage embedded between the prefix
                    #       and the digits) don't get silently rebuilt into
                    #       a recognized index alias (blocking
                    #       OR-COR-d83a3580). The check is conservative —
                    #       ``str(base_candidate)`` starts with the
                    #       uppercase prefix and the remainder is a
                    #       purely-6-digit string.
                    base_after_prefix = (
                        base_candidate[len(suffix_exchange):]
                        if base_candidate.startswith(suffix_exchange)
                        else base_candidate
                    )
                    base_digits = "".join(filter(str.isdigit, raw))
                    clean_alias_shape = (
                        base_candidate.startswith(suffix_exchange)
                        and base_after_prefix.isdigit()
                        and len(base_after_prefix) == 6
                    )
                    alias_ok = (
                        base_candidate.isdigit()
                        and len(base_candidate) == 6
                        and registry.find_by_prefixed_code(
                            rebuilt_prefix, base_candidate
                        )
                        is not None
                    ) or (
                        clean_alias_shape
                        and base_digits == base_after_prefix
                        and len(base_digits) == 6
                        and registry.find_by_prefixed_code(
                            rebuilt_prefix, base_digits
                        )
                        is not None
                    )
                    if alias_ok:
                        raw = f"{rebuilt_prefix}{base_digits or base_candidate}"
                    else:
                        return AnalysisTarget(
                            raw_input=raw_input,
                            asset_type=ParseStatus.UNSUPPORTED,
                            canonical_id=raw,
                            display_code=raw,
                            exchange=suffix_exchange,
                            unsupported_reason=(
                                f"explicit exchange suffix {suffix_exchange!r} "
                                f"does not accept base {base_candidate!r}"
                            ),
                        )
                else:
                    # ``.BJ`` / ``.HK`` reject (base/exchange mismatch,
                    # base too long, base non-numeric, …) — surface as
                    # ``unsupported`` rather than silently rewriting into
                    # ``sh<digits>`` (blocking review OR-COR-607f1395 etc.).
                    return AnalysisTarget(
                        raw_input=raw_input,
                        asset_type=ParseStatus.UNSUPPORTED,
                        canonical_id=raw,
                        display_code=raw,
                        exchange=suffix_exchange,
                        unsupported_reason=(
                            f"explicit exchange suffix {suffix_exchange!r} "
                            f"rejects base {base_candidate!r}"
                        ),
                    )
        else:
            raw = f"{_EXCHANGE_NORMALIZER[norm_exchange]}{norm_code}"
    elif norm_exchange:
        # Foreign explicit-exchange suffix (``.T`` / ``.KS`` / ``.KQ`` / ``.TW``
        # / ``.TWO``) whose base failed ``_valid_exchange_code`` so
        # ``norm_code is None`` but ``norm_exchange`` still carries the
        # recognized suffix name. The legacy bare-code classifier would
        # otherwise silently flip the token into a US stock (blocking
        # review OR-COR-e21e9de5). Surface as ``unsupported`` with the
        # offending suffix so callers can show the user *which* foreign
        # market they typed and why we're rejecting it.
        from .stock_code_utils import _split_explicit_exchange as _split_for_foreign
        raw_upper = raw.upper()
        explicit_parts = _split_for_foreign(raw_upper)
        if explicit_parts is not None:
            suffix_exchange, base_candidate, _ = explicit_parts
            return AnalysisTarget(
                raw_input=raw_input,
                asset_type=ParseStatus.UNSUPPORTED,
                canonical_id=raw,
                display_code=raw,
                exchange=suffix_exchange,
                unsupported_reason=(
                    f"explicit foreign exchange suffix {suffix_exchange!r} "
                    f"rejects base {base_candidate!r}"
                ),
            )
    elif norm_code and norm_exchange == "":
        # ``_normalize_code_and_exchange`` upper-cases the token (``shop`` →
        # ``SHOP``, ``usBRK`` → ``USBRK``). For mixed-case prefix inputs such
        # as ``usBRK`` / ``UsBRK`` / ``uSBRK`` (case-insensitive ``us``
        # prefix + uppercase base, per Phase 1 contract from issue #2063,
        # maintainer clarification 2026-08-01) the normalizer's
        # ``base.isdigit()`` guard in ``_split_explicit_exchange`` prevents
        # ``us`` from being recognised as an exchange prefix, so we restore
        # the ``us``-prefix split here. Tokens with a lowercase base were
        # already rejected by the early-return guard above. An all-uppercase
        # token ≤5 letters (``USFD``/``USM``) is a bare US ticker and is
        # short-circuited by ``_split_prefix`` before reaching this branch
        # (so we do NOT touch it here); an all-uppercase token >5 letters
        # (``USAAPL``) flows into this branch and is split as an explicit
        # ``us`` prefix.
        #
        # PR #2129 round-5 follow-up (OpenReview Bot OR-COR-0e285b84,
        # 2026-08-01): a mixed-case ``us`` prefix paired with a *dotted*
        # uppercase US base such as ``usBRK.B`` / ``usABC.US`` was previously
        # filtered out by the ``raw.isalpha()`` gate below — the dotted base
        # is not all-alpha. After uppercasing it became ``USBRK.B`` /
        # ``USABC.US``, which ``_split_prefix`` short-circuits as a bare
        # dotted US ticker (matches ``_US_TICKER_SHAPE_RE``), silently
        # swallowing the user-supplied ``us`` prefix and producing a
        # different canonical id. We extend the eligible form to the same
        # ``_US_TICKER_SHAPE_RE`` shape the upfront guard accepts, while
        # keeping the bare-short-circuit exclusion (`raw.isupper() and
        # len(raw) <= 5` — bare all-upper USFD/USM) so as not to overrun
        # `_split_prefix`'s bare path. The dotted branch and the existing
        # all-alpha branch are siblings of the same ``us``-prefix recovery
        # rule, and together they mirror the shape gate at lines 566-585.
        if (
            len(raw) > 2
            and raw[:2].lower() == "us"
            # Only recover an explicit ``us`` prefix when the first two
            # characters are NOT both uppercase — that mixed-case shape is
            # the user's signal that ``us`` is a prefix, not the leading
            # letters of a bare US ticker (``SHOP.US`` / ``HKD.US`` /
            # ``USFD.US`` / ``BJRI.US``). A bare dotted all-uppercase US
            # ticker must keep flowing through ``_split_prefix``'s bare
            # short-circuit, so we exclude it here.
            and not raw[:2].isupper()
            and _US_TICKER_SHAPE_RE.match(raw[2:])
        ):
            bare_from_us = raw[2:]
            # Strip the explicit prefix; the dot-suffixed base survives
            # verbatim (preserves ``BRK.B`` / ``ABC.US`` rather than
            # collapsing `.`).
            restored = f"us{bare_from_us}"
            raw = restored
        else:
            raw = norm_code

    prefix, bare = _split_prefix(raw)

    # Contract #1: prefixed index white-list.
    if prefix in ("sh", "sz") and bare:
        entry = registry.find_by_prefixed_code(prefix, bare)
        if entry is not None:
            canonical, display, exchange = _canonicalize_for_index(entry, raw)
            return AnalysisTarget(
                raw_input=raw_input,
                asset_type=ParseStatus.INDEX,
                canonical_id=canonical,
                display_code=display,
                exchange=exchange,
                normalized_prefix=prefix,
                normalized_code=bare,
                matched_index=entry,
            )
        # Contract #3: prefix supplied but registry didn't claim it →
        # degrade to stock and remember the prefix.
        exchange_for_stock, _ = _classify_bare_code(bare)
        # Override exchange with the user's explicit prefix when possible.
        if prefix in _EXCHANGE_PREFIX_TO_CODE:
            exchange_for_stock = _EXCHANGE_PREFIX_TO_CODE[prefix]
        canonical, display = _canonicalize_for_stock(prefix, bare, exchange_for_stock)
        return AnalysisTarget(
            raw_input=raw_input,
            asset_type=ParseStatus.STOCK,
            canonical_id=canonical,
            display_code=display,
            exchange=exchange_for_stock,
            normalized_prefix=prefix,
            normalized_code=bare,
        )

    # Contract #2: bare code (no prefix) — always stock, regardless of whether
    # the registry has a matching index entry. We surface the conflict via
    # ``matched_index`` so callers can warn, but we don't flip asset_type.
    exchange, asset_type = _classify_bare_code(bare) if prefix is None else (
        _EXCHANGE_PREFIX_TO_CODE.get(prefix, "UNKNOWN"),
        ParseStatus.STOCK,
    )
    if asset_type == ParseStatus.UNSUPPORTED:
        return AnalysisTarget(
            raw_input=raw_input,
            asset_type=ParseStatus.UNSUPPORTED,
            canonical_id=bare.lower(),
            display_code=raw,
            exchange=exchange,
            unsupported_reason="unrecognized code shape",
            normalized_prefix=prefix,
            normalized_code=bare,
        )

    canonical, display = _canonicalize_for_stock(prefix, bare, exchange)

    # Surface potential index conflict (e.g. user typed ``000300`` expecting
    # the index but got a stock because the contract defaults bare codes to
    # stock). Don't change asset_type — just expose the match.
    matched_index = None
    if prefix is None and bare:
        candidate = registry.find_by_bare_code(bare)
        if candidate is None:
            # Also surface conflicts via the bare-conflict map so a bare code
            # that is the numeric base of an explicit index alias (e.g.
            # ``930955`` for ``csi930955``) is advertised as ambiguous.
            candidate = registry.find_by_bare_conflict(bare)
        if candidate is not None:
            matched_index = candidate

    return AnalysisTarget(
        raw_input=raw_input,
        asset_type=ParseStatus.STOCK,
        canonical_id=canonical,
        display_code=display,
        exchange=exchange,
        normalized_prefix=prefix,
        normalized_code=bare,
        matched_index=matched_index,
    )


# ---------------------------------------------------------------------------
# Convenience helpers for batch parsing.
# ---------------------------------------------------------------------------
def parse_stock_list(value: str, registry: Optional[IndexRegistry] = None) -> List[AnalysisTarget]:
    """Parse every token in a STOCK_LIST-style string at once.

    Useful for callers that want to drive the UI directly off a parsed list
    rather than chaining :func:`split_stock_list` + :func:`parse_analysis_target`.
    """
    return [
        parse_analysis_target(token, registry=registry)
        for token in split_stock_list(value)
    ]
