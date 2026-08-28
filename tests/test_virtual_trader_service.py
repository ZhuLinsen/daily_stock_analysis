# -*- coding: utf-8 -*-
"""Tests for the virtual trader account service."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

from src.config import Config
from src.repositories.virtual_trader_repo import VirtualTraderRepository
from src.services.virtual_trader.service import (
    PriceQuote,
    VirtualTraderError,
    VirtualTraderService,
)
from src.storage import DatabaseManager


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "virtual_trader.db")
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


def _prices(codes_and_prices):
    table = {code: PriceQuote(code=code, close=price, trade_date=date(2026, 1, 5))
             for code, price in codes_and_prices}

    def get_price(code):
        return table.get(code)

    return get_price


class TestSeedAndAccount:
    def test_seed_creates_three_market_positions_and_reserve(self, isolated_db):
        service = VirtualTraderService(
            repo=VirtualTraderRepository(db_manager=isolated_db),
            get_price_fn=_prices([("600519", 1500.0), ("300750", 200.0),
                                  ("hk00700", 400.0), ("hk09988", 90.0),
                                  ("AAPL", 220.0), ("NVDA", 130.0)]),
            initial_cash_cny=1_000_000.0,
            cash_reserve_pct=30.0,
        )
        account = service.ensure_account()
        positions = service.repo.list_open_positions(account.id)
        assert {p.market for p in positions} == {"cn", "hk", "us"}
        # 每市场建仓约 70%、留约 30% 备用金；高价股一手兜底允许小幅偏差（A 股 40 万分配）
        assert 115_000.0 <= account.cash_cny <= 130_000.0
        cn_value = sum(p.quantity * p.avg_cost for p in positions if p.market == "cn")
        assert 265_000.0 <= cn_value <= 285_000.0
        trades, total = service.repo.list_trades(account.id, page_size=50)
        assert total == 6
        assert all(t.side == "buy" for t in trades)

    def test_seed_is_idempotent_on_ensure(self, isolated_db):
        service = VirtualTraderService(
            repo=VirtualTraderRepository(db_manager=isolated_db),
            get_price_fn=_prices([("600519", 1500.0), ("300750", 200.0),
                                  ("hk00700", 400.0), ("hk09988", 90.0),
                                  ("AAPL", 220.0), ("NVDA", 130.0)]),
        )
        first = service.ensure_account()
        second = service.ensure_account()
        assert first.id == second.id

    def test_seed_twice_raises(self, isolated_db):
        service = VirtualTraderService(
            repo=VirtualTraderRepository(db_manager=isolated_db),
            get_price_fn=_prices([("600519", 1500.0), ("300750", 200.0),
                                  ("hk00700", 400.0), ("hk09988", 90.0),
                                  ("AAPL", 220.0), ("NVDA", 130.0)]),
        )
        service.ensure_account()
        with pytest.raises(VirtualTraderError):
            service.seed_account()


class TestTradeExecution:
    def _service(self, isolated_db):
        service = VirtualTraderService(
            repo=VirtualTraderRepository(db_manager=isolated_db),
            initial_cash_cny=1_000_000.0,
        )
        account = service.repo.create_account(
            {"name": "default", "initial_cash_cny": 1_000_000.0,
             "cash_cny": 200_000.0, "cash_hkd": 0.0, "cash_usd": 50_000.0}
        )
        return service, account

    def test_buy_updates_cash_position_and_prediction(self, isolated_db):
        service, account = self._service(isolated_db)
        trade = service.execute_buy(
            account, code="600519", name="贵州茅台", market="cn",
            quantity=100, price=1500.0, trade_date=date(2026, 1, 5),
            reason="测试买入",
            signal_snapshot={"close": 1500.0},
            prediction={"direction": "up", "target_price": 1600.0, "horizon_days": 10},
        )
        refreshed = service.repo.get_account()
        # 现金 = 200000 - 100*1500 - 佣金37.5
        assert refreshed.cash_cny == pytest.approx(200_000.0 - 150_000.0 - 37.5)
        position = service.repo.get_open_position(account.id, "600519")
        assert position.quantity == 100
        assert position.avg_cost == 1500.0
        preds, total = service.repo.list_predictions(account.id)
        assert total == 1
        assert preds[0].direction == "up"
        assert preds[0].status == "pending"
        assert preds[0].trade_id == trade.id

    def test_buy_rejects_insufficient_cash(self, isolated_db):
        service, account = self._service(isolated_db)
        with pytest.raises(VirtualTraderError):
            service.execute_buy(
                account, code="600519", name=None, market="cn",
                quantity=1000, price=1500.0, trade_date=date(2026, 1, 5),
                reason="超预算",
            )

    def test_sell_full_close_realizes_pnl(self, isolated_db):
        service, account = self._service(isolated_db)
        service.execute_buy(
            account, code="AAPL", name="苹果", market="us",
            quantity=100, price=200.0, trade_date=date(2026, 1, 5), reason="建仓",
        )
        account = service.repo.get_account()
        position = service.repo.get_open_position(account.id, "AAPL")
        service.execute_sell(
            account, position=position, quantity=None, price=250.0,
            trade_date=date(2026, 2, 5), reason="回归兑现",
        )
        closed = service.repo.get_open_position(account.id, "AAPL")
        assert closed is None
        positions = service.repo.list_open_positions(account.id)
        assert positions == []
        # USD 现金 = 50000 - 100*200 - fee(20) + 100*250 - fee(25)
        expected_cash_usd = 50_000.0 - 20_000.0 - 20.0 + 25_000.0 - 25.0
        refreshed = service.repo.get_account()
        assert refreshed.cash_usd == pytest.approx(expected_cash_usd, rel=1e-6)

    def test_partial_sell_keeps_position_open(self, isolated_db):
        service, account = self._service(isolated_db)
        service.execute_buy(
            account, code="600519", name=None, market="cn",
            quantity=1000, price=100.0, trade_date=date(2026, 1, 5), reason="建仓",
        )
        account = service.repo.get_account()
        position = service.repo.get_open_position(account.id, "600519")
        service.execute_sell(
            account, position=position, quantity=400, price=120.0,
            trade_date=date(2026, 2, 5), reason="部分兑现",
        )
        position = service.repo.get_open_position(account.id, "600519")
        assert position.quantity == 600
        assert position.status == "open"
        assert position.realized_pnl > 0


class TestSnapshotAndEvaluation:
    def test_snapshot_values_and_daily_return(self, isolated_db):
        service = VirtualTraderService(
            repo=VirtualTraderRepository(db_manager=isolated_db),
        )
        account = service.repo.create_account(
            {"name": "default", "initial_cash_cny": 1_000_000.0,
             "cash_cny": 500_000.0, "cash_hkd": 100_000.0, "cash_usd": 10_000.0}
        )
        service.repo.create_position({
            "account_id": account.id, "stock_code": "600519", "market": "cn",
            "currency": "CNY", "quantity": 100, "avg_cost": 1500.0,
            "status": "open", "opened_at": date(2026, 1, 5),
        })
        service.write_snapshot(account, trade_date=date(2026, 1, 5),
                               last_prices={"600519": 1600.0})
        snap = service.repo.get_latest_snapshot(account.id)
        # 500000 + 100000*0.92 + 10000*7.2 + 100*1600
        assert snap.total_value_cny == pytest.approx(500_000 + 92_000 + 72_000 + 160_000)
        assert snap.daily_return_pct is None
        service.write_snapshot(account, trade_date=date(2026, 1, 6),
                               last_prices={"600519": 1650.0})
        snap2 = service.repo.get_latest_snapshot(account.id)
        expected = (snap2.total_value_cny - snap.total_value_cny) / snap.total_value_cny * 100
        assert snap2.daily_return_pct == pytest.approx(expected, rel=1e-4)

    def test_prediction_hit_and_miss(self, isolated_db):
        service = VirtualTraderService(
            repo=VirtualTraderRepository(db_manager=isolated_db),
        )
        account = service.repo.create_account(
            {"name": "default", "initial_cash_cny": 1_000_000.0, "cash_cny": 1_000.0}
        )
        trade = service.repo.create_trade({
            "account_id": account.id, "stock_code": "600519", "market": "cn",
            "side": "buy", "quantity": 100, "price": 100.0, "trade_date": date(2026, 1, 5),
        })
        service.repo.create_prediction({
            "account_id": account.id, "trade_id": trade.id, "stock_code": "600519",
            "market": "cn", "direction": "up", "anchor_date": date(2026, 1, 5),
            "horizon_days": 5, "target_price": 110.0, "entry_price": 100.0,
        })
        bars = [(date(2026, 1, 6) + timedelta(days=i), 100.0 + i * 3) for i in range(5)]
        stats = service.evaluate_pending_predictions(
            account, matured_before=date(2026, 1, 12), forward_bars_fn=lambda *a: bars,
        )
        assert stats == {"evaluated": 1, "hit": 1, "miss": 0, "unable": 0}
        preds, _ = service.repo.list_predictions(account.id)
        assert preds[0].outcome == "hit"
        assert preds[0].status == "evaluated"
        assert preds[0].window_high == 112.0

    def test_prediction_unable_without_bars(self, isolated_db):
        service = VirtualTraderService(
            repo=VirtualTraderRepository(db_manager=isolated_db),
        )
        account = service.repo.create_account(
            {"name": "default", "initial_cash_cny": 1_000_000.0, "cash_cny": 1_000.0}
        )
        trade = service.repo.create_trade({
            "account_id": account.id, "stock_code": "600519", "market": "cn",
            "side": "sell", "quantity": 100, "price": 100.0, "trade_date": date(2026, 1, 5),
        })
        service.repo.create_prediction({
            "account_id": account.id, "trade_id": trade.id, "stock_code": "600519",
            "market": "cn", "direction": "down", "anchor_date": date(2026, 1, 5),
            "horizon_days": 5, "target_price": 90.0, "entry_price": 100.0,
        })
        stats = service.evaluate_pending_predictions(
            account, matured_before=date(2026, 1, 12), forward_bars_fn=lambda *a: [],
        )
        assert stats["unable"] == 1
        preds, _ = service.repo.list_predictions(account.id)
        assert preds[0].outcome == "unable"
