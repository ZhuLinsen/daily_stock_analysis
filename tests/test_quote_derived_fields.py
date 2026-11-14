# -*- coding: utf-8 -*-
"""Derived-field unit tests for the quote snapshot service (issue #771).

覆盖口径（计划任务 3 / 默认值 4）：
- MA 严格全窗：不足 N 条返回 null；N 条整窗时取最近 N 条均值。
- VWAP：amount/volume 均价口径；缺 amount 或 volume 无效 → null。
- 委比（bid_ask_ratio）：五档买卖量派生；盘口不可得 → null + missing_fields。
- 成交笔数（trade_count）：em 标准接口不可得 → 恒 null + missing_fields。
- 端点级短 TTL 缓存：复用 realtime_cache_ttl 机制，TTL 内二次请求不重复取数。
- 多市场降级：缺失一律 null 并合入 missing_fields，不做字段级硬失败。
"""

from __future__ import annotations

import time
from contextlib import contextmanager

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.services.quote_snapshot_service import (
    QuoteSnapshotService,
    clear_snapshot_cache,
    compute_bid_ask_ratio,
    compute_moving_averages,
    compute_vwap,
)


def _cn_quote(**overrides) -> UnifiedRealtimeQuote:
    fields = dict(
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
        amplitude=1.69,
        volume_ratio=1.2,
        turnover_rate=0.16,
        change_60d=12.5,
        high_52w=1850.0,
        low_52w=1300.0,
        market="cn",
        currency="CNY",
        data_quality="ok",
        missing_fields=[],
    )
    fields.update(overrides)
    return UnifiedRealtimeQuote(**fields)


def _us_quote(**overrides) -> UnifiedRealtimeQuote:
    fields = dict(
        code="AAPL",
        name="Apple",
        source=RealtimeSource.STOOQ,
        price=200.0,
        high=201.0,
        low=198.5,
        volume=51_000_000,
        market="us",
        currency="USD",
        data_quality="partial",
    )
    fields.update(overrides)
    return UnifiedRealtimeQuote(**fields)


def _closes_df(values) -> pd.DataFrame:
    return pd.DataFrame({"close": list(values)})


@contextmanager
def _patched_service(quote, closes=None, order_book=None, order_book_raises=False):
    """Patch manager + akshare fetcher; return (service, manager_mock, fetcher_cls_mock)."""
    clear_snapshot_cache()
    with patch("src.services.quote_snapshot_service.DataFetcherManager") as mgr_cls, \
            patch("src.services.quote_snapshot_service.AkshareFetcher") as akshare_cls:
        manager = MagicMock()
        mgr_cls.return_value = manager
        manager.get_realtime_quote.return_value = quote
        manager.get_daily_data.return_value = (_closes_df(closes or []), "MockFetcher")
        fetcher = MagicMock()
        if order_book_raises:
            fetcher.get_a_share_order_book.side_effect = RuntimeError("em down")
        else:
            fetcher.get_a_share_order_book.return_value = order_book
        akshare_cls.return_value = fetcher
        service = QuoteSnapshotService(cache_ttl=60)
        yield service, manager, akshare_cls, fetcher
    clear_snapshot_cache()


# ============================================
# MA 严格全窗口径
# ============================================

def test_ma_requires_full_window_and_uses_last_n_closes() -> None:
    result = compute_moving_averages([1.0, 2.0, 3.0, 4.0, 5.0])

    assert result["ma5"] == pytest.approx(3.0)  # (1+2+3+4+5)/5
    assert result["ma10"] is None
    assert result["ma20"] is None
    assert result["ma60"] is None


def test_ma_insufficient_bars_return_null_per_level() -> None:
    result = compute_moving_averages([10.0, 11.0, 12.0])  # 3 bars < 5

    assert result == {"ma5": None, "ma10": None, "ma20": None, "ma60": None}


def test_ma_uses_strict_trailing_window_not_partial() -> None:
    # 12 条：ma10 必须取“最近 10 条”的均值（2.0..11.0 → 6.5），
    # 不允许 min_periods=1 的部分窗口口径。
    closes = [1.0, 1.0] + [float(i) for i in range(2, 12)]
    result = compute_moving_averages(closes)

    assert result["ma10"] == pytest.approx(6.5)
    assert result["ma5"] == pytest.approx(9.0)  # 7,8,9,10,11
    assert result["ma20"] is None


def test_ma_ignores_non_finite_closes() -> None:
    closes = [5.0, None, float("nan"), 5.0, 5.0, 5.0, 6.0]
    result = compute_moving_averages(closes)

    # 有效收盘 [5,5,5,5,6] → ma5 = 5.2
    assert result["ma5"] == pytest.approx(5.2)


# ============================================
# VWAP 均价口径
# ============================================

def test_vwap_is_amount_over_volume() -> None:
    assert compute_vwap(3_000_000_000.0, 2_000_000) == pytest.approx(1500.0)


def test_vwap_missing_amount_returns_null() -> None:
    assert compute_vwap(None, 2_000_000) is None


def test_vwap_invalid_volume_returns_null() -> None:
    assert compute_vwap(3_000_000_000.0, None) is None
    assert compute_vwap(3_000_000_000.0, 0) is None


# ============================================
# 委比（五档派生）
# ============================================

def test_bid_ask_ratio_balanced_book_is_zero() -> None:
    ratio = compute_bid_ask_ratio([100, 200, 300, 400, 500], [500, 400, 300, 200, 100])

    assert ratio == pytest.approx(0.0)


def test_bid_ask_ratio_all_buy_side_is_positive() -> None:
    ratio = compute_bid_ask_ratio([100, 100, 100, 100, 100], [50, 0, 0, 0, 0])

    assert ratio == pytest.approx((500 - 50) / 550 * 100)


def test_bid_ask_ratio_empty_book_returns_null() -> None:
    assert compute_bid_ask_ratio([], []) is None
    assert compute_bid_ask_ratio([0, 0, 0, 0, 0], [0, 0, 0, 0, 0]) is None


# ============================================
# 服务集成：22 字段装配 + 降级 + missing_fields
# ============================================

PINNED_FIELDS = (
    "price", "pre_close", "open_price", "high", "low", "volume", "amount",
    "change_amount", "change_pct", "amplitude", "volume_ratio", "turnover_rate",
    "change_60d", "high_52w", "low_52w",
    "vwap", "bid_ask_ratio", "trade_count",
    "ma5", "ma10", "ma20", "ma60",
)


def test_snapshot_cn_full_fields_and_vwap() -> None:
    closes = [float(1400 + i) for i in range(80)]  # 足够 MA60
    with _patched_service(
        _cn_quote(),
        closes=closes,
        order_book={"buy_volumes": [100, 200, 300, 400, 500], "sell_volumes": [500, 400, 300, 200, 100]},
    ) as (service, manager, akshare_cls, fetcher):
        snapshot = service.get_snapshot("600519")

    assert snapshot is not None
    for field in PINNED_FIELDS:
        assert field in snapshot, f"pinned field missing: {field}"
    assert snapshot["vwap"] == pytest.approx(1500.0)
    assert snapshot["bid_ask_ratio"] == pytest.approx(0.0)
    # MA60 覆盖最近 60 条收盘
    assert snapshot["ma60"] == pytest.approx(sum(closes[-60:]) / 60)
    assert snapshot["trade_count"] is None  # em 标准接口无笔数 → 恒 null
    assert snapshot["missing_fields"] == ["trade_count"]
    assert snapshot["stock_code"] == "600519"
    assert snapshot["stock_name"] == "贵州茅台"
    assert snapshot["source"] == "akshare_em"
    fetcher.get_a_share_order_book.assert_called_once_with("600519")


def test_snapshot_us_degrades_to_null_with_missing_fields() -> None:
    with _patched_service(_us_quote(), closes=[190.0, 195.0, 198.0]) as (
        service, manager, akshare_cls, fetcher,
    ):
        snapshot = service.get_snapshot("AAPL")

    assert snapshot is not None
    # 缺 amount → vwap null；美股非 A 股 → 不探盘口
    assert snapshot["vwap"] is None
    assert snapshot["bid_ask_ratio"] is None
    assert snapshot["trade_count"] is None
    # 3 条 K 线 < 5 → MA 全部 null
    assert snapshot["ma5"] is None
    assert snapshot["ma60"] is None
    for name in ("vwap", "bid_ask_ratio", "trade_count", "ma5", "ma10", "ma20", "ma60"):
        assert name in snapshot["missing_fields"], f"{name} should be reported missing"
    fetcher.get_a_share_order_book.assert_not_called()


def test_snapshot_order_book_failure_stays_null_not_hard_fail() -> None:
    closes = [float(100 + i) for i in range(70)]
    with _patched_service(_cn_quote(), closes=closes, order_book_raises=True) as (
        service, manager, akshare_cls, fetcher,
    ):
        snapshot = service.get_snapshot("600519")

    assert snapshot is not None  # 盘口挂了不硬失败
    assert snapshot["price"] == 1500.0
    assert snapshot["bid_ask_ratio"] is None
    assert "bid_ask_ratio" in snapshot["missing_fields"]


def test_snapshot_unknown_quote_returns_none() -> None:
    with _patched_service(None, closes=[]) as (service, manager, akshare_cls, fetcher):
        assert service.get_snapshot("999999") is None

    manager.get_daily_data.assert_not_called()


def test_snapshot_missing_history_marks_all_ma_missing() -> None:
    with _patched_service(_cn_quote(), closes=[]) as (service, manager, akshare_cls, fetcher):
        snapshot = service.get_snapshot("600519")

    assert snapshot is not None
    assert snapshot["ma5"] is None
    assert snapshot["ma60"] is None
    assert {"ma5", "ma10", "ma20", "ma60"} <= set(snapshot["missing_fields"])


def test_snapshot_history_fetch_failure_marks_ma_missing_not_hard_fail() -> None:
    clear_snapshot_cache()
    with patch("src.services.quote_snapshot_service.DataFetcherManager") as mgr_cls, \
            patch("src.services.quote_snapshot_service.AkshareFetcher") as akshare_cls:
        manager = MagicMock()
        mgr_cls.return_value = manager
        manager.get_realtime_quote.return_value = _cn_quote()
        manager.get_daily_data.side_effect = RuntimeError("all history sources down")
        akshare_cls.return_value = MagicMock()
        akshare_cls.return_value.get_a_share_order_book.return_value = None
        service = QuoteSnapshotService(cache_ttl=60)
        snapshot = service.get_snapshot("600519")
    clear_snapshot_cache()

    assert snapshot is not None
    assert snapshot["ma5"] is None
    assert {"ma5", "ma10", "ma20", "ma60"} <= set(snapshot["missing_fields"])


# ============================================
# 端点级短 TTL 缓存（复用 realtime_cache_ttl 机制）
# ============================================

def test_snapshot_cache_reuses_fetch_within_ttl() -> None:
    closes = [float(100 + i) for i in range(70)]
    with _patched_service(
        _cn_quote(),
        closes=closes,
        order_book={"buy_volumes": [1, 1, 1, 1, 1], "sell_volumes": [1, 1, 1, 1, 1]},
    ) as (service, manager, akshare_cls, fetcher):
        first = service.get_snapshot("600519")
        second = service.get_snapshot("600519")

    assert first == second
    assert manager.get_realtime_quote.call_count == 1
    assert manager.get_daily_data.call_count == 1
    assert fetcher.get_a_share_order_book.call_count == 1


def test_snapshot_cache_ttl_zero_disables_caching() -> None:
    closes = [float(100 + i) for i in range(70)]
    clear_snapshot_cache()
    with patch("src.services.quote_snapshot_service.DataFetcherManager") as mgr_cls, \
            patch("src.services.quote_snapshot_service.AkshareFetcher") as akshare_cls:
        manager = MagicMock()
        mgr_cls.return_value = manager
        manager.get_realtime_quote.return_value = _cn_quote()
        manager.get_daily_data.return_value = (_closes_df(closes), "MockFetcher")
        akshare_cls.return_value = MagicMock()
        akshare_cls.return_value.get_a_share_order_book.return_value = None
        service = QuoteSnapshotService(cache_ttl=0)
        service.get_snapshot("600519")
        service.get_snapshot("600519")
    clear_snapshot_cache()

    assert manager.get_realtime_quote.call_count == 2


def test_snapshot_default_ttl_reads_realtime_cache_ttl_config() -> None:
    """未显式传 TTL 时，服务必须读 config.realtime_cache_ttl（复用既有机制）。"""
    clear_snapshot_cache()
    fake_config = MagicMock()
    fake_config.realtime_cache_ttl = 42
    service = QuoteSnapshotService()
    with patch("src.services.quote_snapshot_service.get_config", return_value=fake_config):
        assert service._effective_cache_ttl() == 42
    clear_snapshot_cache()


# ============================================
# r4 blocker（OR-COR-f52a914c）：MA 日线加载必须有快照级预算
# ============================================

def test_snapshot_ma_history_hang_degrades_within_budget() -> None:
    """历史日线源挂起时，快照必须在 MA 预算内返回：
    price 等已取到的字段完好，MA 全档降级 null + missing_fields，
    不得拖到 Web 客户端 30s 超时。"""
    clear_snapshot_cache()
    started = time.monotonic()
    with patch("src.services.quote_snapshot_service.DataFetcherManager") as mgr_cls, \
            patch("src.services.quote_snapshot_service.AkshareFetcher") as akshare_cls:
        manager = MagicMock()
        mgr_cls.return_value = manager

        def _hanging_daily(*args, **kwargs):
            time.sleep(20)  # 模拟完整 fallback 链挂起（efinance 历史单源 60s 级）

        manager.get_realtime_quote.return_value = _cn_quote()
        manager.get_daily_data.side_effect = _hanging_daily
        akshare_cls.return_value = MagicMock()
        akshare_cls.return_value.get_a_share_order_book.return_value = None
        service = QuoteSnapshotService(cache_ttl=0)
        service.MA_LOAD_BUDGET_SECONDS = 1.0  # r4 修复暴露的实例级预算旋钮
        snapshot = service.get_snapshot("600519")
        elapsed = time.monotonic() - started
    clear_snapshot_cache()

    assert snapshot is not None, "历史源挂起不得拖死整份快照"
    assert elapsed < 10, f"日线挂起必须在 MA 预算内降级返回，实际耗时 {elapsed:.1f}s"
    assert snapshot["price"] == 1500.0, "已取到的实时行情主体必须正常返回"
    assert snapshot["ma5"] is None
    assert snapshot["ma60"] is None
    assert {"ma5", "ma10", "ma20", "ma60"} <= set(snapshot["missing_fields"])
