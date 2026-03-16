# -*- coding: utf-8 -*-
"""
Tests for src/services/stock_code_utils.py
Covers: is_code_like, normalize_code - including exchange prefix handling.
"""

import pytest

from src.services.stock_code_utils import is_code_like, normalize_code


class TestIsCodeLike:
    # --- Plain digit codes ---
    def test_plain_6_digit(self):
        assert is_code_like("600519") is True

    def test_plain_5_digit(self):
        assert is_code_like("00700") is True

    def test_4_digit_rejected(self):
        assert is_code_like("6001") is False

    # --- Suffix format ---
    def test_suffix_sh(self):
        assert is_code_like("600519.SH") is True

    def test_suffix_sz(self):
        assert is_code_like("000001.SZ") is True

    def test_suffix_lowercase(self):
        assert is_code_like("600519.sh") is True

    # --- Exchange prefix format (Issue #6 fix) ---
    def test_prefix_sh_upper(self):
        assert is_code_like("SH600519") is True

    def test_prefix_sh_lower(self):
        assert is_code_like("sh600519") is True

    def test_prefix_sz(self):
        assert is_code_like("SZ000001") is True

    def test_prefix_hk(self):
        assert is_code_like("HK00700") is True

    def test_prefix_hk_lower(self):
        assert is_code_like("hk00700") is True

    # --- US tickers ---
    def test_us_ticker(self):
        assert is_code_like("AAPL") is True

    def test_us_ticker_with_exchange(self):
        assert is_code_like("TSLA.O") is True

    # --- Negative cases ---
    def test_plain_text(self):
        assert is_code_like("贵州茅台") is False

    def test_empty(self):
        assert is_code_like("") is False

    def test_mixed_invalid(self):
        assert is_code_like("abc123") is False


class TestNormalizeCode:
    # --- Plain digit codes ---
    def test_plain_6_digit(self):
        assert normalize_code("600519") == "600519"

    def test_plain_5_digit(self):
        assert normalize_code("00700") == "00700"

    def test_whitespace_stripped(self):
        assert normalize_code("  600519  ") == "600519"

    # --- Suffix format ---
    def test_suffix_sh_strips(self):
        assert normalize_code("600519.SH") == "600519"

    def test_suffix_sz_strips(self):
        assert normalize_code("000001.SZ") == "000001"

    def test_suffix_ss_strips(self):
        assert normalize_code("600000.SS") == "600000"

    # --- Exchange prefix format (Issue #6 fix) ---
    def test_prefix_sh_upper(self):
        assert normalize_code("SH600519") == "600519"

    def test_prefix_sh_lower(self):
        assert normalize_code("sh600519") == "600519"

    def test_prefix_sz(self):
        assert normalize_code("SZ000001") == "000001"

    def test_prefix_hk(self):
        assert normalize_code("HK00700") == "00700"

    def test_prefix_hk_lower(self):
        assert normalize_code("hk00700") == "00700"

    # --- US tickers ---
    def test_us_ticker(self):
        assert normalize_code("AAPL") == "AAPL"

    # --- Invalid inputs ---
    def test_empty_returns_none(self):
        assert normalize_code("") is None

    def test_plain_text_returns_none(self):
        assert normalize_code("贵州茅台") is None

    def test_partial_prefix_no_digits_returns_none(self):
        # SH followed by wrong digit count
        assert normalize_code("SH6005") is None
