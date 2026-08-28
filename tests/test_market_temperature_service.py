# -*- coding: utf-8 -*-
"""Tests for the market temperature service."""

from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace

import pytest

from src.config import Config
from src.services.market_temperature_service import (
    MarketTemperatureService,
    compute_temperature,
    label_for_score,
)
from src.storage import DatabaseManager, StockDaily


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "market_temperature.db")
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


def test_label_for_score_bands():
    assert label_for_score(90) == ("extreme_greed", "极度贪婪")
    assert label_for_score(70) == ("greed", "贪婪")
    assert label_for_score(50) == ("neutral", "中性")
    assert label_for_score(30) == ("fear", "恐惧")
    assert label_for_score(5) == ("extreme_fear", "极度恐惧")


def test_compute_temperature_bullish_snapshot():
    result = compute_temperature({
        "advancers": 3000,
        "decliners": 1000,
        "limit_up": 100,
        "limit_down": 5,
        "new_high_52w": 200,
        "new_low_52w": 50,
    })
    assert result["score"] >= 80
    assert result["label_key"] == "extreme_greed"
    assert result["available_dimensions"] == 3


def test_compute_temperature_bearish_snapshot():
    result = compute_temperature({
        "advancers": 500,
        "decliners": 4500,
        "limit_up": 2,
        "limit_down": 80,
        "new_high_52w": 10,
        "new_low_52w": 300,
    })
    assert result["score"] <= 20
    assert result["label_key"] == "extreme_fear"


def test_compute_temperature_missing_dimensions_neutral():
    result = compute_temperature({})
    assert result["score"] == 50
    assert result["label_key"] == "neutral"
    assert result["available_dimensions"] == 0


def test_compute_temperature_ignores_invalid_values():
    result = compute_temperature({"advancers": "not-a-number", "decliners": 100})
    assert result["available_dimensions"] == 0
    assert result["score"] == 50


def test_snapshot_persists_and_upserts(isolated_db):
    service = MarketTemperatureService(db_manager=isolated_db)
    first = service.snapshot("cn", {"advancers": 3000, "decliners": 1000}, trade_date="2026-01-05")
    assert first["score"] >= 60
    assert first["label_key"] in ("greed", "extreme_greed")
    # 同市场同日期再次写入 -> 更新而非新增
    second = service.snapshot("cn", {"advancers": 1000, "decliners": 3000}, trade_date="2026-01-05")
    assert second["score"] <= 40

    latest = service.latest("cn")
    assert latest["score"] <= 40

    items, total = service.history(market="cn")
    assert total == 1  # upsert 未产生重复快照


def test_compute_from_database_breadth(isolated_db):
    with isolated_db.get_session() as session:
        rows = [
            StockDaily(code="A", date=date(2026, 1, 5), pct_chg=2.0),
            StockDaily(code="B", date=date(2026, 1, 5), pct_chg=1.0),
            StockDaily(code="C", date=date(2026, 1, 5), pct_chg=-1.0),
            StockDaily(code="D", date=date(2026, 1, 5), pct_chg=0.0),
        ]
        session.add_all(rows)
        session.commit()

    service = MarketTemperatureService(db_manager=isolated_db)
    result = service.compute_from_database("cn")
    assert result["source"] == "tracked_universe"
    assert result["score"] > 50  # 2 涨 1 跌 -> 偏多
    assert result["trade_date"] == "2026-01-05"
    # 结果已落库：latest 与 history 立即可见
    latest = service.latest("cn")
    assert latest is not None and latest["score"] == result["score"]
    _, total = service.history(market="cn")
    assert total == 1
    # reasons 附带样本提示
    assert any("4 只自选股" in reason for reason in result["reasons"])


def test_compute_from_database_uses_per_stock_latest(isolated_db):
    # 两只股票数据日期不同步：A 最新到 1/6，B 只到 1/5。
    # 旧实现共享 MAX(date)=1/6 只会统计到 A；新实现每只股票各取最新一条。
    with isolated_db.get_session() as session:
        rows = [
            StockDaily(code="A", date=date(2026, 1, 5), pct_chg=5.0),
            StockDaily(code="A", date=date(2026, 1, 6), pct_chg=-2.0),
            StockDaily(code="B", date=date(2026, 1, 5), pct_chg=3.0),
        ]
        session.add_all(rows)
        session.commit()

    service = MarketTemperatureService(db_manager=isolated_db)
    result = service.compute_from_database("cn")
    assert result["trade_date"] == "2026-01-06"
    # A(-2%) 跌、B(+3%) 涨 -> 1:1 宽度 -> 50 分中性
    assert result["score"] == 50
    assert any("2 只自选股" in reason for reason in result["reasons"])


def test_compute_from_database_requires_daily_data(isolated_db):
    service = MarketTemperatureService(db_manager=isolated_db)
    with pytest.raises(ValueError):
        service.compute_from_database("cn")


def _make_overview(**overrides):
    base = {
        "date": "2026-01-06",
        "up_count": 3200,
        "down_count": 1400,
        "flat_count": 200,
        "limit_up_count": 80,
        "limit_down_count": 6,
        "total_amount": 12000.0,
        "indices": [
            SimpleNamespace(code="399001", name="深证成指", change_pct=1.2),
            SimpleNamespace(code="000001", name="上证指数", change_pct=0.8),
        ],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_compute_from_provider_cn_persists(isolated_db):
    service = MarketTemperatureService(db_manager=isolated_db)
    result = service.compute_from_provider("cn", overview_provider=lambda: _make_overview())

    assert result["source"] == "market_stats"
    assert result["trade_date"] == "2026-01-06"
    keys = {dim["key"] for dim in result["dimensions"]}
    assert keys == {"breadth", "limit", "index"}
    assert result["available_dimensions"] == 3
    # 宽度 3200/(3200+1400) ≈ 70 -> 偏贪婪
    assert 60 <= result["score"] < 80

    # 已落库
    latest = service.latest("cn")
    assert latest is not None and latest["trade_date"] == "2026-01-06"
    _, total = service.history(market="cn")
    assert total == 1


def test_compute_from_provider_prefers_mood_index(isolated_db):
    # 上证 000001 排在后面也应被优先选为情绪指数
    service = MarketTemperatureService(db_manager=isolated_db)
    overview = _make_overview(indices=[
        SimpleNamespace(code="399001", name="深证成指", change_pct=9.9),
        SimpleNamespace(code="000001", name="上证指数", change_pct=0.8),
    ])
    result = service.compute_from_provider("cn", overview_provider=lambda: overview)
    index_dim = next(dim for dim in result["dimensions"] if dim["key"] == "index")
    # 0.8% -> 50 + 0.8/10*50 = 54；若误选深证成指会是 99
    assert index_dim["score"] == 54


def test_compute_from_provider_rejects_unsupported_market(isolated_db):
    service = MarketTemperatureService(db_manager=isolated_db)
    with pytest.raises(ValueError):
        service.compute_from_provider("us", overview_provider=lambda: _make_overview())


def test_compute_from_provider_rejects_empty_overview(isolated_db):
    service = MarketTemperatureService(db_manager=isolated_db)
    empty = _make_overview(up_count=0, down_count=0, limit_up_count=0, limit_down_count=0, indices=[])
    with pytest.raises(ValueError):
        service.compute_from_provider("cn", overview_provider=lambda: empty)
