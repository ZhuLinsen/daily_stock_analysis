# -*- coding: utf-8 -*-
"""板块/概念榜单领涨股透传（Issue #1584）单元测试。

数据边界约定：
- 东财源榜单携带 领涨股票 列时，涨/跌榜行均透传 leader/leader_change_pct
  （字段语义为"板块内领涨股"，与 issue 参考截图一致；东财不提供领跌股）
- 新浪兜底源无领涨股列，行保持 {name, change_pct} 旧形状
"""

import sys
import os
from unittest.mock import MagicMock, patch

import pandas as pd

if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_fetcher():
    from data_provider.akshare_fetcher import AkshareFetcher
    return AkshareFetcher(sleep_min=0, sleep_max=0)


def _em_industry_frame():
    return pd.DataFrame({
        '板块名称': ['煤炭', '燃气', '半导体', '白酒'],
        '涨跌幅': [3.2, 2.1, -2.8, -1.9],
        '领涨股票': ['中国神华', '新天绿能', '中芯国际', '-'],
        '领涨股票-涨跌幅': [5.6, 4.2, 1.1, '-'],
    })


def test_sector_rankings_em_leader_on_both_sides():
    fetcher = _make_fetcher()
    mock_ak = MagicMock()
    mock_ak.stock_board_industry_name_em.return_value = _em_industry_frame()
    with patch.dict(sys.modules, {'akshare': mock_ak}):
        top, bottom = fetcher.get_sector_rankings(n=2)

    assert top[0]['name'] == '煤炭'
    assert top[0]['leader'] == '中国神华'
    assert top[0]['leader_change_pct'] == 5.6
    # 弱板块行同样携带板块内领涨股（issue 参考截图形态；'-' 无效值仍被丢弃）
    row_semi = next(row for row in bottom if row['name'] == '半导体')
    assert row_semi['leader'] == '中芯国际'
    row_liquor = next(row for row in bottom if row['name'] == '白酒')
    assert 'leader' not in row_liquor  # '-' 领涨股整体丢弃


def test_sector_rankings_em_invalid_leader_values_dropped():
    fetcher = _make_fetcher()
    frame = pd.DataFrame({
        '板块名称': ['文化传媒', '软件开发'],
        '涨跌幅': [2.5, 2.0],
        '领涨股票': ['-', '某软件'],
        '领涨股票-涨跌幅': [3.0, '-'],
    })
    mock_ak = MagicMock()
    mock_ak.stock_board_industry_name_em.return_value = frame
    with patch.dict(sys.modules, {'akshare': mock_ak}):
        top, _bottom = fetcher.get_sector_rankings(n=2)

    # '-' 领涨股整体丢弃
    row_media = next(row for row in top if row['name'] == '文化传媒')
    assert 'leader' not in row_media
    # 领涨股有效但涨跌幅无效时：保留 leader，省略 leader_change_pct
    row_soft = next(row for row in top if row['name'] == '软件开发')
    assert row_soft['leader'] == '某软件'
    assert 'leader_change_pct' not in row_soft


def test_sector_rankings_sina_fallback_keeps_legacy_shape():
    fetcher = _make_fetcher()
    mock_ak = MagicMock()
    mock_ak.stock_board_industry_name_em.side_effect = RuntimeError('em down')
    mock_ak.stock_sector_spot.return_value = pd.DataFrame({
        '板块': ['煤炭', '半导体'],
        '涨跌幅': [3.2, -2.8],
    })
    with patch.dict(sys.modules, {'akshare': mock_ak}):
        top, bottom = fetcher.get_sector_rankings(n=1)

    for row in top + bottom:
        assert set(row.keys()) == {'name', 'change_pct'}


def test_concept_rankings_em_leader_on_both_sides():
    fetcher = _make_fetcher()
    mock_ak = MagicMock()
    mock_ak.stock_board_concept_name_em.return_value = pd.DataFrame({
        '板块名称': ['AI PC', '航运概念', '地产链'],
        '涨跌幅': [4.1, 3.3, -2.2],
        '领涨股票': ['某科技', '某航运', '某地产'],
        '领涨股票-涨跌幅': [9.98, 6.5, 0.3],
    })
    with patch.dict(sys.modules, {'akshare': mock_ak}):
        top, bottom = fetcher.get_concept_rankings(n=2)

    assert top[0]['leader'] == '某科技'
    assert top[0]['leader_change_pct'] == 9.98
    # 弱概念行同样携带板块内领涨股
    row_estate = next(row for row in bottom if row['name'] == '地产链')
    assert row_estate['leader'] == '某地产'
