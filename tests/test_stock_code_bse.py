# -*- coding: utf-8 -*-
"""
Unit tests for BSE (Beijing Stock Exchange) code recognition (Issue #491).

Covers:
- is_bse_code()
- normalize_stock_code() BJ prefix/suffix
- TushareFetcher._convert_stock_code() BSE branch
- AkshareFetcher _to_sina_tx_symbol() BSE and Shanghai B-share handling
"""
import sys
import unittest
from unittest.mock import MagicMock

# Provide lightweight stubs so importing data_provider.base does not require
# full LLM runtime dependencies in minimal CI.
if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

# Core imports (should stay runnable even when optional data-source deps are absent)
try:
    from data_provider.base import is_bse_code, normalize_stock_code
    _BASE_IMPORTS_OK = True
    _BASE_IMPORT_ERROR = ""
except ImportError as e:
    _BASE_IMPORTS_OK = False
    _BASE_IMPORT_ERROR = str(e)

# Optional fetcher-specific imports
try:
    from data_provider.tushare_fetcher import TushareFetcher
    _TUSHARE_IMPORTS_OK = True
    _TUSHARE_IMPORT_ERROR = ""
except ImportError as e:
    _TUSHARE_IMPORTS_OK = False
    _TUSHARE_IMPORT_ERROR = str(e)

try:
    from data_provider.akshare_fetcher import _to_sina_tx_symbol
    _AKSHARE_IMPORTS_OK = True
    _AKSHARE_IMPORT_ERROR = ""
except ImportError as e:
    _AKSHARE_IMPORTS_OK = False
    _AKSHARE_IMPORT_ERROR = str(e)


@unittest.skipIf(not _BASE_IMPORTS_OK, f"base imports failed: {_BASE_IMPORT_ERROR}")
class TestIsBseCode(unittest.TestCase):
    """Tests for is_bse_code()."""

    def test_bse_new_format(self):
        """920xxx (BSE new format) should return True."""
        self.assertTrue(is_bse_code("920748"))
        self.assertTrue(is_bse_code("921000"))

    def test_bse_old_format_8(self):
        """8xxxxx (BSE old format) should return True."""
        self.assertTrue(is_bse_code("838163"))
        self.assertTrue(is_bse_code("830799"))

    def test_bse_old_format_4(self):
        """4xxxxx (BSE old format) should return True."""
        self.assertTrue(is_bse_code("430047"))

    def test_shanghai_b_shares_not_bse(self):
        """900xxx (Shanghai B-shares) must return False - critical regression case."""
        self.assertFalse(is_bse_code("900901"))
        self.assertFalse(is_bse_code("900906"))

    def test_shanghai_shenzhen_not_bse(self):
        """Shanghai/Shenzhen A-shares should return False."""
        self.assertFalse(is_bse_code("600519"))
        self.assertFalse(is_bse_code("000001"))
        self.assertFalse(is_bse_code("300750"))

    def test_etf_not_bse(self):
        """ETF codes should return False."""
        self.assertFalse(is_bse_code("512400"))
        self.assertFalse(is_bse_code("159919"))

    def test_with_suffix(self):
        """Code with .BJ suffix should still be recognized."""
        self.assertTrue(is_bse_code("920748.BJ"))


@unittest.skipIf(not _BASE_IMPORTS_OK, "base imports failed")
class TestNormalizeStockCode(unittest.TestCase):
    """Tests for normalize_stock_code() BJ support."""

    def test_bj_suffix(self):
        """920748.BJ should normalize to 920748."""
        self.assertEqual(normalize_stock_code("920748.BJ"), "920748")

    def test_bj_prefix(self):
        """BJ920748 should normalize to 920748."""
        self.assertEqual(normalize_stock_code("BJ920748"), "920748")
        self.assertEqual(normalize_stock_code("bj920748"), "920748")

    def test_hk_suffix_normalized_to_canonical_prefix(self):
        """港股 .HK 后缀格式应归一为 HK+5 位数字。"""
        self.assertEqual(normalize_stock_code("1810.HK"), "HK01810")
        self.assertEqual(normalize_stock_code("0700.hk"), "HK00700")

    def test_hk_prefix_is_zero_padded(self):
        """HK 前缀的短数字格式应补足到 5 位，便于后续缓存与去重。"""
        self.assertEqual(normalize_stock_code("hk1810"), "HK01810")
        self.assertEqual(normalize_stock_code("HK700"), "HK00700")


@unittest.skipIf(not _TUSHARE_IMPORTS_OK, f"tushare fetcher imports failed: {_TUSHARE_IMPORT_ERROR}")
class TestTushareConvertStockCode(unittest.TestCase):
    """Tests for TushareFetcher._convert_stock_code() BSE branch."""

    def test_bse_returns_bj_suffix(self):
        """BSE codes should convert to xxx.BJ."""
        fetcher = TushareFetcher()
        self.assertEqual(fetcher._convert_stock_code("920748"), "920748.BJ")
        self.assertEqual(fetcher._convert_stock_code("838163"), "838163.BJ")
        self.assertEqual(fetcher._convert_stock_code("430047"), "430047.BJ")

    def test_bse_explicit_exchange_hint_is_preserved(self):
        """BSE prefix/suffix forms should keep the BJ Tushare ts_code."""
        fetcher = TushareFetcher()
        self.assertEqual(fetcher._convert_stock_code("920493.BJ"), "920493.BJ")
        self.assertEqual(fetcher._convert_stock_code("BJ920493"), "920493.BJ")


@unittest.skipIf(not _AKSHARE_IMPORTS_OK, f"akshare fetcher imports failed: {_AKSHARE_IMPORT_ERROR}")
class TestAkshareToSinaTxSymbol(unittest.TestCase):
    """Tests for _to_sina_tx_symbol() BSE and Shanghai B-share handling."""

    def test_bse_returns_bj_prefix(self):
        """BSE codes should get bj prefix."""
        self.assertEqual(_to_sina_tx_symbol("920748"), "bj920748")
        self.assertEqual(_to_sina_tx_symbol("838163"), "bj838163")

    def test_shanghai_b_share_not_regression(self):
        """900xxx (Shanghai B-shares) must map to sh - critical regression case."""
        self.assertEqual(_to_sina_tx_symbol("900901"), "sh900901")
        self.assertEqual(_to_sina_tx_symbol("900906"), "sh900906")

    def test_shanghai_shenzhen(self):
        """Shanghai/Shenzhen should map correctly."""
        self.assertEqual(_to_sina_tx_symbol("600519"), "sh600519")
        self.assertEqual(_to_sina_tx_symbol("000001"), "sz000001")
        self.assertEqual(_to_sina_tx_symbol("512400"), "sh512400")

    def test_with_suffix_strips_correctly(self):
        """Code with .BJ suffix should produce bj + base, not bj + full."""
        self.assertEqual(_to_sina_tx_symbol("920748.BJ"), "bj920748")


if __name__ == "__main__":
    unittest.main()
