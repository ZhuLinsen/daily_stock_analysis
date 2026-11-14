# -*- coding: utf-8 -*-
"""Tests for shared suffix-only market symbol helpers."""

from src.services.market_symbol_utils import (
    get_suffix_market,
    is_ca_suffix_symbol,
    is_suffix_market_symbol,
    normalize_suffix_market_symbol,
    suffix_base_lookup_allowed,
)


def test_suffix_market_detection_covers_supported_yahoo_markets() -> None:
    assert get_suffix_market("7203.t") == "jp"
    assert get_suffix_market("005930.ks") == "kr"
    assert get_suffix_market("035720.kq") == "kr"
    assert get_suffix_market("2330.tw") == "tw"
    assert get_suffix_market("6505.two") == "tw"

    assert is_suffix_market_symbol("7203.T", "jp") is True
    assert is_suffix_market_symbol("7203.T", "kr") is False
    assert normalize_suffix_market_symbol("005930.ks") == "005930.KS"


def test_suffix_market_detection_covers_canadian_tickers() -> None:
    # TSX / TSX Venture / Canadian Securities Exchange
    assert get_suffix_market("SHOP.TO") == "ca"
    assert get_suffix_market("shop.to") == "ca"
    assert get_suffix_market("RY.TO") == "ca"
    assert get_suffix_market("ABC.V") == "ca"
    assert get_suffix_market("XYZ.CNX") == "ca"

    assert is_ca_suffix_symbol("SHOP.TO") is True
    assert is_ca_suffix_symbol("ABC.V") is True
    assert is_ca_suffix_symbol("SHOP") is False
    assert is_suffix_market_symbol("SHOP.TO", "ca") is True
    assert is_suffix_market_symbol("SHOP.TO", "us") is False
    assert normalize_suffix_market_symbol("shop.to") == "SHOP.TO"


def test_suffix_market_detection_rejects_invalid_canadian_shapes() -> None:
    # Canadian bases are alphabetic tickers, not numeric codes.
    assert get_suffix_market("600519.TO") is None
    assert get_suffix_market("ABCDEFG.TO") is None
    assert get_suffix_market("ABC.CSE") is None


def test_suffix_market_detection_rejects_ambiguous_or_invalid_bare_codes() -> None:
    assert get_suffix_market("005930") is None
    assert get_suffix_market("2330") is None
    assert get_suffix_market("123.T") is None
    assert get_suffix_market("1234567.TW") is None
    assert get_suffix_market("7203.KS") is None


def test_bare_base_lookup_is_only_allowed_for_jp_kr_mvp() -> None:
    assert suffix_base_lookup_allowed("7203.T") is True
    assert suffix_base_lookup_allowed("005930.KS") is True
    assert suffix_base_lookup_allowed("035720.KQ") is True
    assert suffix_base_lookup_allowed("2330.TW") is False
    assert suffix_base_lookup_allowed("6505.TWO") is False
    # Canadian tickers stay suffix-only: a bare base such as SHOP is a
    # perfectly valid US ticker and must not resolve to a Canadian symbol.
    assert suffix_base_lookup_allowed("SHOP.TO") is False
    assert suffix_base_lookup_allowed("ABC.V") is False
