# -*- coding: utf-8 -*-
"""Tests for the virtual trader daily runner."""

from __future__ import annotations

import os
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.config import Config
from src.repositories.virtual_trader_repo import VirtualTraderRepository
from src.services.virtual_trader.runner import VirtualTraderRunner
from src.services.virtual_trader.service import VirtualTraderService
from src.storage import DatabaseManager


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "virtual_trader_runner.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


TRADE_DAY = date(2026, 1, 9)


def _uptrend_dip_df(days=75, base=100.0):
    closes = list(base * (1.003 ** np.arange(days)))
    last = closes[-1]
    closes += [last * 0.96, last * 0.96 * 0.885, last * 0.96 * 0.885 * 0.80]
    return pd.DataFrame({
        "date": [TRADE_DAY - timedelta(days=len(closes) - 1 - i) for i in range(len(closes))],
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "volume": [1e6] * len(closes),
    })


def _flat_df(days=80, base=100.0):
    closes = [base] * days
    return pd.DataFrame({
        "date": [TRADE_DAY - timedelta(days=days - 1 - i) for i in range(days)],
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1e6] * days,
    })


def _mk_runner(db, *, history_map=None, trade_dates=None):
    history_map = history_map or {}
    trade_dates = trade_dates or {"cn": TRADE_DAY, "hk": TRADE_DAY, "us": TRADE_DAY}

    def history_fn(code, days=120, target_date=None):
        df = history_map.get(code)
        return (df, "test") if df is not None else (None, "none")

    repo = VirtualTraderRepository(db_manager=db)
    service = VirtualTraderService(repo=repo)
    config = SimpleNamespace(
        stock_list="",
        virtual_trader_universe="",
        virtual_trader_fx_usd_cny=7.2,
        virtual_trader_fx_hkd_cny=0.92,
        virtual_trader_initial_cash_cny=1_000_000.0,
        virtual_trader_cash_reserve_pct=30.0,
        virtual_trader_max_position_pct=15.0,
        virtual_trader_stop_loss_pct=8.0,
    )
    return VirtualTraderRunner(
        service=service, repo=repo, config=config,
        history_fn=history_fn,
        trading_date_fn=lambda market: trade_dates.get(market, TRADE_DAY),
    )


class TestRunMarket:
    def test_first_run_seeds_account_and_trades_oversold(self, isolated_db):
        # 全部候选都超卖 → seed 后立即触发卖出（成本=seed 价 80 元，现价 80 触发回归兑现）
        dip = _uptrend_dip_df()
        runner = _mk_runner(isolated_db, history_map={
            "600519": dip, "300750": dip, "hk00700": dip, "hk09988": dip,
            "AAPL": dip, "NVDA": dip,
        })
        result = runner.run_market("cn")
        assert result["status"] == "success"
        account = runner.repo.get_account()
        assert account is not None
        trades, total = runner.repo.list_trades(account.id, page_size=50)
        # seed 买入 600519/300750 + 可能的策略卖出
        assert total >= 2
        # 快照已写入
        snap = runner.repo.get_latest_snapshot(account.id)
        assert snap is not None
        assert snap.trade_date == TRADE_DAY
        assert snap.total_value_cny > 0

    def test_second_run_same_day_is_skipped(self, isolated_db):
        dip = _uptrend_dip_df()
        runner = _mk_runner(isolated_db, history_map={"600519": dip, "300750": dip})
        first = runner.run_market("cn")
        assert first["status"] == "success"
        second = runner.run_market("cn")
        assert second["status"] == "skipped"
        assert "已执行" in second["reason"]

    def test_force_reruns_same_day(self, isolated_db):
        flat = _flat_df()
        runner = _mk_runner(isolated_db, history_map={"600519": flat, "300750": flat})
        runner.run_market("cn")
        again = runner.run_market("cn", force=True)
        assert again["status"] == "success"

    def test_unsupported_market_skipped(self, isolated_db):
        runner = _mk_runner(isolated_db)
        result = runner.run_market("jp")
        assert result["status"] == "skipped"

    def test_flat_market_no_extra_trades(self, isolated_db):
        flat = _flat_df()
        runner = _mk_runner(isolated_db, history_map={
            "600519": flat, "300750": flat, "hk00700": flat, "hk09988": flat,
            "AAPL": flat, "NVDA": flat,
        })
        result = runner.run_market("cn")
        assert result["status"] == "success"
        account = runner.repo.get_account()
        trades, total = runner.repo.list_trades(account.id, page_size=50)
        # 只有 seed 买入，没有策略性卖出/买入
        cn_trades = [t for t in trades if t.market == "cn"]
        assert len(cn_trades) == 2
        assert all(t.reason.startswith("初始建仓") for t in cn_trades)


class TestRunAllMarkets:
    def test_run_all_creates_runs_for_three_markets(self, isolated_db):
        flat = _flat_df()
        runner = _mk_runner(isolated_db, history_map={
            "600519": flat, "300750": flat, "hk00700": flat, "hk09988": flat,
            "AAPL": flat, "NVDA": flat,
        })
        results = runner.run_all_markets()
        assert [r["status"] for r in results] == ["success", "success", "success"]
        runs = runner.repo.list_runs()
        assert len(runs) == 3
        markets = {r.market for r in runs}
        assert markets == {"cn", "hk", "us"}

    def test_market_of_classification(self, isolated_db):
        runner = _mk_runner(isolated_db)
        assert runner.market_of("600519") == "cn"
        assert runner.market_of("300750") == "cn"
        assert runner.market_of("hk00700") == "hk"
        assert runner.market_of("AAPL") == "us"
        assert runner.market_of("NVDA") == "us"

    def test_price_cache_uses_last_closed_bar(self, isolated_db):
        dip = _uptrend_dip_df()
        runner = _mk_runner(isolated_db, history_map={"600519": dip})
        quote = runner.get_price("600519", TRADE_DAY)
        assert quote is not None
        assert quote.close == float(dip["close"].iloc[-1])
        # target_date 早于最后一根 bar 时只取 <= target_date 的 bar
        earlier = TRADE_DAY - timedelta(days=1)
        quote2 = runner.get_price("600519", earlier)
        assert quote2.close == float(dip[dip["date"] <= earlier]["close"].iloc[-1])
