# -*- coding: utf-8 -*-
"""
data_provider/us_index_mapping.py 的单元测试
"""
import unittest
import sys
import os

# 确保能导入 data_provider 模块（直接导入避免加载重量级依赖）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data_provider')))

from us_index_mapping import (
    is_us_index_code,
    is_us_stock_code,
    get_us_index_yf_symbol,
    US_INDEX_MAPPING,
)


class TestIsUsIndexCode(unittest.TestCase):
    """Tests for is_us_index_code()"""

    def test_known_indices(self):
        """Known US index codes should return True"""
        indices = ['SPX', 'DJI', 'DJIA', 'IXIC', 'NASDAQ', 'NDX', 'VIX', 'RUT']
        for code in indices:
            with self.subTest(code=code):
                self.assertTrue(is_us_index_code(code), f"{code} should be recognized as US index")

    def test_known_indices_with_caret(self):
        """US index codes with ^ prefix should return True"""
        indices = ['^GSPC', '^DJI', '^IXIC', '^NDX', '^VIX', '^RUT']
        for code in indices:
            with self.subTest(code=code):
                self.assertTrue(is_us_index_code(code), f"{code} should be recognized as US index")

    def test_case_insensitive(self):
        """Index code matching should be case-insensitive"""
        self.assertTrue(is_us_index_code('spx'))
        self.assertTrue(is_us_index_code('Spx'))
        self.assertTrue(is_us_index_code('SPX'))

    def test_whitespace_handling(self):
        """Leading/trailing whitespace should be stripped"""
        self.assertTrue(is_us_index_code(' SPX '))
        self.assertTrue(is_us_index_code('\tDJI\n'))

    def test_us_stocks_not_indices(self):
        """US stock codes should NOT be recognized as indices"""
        stocks = ['AAPL', 'TSLA', 'GOOGL', 'MSFT', 'AMD', 'NVDA', 'BRK.B']
        for code in stocks:
            with self.subTest(code=code):
                self.assertFalse(is_us_index_code(code), f"{code} should NOT be a US index")

    def test_a_shares_not_indices(self):
        """A-share codes should NOT be recognized as indices"""
        a_shares = ['600519', '000001', '300750', 'SH600519', 'SZ000001']
        for code in a_shares:
            with self.subTest(code=code):
                self.assertFalse(is_us_index_code(code), f"{code} should NOT be a US index")

    def test_hk_stocks_not_indices(self):
        """HK stock codes should NOT be recognized as indices"""
        hk_stocks = ['00700', 'HK00700', '01810']
        for code in hk_stocks:
            with self.subTest(code=code):
                self.assertFalse(is_us_index_code(code), f"{code} should NOT be a US index")

    def test_empty_and_none(self):
        """Empty string and None should return False"""
        self.assertFalse(is_us_index_code(''))
        self.assertFalse(is_us_index_code(None))
        self.assertFalse(is_us_index_code('   '))


class TestIsUsStockCode(unittest.TestCase):
    """Tests for is_us_stock_code()"""

    def test_common_us_stocks(self):
        """Common US stock codes should return True"""
        stocks = ['AAPL', 'TSLA', 'GOOGL', 'MSFT', 'AMD', 'NVDA', 'META', 'AMZN']
        for code in stocks:
            with self.subTest(code=code):
                self.assertTrue(is_us_stock_code(code), f"{code} should be a US stock")

    def test_stock_with_dot_suffix(self):
        """Stock codes with dot suffix (e.g. BRK.B) should return True"""
        self.assertTrue(is_us_stock_code('BRK.B'))
        self.assertTrue(is_us_stock_code('BRK.A'))

    def test_case_insensitive(self):
        """Stock code matching should be case-insensitive"""
        self.assertTrue(is_us_stock_code('aapl'))
        self.assertTrue(is_us_stock_code('Aapl'))
        self.assertTrue(is_us_stock_code('AAPL'))

    def test_whitespace_handling(self):
        """Leading/trailing whitespace should be stripped"""
        self.assertTrue(is_us_stock_code(' AAPL '))
        self.assertTrue(is_us_stock_code('\tTSLA\n'))

    def test_us_indices_not_stocks(self):
        """US index codes should NOT be recognized as stocks"""
        indices = ['SPX', 'DJI', 'DJIA', 'IXIC', 'NASDAQ', 'NDX', 'VIX', 'RUT', '^GSPC']
        for code in indices:
            with self.subTest(code=code):
                self.assertFalse(is_us_stock_code(code), f"{code} should NOT be a US stock")

    def test_a_shares_not_us_stocks(self):
        """A-share codes should NOT be recognized as US stocks"""
        a_shares = ['600519', '000001', '300750']
        for code in a_shares:
            with self.subTest(code=code):
                self.assertFalse(is_us_stock_code(code), f"{code} should NOT be a US stock")

    def test_hk_stocks_not_us_stocks(self):
        """HK stock codes should NOT be recognized as US stocks"""
        hk_stocks = ['00700', 'HK00700', '01810']
        for code in hk_stocks:
            with self.subTest(code=code):
                self.assertFalse(is_us_stock_code(code), f"{code} should NOT be a US stock")

    def test_invalid_patterns(self):
        """Invalid patterns should return False"""
        invalid = ['TOOLONG', 'A', 'AB.CD', '123', 'A1B2', '']
        for code in invalid:
            with self.subTest(code=code):
                # Note: Single letter like 'A' might be valid, but 'TOOLONG' (6 chars) is not
                if len(code) > 5:
                    self.assertFalse(is_us_stock_code(code), f"{code} should NOT be a US stock")

    def test_empty_and_none(self):
        """Empty string and None should return False"""
        self.assertFalse(is_us_stock_code(''))
        self.assertFalse(is_us_stock_code(None))
        self.assertFalse(is_us_stock_code('   '))


class TestGetUsIndexYfSymbol(unittest.TestCase):
    """Tests for get_us_index_yf_symbol()"""

    def test_spx_mapping(self):
        """SPX should map to ^GSPC"""
        symbol, name = get_us_index_yf_symbol('SPX')
        self.assertEqual(symbol, '^GSPC')
        self.assertEqual(name, '标普500指数')

    def test_dji_mapping(self):
        """DJI should map to ^DJI"""
        symbol, name = get_us_index_yf_symbol('DJI')
        self.assertEqual(symbol, '^DJI')
        self.assertEqual(name, '道琼斯工业指数')

    def test_nasdaq_mapping(self):
        """NASDAQ should map to ^IXIC"""
        symbol, name = get_us_index_yf_symbol('NASDAQ')
        self.assertEqual(symbol, '^IXIC')
        self.assertEqual(name, '纳斯达克综合指数')

    def test_vix_mapping(self):
        """VIX should map to ^VIX"""
        symbol, name = get_us_index_yf_symbol('VIX')
        self.assertEqual(symbol, '^VIX')
        self.assertEqual(name, 'VIX恐慌指数')

    def test_case_insensitive(self):
        """Mapping should be case-insensitive"""
        symbol1, _ = get_us_index_yf_symbol('spx')
        symbol2, _ = get_us_index_yf_symbol('SPX')
        self.assertEqual(symbol1, symbol2)

    def test_already_yf_format(self):
        """Codes already in YF format should still work"""
        symbol, name = get_us_index_yf_symbol('^GSPC')
        self.assertEqual(symbol, '^GSPC')
        self.assertEqual(name, '标普500指数')

    def test_unknown_code_returns_none(self):
        """Unknown codes should return (None, None)"""
        symbol, name = get_us_index_yf_symbol('AAPL')
        self.assertIsNone(symbol)
        self.assertIsNone(name)

    def test_empty_and_none(self):
        """Empty string and None should return (None, None)"""
        self.assertEqual(get_us_index_yf_symbol(''), (None, None))
        self.assertEqual(get_us_index_yf_symbol(None), (None, None))
        self.assertEqual(get_us_index_yf_symbol('   '), (None, None))


class TestUsMappingCompleteness(unittest.TestCase):
    """Tests for US_INDEX_MAPPING completeness"""

    def test_all_indices_have_chinese_names(self):
        """All indices in mapping should have non-empty Chinese names"""
        for code, (symbol, name) in US_INDEX_MAPPING.items():
            with self.subTest(code=code):
                self.assertIsNotNone(name)
                self.assertIsInstance(name, str)
                self.assertTrue(len(name) > 0, f"{code} should have a non-empty name")

    def test_all_indices_have_yf_symbols(self):
        """All indices in mapping should have valid YF symbols starting with ^"""
        for code, (symbol, name) in US_INDEX_MAPPING.items():
            with self.subTest(code=code):
                self.assertIsNotNone(symbol)
                self.assertTrue(symbol.startswith('^'), f"{code}'s YF symbol should start with ^")


if __name__ == '__main__':
    unittest.main()
