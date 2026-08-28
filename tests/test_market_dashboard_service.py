# -*- coding: utf-8 -*-
"""Tests for the market dashboard service."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from src.config import Config
from src.services.market_dashboard_service import MarketDashboardService
from src.services.market_temperature_service import MarketTemperatureService
from src.storage import DatabaseManager


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "market_dashboard.db")
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


def _make_overview():
    return SimpleNamespace(
        date="2026-01-06",
        market="cn",
        up_count=3200,
        down_count=1400,
        flat_count=200,
        limit_up_count=80,
        limit_down_count=6,
        total_amount=12500.0,
        indices=[
            SimpleNamespace(code="000001", name="上证指数", change_pct=0.8),
            SimpleNamespace(code="399001", name="深证成指", change_pct=1.2),
        ],
        top_sectors=[
            {"name": "半导体", "change_pct": 3.5},
            {"name": "白酒", "change_pct": 2.1},
            {"name": "券商", "change_pct": 1.8},
        ],
        bottom_sectors=[{"name": "煤炭", "change_pct": -1.9}],
        top_concepts=[{"name": "AI 算力", "change_pct": 4.2}],
        bottom_concepts=[],
    )


def _make_flow_block(top=(("半导体", 52.3),), bottom=(("煤炭", -38.1),)):
    def build(items):
        return [{"name": n, "net_inflow": v} for n, v in items]

    return {
        "status": "ok",
        "data": {"sector_rankings": {"top": build(top), "bottom": build(bottom)}},
    }


def _constituents(sector_name, top_n):
    pool = {
        "半导体": [
            {"code": "688981", "name": "中芯国际", "change_pct": 12.0, "price": 55.1},
            {"code": "600584", "name": "长电科技", "change_pct": 6.4, "price": 31.2},
            {"code": "000725", "name": "ST京东方", "change_pct": 5.0, "price": 4.1},
        ],
        "白酒": [
            {"code": "600519", "name": "贵州茅台", "change_pct": 3.2, "price": 1340.0},
        ],
        "券商": [
            {"code": "600030", "name": "中信证券", "change_pct": 2.5, "price": 21.4},
        ],
    }
    return pool.get(sector_name, [])[:top_n]


def _service(isolated_db):
    return MarketDashboardService(
        temperature_service=MarketTemperatureService(db_manager=isolated_db),
    )


def test_dashboard_happy_path(isolated_db):
    result = _service(isolated_db).dashboard(
        "cn",
        overview_provider=_make_overview,
        flow_provider=lambda: _make_flow_block(),
        constituents_provider=_constituents,
    )

    assert result["market"] == "cn"
    assert result["trade_date"] == "2026-01-06"

    # 温度已计算并带来源
    temperature = result["temperature"]
    assert temperature is not None
    assert temperature["source"] == "market_stats"
    assert temperature["available_dimensions"] == 3

    # 指数与宽度
    assert [i["code"] for i in result["indices"]] == ["000001", "399001"]
    assert result["breadth"]["up_count"] == 3200
    assert result["breadth"]["limit_up_count"] == 80
    assert result["breadth"]["total_amount"] == 12500.0

    # 热门板块 / 概念
    assert result["hot_sectors"]["top"][0]["name"] == "半导体"
    assert result["hot_concepts"]["top"][0]["name"] == "AI 算力"

    # 资金流
    assert result["capital_flow"]["status"] == "ok"
    assert result["capital_flow"]["sector_rankings"]["top"][0]["net_inflow"] == 52.3

    # 候选池：半导体 2 只（ST 被过滤）+ 白酒 1 只 + 券商 1 只
    candidates = result["candidates"]
    assert [c["code"] for c in candidates] == ["688981", "600584", "600519", "600030"]
    assert all("ST" not in c["name"].upper() for c in candidates)
    assert candidates[0]["sector"] == "半导体"
    assert "板块领涨" in candidates[0]["reason"]

    # 无数据缺口提示
    assert result["notes"] == []


def test_dashboard_temperature_persists(isolated_db):
    temperature_service = MarketTemperatureService(db_manager=isolated_db)
    MarketDashboardService(temperature_service=temperature_service).dashboard(
        "cn",
        overview_provider=_make_overview,
        flow_provider=lambda: _make_flow_block(),
        constituents_provider=_constituents,
    )
    latest = temperature_service.latest("cn")
    assert latest is not None
    assert latest["trade_date"] == "2026-01-06"


def test_dashboard_flow_unavailable_fails_open(isolated_db):
    result = _service(isolated_db).dashboard(
        "cn",
        overview_provider=_make_overview,
        flow_provider=lambda: {"status": "not_supported", "data": {}},
        constituents_provider=_constituents,
    )
    assert result["capital_flow"]["status"] == "unavailable"
    assert result["capital_flow"]["sector_rankings"]["top"] == []
    assert any("资金流" in note for note in result["notes"])


def test_dashboard_flow_exception_fails_open(isolated_db):
    def _boom():
        raise RuntimeError("network down")

    result = _service(isolated_db).dashboard(
        "cn",
        overview_provider=_make_overview,
        flow_provider=_boom,
        constituents_provider=_constituents,
    )
    assert result["capital_flow"]["status"] == "unavailable"


def test_dashboard_constituents_failure_fails_open(isolated_db):
    def _no_rows(sector_name, top_n):
        return []

    result = _service(isolated_db).dashboard(
        "cn",
        overview_provider=_make_overview,
        flow_provider=lambda: _make_flow_block(),
        constituents_provider=_no_rows,
    )
    assert result["candidates"] == []
    assert any("候选观察池" in note for note in result["notes"])


def test_dashboard_rejects_non_cn(isolated_db):
    with pytest.raises(ValueError):
        _service(isolated_db).dashboard("us", overview_provider=_make_overview)


def test_dashboard_sector_fetch_timeout_is_bounded(isolated_db, monkeypatch):
    import time

    def _slow_provider(sector_name, top_n):
        time.sleep(0.5)
        return [{"code": "600519", "name": "贵州茅台", "change_pct": 3.0, "price": 1340.0}]

    service = _service(isolated_db)
    monkeypatch.setattr(service, "SECTOR_FETCH_TIMEOUT_SECONDS", 0.05)
    start = time.time()
    result = service.dashboard(
        "cn",
        overview_provider=_make_overview,
        flow_provider=lambda: _make_flow_block(),
        constituents_provider=_slow_provider,
    )
    elapsed = time.time() - start
    # 超时被硬性限制：三个板块各 0.05s 超时，总耗时应远小于 0.5s
    assert elapsed < 0.5
    assert result["candidates"] == []
    assert any("候选观察池" in note for note in result["notes"])


def test_dashboard_dedupes_candidates_across_sectors(isolated_db):
    overview = _make_overview()
    overview.top_sectors = [
        {"name": "半导体", "change_pct": 3.5},
        {"name": "白酒", "change_pct": 2.1},
    ]

    def _same_stock(sector_name, top_n):
        return [{"code": "600519", "name": "贵州茅台", "change_pct": 3.0, "price": 1340.0}]

    result = _service(isolated_db).dashboard(
        "cn",
        overview_provider=lambda: overview,
        flow_provider=lambda: _make_flow_block(),
        constituents_provider=_same_stock,
    )
    codes = [c["code"] for c in result["candidates"]]
    assert codes == ["600519"]  # 跨板块去重
    assert result["candidates"][0]["sector"] == "半导体"  # 归属首个命中板块
