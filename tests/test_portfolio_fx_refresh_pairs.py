# -*- coding: utf-8 -*-
"""FX refresh must cover the account-base → aggregate-currency pair.

Regression: a USD account produced ``pair_count == 0`` because only trade/cash
currencies differing from the *account* base were collected. USD/CNY was never
fetched, so ``_convert_amount`` fell back to 1:1 and the CNY-labelled aggregate
was really raw USD.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.config import Config
from src.services.portfolio_service import PORTFOLIO_AGGREGATE_CURRENCY, PortfolioService
from src.storage import DatabaseManager


class PortfolioFxRefreshPairsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.db_path = Path(self.temp_dir.name) / "portfolio_fx.db"
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
        self.db = DatabaseManager.get_instance()
        self.service = PortfolioService()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _account(self, *, market: str, currency: str):
        return self.service.create_account(
            name=f"{market}-account", broker="Demo", market=market, base_currency=currency
        )

    def test_foreign_base_account_needs_the_aggregate_pair(self) -> None:
        account = self._account(market="us", currency="USD")
        row = self.service.repo.get_account(account["id"])

        currencies = self.service._list_account_refresh_fx_currencies(
            account=row, as_of_date=date(2026, 8, 21)
        )

        self.assertIn(PORTFOLIO_AGGREGATE_CURRENCY, currencies)

    def test_domestic_base_account_needs_no_self_pair(self) -> None:
        account = self._account(market="cn", currency=PORTFOLIO_AGGREGATE_CURRENCY)
        row = self.service.repo.get_account(account["id"])

        currencies = self.service._list_account_refresh_fx_currencies(
            account=row, as_of_date=date(2026, 8, 21)
        )

        self.assertNotIn(PORTFOLIO_AGGREGATE_CURRENCY, currencies)

    def test_refresh_reports_a_pair_for_a_foreign_base_account(self) -> None:
        self._account(market="us", currency="USD")

        summary = self.service.refresh_fx_rates(as_of=date(2026, 8, 21))

        self.assertGreaterEqual(
            summary["pair_count"], 1, "USD 账户必须至少刷新 USD→CNY 这一对"
        )


if __name__ == "__main__":
    unittest.main()
