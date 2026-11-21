# -*- coding: utf-8 -*-
"""Tests for shared suffix-only market symbol helpers."""

from src.services.market_symbol_utils import (
    get_suffix_market,
    is_suffix_market_symbol,
    normalize_suffix_market_symbol,
    suffix_base_lookup_allowed,
)


def test_suffix_market_detection_covers_supported_yahoo_markets() -> None:
    assert get_suffix_market("7203.t") == "jp"
    assert get_suffix_market("005930.ks") == "kr"
    assert get_suffix_market("247540.kq") == "kr"
    assert get_suffix_market("2330.tw") == "tw"
    assert get_suffix_market("6505.two") == "tw"

    assert is_suffix_market_symbol("7203.T", "jp") is True
    assert is_suffix_market_symbol("7203.T", "kr") is False
    assert normalize_suffix_market_symbol("005930.ks") == "005930.KS"


def test_suffix_market_detection_rejects_ambiguous_or_invalid_bare_codes() -> None:
    assert get_suffix_market("005930") is None
    assert get_suffix_market("2330") is None
    assert get_suffix_market("123.T") is None
    assert get_suffix_market("1234567.TW") is None
    assert get_suffix_market("7203.KS") is None


def test_bare_base_lookup_is_only_allowed_for_jp_kr_mvp() -> None:
    assert suffix_base_lookup_allowed("7203.T") is True
    assert suffix_base_lookup_allowed("005930.KS") is True
    assert suffix_base_lookup_allowed("247540.KQ") is True
    assert suffix_base_lookup_allowed("2330.TW") is False
    assert suffix_base_lookup_allowed("6505.TWO") is False


def test_jp_alphanumeric_tickers_are_supported() -> None:
    # JPX issues alphanumeric codes such as 130A; Yahoo lists them as 130A.T.
    assert get_suffix_market("130A.T") == "jp"
    assert get_suffix_market("130a.t") == "jp"
    assert normalize_suffix_market_symbol("130a.t") == "130A.T"
    assert is_suffix_market_symbol("130A.T", "jp") is True


def test_jp_rule_does_not_capture_pure_letter_bases() -> None:
    # Pure-letter dotted US shapes must stay out of the JP rule.
    assert get_suffix_market("ABCD.T") is None
    assert get_suffix_market("AAPL.T") is None
    # Digits remain mandatory for alphanumeric bases.
    assert get_suffix_market("13AA.T") == "jp"
    assert get_suffix_market("A13A.T") == "jp"
    assert get_suffix_market("13AB5.T") == "jp"
