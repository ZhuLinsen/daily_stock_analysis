# -*- coding: utf-8 -*-
"""指数日线历史能力（Issue #1584 复盘工作台均线计算）单元测试。

覆盖：
1. A 股指数代码归一化白名单（避免 000001 指数/个股歧义）
2. DataFetcherManager 数据源链、共享缓存与全失败兜底（绝不抛出）
3. Akshare 东财主源 + 新浪兜底
4. Tushare index_daily 映射
5. Yfinance 各市场符号解析与历史归一化
"""

import sys
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_provider.base import DataFetcherManager  # noqa: E402
from data_provider.index_symbols import cn_index_sina_symbol, normalize_cn_index_code  # noqa: E402


def test_normalize_cn_index_code_variants():
    assert normalize_cn_index_code('sh000001') == '000001'
    assert normalize_cn_index_code('SH000001') == '000001'
    assert normalize_cn_index_code('000001') == '000001'
    assert normalize_cn_index_code('000001.SH') == '000001'
    assert normalize_cn_index_code('000001.SS') == '000001'
    assert normalize_cn_index_code('sz399006') == '399006'
    # 个股/未知代码一律拒绝，不得回退到个股行情
    assert normalize_cn_index_code('600519') is None
    assert normalize_cn_index_code('') is None
    assert normalize_cn_index_code(None) is None
    assert cn_index_sina_symbol('000300') == 'sh000300'
    assert cn_index_sina_symbol('600519') is None


def _make_manager(fetchers):
    manager = DataFetcherManager.__new__(DataFetcherManager)
    manager._fetchers = fetchers
    manager._ensure_concurrency_guards()
    return manager


def _fresh_bars(n, end_offset_days=0, start_close=3000.0):
    """生成截至（今天 - end_offset_days）的 n 根连续日线，避免固定日期时间炸弹。"""
    from datetime import datetime, timedelta

    end = datetime.now() - timedelta(days=end_offset_days)
    return [
        {
            'date': (end - timedelta(days=n - 1 - i)).strftime('%Y-%m-%d'),
            'close': start_close + i,
        }
        for i in range(n)
    ]


def test_manager_chain_fallback_and_cache():
    DataFetcherManager.clear_index_history_cache_for_tests()
    calls = {'good': 0}
    fresh = _fresh_bars(25)

    def failing(code, region='cn', days=40):
        raise RuntimeError('boom')

    def good(code, region='cn', days=40):
        calls['good'] += 1
        return list(fresh)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=failing),
        SimpleNamespace(name='F2', get_index_daily_history=good),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=20)
    assert bars == fresh
    assert calls['good'] == 1

    # 第二次命中共享缓存，不再触发抓取
    bars_cached = manager.get_index_daily_history('sh000001', region='cn', days=20)
    assert bars_cached == bars
    assert calls['good'] == 1
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_continues_fallback_when_first_source_unusable_short():
    """PR #1888 评审回归：首源非空但条数不足以计算均线时，
    不得终止链，应继续尝试并采纳次源的完整历史。"""
    DataFetcherManager.clear_index_history_cache_for_tests()
    full = _fresh_bars(40)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: _fresh_bars(1)),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: list(full)),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == full
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_continues_fallback_when_first_source_stale():
    """首源返回停更旧数据（镜像故障）时继续 fallback，采纳新鲜历史。"""
    DataFetcherManager.clear_index_history_cache_for_tests()
    fresh = _fresh_bars(40)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: _fresh_bars(40, end_offset_days=30)),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: list(fresh)),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == fresh
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_prefers_full_history_over_partial_first_source():
    """两级质量门回归：首源仅够 MA5/10 的 partial 历史（如 6 根）不得挡住
    次源的完整历史，否则 MA20 被不必要省略——与评审指出的缺陷同类。"""
    DataFetcherManager.clear_index_history_cache_for_tests()
    full = _fresh_bars(40)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: _fresh_bars(6)),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: list(full)),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == full
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_partial_only_chain_returns_partial_fail_open():
    """全链只有 partial 历史（如新指数）时按最优候选返回，
    消费方照常计算 MA5/10 并记录 MA20 缺失。"""
    DataFetcherManager.clear_index_history_cache_for_tests()
    partial = _fresh_bars(8)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: list(partial)),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: _fresh_bars(1)),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == partial
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_prefers_fresh_partial_over_larger_stale():
    """择优序回归：新鲜的 partial（可算 MA5/10）优于更长但停更的历史（什么都算不了）。"""
    DataFetcherManager.clear_index_history_cache_for_tests()
    fresh_partial = _fresh_bars(8)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: _fresh_bars(40, end_offset_days=30)),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: list(fresh_partial)),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == fresh_partial
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_prefers_recency_over_bar_count_within_fresh_window():
    """对抗审查回归：同为新鲜档（15 天容忍内）时，末根更近者优先——
    滞后 12 天的镜像即使条数更多，其历史缺少中间交易日，消费方会算出
    失真均线且标记 ok；必须选择截至今天的诚实 partial。"""
    DataFetcherManager.clear_index_history_cache_for_tests()
    fresh_today = _fresh_bars(8)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: _fresh_bars(19, end_offset_days=12)),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: list(fresh_today)),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == fresh_today
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_quality_gate_constants_mirror_consumer_contract():
    """drift guard：base.py 的质量门阈值与消费方契约是手工镜像的两组常量，
    钉住等值关系，防止一侧调整后另一侧静默漂移。"""
    from src.core import market_review_workbench as workbench

    assert (
        DataFetcherManager._INDEX_HISTORY_MAX_STALE_DAYS
        == workbench._STALE_HISTORY_DAYS
    )
    # partial 档下限 = 最小均线窗口（MA5）；full 档 = 最大均线窗口（MA20）
    assert DataFetcherManager._INDEX_HISTORY_MIN_USABLE_BARS == 5
    assert DataFetcherManager._INDEX_HISTORY_FULL_BARS == 20


def test_manager_full_tier_scales_with_requested_days():
    """days<20 的请求以请求条数为 full 标准：10 根满足 days=10 即接受并终止链，
    不再全链扫描，且享受完整 TTL。"""
    import time as time_module

    DataFetcherManager.clear_index_history_cache_for_tests()
    ten = _fresh_bars(10)
    calls = {'second': 0}

    def second(*a, **k):
        calls['second'] += 1
        return _fresh_bars(40)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: list(ten)),
        SimpleNamespace(name='F2', get_index_daily_history=second),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=10)
    assert bars == ten
    assert calls['second'] == 0

    cache_entries = list(DataFetcherManager._index_history_cache.values())
    assert len(cache_entries) == 1
    remaining = cache_entries[0][0] - time_module.monotonic()
    assert remaining > DataFetcherManager._INDEX_HISTORY_EMPTY_CACHE_TTL_SECONDS + 1
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_returns_best_effort_with_short_ttl_when_all_unusable():
    """全链均不可用时按最优候选 fail-open 返回（消费方判 insufficient/stale），
    且只用短 TTL 缓存，避免锁定降级结果 30 分钟。"""
    import time as time_module

    DataFetcherManager.clear_index_history_cache_for_tests()
    three = _fresh_bars(3)

    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: list(three)),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: _fresh_bars(1)),
    ])
    bars = manager.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == three

    cache_entries = list(DataFetcherManager._index_history_cache.values())
    assert len(cache_entries) == 1
    expiry, _ = cache_entries[0]
    remaining = expiry - time_module.monotonic()
    assert remaining <= DataFetcherManager._INDEX_HISTORY_EMPTY_CACHE_TTL_SECONDS + 1
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_all_sources_fail_returns_empty_without_raising():
    DataFetcherManager.clear_index_history_cache_for_tests()
    manager = _make_manager([
        SimpleNamespace(name='F1', get_index_daily_history=lambda *a, **k: None),
        SimpleNamespace(name='F2', get_index_daily_history=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('x'))),
    ])
    assert manager.get_index_daily_history('sh000001', region='cn') == []
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_manager_skips_fetchers_without_capability():
    DataFetcherManager.clear_index_history_cache_for_tests()
    fresh = _fresh_bars(25)
    manager = _make_manager([
        SimpleNamespace(name='NoCap'),
        SimpleNamespace(
            name='F2',
            get_index_daily_history=lambda code, region='cn', days=40: list(fresh),
        ),
    ])
    assert manager.get_index_daily_history('sh000001') == fresh
    DataFetcherManager.clear_index_history_cache_for_tests()


# ---------------------------------------------------------------------------
# Akshare
# ---------------------------------------------------------------------------

def _make_akshare_fetcher():
    from data_provider.akshare_fetcher import AkshareFetcher
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    return fetcher


def _em_history_frame(days=30):
    dates = pd.date_range('2026-05-01', periods=days, freq='D')
    return pd.DataFrame({
        '日期': [d.strftime('%Y-%m-%d') for d in dates],
        '收盘': [3300.0 + i for i in range(days)],
        '开盘': [3290.0 + i for i in range(days)],
    })


def test_akshare_index_history_em_primary():
    fetcher = _make_akshare_fetcher()
    mock_ak = MagicMock()
    mock_ak.index_zh_a_hist.return_value = _em_history_frame(30)
    with patch.dict(sys.modules, {'akshare': mock_ak}):
        bars = fetcher.get_index_daily_history('sh000001', region='cn', days=20)
    assert len(bars) == 20
    assert bars[0]['date'] < bars[-1]['date']
    assert bars[-1]['close'] == 3329.0
    # 东财接口按纯数字代码调用
    assert mock_ak.index_zh_a_hist.call_args.kwargs['symbol'] == '000001'


def test_akshare_index_history_sina_fallback():
    fetcher = _make_akshare_fetcher()
    mock_ak = MagicMock()
    mock_ak.index_zh_a_hist.side_effect = RuntimeError('em down')
    mock_ak.stock_zh_index_daily.return_value = pd.DataFrame({
        'date': ['2026-06-30', '2026-07-01'],
        'close': [3390.0, 3400.0],
    })
    with patch.dict(sys.modules, {'akshare': mock_ak}):
        bars = fetcher.get_index_daily_history('000300', region='cn', days=40)
    assert bars == [
        {'date': '2026-06-30', 'close': 3390.0},
        {'date': '2026-07-01', 'close': 3400.0},
    ]
    assert mock_ak.stock_zh_index_daily.call_args.kwargs['symbol'] == 'sh000300'


def test_akshare_index_history_rejects_non_index_and_foreign_region():
    fetcher = _make_akshare_fetcher()
    assert fetcher.get_index_daily_history('600519', region='cn') is None
    assert fetcher.get_index_daily_history('sh000001', region='us') is None


# ---------------------------------------------------------------------------
# Tushare
# ---------------------------------------------------------------------------

def test_tushare_index_history_mapping_and_order():
    from data_provider.tushare_fetcher import TushareFetcher

    fetcher = TushareFetcher.__new__(TushareFetcher)
    fetcher._check_rate_limit = lambda: None
    mock_api = MagicMock()
    mock_api.index_daily.return_value = pd.DataFrame({
        'trade_date': ['20260702', '20260701', '20260630'],
        'close': [3400.0, 3390.0, 3380.0],
    })
    fetcher._api = mock_api

    bars = fetcher.get_index_daily_history('sh000001', region='cn', days=40)
    assert bars == [
        {'date': '2026-06-30', 'close': 3380.0},
        {'date': '2026-07-01', 'close': 3390.0},
        {'date': '2026-07-02', 'close': 3400.0},
    ]
    assert mock_api.index_daily.call_args.kwargs['ts_code'] == '000001.SH'


def test_tushare_index_history_no_api_or_unknown_code():
    from data_provider.tushare_fetcher import TushareFetcher

    fetcher = TushareFetcher.__new__(TushareFetcher)
    fetcher._check_rate_limit = lambda: None
    fetcher._api = None
    assert fetcher.get_index_daily_history('sh000001') is None

    fetcher._api = MagicMock()
    assert fetcher.get_index_daily_history('600519') is None
    fetcher._api.index_daily.assert_not_called()


# ---------------------------------------------------------------------------
# Yfinance
# ---------------------------------------------------------------------------

def test_yfinance_index_symbol_resolution():
    from data_provider.yfinance_fetcher import YfinanceFetcher

    resolve = YfinanceFetcher._resolve_index_yf_symbol
    assert resolve('SPX', 'us') == '^GSPC'
    assert resolve('RUT', 'us') == '^RUT'
    assert resolve('VIX', 'us') == '^VIX'
    assert resolve('HSI', 'hk') == '^HSI'
    assert resolve('HSTECH', 'hk') == 'HSTECH.HK'
    assert resolve('HSCEI', 'hk') == '^HSCE'
    assert resolve('N225', 'jp') == '^N225'
    assert resolve('KS11', 'kr') == '^KS11'
    assert resolve('TWII', 'tw') == '^TWII'
    assert resolve('sh000001', 'cn') == '000001.SS'
    # A 股兜底须兼容 tushare 纯数字/带后缀格式（避免兜底链路对这类代码失效）
    assert resolve('000001', 'cn') == '000001.SS'
    assert resolve('000001.SH', 'cn') == '000001.SS'
    assert resolve('600519', 'cn') is None
    assert resolve('UNKNOWN', 'us') is None
    assert resolve('HSI', 'jp') is None
    assert resolve('', 'us') is None


def test_yfinance_us_main_indices_include_russell_2000():
    """Issue #1584 验收：美股复盘指数集合须包含罗素2000（小盘股强弱观察）。"""
    from data_provider.yfinance_fetcher import YfinanceFetcher

    fetcher = YfinanceFetcher()
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    fetcher._get_us_main_indices(mock_yf)
    ticker_calls = [call.args[0] for call in mock_yf.Ticker.call_args_list]
    assert '^RUT' in ticker_calls
    assert {'^GSPC', '^IXIC', '^DJI', '^VIX'}.issubset(set(ticker_calls))


def test_manager_cn_cache_key_normalized_across_code_formats():
    """同一 A 股指数的不同代码格式共享缓存，避免重复抓取。"""
    DataFetcherManager.clear_index_history_cache_for_tests()
    calls = {'n': 0}

    fresh = _fresh_bars(25)

    def good(code, region='cn', days=40):
        calls['n'] += 1
        return list(fresh)

    manager = _make_manager([SimpleNamespace(name='F1', get_index_daily_history=good)])
    manager.get_index_daily_history('sh000001', region='cn', days=20)
    manager.get_index_daily_history('000001', region='cn', days=20)
    manager.get_index_daily_history('000001.SH', region='cn', days=20)
    assert calls['n'] == 1
    DataFetcherManager.clear_index_history_cache_for_tests()


def test_yfinance_index_history_normalization_and_empty():
    from data_provider.yfinance_fetcher import YfinanceFetcher

    fetcher = YfinanceFetcher()
    hist = pd.DataFrame(
        {'Close': [5000.0, 5050.0], 'Open': [4990.0, 5010.0]},
        index=pd.DatetimeIndex(['2026-06-30', '2026-07-01']),
    )
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with patch.dict(sys.modules, {'yfinance': mock_yf}):
        bars = fetcher.get_index_daily_history('SPX', region='us', days=40)
    assert bars == [
        {'date': '2026-06-30', 'close': 5000.0},
        {'date': '2026-07-01', 'close': 5050.0},
    ]
    mock_yf.Ticker.assert_called_once_with('^GSPC')

    mock_ticker.history.return_value = pd.DataFrame()
    with patch.dict(sys.modules, {'yfinance': mock_yf}):
        assert fetcher.get_index_daily_history('SPX', region='us') is None

    with patch.dict(sys.modules, {'yfinance': mock_yf}):
        assert fetcher.get_index_daily_history('UNKNOWN', region='us') is None
