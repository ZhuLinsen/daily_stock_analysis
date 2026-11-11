# -*- coding: utf-8 -*-
"""Realtime quote volume unit normalization tests (PR #2492 r2, blocker C).

口径（评审 OR-COR-7f30775f / f7b1179f）：UnifiedRealtimeQuote.volume 契约单位为股
（与历史日线口径一致）。东财 push2 现货表族（stock_zh_a_spot_em / fund_etf_spot_em /
stock_hk_spot_em）成交量单位为手 → 适配器层按源归一（手→股 ×100）；
其余源按源核对、不得统一乘 100：
- 新浪 A 股实时（自建 endpoint）：字段 8 = 成交量（股）→ 保持原值；
- 腾讯直连：_normalize_tencent_volume 交叉校验归一（既有）→ 不动；
- tickflow：_cn_lots_to_shares 已归一股（既有）→ 不动；
- yfinance / longbridge：原生股 → 不动。

集成口径：em 返回 30 亿元成交额 / 20000 手 → quote.volume=2,000,000 股 →
快照 VWAP = 1500（而非百倍错的 150000）。
"""

from __future__ import annotations

import time

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from data_provider import akshare_fetcher as akshare_module
from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.services.quote_snapshot_service import QuoteSnapshotService, clear_snapshot_cache


def _reset_em_caches() -> None:
    """重置 akshare_fetcher 模块级行情缓存，避免用例间串数据。"""
    for cache in (
        akshare_module._realtime_cache,
        akshare_module._etf_realtime_cache,
        akshare_module._hk_realtime_cache,
    ):
        cache["data"] = None
        cache["timestamp"] = 0.0


def _hanging_order_book_stub(symbol: str = ""):
    """模拟盘口源挂起（requests.get 无 timeout 的真实故障形态）。

    模块级定义：_akshare_call_with_timeout 走 spawn 子进程，
    stub 必须可按引用 pickle。
    """
    time.sleep(15)


def _cn_quote_fixture() -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code="600519",
        name="贵州茅台",
        source=RealtimeSource.AKSHARE_EM,
        price=1500.0,
        pre_close=1480.0,
        open_price=1490.0,
        high=1510.0,
        low=1485.0,
        volume=2_000_000,
        amount=3_000_000_000.0,
        change_amount=20.0,
        change_pct=1.35,
        market="cn",
        currency="CNY",
        data_quality="ok",
        missing_fields=[],
    )


def _closes_fixture(count: int = 70) -> pd.DataFrame:
    return pd.DataFrame({"close": [100.0 + i for i in range(count)]})


def _em_stock_frame() -> pd.DataFrame:
    """stock_zh_a_spot_em 形状：成交量=手（20000 手），成交额=30 亿元。"""
    return pd.DataFrame([
        {
            "代码": "600519",
            "名称": "贵州茅台",
            "最新价": 1500.0,
            "涨跌幅": 1.35,
            "涨跌额": 20.0,
            "成交量": 20000,  # 手
            "成交额": 3_000_000_000.0,
            "振幅": 1.69,
            "量比": 1.2,
            "换手率": 0.16,
            "今开": 1490.0,
            "最高": 1510.0,
            "最低": 1485.0,
            "市盈率-动态": 30.0,
            "市净率": 10.0,
            "总市值": 1_880_000_000_000.0,
            "流通市值": 1_880_000_000_000.0,
            "60日涨跌幅": 12.5,
            "52周最高": 1850.0,
            "52周最低": 1300.0,
        }
    ])


def test_em_stock_spot_volume_normalized_lots_to_shares() -> None:
    _reset_em_caches()
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    with patch("akshare.stock_zh_a_spot_em", return_value=_em_stock_frame()):
        quote = fetcher.get_realtime_quote("600519", source="em")

    assert quote is not None
    assert quote.volume == 2_000_000, "em 成交量必须按源归一：20000 手 → 2,000,000 股"
    assert quote.amount == 3_000_000_000.0

    # 集成：快照 VWAP 必须是均价口径的正确值 1500，而非百倍错的 150000
    clear_snapshot_cache()
    service = QuoteSnapshotService(manager=MagicMock(), cache_ttl=0)
    service._manager.get_realtime_quote.return_value = quote
    service._manager.get_daily_data.side_effect = RuntimeError("no history in unit test")
    snapshot = service.get_snapshot("600519")
    clear_snapshot_cache()

    assert snapshot is not None
    assert snapshot["vwap"] == pytest.approx(1500.0), (
        f"VWAP 必须为 1500（30 亿元 / 200 万股），实际 {snapshot['vwap']}"
    )


def test_em_etf_spot_volume_normalized_lots_to_shares() -> None:
    _reset_em_caches()
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    etf_frame = pd.DataFrame([
        {
            "代码": "510300",
            "名称": "沪深300ETF",
            "最新价": 4.0,
            "涨跌幅": 0.5,
            "涨跌额": 0.02,
            "成交量": 10000,  # 手（东财 push2 同族字段）
            "成交额": 40_000_000.0,
            "振幅": 1.0,
            "量比": 1.0,
            "换手率": 0.5,
            "今开": 3.98,
            "最高": 4.02,
            "最低": 3.97,
        }
    ])
    with patch("akshare.fund_etf_spot_em", return_value=etf_frame):
        quote = fetcher._get_etf_realtime_quote("510300")

    assert quote is not None
    assert quote.volume == 1_000_000, "em ETF 成交量同族字段必须归一：10000 手 → 1,000,000 股"


def test_em_hk_spot_volume_stays_shares_and_must_not_be_scaled() -> None:
    """r3 事实修正（OR-COR-2c6d1b9a）：stock_hk_spot_em 成交量单位本就是股
    （AKShare 官方文档），不得 ×100；否则 volume 百倍放大、VWAP 百倍缩小。"""
    _reset_em_caches()
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    hk_frame = pd.DataFrame([
        {
            "代码": "00700",
            "名称": "腾讯控股",
            "最新价": 400.0,
            "涨跌幅": 1.0,
            "涨跌额": 4.0,
            "成交量": 5000,  # 股（AKShare 官方口径，非手）
            "成交额": 2_000_000.0,
            "振幅": 1.2,
            "量比": 1.1,
            "换手率": 0.05,
            "市盈率": 20.0,
            "市净率": 4.0,
            "总市值": 3_800_000_000_000.0,
        }
    ])
    with patch("akshare.stock_hk_spot_em", return_value=hk_frame):
        quote = fetcher.get_realtime_quote("00700.HK", source="hk")

    assert quote is not None
    assert quote.volume == 5_000, (
        f"港股 em 成交量已是股，必须保持原值不被缩放，实际 {quote.volume}"
    )
    assert quote.amount == 2_000_000.0


def test_sina_realtime_volume_is_shares_and_must_not_be_scaled() -> None:
    """按源核对守卫：新浪字段 8 本身是股，任何全局 ×100 都会把它破坏。"""
    _reset_em_caches()
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    # 新浪 hq 格式：0:名称 1:今开 2:昨收 3:最新价 4:最高 5:最低 ... 8:成交量(股) 9:成交额(元)
    hq_payload = (
        'var hq_str_sh600519="贵州茅台,1490.0,1480.0,1500.0,1510.0,1485.0,'
        '1499.0,1501.0,2500000,3750000000.0,40000,30000,'
        '1.35,1500.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,'
        '2026-11-11,15:00:00,00,";'
    )
    mock_response = MagicMock(status_code=200, text=hq_payload)
    with patch("data_provider.akshare_fetcher.requests.get", return_value=mock_response):
        quote = fetcher._get_stock_realtime_quote_sina("600519")

    assert quote is not None
    assert quote.volume == 2_500_000, "新浪成交量已是股，必须保持原值不被缩放"
    assert quote.amount == 3_750_000_000.0


def test_hanging_order_book_degrades_snapshot_promptly() -> None:
    """r3 blocker C（OR-COR-2d4fb637）：盘口源挂起时快照必须在时限内返回，
    bid_ask_ratio 降级 null + missing_fields，其余字段（含已取到的 price）正常。
    """
    _reset_em_caches()
    clear_snapshot_cache()
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    fetcher.ORDER_BOOK_CALL_TIMEOUT = 1.0  # r3 修复暴露的实例级超时旋钮
    started = time.monotonic()
    try:
        with patch("akshare.stock_bid_ask_em", _hanging_order_book_stub), \
                patch("src.services.quote_snapshot_service.DataFetcherManager") as mgr_cls, \
                patch("src.services.quote_snapshot_service.AkshareFetcher",
                      return_value=fetcher):
            manager = MagicMock()
            mgr_cls.return_value = manager
            manager.get_realtime_quote.return_value = _cn_quote_fixture()
            manager.get_daily_data.return_value = (_closes_fixture(), "MockFetcher")
            snapshot = QuoteSnapshotService(cache_ttl=0).get_snapshot("600519")
        elapsed = time.monotonic() - started
    finally:
        clear_snapshot_cache()

    assert snapshot is not None, "盘口挂起不得拖死整份快照"
    assert elapsed < 10, f"盘口挂起必须在时限内降级返回，实际耗时 {elapsed:.1f}s"
    assert snapshot["bid_ask_ratio"] is None
    assert "bid_ask_ratio" in snapshot["missing_fields"]
    assert snapshot["price"] == 1500.0, "已取到的行情主体必须正常返回"
