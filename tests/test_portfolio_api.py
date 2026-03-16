# -*- coding: utf-8 -*-
"""Integration tests for portfolio API endpoints (P0 PR1 scope)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient

# Keep this test runnable when optional LLM runtime deps are not installed.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class PortfolioApiTestCase(unittest.TestCase):
    """Portfolio API contract tests for account/events/snapshot."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.db_path = self.data_dir / "portfolio_api_test.db"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    f"DATABASE_PATH={self.db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        app = create_app(static_dir=self.data_dir / "empty-static")
        self.client = TestClient(app)
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _save_close(self, symbol: str, on_date: date, close: float) -> None:
        df = pd.DataFrame(
            [
                {
                    "date": on_date,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                    "amount": close,
                    "pct_chg": 0.0,
                }
            ]
        )
        self.db.save_daily_data(df, code=symbol, data_source="portfolio-api-test")

    def test_account_event_snapshot_flow(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Main", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        list_resp = self.client.get("/api/v1/portfolio/accounts")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json()["accounts"]), 1)

        cash_resp = self.client.post(
            "/api/v1/portfolio/cash-ledger",
            json={
                "account_id": account_id,
                "event_date": "2026-01-01",
                "direction": "in",
                "amount": 10000,
                "currency": "CNY",
            },
        )
        self.assertEqual(cash_resp.status_code, 200)

        trade_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": account_id,
                "symbol": "600519",
                "trade_date": "2026-01-02",
                "side": "buy",
                "quantity": 100,
                "price": 100,
                "fee": 0,
                "tax": 0,
                "market": "cn",
                "currency": "CNY",
            },
        )
        self.assertEqual(trade_resp.status_code, 200)
        self._save_close("600519", date(2026, 1, 3), 110.0)

        snapshot_resp = self.client.get(
            "/api/v1/portfolio/snapshot",
            params={"account_id": account_id, "as_of": "2026-01-03"},
        )
        self.assertEqual(snapshot_resp.status_code, 200)
        payload = snapshot_resp.json()
        self.assertEqual(payload["account_count"], 1)
        self.assertEqual(payload["cost_method"], "fifo")
        account_snapshot = payload["accounts"][0]
        self.assertAlmostEqual(account_snapshot["total_cash"], 0.0, places=6)
        self.assertAlmostEqual(account_snapshot["total_market_value"], 11000.0, places=6)
        self.assertAlmostEqual(account_snapshot["total_equity"], 11000.0, places=6)

    def test_snapshot_invalid_cost_method_returns_400(self) -> None:
        resp = self.client.get("/api/v1/portfolio/snapshot", params={"cost_method": "bad"})
        self.assertEqual(resp.status_code, 400)
        detail = resp.json()
        self.assertEqual(detail.get("error"), "validation_error")

    def test_duplicate_trade_uid_returns_409(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Main", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        payload = {
            "account_id": account_id,
            "symbol": "600519",
            "trade_date": "2026-01-02",
            "side": "buy",
            "quantity": 10,
            "price": 100,
            "fee": 0,
            "tax": 0,
            "market": "cn",
            "currency": "CNY",
            "trade_uid": "dup-uid-1",
        }
        first = self.client.post("/api/v1/portfolio/trades", json=payload)
        self.assertEqual(first.status_code, 200)

        second = self.client.post("/api/v1/portfolio/trades", json=payload)
        self.assertEqual(second.status_code, 409)
        detail = second.json()
        self.assertEqual(detail.get("error"), "conflict")

    def test_event_list_endpoints_and_filters(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Main", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        cash_resp = self.client.post(
            "/api/v1/portfolio/cash-ledger",
            json={
                "account_id": account_id,
                "event_date": "2026-01-01",
                "direction": "in",
                "amount": 10000,
                "currency": "CNY",
            },
        )
        self.assertEqual(cash_resp.status_code, 200)

        trade_payload = {
            "account_id": account_id,
            "symbol": "600519",
            "side": "buy",
            "quantity": 10,
            "price": 100,
            "fee": 1,
            "tax": 0,
            "market": "cn",
            "currency": "CNY",
        }
        self.assertEqual(
            self.client.post("/api/v1/portfolio/trades", json={**trade_payload, "trade_date": "2026-01-02"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post("/api/v1/portfolio/trades", json={**trade_payload, "trade_date": "2026-01-03"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/portfolio/corporate-actions",
                json={
                    "account_id": account_id,
                    "symbol": "600519",
                    "effective_date": "2026-01-04",
                    "action_type": "cash_dividend",
                    "market": "cn",
                    "currency": "CNY",
                    "cash_dividend_per_share": 0.5,
                },
            ).status_code,
            200,
        )

        trades_resp = self.client.get(
            "/api/v1/portfolio/trades",
            params={"account_id": account_id, "page": 1, "page_size": 1},
        )
        self.assertEqual(trades_resp.status_code, 200)
        trades_payload = trades_resp.json()
        self.assertEqual(trades_payload["total"], 2)
        self.assertEqual(len(trades_payload["items"]), 1)
        self.assertEqual(trades_payload["items"][0]["trade_date"], "2026-01-03")

        cash_list_resp = self.client.get(
            "/api/v1/portfolio/cash-ledger",
            params={"account_id": account_id, "direction": "in"},
        )
        self.assertEqual(cash_list_resp.status_code, 200)
        cash_payload = cash_list_resp.json()
        self.assertEqual(cash_payload["total"], 1)
        self.assertEqual(cash_payload["items"][0]["direction"], "in")

        corp_list_resp = self.client.get(
            "/api/v1/portfolio/corporate-actions",
            params={"account_id": account_id, "action_type": "cash_dividend"},
        )
        self.assertEqual(corp_list_resp.status_code, 200)
        corp_payload = corp_list_resp.json()
        self.assertEqual(corp_payload["total"], 1)
        self.assertEqual(corp_payload["items"][0]["action_type"], "cash_dividend")

    def test_csv_broker_list_endpoint(self) -> None:
        resp = self.client.get("/api/v1/portfolio/imports/csv/brokers")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        brokers = {item["broker"] for item in payload["brokers"]}
        self.assertIn("huatai", brokers)
        self.assertIn("citic", brokers)
        self.assertIn("cmb", brokers)

    def test_event_list_invalid_page_size_returns_422(self) -> None:
        resp = self.client.get("/api/v1/portfolio/trades", params={"page_size": 101})
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
