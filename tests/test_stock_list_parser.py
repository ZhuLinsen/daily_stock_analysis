# -*- coding: utf-8 -*-
"""Tests for :mod:`src.services.stock_list_parser`.

Phase 1 (issue #2063): covers the three core contracts —
* 前缀白名单指数: prefixed ``sh``/``sz`` + registry-known code → ``index``
* 裸码默认个股: bare numeric code → ``stock`` even if it's an index code
* 前缀未命中降级为股票: prefixed unknown code → ``stock`` (never ``unsupported``)

Also keeps the legacy ``split_stock_list`` / ``serialize_stock_list`` tests
so PR1 is a strict superset of pre-PR coverage rather than a replacement.
"""

from __future__ import annotations

from typing import Optional

import pytest

from src.services.stock_list_parser import (
    AnalysisTarget,
    IndexEntry,
    IndexRegistry,
    ParseStatus,
    default_index_registry,
    parse_analysis_target,
    parse_stock_list,
    serialize_stock_list,
    split_stock_list,
)


# ---------------------------------------------------------------------------
# Legacy helpers — unchanged behaviour.
# ---------------------------------------------------------------------------
def test_split_stock_list_accepts_common_copy_paste_separators() -> None:
    value = "600519，300750  hk00700;AAPL、7203.T\n005930.KS；002594"

    assert split_stock_list(value) == [
        "600519",
        "300750",
        "hk00700",
        "AAPL",
        "7203.T",
        "005930.KS",
        "002594",
    ]


def test_serialize_stock_list_uses_canonical_commas() -> None:
    assert serialize_stock_list("600519，300750\nAAPL") == "600519,300750,AAPL"


# ---------------------------------------------------------------------------
# Contract #1 — prefixed index white-list.
# ---------------------------------------------------------------------------
class TestContract1PrefixedIndex:
    """前缀白名单指数 — prefixed ``sh``/``sz`` + registry-known code → index."""

    def test_sh000300_resolves_to_index(self) -> None:
        target = parse_analysis_target("sh000300")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"
        assert target.display_code == "沪深300"
        assert target.exchange == "SH"
        assert target.normalized_prefix == "sh"
        assert target.normalized_code == "000300"
        assert target.matched_index is not None
        assert target.matched_index.display_name == "沪深300"

    def test_sz399001_resolves_to_index(self) -> None:
        target = parse_analysis_target("sz399001")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sz399001"
        assert target.display_code == "深证成指"
        assert target.exchange == "SZ"

    def test_uppercase_prefix_is_normalized(self) -> None:
        target = parse_analysis_target("SH000300")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"

    def test_alias_resolution_sh000300_dot_sh(self) -> None:
        """Alias-style ``sh000300.SH`` — prefix ``sh`` carries, bare becomes
        ``000300.SH`` which matches the canonical entry's alias.
        """
        # ``sh`` prefix + bare ``000300.SH`` — the registry stores ``000300.SH``
        # as an alias, so this still resolves to index. Test the alias path
        # without having to teach the prefix splitter about dots.
        registry = IndexRegistry([
            IndexEntry(
                bare_code="000300",
                exchange="SH",
                canonical_id="sh000300",
                display_name="沪深300",
                aliases=("000300.SH",),
            )
        ])
        target = parse_analysis_target("sh000300.SH", registry=registry)
        # Contract #1 — alias matches even when bare carries a dot suffix.
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"

    def test_unknown_prefixed_index_code_degrades_to_stock(self) -> None:
        """Contract #3 leak: ``sh000999`` isn't in the registry → stock."""
        target = parse_analysis_target("sh000999")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SH"
        assert target.normalized_prefix == "sh"
        assert target.normalized_code == "000999"


# ---------------------------------------------------------------------------
# Contract #2 — bare code defaults to stock.
# ---------------------------------------------------------------------------
class TestContract2BareCodeDefaultsToStock:
    """裸码默认个股 — bare numeric code always resolves to stock."""

    def test_bare_000300_is_stock_not_index(self) -> None:
        """Conflict code: ``000300`` is the沪深300 index code, but per the
        contract the parser MUST default bare codes to ``stock``. We surface
        the conflict via ``matched_index`` so the UI can warn, but we never
        flip asset_type.

        ``canonical_id`` follows the synthesised stock exchange (``sz`` because
        the bare-code classifier routes ``000xxx`` to SZ), NOT the index's
        ``sh`` exchange — keeping the round-trippable stock canonical lets
        downstream fetchers look it up without surprise; the index conflict
        is advertised via ``matched_index`` alone.
        """
        target = parse_analysis_target("000300")
        assert target.asset_type == ParseStatus.STOCK
        assert target.canonical_id == "sz000300"  # synthesised via SZ detect
        # display_code preserves the user input shape (bare).
        assert target.display_code == "000300"
        # The conflict surface — registry's index entry is exposed but not
        # used for asset_type resolution.
        assert target.matched_index is not None
        assert target.matched_index.display_name == "沪深300"

    def test_bare_000001_is_stock(self) -> None:
        """Conflict code: ``000001`` is平安银行 (SZ stock) AND the上证指数
        (``sh000001``) is now in the registry. Per contract #2 bare codes
        always resolve to stock; the index conflict is surfaced via
        ``matched_index`` without flipping asset_type.
        """
        target = parse_analysis_target("000001")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SZ"
        # canonical_id is round-trippable: sh/sz prefix synthesised from 0/2/3.
        assert target.canonical_id == "sz000001"
        # The registry now carries sh000001 (上证指数) whose alias base is 000001.
        assert target.matched_index is not None
        assert target.matched_index.canonical_id == "sh000001"

    def test_bare_600519_is_sh_stock(self) -> None:
        target = parse_analysis_target("600519")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SH"
        assert target.canonical_id == "sh600519"
        assert target.display_code == "600519"
        assert target.matched_index is None

    def test_bare_000016_conflict_is_visible(self) -> None:
        """same logic as 000300 — bare code conflicts with sh000016 上证50."""
        target = parse_analysis_target("000016")
        assert target.asset_type == ParseStatus.STOCK
        assert target.matched_index is not None
        assert target.matched_index.display_name == "上证50"

    def test_bare_300750_is_sz_stock(self) -> None:
        target = parse_analysis_target("300750")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SZ"
        assert target.canonical_id == "sz300750"

    def test_bse_920xxx_is_stock(self) -> None:
        """920xxx — Beijing Stock Exchange new codes (post-2024 migration)."""
        target = parse_analysis_target("920001")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "BJ"
        assert target.canonical_id == "bj920001"

    def test_bare_us_ticker_is_stock(self) -> None:
        target = parse_analysis_target("AAPL")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        # US tickers preserve case so the canonical ID doubles as the
        # display code that fetchers accept directly.
        assert target.canonical_id == "AAPL"
        assert target.display_code == "AAPL"
        assert target.matched_index is None

    def test_bare_hk_5_digit_is_stock(self) -> None:
        target = parse_analysis_target("00700")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "HK"
        assert target.canonical_id == "hk00700"

    def test_bare_hk_4_digit_is_stock(self) -> None:
        target = parse_analysis_target("0941")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "HK"
        assert target.canonical_id == "hk0941"


# ---------------------------------------------------------------------------
# Contract #3 — prefixed unknown degrades to stock.
# ---------------------------------------------------------------------------
class TestContract3PrefixedUnknownDegradesToStock:
    """前缀未命中降级为股票 — prefixed unknown → stock (never unsupported)."""

    def test_sh_unknown_code_is_stock(self) -> None:
        target = parse_analysis_target("sh000999")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SH"
        assert target.canonical_id == "sh000999"

    def test_sz_unknown_code_is_stock(self) -> None:
        target = parse_analysis_target("sz000999")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SZ"
        assert target.canonical_id == "sz000999"

    def test_hk_prefixed_code_is_stock(self) -> None:
        target = parse_analysis_target("hk00700")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "HK"
        assert target.canonical_id == "hk00700"

    def test_us_prefixed_ticker_is_stock(self) -> None:
        target = parse_analysis_target("usAAPL")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        # ``us`` prefix is recognised, but US canonical IDs are the bare
        # ticker (fetchers don't accept ``usAAPL``) — the prefix only biases
        # the exchange detection; it doesn't enter the canonical ID.
        assert target.canonical_id == "AAPL"
        assert target.normalized_prefix == "us"
        assert target.normalized_code == "AAPL"

    @pytest.mark.parametrize(
        "ticker,expected_canonical_id",
        [
            # Phase 1 contract (issue #2063, maintainer clarification
            # 2026-08-01): the ``us`` exchange prefix is case-insensitive
            # on the prefix itself, but the ticker base must arrive in the
            # canonical uppercase US symbol shape (regex
            # ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$``). ``us``-prefixed tokens
            # whose base does NOT match that shape are surfaced as
            # ``unsupported`` so callers can prompt the user to retype in
            # mixed/upper case. This uniformly rejects:
            #   - bare-US collisions (``usfd``/``usm``, previously
            #     OR-COR-9c3d2c44)
            #   - explicit-prefix collisions (``usibm``/``usamd``/``usge``
            #     /``usbk``/``usaapl``/``usshop``, previously OR-COR-2f0d1a7e)
            #   - mixed-case prefix with lowercase base (``Usfd``/``USibm``/
            #     ``Usaapl``/``uSfd``/``USaapl``, previously OR-COR-7b45f5c1)
            #   - lowercase/non-alphabetic base bypassing the earlier
            #     ``raw.isalpha()``-gated guard (``usbrk.b``/``usshop.us``/
            #     ``us1``, previously OR-COR-us-prefix-nonalpha-guard-gap)
            # under one consistent contract rule — no US ticker whitelist
            # or length-dependent heuristic needed. ``canonical_id`` carries
            # the raw token verbatim so the caller can echo it back to the
            # user as the offending input; ``normalized_prefix`` is None
            # because the input was NOT accepted as an explicit prefix form.
            ("usfd", "usfd"),
            ("usm", "usm"),
            ("usibm", "usibm"),
            ("usamd", "usamd"),
            ("usge", "usge"),
            ("usbk", "usbk"),
            ("usaapl", "usaapl"),
            ("usshop", "usshop"),
            # Mixed-case prefix + lowercase base (OR-COR-7b45f5c1): the
            # prefix alone being uppercase (or partially uppercase) is not
            # sufficient — the base must be all uppercase for the explicit
            # ``us``-prefix contract to apply.
            ("Usfd", "Usfd"),
            ("USibm", "USibm"),
            ("Usaapl", "Usaapl"),
            ("uSfd", "uSfd"),
            ("USaapl", "USaapl"),
            # Lowercase base with punctuation/digits (OR-COR-us-prefix-
            # nonalpha-guard-gap): the earlier ``raw.isalpha()``-gated
            # guard let ``usbrk.b`` / ``usshop.us`` / ``us1`` slip through
            # to the normalizer, which silently rewrote them to ``BRK.B``
            # / ``SHOP.US`` / ``1``. The new regex-based guard catches
            # these regardless of character class — digit-only bases,
            # lowercase+dotted bases, lowercase+digit bases alike.
            ("usbrk.b", "usbrk.b"),
            ("usshop.us", "usshop.us"),
            ("us1", "us1"),
            ("us1a", "us1a"),
            ("us12a", "us12a"),
            # All-uppercase but invalid US shape (digits in base): ``US1``
            # contains a digit so it doesn't match ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$``.
            # Previously ``_split_prefix`` would strip ``US`` and the
            # normalizer would accept ``1`` as the canonical_id — surfacing
            # an invalid US symbol to callers. The regex-based guard
            # rejects it up-front.
            ("US1", "US1"),
            ("US12345", "US12345"),
        ],
    )
    def test_lowercase_us_prefix_is_unsupported(
        self,
        ticker: str,
        expected_canonical_id: str,
    ) -> None:
        r"""Regression for PR #2129 review blockers OR-COR-9c3d2c44 (closed),
        OR-COR-2f0d1a7e (closed), OR-COR-7b45f5c1 (closed), and
        OR-COR-us-prefix-nonalpha-guard-gap: ``us``-prefixed tokens whose
        ticker base does NOT match the canonical US symbol shape regex
        ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$`` — whether the prefix itself is
        lowercase, mixed-case, or uppercase, and whether the base
        contains lowercase letters, digits, or punctuation — are neither
        bare US tickers nor explicit-prefix stock symbols under the Phase
        1 contract from issue #2063 (maintainer clarification 2026-08-01).
        They are surfaced as ``unsupported`` so callers can prompt the
        user to retype the ticker base in canonical uppercase form
        (``usAAPL``/``usBRK.B``/``USFD``). The contract closes four
        prior blockers under one uniform rule — no US ticker whitelist
        required:
            * OR-COR-9c3d2c44: ``usfd``/``usm`` silent bare-rewrite bloom
            * OR-COR-2f0d1a7e: ``usibm``/``usge``/``usbk``/``usaapl``
              length-dependent explicit-prefix split bifurcation
            * OR-COR-7b45f5c1: ``Usfd``/``USibm``/``Usaapl`` mixed-case
              prefix with lowercase base bypassing the lowercase-only guard
            * OR-COR-us-prefix-nonalpha-guard-gap: ``usbrk.b``/``usshop.us``/
              ``us1`` lowercase base with punctuation/digits bypassing the
              earlier ``raw.isalpha()``-gated guard
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == "US"
        assert target.canonical_id == expected_canonical_id
        assert target.normalized_prefix is None
        assert target.unsupported_reason is not None
        assert "uppercase" in target.unsupported_reason


# ---------------------------------------------------------------------------
# Edge cases — empty input + unsupported shapes.
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_string_is_unsupported(self) -> None:
        target = parse_analysis_target("")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.canonical_id == ""
        assert target.unsupported_reason == "empty input"

    def test_whitespace_only_is_unsupported(self) -> None:
        target = parse_analysis_target("   ")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.unsupported_reason == "empty input"

    def test_three_digit_bare_code_is_unsupported(self) -> None:
        """Three-digit bare codes don't map to any known market shape — the
        parser surfaces ``unsupported`` with a reason rather than guessing.
        """
        target = parse_analysis_target("007")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.unsupported_reason == "unrecognized code shape"

    def test_seven_digit_bare_code_is_unsupported(self) -> None:
        target = parse_analysis_target("1234567")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.unsupported_reason == "unrecognized code shape"


# ---------------------------------------------------------------------------
# Default registry — public API surface.
# ---------------------------------------------------------------------------
class TestDefaultIndexRegistry:
    def test_default_registry_has_31_entries(self) -> None:
        registry = default_index_registry()
        assert len(registry) == 31

    def test_default_registry_canonical_ids(self) -> None:
        registry = default_index_registry()
        ids = {entry.canonical_id for entry in registry}
        assert len(ids) == 31
        # The 5 original hard-coded indices are preserved.
        assert {"sh000300", "sh000016", "sh000688", "sz399001", "sz399006"} <= ids
        # CSI entries are present.
        assert {"csi930955", "csi932365"} <= ids

    def test_default_registry_find_by_prefixed_code(self) -> None:
        registry = default_index_registry()
        entry = registry.find_by_prefixed_code("sh", "000300")
        assert entry is not None
        assert entry.display_name == "沪深300"

    def test_default_registry_find_by_prefixed_code_rejects_non_sh_sz(self) -> None:
        registry = default_index_registry()
        # Even if a code looks like a known index, hk/us/bj prefixes don't
        # elevate to index status — they degrade to stock (contract #3).
        assert registry.find_by_prefixed_code("hk", "000300") is None
        assert registry.find_by_prefixed_code("us", "000300") is None

    def test_default_registry_find_by_explicit_key_csi(self) -> None:
        registry = default_index_registry()
        entry = registry.find_by_explicit_key("csi930955")
        assert entry is not None
        assert entry.canonical_id == "csi930955"
        assert entry.exchange == "CSI"
        # display form also resolves
        entry2 = registry.find_by_explicit_key("930955.CSI")
        assert entry2 is not None
        assert entry2.canonical_id == "csi930955"

    def test_default_registry_find_by_bare_conflict(self) -> None:
        registry = default_index_registry()
        # 930955 is the bare base of the csi930955 alias.
        entry = registry.find_by_bare_conflict("930955")
        assert entry is not None
        assert entry.canonical_id == "csi930955"

    def test_display_name_is_not_an_identity_alias(self) -> None:
        """Gap 2: a Chinese display name (e.g. ``沪深300``) must never resolve
        as an index identity — text names are not identity aliases."""
        registry = default_index_registry()
        assert registry.find_by_explicit_key("沪深300") is None
        assert registry.find_by_explicit_key("上证50") is None
        # The canonical/display/alias code forms still resolve.
        assert registry.find_by_explicit_key("sh000300") is not None
        assert registry.find_by_explicit_key("000300.SH") is not None
        # Parsing the Chinese name must not elevate to index.
        target = parse_analysis_target("沪深300")
        assert target.asset_type != ParseStatus.INDEX

    def test_find_by_display_name_resolves_registered_name(self) -> None:
        """PR2: exact registered display names resolve through the dedicated
        name lookup — independent of ``find_by_explicit_key``."""
        registry = default_index_registry()
        entry = registry.find_by_display_name("上证50")
        assert entry is not None
        assert entry.canonical_id == "sh000016"
        entry2 = registry.find_by_display_name("沪深300")
        assert entry2 is not None
        assert entry2.canonical_id == "sh000300"

    def test_find_by_display_name_is_nfkc_trim_casefold_exact(self) -> None:
        """PR2: name lookup normalizes NFKC + trim + casefold before the exact
        match, but never falls back to fuzzy matching."""
        registry = default_index_registry()
        # Full-width / whitespace variants of a registered name still match.
        assert registry.find_by_display_name("　上证50　") is not None
        assert registry.find_by_display_name("上证５０") is not None
        # Unknown names return None (no fuzzy fallback).
        assert registry.find_by_display_name("不存在标的") is None
        assert registry.find_by_display_name("上证5") is None

    def test_find_by_display_name_does_not_leak_into_identity_alias(self) -> None:
        """PR2: a display-name hit must not make the name resolvable as an
        identity alias — the parser contract stays untouched."""
        registry = default_index_registry()
        assert registry.find_by_display_name("上证50") is not None
        assert registry.find_by_explicit_key("上证50") is None
        target = parse_analysis_target("上证50")
        assert target.asset_type != ParseStatus.INDEX

    def test_ambiguous_display_name_is_reported(self) -> None:
        """PR2: two entries with NFKC/casefold-equivalent display names make
        the name lookup ambiguous — no guessing, no single winner."""
        registry = IndexRegistry((
            IndexEntry(
                bare_code="000300",
                exchange="SH",
                canonical_id="sh000300",
                display_name="沪深300",
            ),
            IndexEntry(
                bare_code="000999",
                exchange="SH",
                canonical_id="sh000999",
                display_name="沪深300",
            ),
        ))
        assert registry.is_ambiguous_display_name("沪深300") is True
        assert registry.find_by_display_name("沪深300") is None
        # Explicit identity still resolves deterministically.
        assert registry.find_by_explicit_key("sh000300") is not None
        assert registry.find_by_explicit_key("sh000999") is not None

    def test_custom_registry_rejects_text_identity_alias(self) -> None:
        with pytest.raises(ValueError, match="explicit code form"):
            IndexRegistry((
                IndexEntry(
                    bare_code="000300",
                    exchange="SH",
                    canonical_id="sh000300",
                    display_name="沪深300",
                    aliases=("CSI300",),
                ),
            ))

    def test_code_shaped_display_names_stay_distinct_under_exact_name_lookup(
        self,
    ) -> None:
        """PR2 review fix: display-name equality is exactly NFKC + trim +
        casefold. Code-shaped names (``000016.SH`` vs ``sh000016``) that
        identity normalization would falsely collapse (``_normalize_index_key``
        treats them as the same resolver key ``sh000016``) must stay distinct
        for the name lookup, so each exact query resolves its own entry and
        neither is reported ambiguous."""
        registry = IndexRegistry((
            IndexEntry(
                bare_code="000016",
                exchange="SH",
                canonical_id="sh000016",
                display_name="000016.SH",
            ),
            IndexEntry(
                bare_code="000999",
                exchange="SH",
                canonical_id="sh000999",
                display_name="sh000016",
            ),
        ))
        # Identity normalization collapses both names to ``sh000016``, but the
        # name lookup must NOT reuse it — each display name resolves exactly.
        entry = registry.find_by_display_name("000016.SH")
        assert entry is not None
        assert entry.display_name == "000016.SH"
        entry = registry.find_by_display_name("sh000016")
        assert entry is not None
        assert entry.display_name == "sh000016"
        assert registry.is_ambiguous_display_name("000016.SH") is False
        assert registry.is_ambiguous_display_name("sh000016") is False


# ---------------------------------------------------------------------------
# Batch parsing helper.
# ---------------------------------------------------------------------------
class TestParseStockList:
    def test_parse_stock_list_returns_one_target_per_token(self) -> None:
        targets = parse_stock_list("sh000300,600519,bk0001")
        # Three tokens, three targets — bk0001 is unrecognized prefix but
        # contract #3 degrades it to stock rather than raising.
        assert len(targets) == 3
        assert targets[0].asset_type == ParseStatus.INDEX
        assert targets[1].asset_type == ParseStatus.STOCK
        assert targets[2].asset_type == ParseStatus.STOCK

    def test_parse_stock_list_handles_separators(self) -> None:
        targets = parse_stock_list("sh000300；600519\nAAPL、hk00700")
        assert len(targets) == 4
        assert targets[0].asset_type == ParseStatus.INDEX
        assert targets[1].asset_type == ParseStatus.STOCK
        assert targets[2].asset_type == ParseStatus.STOCK
        assert targets[3].exchange == "HK"


# ---------------------------------------------------------------------------
# Regression — exact maintainer spec samples from issue #2063.
# ---------------------------------------------------------------------------
class TestMaintainerSpecSamples:
    """Six samples ZhuLinsen called out as minimum coverage."""

    def test_sh000300(self) -> None:
        target = parse_analysis_target("sh000300")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"

    def test_sz399300_resolves_to_index(self) -> None:
        """``sz399300`` is a registered cross-market alias of ``sh000300``
        (沪深300) per the manifest, so it resolves to the index.
        """
        target = parse_analysis_target("sz399300")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"
        assert target.exchange == "SH"

    def test_sh600519(self) -> None:
        target = parse_analysis_target("sh600519")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SH"
        assert target.canonical_id == "sh600519"

    def test_bare_000300(self) -> None:
        target = parse_analysis_target("000300")
        assert target.asset_type == ParseStatus.STOCK

    def test_bare_000001(self) -> None:
        target = parse_analysis_target("000001")
        assert target.asset_type == ParseStatus.STOCK

    def test_bare_920xxx(self) -> None:
        target = parse_analysis_target("920001")
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "BJ"


# ---------------------------------------------------------------------------
# Dataclass serialization sanity — keeps the contract JSON-friendly.
# ---------------------------------------------------------------------------
def test_analysis_target_is_immutable_and_hashable() -> None:
    target = parse_analysis_target("sh000300")
    with pytest.raises(Exception):
        target.asset_type = "mutated"  # type: ignore[misc]
    hash(target)  # should not raise


def test_analysis_target_with_index_entry_is_hashable() -> None:
    """``matched_index`` is non-hashable by default; ensure the dataclass
    override (``compare=False, hash=False``) keeps AnalysisTarget hashable
    when an IndexEntry is attached.
    """
    target = parse_analysis_target("000300")
    assert target.matched_index is not None
    hash(target)  # should not raise


# ---------------------------------------------------------------------------
# Review-blocker regressions — covers the three correctness blockers raised
# by maintainer on PR #2094 (issue #2063 phase 1):
#   OR-COR-d24a4e9a: 1-5 letter US tickers colliding with sh/sz/bj/hk/us
#                    prefixes were mis-split (SHOP -> shOP, HKD -> hkD, ...)
#   OR-COR-1b643ee6: bare A-share ETF codes (510300 etc.) were canonicalised
#                    to ``cn510300`` which no upstream fetcher accepts.
#   OR-COR-403bd018: passing ``IndexRegistry([])`` was silently replaced by
#                    the default registry, hiding the empty-white-list config.
# These tests pin the fixes so the same regressions can't land unnoticed.
# ---------------------------------------------------------------------------
class TestReviewBlockerRegressions:
    """Maintainer-specified regression inputs (issue #2063 phase 1 review)."""

    # ---- OR-COR-d24a4e9a: US ticker prefix collisions ---------------------

    @pytest.mark.parametrize(
        "ticker",
        ["SHOP", "HKD", "BJRI", "USM", "SHAK", "USFD", "BJDX", "SZKMY",
         "AAPL", "TSLA", "BRK", "A", "Z"],
    )
    def test_us_ticker_prefix_collision_is_not_split(self, ticker: str) -> None:
        """1-5 letter US tickers must round-trip as US stock, not be split
        into ``(sh, OP)`` / ``(hk, D)`` / ... by the prefix scanner.
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        assert target.canonical_id == ticker
        assert target.display_code == ticker
        assert target.normalized_prefix is None
        assert target.normalized_code == ticker
        assert target.matched_index is None

    # ---- OR-COR-bare-us-suffix-prefix-collision ----------------------------

    @pytest.mark.parametrize(
        "ticker",
        # Bare ``.US`` suffix US tickers (round-4 blocker
        # OR-COR-bare-us-suffix-prefix-collision): a token like ``SHOP.US`` /
        # ``HKD.US`` / ``BJRI.US`` / ``USFD.US`` has the same canonical US
        # symbol shape ``^[A-Z]{1,5}\.[A-Z]{1,2}$`` as ``BRK.B`` / ``AAPL.US``.
        # Previously ``_split_prefix`` only short-circuited bare uppercase
        # letters (``USFD``-form), so dotted ``.US`` codes whose first 2
        # letters happened to collide with a known exchange prefix
        # (``sh``/``hk``/``bj``/``us``) were mis-split into
        # ``(sh, OP.US)`` / ``(hk, D.US)`` / ``(bj, RI.US)`` / ``(us, FD.US)``,
        # producing wrong market and non-canonical stock id.
        ["SHOP.US", "HKD.US", "BJRI.US", "USFD.US", "AAPL.US", "BRK.B"],
    )
    def test_bare_dotted_us_suffix_collision_is_not_split(self, ticker: str) -> None:
        r"""Bare ``.US`` / ``.B`` dotted US tickers whose first 1-2 letters
        collide with a known exchange prefix (``sh`` / ``hk`` / ``bj`` /
        ``us``) must round-trip as US stock, not be split by the prefix
        scanner into ``(sh, OP.US)`` / ``(hk, D.US)`` / ``(us, FD.US)`` etc.

        Regression for PR #2129 round-4 review blocker
        ``OR-COR-bare-us-suffix-prefix-collision``.

        Both bare form (``USFD``) and dotted form (``SHOP.US`` / ``BRK.B``)
        share the canonical ``_US_TICKER_SHAPE_RE`` regex
        ``^[A-Z]{1,5}(\.[A-Z]{1,2})?$``, so ``_split_prefix`` now applies
        the same short-circuit to both families.
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        assert target.canonical_id == ticker
        assert target.display_code == ticker
        assert target.normalized_prefix is None
        assert target.normalized_code == ticker
        assert target.matched_index is None

    @pytest.mark.parametrize(
        "ticker,expected_prefix,expected_bare",
        [
            ("usAAPL", "us", "AAPL"),
            ("usBRK", "us", "BRK"),
            ("hk00700", "hk", "00700"),
            ("sh000300", "sh", "000300"),
            ("sz399001", "sz", "399001"),
            ("bj920001", "bj", "920001"),
        ],
    )
    def test_explicit_prefixed_codes_still_split(
        self, ticker: str, expected_prefix: str, expected_bare: str
    ) -> None:
        """Codes with explicit sh/sz/bj/hk/us prefixes that *also* contain
        digits must still be split into ``(prefix, bare)``. The US-ticker
        short-circuit only triggers for 1-5 letter alphabetic tokens.
        """
        target = parse_analysis_target(ticker)
        assert target.normalized_prefix == expected_prefix
        assert target.normalized_code == expected_bare

    # ---- OR-COR-0e285b84: us-prefixed dotted uppercase US base accepted-path
    # regression (PR #2129 round-5 review) -----------------------------

    @pytest.mark.parametrize(
        "ticker,expected_canonical,expected_prefix,expected_bare",
        [
            # mixed-case us-prefix + bare US base: usAAPL / usBRK — the
            # explicit ``us`` prefix is recorded in ``normalized_prefix``
            # and the bare US ticker form is the canonical id.
            ("usAAPL", "AAPL", "us", "AAPL"),
            ("usBRK", "BRK", "us", "BRK"),
            # mixed-case us-prefix + dotted uppercase US base (the new
            # contract): usBRK.B and usABC.US must preserve the explicit
            # ``us`` prefix and pass the bare US short-circuit in
            # ``_split_prefix`` intact — they are valid US-ticker shapes
            # that carry the user's intent of a ``us`` prefix.
            ("usBRK.B", "BRK.B", "us", "BRK.B"),
            ("usABC.US", "ABC.US", "us", "ABC.US"),
        ],
    )
    def test_us_prefixed_dotted_uppercase_us_base_preserves_prefix(
        self, ticker: str, expected_canonical: str, expected_prefix: str, expected_bare: str
    ) -> None:
        """Explicit ``us`` prefix paired with a dotted uppercase US base
        must not be silently rewritten to a bare ticker shape.

        Regression for PR #2129 round-5 review blocker
        ``OR-COR-0e285b84``: previously ``usBRK.B`` / ``usABC.US`` were
        uppercased to ``USBRK.B`` / ``USABC.US`` and then short-circuited
        by ``_split_prefix`` as bare US tickers, swallowing the user's
        explicit ``us`` prefix and producing a different canonical id
        (e.g. canonical ``USBRK.B`` instead of bare ``BRK.B`` with
        ``normalized_prefix='us'``).

        The fix extends the ``us``-prefix recovery gate at
        ``stock_list_parser.py:~825`` to match the same
        ``_US_TICKER_SHAPE_RE`` shape the upfront guard at
        ``~566-585`` already accepts, while keeping the bare all-uppercase
        short-circuit exclusion (``bare USFD.US`` / ``BRK.B``) intact.
        """
        target = parse_analysis_target(ticker)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "US"
        assert target.canonical_id == expected_canonical
        assert target.normalized_prefix == expected_prefix
        assert target.normalized_code == expected_bare

    # ---- OR-COR-1b643ee6: bare A-share ETF routing ------------------------

    @pytest.mark.parametrize(
        "bare_code,expected_exchange,expected_canonical",
        [
            # Shanghai ETF prefixes 51/52/56/58
            ("510300", "SH", "sh510300"),
            ("510050", "SH", "sh510050"),
            ("520000", "SH", "sh520000"),
            ("562000", "SH", "sh562000"),
            ("588000", "SH", "sh588000"),
            # Shenzhen ETF prefixes 15/16/18
            ("159915", "SZ", "sz159915"),
            ("159919", "SZ", "sz159919"),
            ("160000", "SZ", "sz160000"),
            ("164000", "SZ", "sz164000"),
            ("184000", "SZ", "sz184000"),
        ],
    )
    def test_bare_a_share_etf_routes_to_sh_or_sz(
        self,
        bare_code: str,
        expected_exchange: str,
        expected_canonical: str,
    ) -> None:
        """Bare 6-digit ETF codes must canonicalise through the same sh/sz
        prefixes already used by ``data_provider/{baostock,yfinance}_fetcher,
        py`` and the ``ETF_PREFIXES`` tuple in ``data_provider/base.py`` —
        never through the ``cn`` prefix that no upstream fetcher accepts.
        """
        target = parse_analysis_target(bare_code)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == expected_exchange
        assert target.canonical_id == expected_canonical
        assert target.display_code == bare_code
        assert target.matched_index is None

    def test_bare_etf_canonical_id_round_trips_into_baostock_fetcher(
        self,
    ) -> None:
        """End-to-end round-trip: the canonical_id produced by
        ``parse_analysis_target`` for a bare A-share ETF must be accepted
        verbatim by ``BaostockFetcher._convert_stock_code`` and yield the
        same ``sh.<code>`` / ``sz.<code>`` form the fetcher already produces
        for the same bare code. Failures here mean future formatter drift
        between ``stock_list_parser`` and the upstream fetcher would break
        STOCK_LIST ingestion.
        """
        from data_provider.baostock_fetcher import BaostockFetcher

        fetcher = BaostockFetcher()
        for bare in ("510300", "159915", "510050", "588000"):
            target = parse_analysis_target(bare)
            assert target.canonical_id == fetcher._convert_stock_code(
                target.canonical_id
            ).replace(".", "")

    # ---- OR-COR-403bd018: explicit empty IndexRegistry -------------------

    def test_empty_registry_disables_index_elevation_for_sh000300(
        self,
    ) -> None:
        """An explicitly-injected ``IndexRegistry([])`` must be honoured as
        a "no indices whitelisted" configuration: ``sh000300`` then degrades
        to a SH stock per contract #3 instead of being elevated to an index.
        """
        target = parse_analysis_target("sh000300", registry=IndexRegistry([]))
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SH"
        assert target.canonical_id == "sh000300"
        assert target.normalized_prefix == "sh"
        assert target.normalized_code == "000300"
        assert target.matched_index is None

    def test_empty_registry_disables_index_elevation_for_sz399001(
        self,
    ) -> None:
        """Same guard for the SZ side — ``sz399001`` (CSI 100 default index)
        must also degrade to stock under an empty registry.
        """
        target = parse_analysis_target("sz399001", registry=IndexRegistry([]))
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SZ"
        assert target.canonical_id == "sz399001"
        assert target.matched_index is None

    def test_default_registry_still_elevates_sh000300_after_empty_path(
        self,
    ) -> None:
        """Reading the inverse: with no registry argument the default
        registry still elevates ``sh000300`` to an index. This guards against
        accidentally flipping the empty-registry patch into a global override
        that swallows the default registry too.
        """
        target = parse_analysis_target("sh000300")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"
        assert target.matched_index is not None

    def test_custom_registry_with_subset_entries_only_matches_subset(
        self,
    ) -> None:
        """A non-empty custom registry only honours the indices it carries;
        other ``sh``/``sz`` codes (even ones in the default registry) fall
        through to stock. This is the contract #1 semantics that the
        ``is None`` change must preserve.
        """
        custom = IndexRegistry((
            IndexEntry(
                bare_code="000999",
                exchange="SH",
                canonical_id="sh000999",
                display_name="custom-only",
            ),
        ))
        # Custom registry knows sh000999 -> index
        target = parse_analysis_target("sh000999", registry=custom)
        assert target.asset_type == ParseStatus.INDEX
        assert target.matched_index is not None

        # Custom registry does NOT know sh000300 -> degrade to stock
        target = parse_analysis_target("sh000300", registry=custom)
        assert target.asset_type == ParseStatus.STOCK
        assert target.exchange == "SH"
        assert target.matched_index is None


# ---------------------------------------------------------------------------
# Explicit-exchange-suffix review-blocker regressions (issue #2063 phase 1
# review): when a user types ``600519.BJ`` / ``00700.HK`` / ``abc.SH`` /
# ``1234567.SH`` they must see ``unsupported`` rather than be silently
# rewritten to a ``sh600519.bj`` / ``hk00700`` / ``sh1234567`` / ``shabc``
# token that no fetcher accepts.
# ---------------------------------------------------------------------------
class TestExplicitExchangeSuffixRejections:
    """Maintainer-specified explicit-suffix rejection inputs."""

    @pytest.mark.parametrize(
        "code,expected_exchange,reason_substr",
        [
            ("600519.BJ", "BJ", "BJ"),
            ("600000.HK", "HK", "HK"),
            ("1234567.SH", "SH", "SH"),
            ("abc.SH", "SH", "SH"),
        ],
    )
    def test_explicit_suffix_with_invalid_base_is_unsupported(
        self,
        code: str,
        expected_exchange: str,
        reason_substr: str,
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == expected_exchange
        assert target.canonical_id == code
        assert target.unsupported_reason is not None
        assert reason_substr in target.unsupported_reason

    def test_explicit_sh_suffix_resolves_through_index_alias(self) -> None:
        """``000300.SH`` matches the default registry alias for the CSI 300
        index; ``sh`` is the registered exchange for that bare code so the
        suffix must not flip the asset_type to unsupported."""
        target = parse_analysis_target("000300.SH")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"
        assert target.exchange == "SH"
        assert target.unsupported_reason is None

    # ---- OR-COR-4b91e5a0: ``sz399001.SZ`` / ``sz399006.SZ`` mixed
    #      prefix+suffix forms must resolve through the same index-alias
    #      rebuild path as ``sh000300.SH``. The default registry already
    #      lists both as SZ indices, so the parser must rebuild them into
    #      ``sz399001`` / ``sz399006`` instead of rejecting with
    #      "explicit exchange suffix 'SZ' rejects base 'SZ399001'".
    @pytest.mark.parametrize(
        "code,expected_canonical,expected_display",
        [
            ("sz399001.SZ", "sz399001", "深证成指"),
            ("sz399006.SZ", "sz399006", "创业板指"),
        ],
    )
    def test_sz_mixed_prefix_suffix_resolves_through_index_alias(
        self, code: str, expected_canonical: str, expected_display: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == expected_canonical
        assert target.exchange == "SZ"
        assert target.display_code == expected_display
        assert target.unsupported_reason is None

    # ---- OR-COR-d83a3580: malformed explicit-suffix with embedded hex-like
    #      digits must NOT be silently rebuilt into a valid index alias.
    @pytest.mark.parametrize(
        "code,expected_exchange",
        [
            ("sh0x00300.SH", "SH"),       # hex-like garbage before digits
            ("SZ0x000300.SZ", "SZ"),      # leading 0x-style hex in base
            ("HK0x000700.HK", "HK"),      # hex-like garbage in HK context
        ],
    )
    def test_malformed_explicit_suffix_with_embedded_hex_is_unsupported(
        self, code: str, expected_exchange: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == expected_exchange
        assert target.canonical_id == code
        assert target.unsupported_reason is not None
        assert expected_exchange in target.unsupported_reason

    # ---- OR-COR-b3e32200 / OR-COR-6f4d6b12: dotted-prefix form
    #      (``SH.000999`` / ``BJ.600519`` / ``HK.600519`` / ``SS.000999``)
    #      with a base the normalizer rejected must reject as ``unsupported``
    #      rather than degrade to a malformed canonical stock (``sh.000999``)
    #      or — worse — silently flip to US (``SS.000999`` → exchange='US').
    #      Contract #3 (``sh + unknown → degrade to stock``) only applies when
    #      the bare base is a passable code shape; an explicit dotted-prefix
    #      reject is a typo, not a stock.
    #
    #      NOTE: ``SZ.000001`` is intentionally NOT included here — ``SZ`` is
    #      in the alias-rebuild whitelist, so the dotted-prefix form is
    #      equivalent to the strict-suffix form ``000001.SZ`` (alias for SZ
    #      stock 000001) and must resolve to a real STOCK, not reject.
    @pytest.mark.parametrize(
        "code,expected_exchange",
        [
            ("SH.000999", "SH"),
            ("BJ.600519", "BJ"),
            ("HK.600519", "HK"),
            ("SS.000999", "SS"),
        ],
    )
    def test_dotted_prefix_with_invalid_base_is_unsupported(
        self, code: str, expected_exchange: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == expected_exchange
        assert target.canonical_id == code
        assert target.unsupported_reason is not None
        assert expected_exchange in target.unsupported_reason

    # ---- OR-COR-e21e9de5: foreign-exchange suffixes (.T/.KS/.KQ/.TW/.TWO)
    #      with invalid bases must reject — not silently flip to US stock.
    @pytest.mark.parametrize(
        "code,expected_exchange",
        [
            ("abc.T", "T"),
            ("!@#.KS", "KS"),
            ("0x.TW", "TW"),
            ("x.TWO", "TWO"),
            ("a1b.KQ", "KQ"),
        ],
    )
    def test_foreign_exchange_suffix_with_invalid_base_is_unsupported(
        self, code: str, expected_exchange: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == expected_exchange
        assert target.canonical_id == code
        assert target.unsupported_reason is not None
        assert expected_exchange in target.unsupported_reason


# ---------------------------------------------------------------------------
# Index registry & CSI provider symbol governance.
# ---------------------------------------------------------------------------
class TestIndexAliasMatrix:
    """Canonical/display/alias converge; CSI explicit; bare stays stock."""

    @pytest.mark.parametrize(
        "code,expected_canonical,expected_exchange",
        [
            ("sh000300", "sh000300", "SH"),
            ("000300.SH", "sh000300", "SH"),
            ("sz399300", "sh000300", "SH"),
            ("399300.SZ", "sh000300", "SH"),
            ("000300.CSI", "sh000300", "SH"),
        ],
    )
    def test_sh000300_alias_forms_resolve_to_index(
        self, code: str, expected_canonical: str, expected_exchange: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == expected_canonical
        assert target.exchange == expected_exchange

    @pytest.mark.parametrize(
        "code",
        ["csi930955", "930955.CSI", "CSI930955", "  csi930955  "],
    )
    def test_csi930955_forms_resolve_to_index(self, code: str) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "csi930955"
        assert target.exchange == "CSI"

    def test_unknown_csi_is_unsupported_not_us_stock(self) -> None:
        target = parse_analysis_target("930956.CSI")
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == "UNKNOWN"
        assert target.unsupported_reason is not None
        assert "CSI" in target.unsupported_reason

    @pytest.mark.parametrize(
        "code",
        [
            "csi930956",
            "CSI930956",
            "930956.CSI",
            "csi000300",
            "CSI000300",
            "csi93095",
            "csi9309557",
            "93095.CSI",
            "9309557.CSI",
        ],
    )
    def test_unregistered_explicit_csi_prefix_and_suffix_is_unsupported(
        self, code: str
    ) -> None:
        """PR #2267 review fix: an unknown explicit ``csi`` prefix (or an
        unregistered ``.CSI`` suffix) must surface as ``unsupported`` — never a
        US ticker and never a guessed SH/SZ index. Only a manifest-owned
        identity may route/persist as an index."""
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.UNSUPPORTED
        assert target.exchange == "UNKNOWN"
        assert target.canonical_id == code
        assert target.unsupported_reason is not None
        assert "CSI" in target.unsupported_reason

    def test_csi_prefix_is_not_overequated_to_csi_suffix_alias(self) -> None:
        """PR #2267 review fix: ``000300.CSI`` is the registered alias of
        ``sh000300``, but the bare ``csi000300`` prefix is NOT — it must stay
        unsupported rather than being promoted to the same-code index."""
        target = parse_analysis_target("000300.CSI")
        assert target.asset_type == ParseStatus.INDEX
        assert target.canonical_id == "sh000300"
        assert target.exchange == "SH"

        unregistered = parse_analysis_target("csi000300")
        assert unregistered.asset_type == ParseStatus.UNSUPPORTED
        assert unregistered.exchange == "UNKNOWN"

    def test_us_ticker_starting_with_csi_remains_stock(self) -> None:
        target = parse_analysis_target("CSIQ")
        assert target.asset_type == ParseStatus.STOCK
        assert target.canonical_id == "CSIQ"

    @pytest.mark.parametrize(
        "code,expected_canonical",
        [
            ("000001", "sz000001"),
            ("000016", "sz000016"),
            ("000688", "sz000688"),
            ("000300", "sz000300"),
            ("399300", "sz399300"),
            ("930955", "bj930955"),
        ],
    )
    def test_bare_conflict_codes_stay_stock_with_matched_index(
        self, code: str, expected_canonical: str
    ) -> None:
        target = parse_analysis_target(code)
        assert target.asset_type == ParseStatus.STOCK
        assert target.canonical_id == expected_canonical
        assert target.matched_index is not None

    def test_unregistered_sh_sz_prefixed_stock_keeps_stock_path(self) -> None:
        target = parse_analysis_target("sh600519")
        assert target.asset_type == ParseStatus.STOCK
        assert target.canonical_id == "sh600519"
        target2 = parse_analysis_target("sz000001")
        assert target2.asset_type == ParseStatus.STOCK
        assert target2.canonical_id == "sz000001"

    def test_old_text_aliases_do_not_resolve_to_index(self) -> None:
        # CSI300 / HS300 / SSE50 / STAR50 are not in the manifest aliases.
        for code in ("CSI300", "HS300", "SSE50", "STAR50", "SZSE", "ChiNext"):
            target = parse_analysis_target(code)
            assert target.asset_type != ParseStatus.INDEX

    def test_nfkc_and_case_normalization_do_not_create_second_identity(self) -> None:
        a = parse_analysis_target("csi930955")
        b = parse_analysis_target("ＣＳＩ９３０９５５")  # full-width
        assert a.asset_type == ParseStatus.INDEX
        assert b.asset_type == ParseStatus.INDEX
        assert a.canonical_id == b.canonical_id
