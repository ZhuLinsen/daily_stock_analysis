# -*- coding: utf-8 -*-
"""
data_provider/yfinance_fetcher 中加拿大指数获取与 CA 行情路由的单元测试

使用 unittest.mock 模拟 yfinance API 响应，覆盖（Issue #2420）：
- _get_ca_main_indices 加拿大指数批量获取（S&P/TSX Composite ^GSPTSE）
- 加拿大指数 Yahoo Finance 符号映射正确性
- 全部失败的降级场景（单一指数，部分失败 == 全部失败语义）
- get_main_indices(region='ca') 分发
- data_provider.base._is_ca_market 后缀判定（.TO 大小写不敏感 / .V 仅大写）
- YfinanceFetcher.get_realtime_quote 接受 CA suffix 代码并直传 Yahoo 符号
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

# 在导入 data_provider 前 mock 可能缺失的依赖，避免环境差异导致测试无法运行
if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

# 确保能导入项目模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_mock_hist(close: float, prev_close: float, high: float = None, low: float = None) -> pd.DataFrame:
    """构造模拟的 history DataFrame，包含计算涨跌幅所需字段"""
    high = high if high is not None else close + 100
    low = low if low is not None else close - 100
    return pd.DataFrame({
        'Close': [prev_close, close],
        'Open': [prev_close - 50, close - 30],
        'High': [prev_close + 100, high],
        'Low': [prev_close - 100, low],
        'Volume': [5000000000.0, 5200000000.0],
    }, index=pd.DatetimeIndex(['2025-02-16', '2025-02-17']))


def _make_mock_yf(hist_df: pd.DataFrame):
    """构造模拟的 yf 模块，Ticker().history() 返回给定 DataFrame"""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist_df
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    return mock_yf


class TestCaIndexSymbolMapping(unittest.TestCase):
    """验证加拿大指数 Yahoo Finance 符号映射的正确性"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_ca_indices_mapping_symbols(self):
        """加拿大指数映射应使用 ^GSPTSE（S&P/TSX Composite）"""
        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        self.fetcher._get_ca_main_indices(mock_yf)

        ticker_calls = [call.args[0] for call in mock_yf.Ticker.call_args_list]

        self.assertIn('^GSPTSE', ticker_calls, 'S&P/TSX Composite 应使用 ^GSPTSE')

    def test_ca_indices_no_invalid_symbols(self):
        """确保不使用错误的候选符号（复盘指数仅 S&P/TSX Composite，不做 TSXV/CSE 大盘）"""
        mock_yf = MagicMock()
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.Ticker.return_value = mock_ticker

        self.fetcher._get_ca_main_indices(mock_yf)

        ticker_calls = [call.args[0] for call in mock_yf.Ticker.call_args_list]

        self.assertNotIn('^TXSX', ticker_calls, '^TXSX 不是本仓库约定的 TSX Composite 符号')
        self.assertNotIn('GSPTSE.TO', ticker_calls, '指数不应走股票后缀形态')
        self.assertNotIn('^JNX', ticker_calls, 'CSE 综合指数不在 #2420 范围内')


class TestGetCaMainIndices(unittest.TestCase):
    """_get_ca_main_indices 加拿大指数批量获取测试"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_returns_list_when_succeed(self):
        """指数取数成功时返回包含 S&P/TSX Composite 的列表"""
        mock_hist = _make_mock_hist(close=25000.0, prev_close=24800.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_ca_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

        codes = {item['code'] for item in result}
        self.assertEqual(codes, {'GSPTSE'})

        for item in result:
            self.assertIn('code', item)
            self.assertIn('name', item)
            self.assertIn('current', item)
            self.assertIn('change_pct', item)
            self.assertIn('prev_close', item)
            self.assertIn('amplitude', item)

    def test_return_name_mentions_tsx_composite(self):
        """显示名称应标明 S&P/TSX Composite"""
        mock_hist = _make_mock_hist(close=25000.0, prev_close=24800.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_ca_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIn('S&P/TSX', result[0]['name'])

    def test_returns_correct_computed_values(self):
        """验证涨跌幅和振幅的计算结果"""
        mock_hist = _make_mock_hist(
            close=25000.0, prev_close=24800.0, high=25200.0, low=24700.0
        )
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_ca_main_indices(mock_yf)

        self.assertIsNotNone(result)
        item = result[0]
        self.assertEqual(item['current'], 25000.0)
        self.assertEqual(item['prev_close'], 24800.0)
        self.assertAlmostEqual(item['change'], 200.0)
        expected_pct = (200.0 / 24800.0) * 100
        self.assertAlmostEqual(item['change_pct'], expected_pct)
        expected_amplitude = ((25200.0 - 24700.0) / 24800.0) * 100
        self.assertAlmostEqual(item['amplitude'], expected_amplitude)

    def test_returns_none_when_fail(self):
        """history 为空（全部失败——单一指数时部分失败即全部失败）时返回 None"""
        mock_yf = _make_mock_yf(pd.DataFrame())

        result = self.fetcher._get_ca_main_indices(mock_yf)

        self.assertIsNone(result)

    def test_handles_ticker_exception(self):
        """Ticker.history 抛异常时不整体崩溃，返回 None"""
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("Network error")
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        result = self.fetcher._get_ca_main_indices(mock_yf)

        self.assertIsNone(result)

    def test_return_code_matches_mood_index(self):
        """返回的 code 字段应为 GSPTSE，与 CA_PROFILE.mood_index_code 一致"""
        from src.core.market_profile import get_profile

        mock_hist = _make_mock_hist(close=25000.0, prev_close=24800.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_ca_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIn(get_profile('ca').mood_index_code, [item['code'] for item in result])


class TestGetMainIndicesDispatch(unittest.TestCase):
    """get_main_indices region 分发测试"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_region_ca_dispatches_to_ca_method(self):
        """region='ca' 应委托给 _get_ca_main_indices"""
        mock_yf = MagicMock()
        with patch.dict('sys.modules', {'yfinance': mock_yf}):
            with patch.object(
                self.fetcher, '_get_ca_main_indices', return_value=[{'code': 'GSPTSE'}]
            ) as mock_ca:
                result = self.fetcher.get_main_indices(region='ca')

                mock_ca.assert_called_once()
                self.assertEqual(result, [{'code': 'GSPTSE'}])


class TestBaseCaMarketRouting(unittest.TestCase):
    """data_provider.base 的 CA 市场判定与路由测试"""

    def test_is_ca_market_suffix_rules(self):
        """.TO 大小写不敏感；.V 仅大写形态视为 TSXV；与既有后缀不冲突"""
        from data_provider.base import _is_ca_market

        # TSX .TO：大小写不敏感
        self.assertTrue(_is_ca_market('SHOP.TO'))
        self.assertTrue(_is_ca_market('shop.to'))
        self.assertTrue(_is_ca_market('BANK.TO'))
        # TSXV .V：仅大写形态
        self.assertTrue(_is_ca_market('SHOP.V'))
        self.assertFalse(_is_ca_market('shop.v'), '小写 .v 不得误判为 TSXV')
        self.assertFalse(_is_ca_market('Shop.v'), '混合大小写 .v 不得误判为 TSXV')
        # base 必须是字母 ticker
        self.assertFalse(_is_ca_market('7203.TO'))
        self.assertFalse(_is_ca_market('7203.T'), '日股后缀不受影响')
        self.assertFalse(_is_ca_market('005930.KS'), '韩股后缀不受影响')
        self.assertFalse(_is_ca_market('2330.TW'), '台股后缀不受影响')
        # 与美股形态不冲突
        self.assertFalse(_is_ca_market('AAPL'))
        self.assertFalse(_is_ca_market('BRK.B'), '美股单字母分类后缀 .B 不受影响')
        self.assertFalse(_is_ca_market('SHOP.U'), '.U 不在本期 CA 范围')
        self.assertFalse(_is_ca_market('600519'))

    def test_convert_stock_code_preserves_ca_suffix(self):
        """YfinanceFetcher 应将 CA suffix 代码原样传给 Yahoo"""
        from data_provider.yfinance_fetcher import YfinanceFetcher

        fetcher = YfinanceFetcher()
        self.assertEqual(fetcher._convert_stock_code('SHOP.TO'), 'SHOP.TO')
        self.assertEqual(fetcher._convert_stock_code('SHOP.V'), 'SHOP.V')

    def test_get_realtime_quote_accepts_ca_codes(self):
        """get_realtime_quote 应接受 CA suffix 代码并返回行情（不被市场门槛拦截）"""
        from data_provider.yfinance_fetcher import YfinanceFetcher

        fetcher = YfinanceFetcher()

        mock_fast_info = MagicMock()
        mock_fast_info.lastPrice = 120.0
        mock_fast_info.previousClose = 118.0
        mock_fast_info.open = 119.0
        mock_fast_info.dayHigh = 121.0
        mock_fast_info.dayLow = 117.5
        mock_fast_info.lastVolume = 1000000
        mock_fast_info.marketCap = 10000000000
        mock_ticker = MagicMock()
        mock_ticker.fast_info = mock_fast_info
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict('sys.modules', {'yfinance': mock_yf}):
            for code in ('SHOP.TO', 'SHOP.V'):
                quote = fetcher.get_realtime_quote(code)
                self.assertIsNotNone(quote, f'{code} 应走 yfinance 路径返回行情')
                self.assertEqual(quote.code, code)
                self.assertEqual(quote.market, 'ca')


if __name__ == '__main__':
    unittest.main()
