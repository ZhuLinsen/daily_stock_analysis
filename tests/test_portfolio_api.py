# -*- coding: utf-8 -*-
"""Integration tests for portfolio API endpoints (P0 PR1 scope)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
from src.services.portfolio_service import PortfolioBusyError
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

    def _create_position(
        self,
        *,
        name: str = "Main",
        symbol: str = "600519",
        quantity: float = 10.0,
        market: str = "cn",
        currency: str = "CNY",
    ) -> int:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": name, "broker": "Demo", "market": market, "base_currency": currency},
        )
        self.assertEqual(create_resp.status_code, 200, create_resp.text)
        account_id = create_resp.json()["id"]
        trade_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": account_id,
                "symbol": symbol,
                "trade_date": "2026-01-02",
                "side": "buy",
                "quantity": quantity,
                "price": 100,
                "fee": 0,
                "tax": 0,
                "market": market,
                "currency": currency,
            },
        )
        self.assertEqual(trade_resp.status_code, 200, trade_resp.text)
        self._save_close(symbol, date(2026, 1, 3), 110.0)
        return account_id

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

    def test_snapshot_exposes_partial_quality_fields_for_mixed_position_markets(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Mixed", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        trade_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": account_id,
                "symbol": "7203.T",
                "trade_date": "2026-01-02",
                "side": "buy",
                "quantity": 10,
                "price": 1000,
                "fee": 0,
                "tax": 0,
                "market": "jp",
                "currency": "JPY",
            },
        )
        self.assertEqual(trade_resp.status_code, 200, trade_resp.text)
        self._save_close("7203.T", date(2026, 1, 3), 1200.0)

        snapshot_resp = self.client.get(
            "/api/v1/portfolio/snapshot",
            params={"as_of": "2026-01-03"},
        )
        self.assertEqual(snapshot_resp.status_code, 200)
        payload = snapshot_resp.json()
        self.assertEqual(payload["data_quality"], "partial")
        self.assertIn("fx_and_cost_basis_partial", payload["limitations"])
        account_snapshot = payload["accounts"][0]
        position = account_snapshot["positions"][0]

        self.assertEqual(account_snapshot["market"], "cn")
        self.assertEqual(account_snapshot["data_quality"], "partial")
        self.assertIn("fx_and_cost_basis_partial", account_snapshot["limitations"])
        self.assertEqual(position["market"], "jp")
        self.assertEqual(position["data_quality"], "partial")
        self.assertIn("realtime_quote_best_effort", position["limitations"])

    def test_delete_account_deactivates_without_hard_deleting(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Mistyped", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        delete_resp = self.client.delete(f"/api/v1/portfolio/accounts/{account_id}")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertEqual(delete_resp.json()["deleted"], 1)

        active_resp = self.client.get("/api/v1/portfolio/accounts")
        self.assertEqual(active_resp.status_code, 200)
        self.assertEqual(active_resp.json()["accounts"], [])

        inactive_resp = self.client.get(
            "/api/v1/portfolio/accounts",
            params={"include_inactive": True},
        )
        self.assertEqual(inactive_resp.status_code, 200)
        inactive_accounts = inactive_resp.json()["accounts"]
        self.assertEqual(len(inactive_accounts), 1)
        self.assertEqual(inactive_accounts[0]["id"], account_id)
        self.assertFalse(inactive_accounts[0]["is_active"])

        snapshot_resp = self.client.get(
            "/api/v1/portfolio/snapshot",
            params={"account_id": account_id, "as_of": "2026-01-03"},
        )
        self.assertEqual(snapshot_resp.status_code, 400)
        self.assertEqual(snapshot_resp.json()["error"], "validation_error")

    def test_event_lists_hide_archived_account_rows_by_default(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Archived", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
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
        trade_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
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
            },
        )
        corp_resp = self.client.post(
            "/api/v1/portfolio/corporate-actions",
            json={
                "account_id": account_id,
                "symbol": "600519",
                "effective_date": "2026-01-03",
                "action_type": "cash_dividend",
                "market": "cn",
                "currency": "CNY",
                "cash_dividend_per_share": 1.0,
            },
        )
        self.assertEqual(cash_resp.status_code, 200)
        self.assertEqual(trade_resp.status_code, 200)
        self.assertEqual(corp_resp.status_code, 200)

        delete_resp = self.client.delete(f"/api/v1/portfolio/accounts/{account_id}")
        self.assertEqual(delete_resp.status_code, 200)

        for endpoint in (
            "/api/v1/portfolio/trades",
            "/api/v1/portfolio/cash-ledger",
            "/api/v1/portfolio/corporate-actions",
        ):
            list_resp = self.client.get(endpoint)
            self.assertEqual(list_resp.status_code, 200, list_resp.text)
            payload = list_resp.json()
            self.assertEqual(payload["total"], 0)
            self.assertEqual(payload["items"], [])

    def test_default_risk_hides_archived_account_snapshot_drawdown(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Archived Risk", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        cash_resp = self.client.post(
            "/api/v1/portfolio/cash-ledger",
            json={
                "account_id": account_id,
                "event_date": "2026-01-01",
                "direction": "in",
                "amount": 20000,
                "currency": "CNY",
            },
        )
        trade_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": account_id,
                "symbol": "600519",
                "trade_date": "2026-01-01",
                "side": "buy",
                "quantity": 100,
                "price": 100,
                "fee": 0,
                "tax": 0,
                "market": "cn",
                "currency": "CNY",
            },
        )
        self.assertEqual(cash_resp.status_code, 200)
        self.assertEqual(trade_resp.status_code, 200)
        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("600519", date(2026, 1, 2), 70.0)

        before_archive = self.client.get(
            "/api/v1/portfolio/risk",
            params={"as_of": "2026-01-02", "cost_method": "fifo"},
        )
        self.assertEqual(before_archive.status_code, 200, before_archive.text)
        before_payload = before_archive.json()
        self.assertGreaterEqual(before_payload["drawdown"]["series_points"], 2)
        self.assertGreater(before_payload["drawdown"]["max_drawdown_pct"], 10.0)
        self.assertTrue(before_payload["drawdown"]["alert"])

        delete_resp = self.client.delete(f"/api/v1/portfolio/accounts/{account_id}")
        self.assertEqual(delete_resp.status_code, 200)

        after_archive = self.client.get(
            "/api/v1/portfolio/risk",
            params={"as_of": "2026-01-02", "cost_method": "fifo"},
        )
        self.assertEqual(after_archive.status_code, 200, after_archive.text)
        after_payload = after_archive.json()
        self.assertAlmostEqual(after_payload["concentration"]["total_market_value"], 0.0, places=6)
        self.assertEqual(after_payload["drawdown"]["series_points"], 0)
        self.assertAlmostEqual(after_payload["drawdown"]["max_drawdown_pct"], 0.0, places=6)
        self.assertAlmostEqual(after_payload["drawdown"]["current_drawdown_pct"], 0.0, places=6)
        self.assertFalse(after_payload["drawdown"]["alert"])

    def test_position_analysis_accepts_real_holding_and_passes_internal_context(self) -> None:
        account_id = self._create_position(quantity=10)
        accepted_task = SimpleNamespace(
            task_id="task-portfolio-1",
            trace_id="trace-portfolio-1",
            stock_code="600519",
            analysis_phase="intraday",
        )
        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([accepted_task], [])

        with patch(
            "src.services.portfolio_service.PortfolioService._fetch_realtime_position_price",
            return_value=(None, None),
        ), patch("api.v1.endpoints.portfolio.get_task_queue", return_value=queue):
            resp = self.client.post(
                "/api/v1/portfolio/positions/600519/analysis",
                json={"account_id": account_id, "analysis_phase": "intraday", "force": True},
            )

        self.assertEqual(resp.status_code, 202, resp.text)
        payload = resp.json()
        self.assertEqual(payload["task_id"], "task-portfolio-1")
        self.assertEqual(payload["analysis_phase"], "intraday")
        self.assertNotIn("portfolio_context", str(payload))

        args, kwargs = queue.submit_tasks_batch.call_args
        self.assertEqual(args[0], ["600519"])
        self.assertEqual(kwargs["selection_source"], "manual")
        self.assertEqual(kwargs["query_source"], "portfolio")
        self.assertEqual(kwargs["analysis_phase"], "intraday")
        self.assertTrue(kwargs["force_refresh"])
        self.assertEqual(kwargs["portfolio_context"]["account_id"], account_id)
        self.assertEqual(kwargs["portfolio_context"]["quantity"], 10.0)
        self.assertEqual(kwargs["portfolio_context"]["cost_method"], "fifo")

    def test_position_analysis_matches_exchange_suffix_position_symbol(self) -> None:
        account_id = self._create_position(symbol="600519.SH", quantity=10)
        accepted_task = SimpleNamespace(
            task_id="task-portfolio-sh",
            trace_id="trace-portfolio-sh",
            stock_code="SH600519",
            analysis_phase="auto",
        )
        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([accepted_task], [])

        with patch(
            "src.services.portfolio_service.PortfolioService._fetch_realtime_position_price",
            return_value=(None, None),
        ), patch("api.v1.endpoints.portfolio.get_task_queue", return_value=queue):
            resp = self.client.post(
                "/api/v1/portfolio/positions/600519.SH/analysis",
                json={"account_id": account_id},
            )

        self.assertEqual(resp.status_code, 202, resp.text)
        args, kwargs = queue.submit_tasks_batch.call_args
        self.assertEqual(args[0], ["SH600519"])
        self.assertEqual(kwargs["portfolio_context"]["symbol"], "SH600519")

    def test_position_analysis_matches_hk_suffix_position_symbol(self) -> None:
        account_id = self._create_position(
            symbol="1810.HK",
            quantity=10,
            market="hk",
            currency="HKD",
        )
        accepted_task = SimpleNamespace(
            task_id="task-portfolio-hk",
            trace_id="trace-portfolio-hk",
            stock_code="HK01810",
            analysis_phase="auto",
        )
        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([accepted_task], [])

        with patch(
            "src.services.portfolio_service.PortfolioService._fetch_realtime_position_price",
            return_value=(None, None),
        ), patch("api.v1.endpoints.portfolio.get_task_queue", return_value=queue):
            resp = self.client.post(
                "/api/v1/portfolio/positions/1810.HK/analysis",
                json={"account_id": account_id},
            )

        self.assertEqual(resp.status_code, 202, resp.text)
        args, kwargs = queue.submit_tasks_batch.call_args
        self.assertEqual(args[0], ["HK01810"])
        self.assertEqual(kwargs["portfolio_context"]["symbol"], "HK01810")
        self.assertEqual(kwargs["portfolio_context"]["market"], "hk")
        self.assertEqual(kwargs["portfolio_context"]["currency"], "HKD")

    def test_position_analysis_returns_404_for_missing_holding(self) -> None:
        resp = self.client.post("/api/v1/portfolio/positions/600519/analysis", json={})

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"], "not_found")

    def test_position_analysis_requires_account_when_symbol_is_held_in_multiple_accounts(self) -> None:
        self._create_position(name="Main", quantity=10)
        self._create_position(name="Second", quantity=20)

        resp = self.client.post("/api/v1/portfolio/positions/600519/analysis", json={})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "ambiguous_position_account")

    def test_position_analysis_duplicate_task_returns_409(self) -> None:
        account_id = self._create_position(quantity=10)
        duplicate = SimpleNamespace(stock_code="600519.SH", existing_task_id="existing-task-1")
        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [duplicate])

        with patch(
            "src.services.portfolio_service.PortfolioService._fetch_realtime_position_price",
            return_value=(None, None),
        ), patch("api.v1.endpoints.portfolio.get_task_queue", return_value=queue):
            resp = self.client.post(
                "/api/v1/portfolio/positions/600519/analysis",
                json={"account_id": account_id, "force": True},
            )

        self.assertEqual(resp.status_code, 409, resp.text)
        payload = resp.json()
        self.assertEqual(payload["error"], "duplicate_task")
        self.assertEqual(payload["existing_task_id"], "existing-task-1")
        self.assertTrue(queue.submit_tasks_batch.call_args.kwargs["force_refresh"])

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

    def test_oversell_trade_returns_409_with_business_error(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Main", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        buy_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
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
            },
        )
        self.assertEqual(buy_resp.status_code, 200)

        sell_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": account_id,
                "symbol": "600519",
                "trade_date": "2026-01-03",
                "side": "sell",
                "quantity": 20,
                "price": 90,
                "fee": 0,
                "tax": 0,
                "market": "cn",
                "currency": "CNY",
            },
        )
        self.assertEqual(sell_resp.status_code, 409)
        detail = sell_resp.json()
        self.assertEqual(detail.get("error"), "portfolio_oversell")
        self.assertIn("Oversell detected", detail.get("message", ""))

    def test_duplicate_full_close_sell_still_returns_conflict(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Main", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        buy_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
                "account_id": account_id,
                "symbol": "600519",
                "trade_date": "2026-01-01",
                "side": "buy",
                "quantity": 10,
                "price": 100,
                "fee": 0,
                "tax": 0,
                "market": "cn",
                "currency": "CNY",
            },
        )
        self.assertEqual(buy_resp.status_code, 200)

        payload = {
            "account_id": account_id,
            "symbol": "600519",
            "trade_date": "2026-01-02",
            "side": "sell",
            "quantity": 10,
            "price": 90,
            "fee": 0,
            "tax": 0,
            "market": "cn",
            "currency": "CNY",
            "trade_uid": "dup-full-close-sell-1",
        }
        first_sell = self.client.post("/api/v1/portfolio/trades", json=payload)
        self.assertEqual(first_sell.status_code, 200)

        second_sell = self.client.post("/api/v1/portfolio/trades", json=payload)
        self.assertEqual(second_sell.status_code, 409)
        detail = second_sell.json()
        self.assertEqual(detail.get("error"), "conflict")
        self.assertIn("Duplicate trade_uid", detail.get("message", ""))

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

    def test_delete_event_endpoints_remove_records_and_allow_snapshot_recovery(self) -> None:
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
        trade_resp = self.client.post(
            "/api/v1/portfolio/trades",
            json={
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
            },
        )
        corp_resp = self.client.post(
            "/api/v1/portfolio/corporate-actions",
            json={
                "account_id": account_id,
                "symbol": "600519",
                "effective_date": "2026-01-03",
                "action_type": "cash_dividend",
                "market": "cn",
                "currency": "CNY",
                "cash_dividend_per_share": 1.0,
            },
        )
        self.assertEqual(cash_resp.status_code, 200)
        self.assertEqual(trade_resp.status_code, 200)
        self.assertEqual(corp_resp.status_code, 200)

        self._save_close("600519", date(2026, 1, 3), 100.0)
        snapshot_before = self.client.get(
            "/api/v1/portfolio/snapshot",
            params={"account_id": account_id, "as_of": "2026-01-03"},
        )
        self.assertEqual(snapshot_before.status_code, 200)
        self.assertEqual(snapshot_before.json()["accounts"][0]["positions"][0]["quantity"], 10.0)

        delete_trade = self.client.delete(f"/api/v1/portfolio/trades/{trade_resp.json()['id']}")
        self.assertEqual(delete_trade.status_code, 200)
        self.assertEqual(delete_trade.json()["deleted"], 1)

        snapshot_after_trade = self.client.get(
            "/api/v1/portfolio/snapshot",
            params={"account_id": account_id, "as_of": "2026-01-03"},
        )
        self.assertEqual(snapshot_after_trade.status_code, 200)
        self.assertEqual(snapshot_after_trade.json()["accounts"][0]["positions"], [])

        delete_cash = self.client.delete(f"/api/v1/portfolio/cash-ledger/{cash_resp.json()['id']}")
        self.assertEqual(delete_cash.status_code, 200)
        self.assertEqual(delete_cash.json()["deleted"], 1)

        delete_corp = self.client.delete(f"/api/v1/portfolio/corporate-actions/{corp_resp.json()['id']}")
        self.assertEqual(delete_corp.status_code, 200)
        self.assertEqual(delete_corp.json()["deleted"], 1)

        missing_trade = self.client.delete("/api/v1/portfolio/trades/999999")
        self.assertEqual(missing_trade.status_code, 404)

    def test_create_trade_busy_returns_409(self) -> None:
        with patch(
            "api.v1.endpoints.portfolio.PortfolioService.record_trade",
            side_effect=PortfolioBusyError("Portfolio ledger is busy; please retry shortly."),
        ):
            resp = self.client.post(
                "/api/v1/portfolio/trades",
                json={
                    "account_id": 1,
                    "symbol": "600519",
                    "trade_date": "2026-01-02",
                    "side": "buy",
                    "quantity": 10,
                    "price": 100,
                    "fee": 0,
                    "tax": 0,
                    "market": "cn",
                    "currency": "CNY",
                },
            )

        self.assertEqual(resp.status_code, 409)
        detail = resp.json()
        self.assertEqual(detail.get("error"), "portfolio_busy")

    def test_delete_trade_busy_returns_409(self) -> None:
        with patch(
            "api.v1.endpoints.portfolio.PortfolioService.delete_trade_event",
            side_effect=PortfolioBusyError("Portfolio ledger is busy; please retry shortly."),
        ):
            resp = self.client.delete("/api/v1/portfolio/trades/1")

        self.assertEqual(resp.status_code, 409)
        detail = resp.json()
        self.assertEqual(detail.get("error"), "portfolio_busy")

    def test_create_cash_ledger_busy_returns_409(self) -> None:
        with patch(
            "api.v1.endpoints.portfolio.PortfolioService.record_cash_ledger",
            side_effect=PortfolioBusyError("Portfolio ledger is busy; please retry shortly."),
        ):
            resp = self.client.post(
                "/api/v1/portfolio/cash-ledger",
                json={
                    "account_id": 1,
                    "event_date": "2026-01-02",
                    "direction": "in",
                    "amount": 1000,
                    "currency": "CNY",
                },
            )

        self.assertEqual(resp.status_code, 409)
        detail = resp.json()
        self.assertEqual(detail.get("error"), "portfolio_busy")

    def test_delete_cash_ledger_busy_returns_409(self) -> None:
        with patch(
            "api.v1.endpoints.portfolio.PortfolioService.delete_cash_ledger_event",
            side_effect=PortfolioBusyError("Portfolio ledger is busy; please retry shortly."),
        ):
            resp = self.client.delete("/api/v1/portfolio/cash-ledger/1")

        self.assertEqual(resp.status_code, 409)
        detail = resp.json()
        self.assertEqual(detail.get("error"), "portfolio_busy")

    def test_create_corporate_action_busy_returns_409(self) -> None:
        with patch(
            "api.v1.endpoints.portfolio.PortfolioService.record_corporate_action",
            side_effect=PortfolioBusyError("Portfolio ledger is busy; please retry shortly."),
        ):
            resp = self.client.post(
                "/api/v1/portfolio/corporate-actions",
                json={
                    "account_id": 1,
                    "symbol": "600519",
                    "effective_date": "2026-01-02",
                    "action_type": "split_adjustment",
                    "market": "cn",
                    "currency": "CNY",
                    "split_ratio": 2.0,
                },
            )

        self.assertEqual(resp.status_code, 409)
        detail = resp.json()
        self.assertEqual(detail.get("error"), "portfolio_busy")

    def test_delete_corporate_action_busy_returns_409(self) -> None:
        with patch(
            "api.v1.endpoints.portfolio.PortfolioService.delete_corporate_action_event",
            side_effect=PortfolioBusyError("Portfolio ledger is busy; please retry shortly."),
        ):
            resp = self.client.delete("/api/v1/portfolio/corporate-actions/1")

        self.assertEqual(resp.status_code, 409)
        detail = resp.json()
        self.assertEqual(detail.get("error"), "portfolio_busy")

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
