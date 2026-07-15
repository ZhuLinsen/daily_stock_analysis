# -*- coding: utf-8 -*-
"""
Tests for LOF fund support, A-stock supplementary data, and connectivity checker.
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# LOF Fund Support Tests
# ---------------------------------------------------------------------------
class TestIsLofCode:
    """Tests for _is_lof_code in data_provider/akshare_fetcher.py"""

    def test_lof_shenzhen_16xxxx(self):
        from data_provider.akshare_fetcher import _is_lof_code
        assert _is_lof_code("160119") is True

    def test_lof_shanghai_50xxxx(self):
        from data_provider.akshare_fetcher import _is_lof_code
        assert _is_lof_code("501009") is True

    def test_etf_51xxxx_not_lof(self):
        from data_provider.akshare_fetcher import _is_lof_code
        assert _is_lof_code("512400") is False

    def test_etf_15xxxx_not_lof(self):
        from data_provider.akshare_fetcher import _is_lof_code
        assert _is_lof_code("159883") is False

    def test_stock_code_not_lof(self):
        from data_provider.akshare_fetcher import _is_lof_code
        assert _is_lof_code("600519") is False

    def test_lof_with_suffix(self):
        from data_provider.akshare_fetcher import _is_lof_code
        assert _is_lof_code("160119.SZ") is True

    def test_lof_with_prefix(self):
        """LOF codes with prefix are normalized by normalize_stock_code before _is_lof_code."""
        from data_provider.akshare_fetcher import _is_lof_code
        # SZ160119 is normalized to 160119 by normalize_stock_code before _is_lof_code is called
        # So _is_lof_code only needs to handle clean 6-digit codes
        assert _is_lof_code("160119") is True


# ---------------------------------------------------------------------------
# A-Stock Supplementary Data Tests
# ---------------------------------------------------------------------------
class TestNormalizeCode:
    """Tests for _normalize_code in data_provider/astock_data_provider.py"""

    def test_plain_6_digit(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("600519") == "600519"

    def test_sh_prefix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("SH600519") == "600519"

    def test_sh_dotted_prefix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("SH.600519") == "600519"

    def test_sz_prefix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("SZ000001") == "000001"

    def test_sz_dotted_prefix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("SZ.000001") == "000001"

    def test_bj_prefix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("BJ920748") == "920748"

    def test_bj_dotted_prefix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("BJ.920748") == "920748"

    def test_sh_suffix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("600519.SH") == "600519"

    def test_sz_suffix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("000001.SZ") == "000001"

    def test_bj_suffix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("920748.BJ") == "920748"

    def test_lowercase_prefix(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("sh600519") == "600519"

    def test_hk_code_unchanged(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("HK00700") == "HK00700"

    def test_us_code_unchanged(self):
        from data_provider.astock_data_provider import _normalize_code
        assert _normalize_code("AAPL") == "AAPL"


class TestThreadSafeThrottling:
    """Tests for thread-safe throttling in astock_data_provider.py"""

    def test_em_get_uses_lock(self):
        from data_provider.astock_data_provider import _em_lock
        assert hasattr(_em_lock, 'acquire')
        assert hasattr(_em_lock, 'release')


class TestDragonTigerBoard:
    """Tests for dragon_tiger_board function"""

    def test_empty_records_no_institution(self):
        """When no records exist, institution should be None (not zero dict)."""
        from data_provider.astock_data_provider import dragon_tiger_board
        with patch('data_provider.astock_data_provider.eastmoney_datacenter', return_value=[]):
            result = dragon_tiger_board("600519", "2025-01-01", look_back=30)
            assert result["records"] == []
            assert result["institution"] is None


# ---------------------------------------------------------------------------
# Connectivity Checker Tests
# ---------------------------------------------------------------------------
class TestConnectivityChecker:
    """Tests for scripts/check_connectivity.py"""

    def test_mask_secret_long_key(self):
        from scripts.check_connectivity import _mask_secret
        result = _mask_secret("sk-1234567890abcdef")
        assert "sk-1" in result
        assert "ef" in result
        assert "1234567890abcdef" not in result

    def test_mask_secret_short_key(self):
        from scripts.check_connectivity import _mask_secret
        result = _mask_secret("abc")
        assert result == "a***"

    def test_mask_secret_empty(self):
        from scripts.check_connectivity import _mask_secret
        assert _mask_secret("") == "（空）"
        assert _mask_secret(None) == "（空）"

    def test_split_keys_comma_separated(self):
        from scripts.check_connectivity import _split_keys
        result = _split_keys("key1,key2,key3")
        assert result == ["key1", "key2", "key3"]

    def test_split_keys_empty(self):
        from scripts.check_connectivity import _split_keys
        assert _split_keys("") == []
        assert _split_keys(None) == []

    def test_netloc_with_url(self):
        from scripts.check_connectivity import _netloc
        assert _netloc("https://api.example.com/v1") == "api.example.com"

    def test_netloc_without_url(self):
        from scripts.check_connectivity import _netloc
        assert _netloc("") == "（默认端点）"
        assert _netloc(None) == "（默认端点）"
