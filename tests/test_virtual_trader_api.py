# -*- coding: utf-8 -*-
"""API tests for the virtual trader endpoints."""

from __future__ import annotations

import os
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager


@pytest.fixture()
def client(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "virtual_trader_api.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False):
        app = create_app(static_dir=tmp_path / "static")
        yield TestClient(app)
    DatabaseManager.reset_instance()
    Config.reset_instance()
    if old_database_path is None:
        os.environ.pop("DATABASE_PATH", None)
    else:
        os.environ["DATABASE_PATH"] = old_database_path


def _flat_history_fn(code, days=120, target_date=None):
    closes = [100.0] * 80
    return (
        pd.DataFrame({
            "date": [date(2026, 1, 1) + timedelta(days=i) for i in range(80)],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1e6] * 80,
        }),
        "test",
    )


class TestVirtualTraderApi:
    def test_run_seeds_account_and_endpoints_return_data(self, client):
        with patch(
            "src.services.virtual_trader.runner.load_history_df",
            side_effect=_flat_history_fn,
        ):
            run = client.post("/api/v1/virtual-trader/run", json={})
            assert run.status_code == 200
            body = run.json()
            assert len(body["results"]) == 3
            assert all(r["status"] == "success" for r in body["results"])

        account = client.get("/api/v1/virtual-trader/account").json()
        assert account["status"] == "active"
        assert len(account["positions"]) == 6
        assert account["initial_cash_cny"] == pytest.approx(1_000_000.0)
        assert account["total_value_cny"] > 0

        trades = client.get("/api/v1/virtual-trader/trades").json()
        assert trades["total"] == 6

        curve = client.get("/api/v1/virtual-trader/equity-curve").json()
        # 三个市场同属一个交易日时只落一条快照（按账户+日期唯一）
        assert len(curve["points"]) == 1
        assert curve["points"][0]["positions_count"] == 6

        stats = client.get("/api/v1/virtual-trader/stats").json()
        assert stats["total_trades"] == 6
        assert stats["buy_trades"] == 6
        assert stats["prediction"]["total"] == 0

    def test_account_before_seed_returns_empty_placeholder(self, client):
        account = client.get("/api/v1/virtual-trader/account").json()
        assert account["status"] == "not_seeded"
        assert account["positions"] == []

    def test_run_single_market(self, client):
        with patch(
            "src.services.virtual_trader.runner.load_history_df",
            side_effect=_flat_history_fn,
        ):
            run = client.post("/api/v1/virtual-trader/run", json={"market": "cn"})
            assert run.status_code == 200
            assert len(run.json()["results"]) == 1

    def test_run_rejects_invalid_market(self, client):
        run = client.post("/api/v1/virtual-trader/run", json={"market": "mars"})
        # 未支持的市场返回 skipped 而不是报错
        assert run.status_code == 200
        assert run.json()["results"][0]["status"] == "skipped"

    def test_reset_requires_confirm(self, client):
        no_confirm = client.post("/api/v1/virtual-trader/reset", json={"confirm": False})
        assert no_confirm.status_code == 400

        with patch(
            "src.services.virtual_trader.runner.load_history_df",
            side_effect=_flat_history_fn,
        ):
            client.post("/api/v1/virtual-trader/run", json={})
            reset = client.post("/api/v1/virtual-trader/reset", json={"confirm": True})
            assert reset.status_code == 200
            assert reset.json()["success"] is True

    def test_predictions_list_empty(self, client):
        preds = client.get("/api/v1/virtual-trader/predictions").json()
        assert preds["total"] == 0
