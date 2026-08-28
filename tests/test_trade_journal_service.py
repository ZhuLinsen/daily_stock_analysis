# -*- coding: utf-8 -*-
"""Tests for the trade journal service."""

from __future__ import annotations

import os

import pytest

from src.config import Config
from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.services.trade_journal_service import (
    TradeJournalService,
    TradeJournalValidationError,
    classify_discipline,
    normalize_side,
)
from src.storage import DatabaseManager


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "trade_journal.db")
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


def _entry(**overrides):
    fields = {
        "code": "600519",
        "name": "贵州茅台",
        "market": "cn",
        "side": "buy",
        "quantity": 100,
        "price": 10.0,
        "fee": 0.0,
        "tax": 0.0,
        "trade_date": "2026-01-05",
        "thesis": "测试理由",
        "strategy": "trend",
        "emotion": "calm",
    }
    fields.update(overrides)
    return fields


def test_normalize_side_aliases():
    assert normalize_side("buy") == "buy"
    assert normalize_side("sell") == "sell"
    assert normalize_side("加仓") == "buy"
    assert normalize_side("reduce") == "sell"
    with pytest.raises(TradeJournalValidationError):
        normalize_side("hold")


def test_classify_discipline_matrix():
    assert classify_discipline("buy", "buy") == "aligned"
    assert classify_discipline("buy", "add") == "aligned"
    assert classify_discipline("sell", "reduce") == "aligned"
    assert classify_discipline("sell", "sell") == "aligned"
    assert classify_discipline("buy", "sell") == "contradicted"
    assert classify_discipline("sell", "buy") == "contradicted"
    assert classify_discipline("buy", "hold") == "neutral"
    assert classify_discipline("sell", None) == "no_signal"


def test_create_and_get_entry(isolated_db):
    service = TradeJournalService(db_manager=isolated_db)
    item = service.create_entry(_entry())
    assert item["id"] > 0
    assert item["side"] == "buy"
    assert item["emotion"] == "calm"
    assert service.get_entry(item["id"])["code"] == "600519"


def test_create_entry_rejects_bad_side_and_market(isolated_db):
    service = TradeJournalService(db_manager=isolated_db)
    with pytest.raises(TradeJournalValidationError):
        service.create_entry(_entry(side="hold"))
    with pytest.raises(TradeJournalValidationError):
        service.create_entry(_entry(market="xx"))
    with pytest.raises(TradeJournalValidationError):
        service.create_entry(_entry(quantity=-1))


def test_fifo_pnl(isolated_db):
    service = TradeJournalService(db_manager=isolated_db)
    service.create_entry(_entry(side="buy", quantity=100, price=10.0, trade_date="2026-01-01"))
    service.create_entry(_entry(side="sell", quantity=60, price=12.0, trade_date="2026-01-02"))
    service.create_entry(_entry(side="buy", quantity=40, price=8.0, trade_date="2026-01-03"))
    service.create_entry(_entry(side="sell", quantity=80, price=11.0, trade_date="2026-01-04"))

    result = service.compute_position_pnl(market="cn", code="600519")
    assert result["closed_count"] == 3
    assert result["open_quantity"] == 0
    # sell 60@12 vs cost 10 -> +120; sell 40@11 vs 10 -> +40; sell 40@11 vs 8 -> +120
    assert result["realized_pnl"] == 280.0


def test_fifo_pnl_with_fees_builds_cost_basis(isolated_db):
    service = TradeJournalService(db_manager=isolated_db)
    # 买入 100 股 @10，费用 10 -> 每股成本 10.1
    service.create_entry(_entry(side="buy", quantity=100, price=10.0, fee=10.0))
    service.create_entry(_entry(side="sell", quantity=100, price=11.0))
    result = service.compute_position_pnl(market="cn", code="600519")
    assert result["realized_pnl"] == 90.0  # (11 - 10.1) * 100


def test_review_aggregates_discipline_and_emotions(isolated_db):
    service = TradeJournalService(db_manager=isolated_db)
    service.create_entry(_entry(side="buy", quantity=100, price=10.0, plan_followed=True, emotion="calm"))
    service.create_entry(_entry(side="sell", quantity=100, price=12.0, plan_followed=False, emotion="fomo"))
    review = service.review()
    assert review["entry_count"] == 2
    assert review["closed_trade_count"] == 1
    assert review["win_rate"] == 100
    assert review["discipline_score"] == 50  # 1 followed / 2 declared
    assert review["emotion_breakdown"] == {"calm": 1, "fomo": 1}


def test_classify_entry_discipline_with_linked_signal(isolated_db):
    service = TradeJournalService(db_manager=isolated_db)
    signal_repo = DecisionSignalRepository(isolated_db)
    signal = signal_repo.create({
        "stock_code": "600519",
        "market": "cn",
        "source_type": "analysis",
        "trigger_source": "test",
        "action": "buy",
        "status": "active",
    })
    item = service.create_entry(_entry(side="buy", linked_signal_id=signal.id))
    result = service.classify_entry_discipline(item["id"])
    assert result["signal_action"] == "buy"
    assert result["discipline"] == "aligned"


def test_delete_entry(isolated_db):
    service = TradeJournalService(db_manager=isolated_db)
    item = service.create_entry(_entry())
    assert service.delete_entry(item["id"]) is True
    with pytest.raises(Exception):
        service.get_entry(item["id"])
